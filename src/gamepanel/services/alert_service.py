"""Quando vale a pena avisar — as regras de cada alerta do painel.

O que NAO esta aqui: a entrega (`integrations.webhook_client`), e o diario/leitura de
configuracao no banco (`notifica`, `_registra_alerta`, `webhook_config` e companhia
seguem em `app.py` ate a camada de repositorios existir — ver a ordem da secao 4 de
docs/architecture-proposal.md). Aqui fica so a decisao: com este estado, esta leitura e
o que se viu da ultima vez, sai alerta ou nao?

O fio condutor de quase toda regra abaixo e o mesmo: **avisar na virada, nao no
estado**. Disco a 95% continua a 95% no minuto seguinte, e um alerta por minuto ate
alguem arrumar e como se ensina uma equipe a ignorar o canal. Por isso quase todas
escrevem no `anterior` (a memoria daquele servidor) alem de avisar.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from gamepanel.i18n import Mensagem
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.log_probe import compile_pattern
from gamepanel.runtime.ssh import RemoteError, ServerLike

# (conn, evento, titulo, detalhe) -> saiu para alguem?
Notifica = Callable[..., bool]
# (conn, server_id) -> houve acao do painel neste servidor ha pouco?
JobRecente = Callable[..., bool]

# Quem responde a uma sondagem de verdade pode ficar MUDO; contagem por log nao
# pergunta nada ao jogo, entao nao tem o que travar.
FONTES_QUE_RESPONDEM = ("a2s", "http")

DETALHE_MAX = 300


class AlertDeps(NamedTuple):
    """O resto do painel, como as regras precisam enxerga-lo.

    Bundle e nao parametros soltos porque sao treze pecas e elas andam juntas; por
    funcao, e a diferenca entre cinco argumentos e um. Todas entram por injecao pelo
    motivo de sempre: `app.py` importa este modulo, e varios destes nomes sao trocados
    por falsos nos testes (`server_players`, `server_metrics`, `notifica`).
    """

    notifica: Notifica
    job_recente: JobRecente
    player_source: Callable[[ServerLike], str]
    server_players: Callable[..., dict]
    server_metrics: Callable[..., dict]
    read_log_lines: Callable[..., list[str]]
    valor_guardado: Callable[[ServerLike, str], str]
    tamanho_legivel: Callable[..., str]
    # O MESMO dicionario de `app.py`: o monitor, o stream de log e os alertas de recurso
    # anotam no estado do mesmo servidor.
    estado_monitor: dict[int, dict]
    logger: logging.Logger
    mute_rounds: int
    log_err_lines: int
    log_err_cooldown: float


def _alvo(server: ServerLike) -> str:
    return f"{server['ssh_user']}@{server['host']}"


# ------------------------------------------------------- contato e servico

def alerta_de_estado(deps: AlertDeps, conn: Any, server: ServerLike, estado: dict,
                     anterior: dict) -> None:
    """Contato com o container e estado do servico.

    NAO recebe a configuracao dos alertas: quem decide se um evento sai e o `notifica`,
    que a le por conta propria. Um parametro que ninguem usa vira ruido na assinatura e
    mentira na leitura ("ah, entao aqui olha a config").
    """
    sid, nome = int(server["id"]), server["name"]
    alvo = _alvo(server)

    if estado["reachable"] != anterior["reachable"]:
        if estado["reachable"]:
            deps.notifica(conn, "acessivel", Mensagem("alert.contact_back", nome=nome), alvo)
        else:
            deps.notifica(conn, "inacessivel", Mensagem("alert.lost_contact", nome=nome),
                          f"{alvo}\n{estado.get('error') or Mensagem('alert.no_detail')}")
        return  # sem contato nao da para falar do servico com honestidade

    if not estado["reachable"]:
        return
    if estado["service"] == anterior["service"]:
        return
    if estado["service"] == "active":
        deps.notifica(conn, "voltou", Mensagem("alert.server_back", nome=nome), alvo)
        return
    if anterior["service"] != "active":
        return

    # 'failed' e o systemd dizendo que o jogo quebrou (saiu com erro, estourou o limite de
    # restarts, foi morto pelo OOM). Nao passa pela janela de silencio: se alguem mandou
    # reiniciar e o resultado foi 'failed', isso e exatamente o que a pessoa precisa saber.
    if estado["service"] == "failed":
        deps.notifica(conn, "quebrou", Mensagem("alert.game_failed", nome=nome),
                      f"{alvo}\n"
                      + Mensagem("alert.service_is_failed", servico=server["service"])
                      + (f" (Result={estado['result']})" if estado.get("result") else ""))
    elif not deps.job_recente(conn, sid):
        deps.notifica(conn, "caiu", Mensagem("alert.server_stopped", nome=nome),
                      f"{alvo}\n" + Mensagem("alert.service_is",
                                              servico=server["service"],
                                              estado=estado["service"]))


def alerta_de_restart(deps: AlertDeps, conn: Any, server: ServerLike, estado: dict,
                      anterior: dict) -> None:
    """Loop de crash: o systemd ressuscitando o jogo sem parar.

    E o buraco que o alerta de queda nao cobre. Com `Restart=always` o jogo pode morrer a
    cada 20 segundos que o `ActiveState` responde 'active' quase sempre — a queda nunca
    'acontece' aos olhos do painel, e o canal fica em silencio enquanto ninguem consegue
    jogar. Quem denuncia e o NRestarts, que so sobe.
    """
    sid, nome = int(server["id"]), server["name"]
    agora = int(estado.get("restarts") or 0)
    antes = int(anterior.get("restarts") or 0)

    # O contador zera quando alguem reinicia a unidade na mao (e ao recarregar o daemon).
    # Isso nao e um loop: e so uma linha de base nova.
    if agora < antes:
        anterior["restarts"] = agora
        anterior["loop_avisado"] = False
        return
    if agora == antes:
        # Uma volta inteira sem nenhum restart novo: o loop passou, e o proximo pode
        # voltar a avisar.
        anterior["loop_avisado"] = False
        return

    quantos = agora - antes
    anterior["restarts"] = agora
    # Enquanto o contador sobe volta apos volta, o alerta sai UMA vez. Repetir a cada
    # minuto seria o mesmo spam que a regra da mudanca existe para evitar.
    if anterior.get("loop_avisado") or deps.job_recente(conn, sid):
        return
    anterior["loop_avisado"] = True
    deps.notifica(
        conn, "reiniciando", Mensagem("alert.restart_loop", nome=nome),
        f"{_alvo(server)}\n"
        + Mensagem("alert.systemd_restarted", servico=server["service"],
                   quantos=quantos)
        + Mensagem("alert.restarts_total", n=agora),
    )


def alerta_de_mudez(deps: AlertDeps, conn: Any, server: ServerLike, estado: dict,
                    anterior: dict) -> None:
    """Servico de pe, jogo mudo: nao responde mais a consulta do proprio jogo.

    E o caso que mais engana. O processo continua vivo, o systemd continua feliz, o
    dashboard continua verde — e ninguem consegue entrar.
    """
    sid, nome = int(server["id"]), server["name"]
    if deps.player_source(server) not in FONTES_QUE_RESPONDEM:
        return

    # Jogo que acabou de subir ainda esta carregando mapa e nao responde: contar essas
    # voltas transformaria toda partida do zero num alerta. O mesmo para a janela de
    # silencio depois de uma acao pelo painel.
    if estado["service"] != "active" or deps.job_recente(conn, sid):
        anterior["mudo"] = 0
        return

    dados = deps.server_players(server)
    if not dados.get("configured"):
        return

    if not dados.get("error"):
        anterior["mudo"] = 0
        if anterior.get("mudo_avisado"):
            anterior["mudo_avisado"] = False
            deps.notifica(conn, "respondeu", Mensagem("alert.game_answering", nome=nome),
                          Mensagem("alert.players_online_rough",
                                   n=dados.get("players")))
        return

    anterior["mudo"] = int(anterior.get("mudo") or 0) + 1
    if anterior["mudo"] < deps.mute_rounds or anterior.get("mudo_avisado"):
        return
    anterior["mudo_avisado"] = True
    deps.notifica(
        conn, "travou", Mensagem("alert.game_mute", nome=nome),
        f"{_alvo(server)}\n"
        + Mensagem("alert.service_up_game_mute", servico=server["service"])
        + Mensagem("alert.mute_rounds", n=anterior["mudo"])
        + f"\n{dados['error']}",
    )


# ----------------------------------------------------------- erro no log

def alerta_de_log(deps: AlertDeps, conn: Any, server: ServerLike, anterior: dict) -> None:
    """Procura a expressao de erro do servidor no rabo do log do jogo.

    E o unico alerta que depende de configuracao: cada jogo grita de um jeito, entao a
    expressao vem do cadastro. Sem ela, nem a ida de SSH acontece.
    """
    padrao = deps.valor_guardado(server, "error_re")
    if not padrao:
        return
    nome = server["name"]
    try:
        regex = compile_pattern(padrao, "pattern.error")
    except QueryError as exc:
        deps.logger.warning("expressao de erro de '%s' invalida: %s", nome, exc)
        return
    if regex is None:
        return  # padrao so de espacos: nao ha o que procurar
    try:
        linhas = deps.read_log_lines(server, deps.log_err_lines)
    except (RemoteError, QueryError) as exc:
        # Log ilegivel nao e erro DO JOGO. Se o servidor sumiu, quem avisa e o
        # 'inacessivel'; inventar um alerta de log aqui seria contar a mesma coisa duas
        # vezes, com o nome errado.
        deps.logger.info("nao consegui ler o log de '%s' para procurar erro: %s", nome, exc)
        return

    achados = [linha.strip() for linha in linhas if regex.search(linha)]
    if not achados:
        # A linha saiu do rabo do log: se o erro voltar, e um erro novo e avisa de novo.
        anterior["ultimo_erro"] = ""
        return

    ultima = achados[-1][:DETALHE_MAX]
    # Mesma linha da volta passada: um jogo que repete o erro a cada segundo renderia um
    # alerta por minuto ate alguem desligar o webhook.
    if ultima == anterior.get("ultimo_erro"):
        return
    # Trava de seguranca para expressao larga demais (um `.` casa tudo): mesmo com linhas
    # sempre diferentes, o canal nao leva mais de um alerta destes por janela.
    agora = time.monotonic()
    ultimo_envio = float(anterior.get("erro_em") or 0)
    if ultimo_envio and agora - ultimo_envio < deps.log_err_cooldown:
        anterior["ultimo_erro"] = ultima
        return
    anterior["ultimo_erro"] = ultima
    anterior["erro_em"] = agora
    quantas = f" ({len(achados)} linhas casaram)" if len(achados) > 1 else ""
    deps.notifica(conn, "erro-no-log", Mensagem("alert.log_error", nome=nome),
                  f"{_alvo(server)}{quantas}\n{ultima}")


# -------------------------------------------------------------- recursos

def alerta_de_disco(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    dados = deps.server_metrics(server)
    if dados.get("error"):
        return
    pior = max((d for d in dados.get("disks", []) if d.get("pct") is not None),
               key=lambda d: d["pct"], default=None)
    if not pior:
        return
    cheio = pior["pct"] >= cfg["disco"]
    marca = deps.estado_monitor.setdefault(sid, {})
    # So avisa na VIRADA: um disco a 95% continua a 95% na volta seguinte, e ninguem
    # merece o mesmo alerta a cada minuto ate arrumar.
    if cheio and not marca.get("disco_cheio"):
        deps.notifica(conn, "disco-cheio",
                      Mensagem("alert.disk_almost_full", nome=server["name"]),
                      Mensagem("alert.disk_detail", ponto=pior["mount"],
                               pct=pior["pct"],
                               usado=deps.tamanho_legivel(pior["used"]),
                               total=deps.tamanho_legivel(pior["total"])))
    marca["disco_cheio"] = cheio


def alerta_de_memoria(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    dados = deps.server_metrics(server)
    if dados.get("error"):
        return
    mem = dados.get("mem")
    if not mem or mem.get("pct") is None:
        return
    cheio = mem["pct"] >= cfg["memoria"]
    marca = deps.estado_monitor.setdefault(sid, {})
    # So avisa na virada
    if cheio and not marca.get("memoria_alta"):
        deps.notifica(
            conn, "memoria-alta",
            Mensagem("alert.memory_almost_full", nome=server["name"]),
            Mensagem("alert.memory_detail", pct=mem["pct"],
                     usado=deps.tamanho_legivel(mem["used"]),
                     total=deps.tamanho_legivel(mem["total"])))
    marca["memoria_alta"] = cheio


def alerta_de_cpu(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    dados = deps.server_metrics(server)
    if dados.get("error"):
        return
    cpu = dados.get("cpu_pct")
    if cpu is None:
        return
    alto = cpu >= cfg["cpu"]
    marca = deps.estado_monitor.setdefault(sid, {})
    # So avisa na virada
    if alto and not marca.get("cpu_alta"):
        cores = dados.get("cores", 1)
        proc = dados.get("proc", {})
        proc_cpu = proc.get("cpu_pct")
        detalhe = str(Mensagem("alert.cpu_detail_one" if cores == 1
                               else "alert.cpu_detail_many", pct=cpu, cores=cores))
        if proc_cpu is not None:
            detalhe += str(Mensagem("alert.cpu_game_part", pct=proc_cpu))
        deps.notifica(conn, "cpu-alta",
                      Mensagem("alert.cpu_high", nome=server["name"]), detalhe)
    marca["cpu_alta"] = alto


# ------------------------------------------------------------- jogadores

def alerta_de_jogadores(deps: AlertDeps, conn: Any, server: ServerLike, servico: str,
                        anterior: dict, cfg: dict) -> None:
    """Avisa quando jogadores entram ou saem do servidor.

    Compara a lista de jogadores atual com a da verificacao anterior. Se o jogo
    tiver nomes (pelo log com (?P<name>...), API HTTP ou A2S), cita o nome de quem
    entrou ou saiu. Se o jogo so devolver a contagem, avisa a variacao numerica.

    Recebe o `servico` (string) em vez do estado inteiro de proposito: a volta rapida do
    monitor nao consulta o systemd, e passa aqui o ultimo estado ja conhecido. Pedir o
    dicionario obrigaria a pagar um SSH so para preencher um campo que ja se sabe.
    """
    sid, nome = int(server["id"]), server["name"]
    if not deps.player_source(server):
        return

    # Se o servico nao estiver ativo ou tiver job recente (restart, update),
    # reseta o estado para nao disparar alertas falsos de desconexao.
    if servico != "active" or deps.job_recente(conn, sid):
        anterior["jogadores_nomes"] = None
        anterior["jogadores_count"] = None
        return

    dados = deps.server_players(server)
    if not dados.get("configured") or dados.get("error"):
        return

    nomes_atuais, contagem_atual = leitura_de_jogadores(dados)

    # Primeira olhada deste servidor: so estabelece a linha de base
    if anterior.get("jogadores_nomes") is None and anterior.get("jogadores_count") is None:
        anterior["jogadores_nomes"] = nomes_atuais
        anterior["jogadores_count"] = contagem_atual
        return

    nomes_anteriores = anterior.get("jogadores_nomes") or set()
    contagem_anterior = int(anterior.get("jogadores_count") or 0)

    if nomes_atuais or nomes_anteriores:
        # O jogo da os nomes (exatos ou aproximados): o aviso cita quem foi.
        _avisa_por_nome(deps, conn, nome, cfg, nomes_atuais, nomes_anteriores, contagem_atual)
    else:
        # So a contagem: o aviso fala da variacao.
        _avisa_por_contagem(deps, conn, nome, cfg, contagem_atual, contagem_anterior)

    anterior["jogadores_nomes"] = nomes_atuais
    anterior["jogadores_count"] = contagem_atual


def leitura_de_jogadores(dados: dict) -> tuple[set, int]:
    """Normaliza a resposta da consulta em (nomes, contagem).

    Jogo que so devolve numero vem com a lista vazia; jogo que so devolve nomes vem
    sem contagem. Os dois casos saem daqui com a mesma forma, e e isso que permite ao
    resto da funcao nao repetir `or 0` e `or []` a cada linha.
    """
    lista = dados.get("list") or []
    nomes = {p["name"].strip() for p in lista if p.get("name") and p["name"].strip()}
    contagem = dados.get("players")
    if contagem is None and nomes:
        contagem = len(nomes)
    return nomes, max(0, int(contagem or 0))


def texto_de_online(contagem: int) -> str:
    """"3 jogadores online", "1 jogador online", "nenhum jogador online".

    Existia em quatro lugares desta tela, com uma diferenca sutil entre eles: um dos
    quatro nao tratava o zero e podia dizer "0 jogadores online". Um lugar so.
    """
    if contagem == 0:
        return Mensagem("alert.nobody_online")
    return Mensagem("alert.players_online_one" if contagem == 1
                    else "alert.players_online_many", n=contagem)


def _avisa_por_nome(deps: AlertDeps, conn: Any, nome: str, cfg: dict, atuais: set,
                    anteriores: set, contagem: int) -> None:
    """Um aviso por pessoa que entrou ou saiu."""
    detalhe = texto_de_online(contagem)
    if "jogador-entrou" in cfg["eventos"]:
        for jogador in sorted(atuais - anteriores):
            deps.notifica(conn, "jogador-entrou",
                          Mensagem("alert.player_joined", nome=nome,
                                   jogador=jogador), detalhe)
    if "jogador-saiu" in cfg["eventos"]:
        for jogador in sorted(anteriores - atuais):
            deps.notifica(conn, "jogador-saiu",
                          Mensagem("alert.player_left", nome=nome,
                                   jogador=jogador), detalhe)


def _avisa_por_contagem(deps: AlertDeps, conn: Any, nome: str, cfg: dict, atual: int,
                        anterior: int) -> None:
    """Um aviso por variacao, para o jogo que nao publica nomes."""
    if atual == anterior:
        return
    detalhe = texto_de_online(atual)
    if atual > anterior and "jogador-entrou" in cfg["eventos"]:
        dif = atual - anterior
        deps.notifica(conn, "jogador-entrou",
                      Mensagem("alert.joined_one" if dif == 1 else "alert.joined_many",
                               nome=nome, n=dif), detalhe)
    elif atual < anterior and "jogador-saiu" in cfg["eventos"]:
        dif = anterior - atual
        deps.notifica(conn, "jogador-saiu",
                      Mensagem("alert.left_one" if dif == 1 else "alert.left_many",
                               nome=nome, n=dif), detalhe)
