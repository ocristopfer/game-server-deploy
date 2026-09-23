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

from gamepanel.i18n import Message
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.log_probe import compile_pattern
from gamepanel.runtime.ssh import RemoteError, ServerLike

# (conn, evento, titulo, detalhe) -> saiu para alguem?
Notifica = Callable[..., bool]
# (conn, server_id) -> houve acao do painel neste servidor ha pouco?
JobRecente = Callable[..., bool]

# Quem responde a uma sondagem de verdade pode ficar MUDO; contagem por log nao
# pergunta nada ao jogo, entao nao tem o que travar.
ANSWERING_SOURCES = ("a2s", "http")

DETALHE_MAX = 300


class AlertDeps(NamedTuple):
    """O resto do painel, como as regras precisam enxerga-lo.

    Bundle e nao parametros soltos porque sao treze pecas e elas andam juntas; por
    funcao, e a diferenca entre cinco argumentos e um. Todas entram por injecao pelo
    motivo de sempre: `app.py` importa este modulo, e varios destes nomes sao trocados
    por falsos nos testes (`server_players`, `server_metrics`, `notifica`).
    """

    notify: Notifica
    recent_job: JobRecente
    player_source: Callable[[ServerLike], str]
    server_players: Callable[..., dict]
    server_metrics: Callable[..., dict]
    read_log_lines: Callable[..., list[str]]
    stored_value: Callable[[ServerLike, str], str]
    human_size: Callable[..., str]
    # O MESMO dicionario de `app.py`: o monitor, o stream de log e os alertas de recurso
    # anotam no estado do mesmo servidor.
    monitor_state: dict[int, dict]
    logger: logging.Logger
    mute_rounds: int
    log_err_lines: int
    log_err_cooldown: float


def _target(server: ServerLike) -> str:
    return f"{server['ssh_user']}@{server['host']}"


# ------------------------------------------------------- contato e servico

def state_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                     previous: dict) -> None:
    """Contato com o container e estado do servico.

    NAO recebe a configuracao dos alertas: quem decide se um evento sai e o `notifica`,
    que a le por conta propria. Um parametro que ninguem usa vira ruido na assinatura e
    mentira na leitura ("ah, entao aqui olha a config").
    """
    sid, name = int(server["id"]), server["name"]
    target = _target(server)

    if state["reachable"] != previous["reachable"]:
        if state["reachable"]:
            deps.notify(conn, "acessivel", Message("alert.contact_back", name=name), target)
        else:
            deps.notify(conn, "inacessivel", Message("alert.lost_contact", name=name),
                          f"{target}\n{state.get('error') or Message('alert.no_detail')}")
        return  # sem contato nao da para falar do servico com honestidade

    if not state["reachable"]:
        return
    if state["service"] == previous["service"]:
        return
    if state["service"] == "active":
        deps.notify(conn, "voltou", Message("alert.server_back", name=name), target)
        return
    if previous["service"] != "active":
        return

    # 'failed' e o systemd dizendo que o jogo quebrou (saiu com erro, estourou o limite de
    # restarts, foi morto pelo OOM). Nao passa pela janela de silencio: se alguem mandou
    # reiniciar e o resultado foi 'failed', isso e exatamente o que a pessoa precisa saber.
    if state["service"] == "failed":
        deps.notify(conn, "quebrou", Message("alert.game_failed", name=name),
                      f"{target}\n"
                      + Message("alert.service_is_failed", service=server["service"])
                      + (f" (Result={state['result']})" if state.get("result") else ""))
    elif not deps.recent_job(conn, sid):
        deps.notify(conn, "caiu", Message("alert.server_stopped", name=name),
                      f"{target}\n" + Message("alert.service_is",
                                              service=server["service"],
                                              state=state["service"]))


def restart_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                      previous: dict) -> None:
    """Loop de crash: o systemd ressuscitando o jogo sem parar.

    E o buraco que o alerta de queda nao cobre. Com `Restart=always` o jogo pode morrer a
    cada 20 segundos que o `ActiveState` responde 'active' quase sempre — a queda nunca
    'acontece' aos olhos do painel, e o canal fica em silencio enquanto ninguem consegue
    jogar. Quem denuncia e o NRestarts, que so sobe.
    """
    sid, name = int(server["id"]), server["name"]
    now_ts = int(state.get("restarts") or 0)
    before = int(previous.get("restarts") or 0)

    # O contador zera quando alguem reinicia a unidade na mao (e ao recarregar o daemon).
    # Isso nao e um loop: e so uma linha de base nova.
    if now_ts < before:
        previous["restarts"] = now_ts
        previous["loop_avisado"] = False
        return
    if now_ts == before:
        # Uma volta inteira sem nenhum restart novo: o loop passou, e o proximo pode
        # voltar a avisar.
        previous["loop_avisado"] = False
        return

    how_many = now_ts - before
    previous["restarts"] = now_ts
    # Enquanto o contador sobe volta apos volta, o alerta sai UMA vez. Repetir a cada
    # minuto seria o mesmo spam que a regra da mudanca existe para evitar.
    if previous.get("loop_avisado") or deps.recent_job(conn, sid):
        return
    previous["loop_avisado"] = True
    deps.notify(
        conn, "reiniciando", Message("alert.restart_loop", name=name),
        f"{_target(server)}\n"
        + Message("alert.systemd_restarted", service=server["service"],
                   times=how_many)
        + Message("alert.restarts_total", n=now_ts),
    )


def mute_alert(deps: AlertDeps, conn: Any, server: ServerLike, state: dict,
                    previous: dict) -> None:
    """Servico de pe, jogo mudo: nao responde mais a consulta do proprio jogo.

    E o caso que mais engana. O processo continua vivo, o systemd continua feliz, o
    dashboard continua verde — e ninguem consegue entrar.
    """
    sid, name = int(server["id"]), server["name"]
    if deps.player_source(server) not in ANSWERING_SOURCES:
        return

    # Jogo que acabou de subir ainda esta carregando mapa e nao responde: contar essas
    # voltas transformaria toda partida do zero num alerta. O mesmo para a janela de
    # silencio depois de uma acao pelo painel.
    if state["service"] != "active" or deps.recent_job(conn, sid):
        previous["mudo"] = 0
        return

    data = deps.server_players(server)
    if not data.get("configured"):
        return

    if not data.get("error"):
        previous["mudo"] = 0
        if previous.get("mudo_avisado"):
            previous["mudo_avisado"] = False
            deps.notify(conn, "respondeu", Message("alert.game_answering", name=name),
                          Message("alert.players_online_rough",
                                   n=data.get("players")))
        return

    previous["mudo"] = int(previous.get("mudo") or 0) + 1
    if previous["mudo"] < deps.mute_rounds or previous.get("mudo_avisado"):
        return
    previous["mudo_avisado"] = True
    deps.notify(
        conn, "travou", Message("alert.game_mute", name=name),
        f"{_target(server)}\n"
        + Message("alert.service_up_game_mute", service=server["service"])
        + Message("alert.mute_rounds", n=previous["mudo"])
        + f"\n{data['error']}",
    )


# ----------------------------------------------------------- erro no log

def log_alert(deps: AlertDeps, conn: Any, server: ServerLike, previous: dict) -> None:
    """Procura a expressao de erro do servidor no rabo do log do jogo.

    E o unico alerta que depende de configuracao: cada jogo grita de um jeito, entao a
    expressao vem do cadastro. Sem ela, nem a ida de SSH acontece.
    """
    default = deps.stored_value(server, "error_re")
    if not default:
        return
    name = server["name"]
    try:
        regex = compile_pattern(default, "pattern.error")
    except QueryError as exc:
        deps.logger.warning("expressao de erro de '%s' invalida: %s", name, exc)
        return
    if regex is None:
        return  # padrao so de espacos: nao ha o que procurar
    try:
        lines_of = deps.read_log_lines(server, deps.log_err_lines)
    except (RemoteError, QueryError) as exc:
        # Log ilegivel nao e erro DO JOGO. Se o servidor sumiu, quem avisa e o
        # 'inacessivel'; inventar um alerta de log aqui seria contar a mesma coisa duas
        # vezes, com o nome errado.
        deps.logger.info("nao consegui ler o log de '%s' para procurar erro: %s", name, exc)
        return

    found = [line.strip() for line in lines_of if regex.search(line)]
    if not found:
        # A linha saiu do rabo do log: se o erro voltar, e um erro novo e avisa de novo.
        previous["ultimo_erro"] = ""
        return

    last_one = found[-1][:DETALHE_MAX]
    # Mesma linha da volta passada: um jogo que repete o erro a cada segundo renderia um
    # alerta por minuto ate alguem desligar o webhook.
    if last_one == previous.get("ultimo_erro"):
        return
    # Trava de seguranca para expressao larga demais (um `.` casa tudo): mesmo com linhas
    # sempre diferentes, o canal nao leva mais de um alerta destes por janela.
    now_ts = time.monotonic()
    last_sent = float(previous.get("erro_em") or 0)
    if last_sent and now_ts - last_sent < deps.log_err_cooldown:
        previous["ultimo_erro"] = last_one
        return
    previous["ultimo_erro"] = last_one
    previous["erro_em"] = now_ts
    how_many = f" ({len(found)} linhas casaram)" if len(found) > 1 else ""
    deps.notify(conn, "erro-no-log", Message("alert.log_error", name=name),
                  f"{_target(server)}{how_many}\n{last_one}")


# -------------------------------------------------------------- recursos

def disk_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    worst = max((d for d in data.get("disks", []) if d.get("pct") is not None),
               key=lambda d: d["pct"], default=None)
    if not worst:
        return
    full = worst["pct"] >= cfg["disk"]
    mark = deps.monitor_state.setdefault(sid, {})
    # So avisa na VIRADA: um disco a 95% continua a 95% na volta seguinte, e ninguem
    # merece o mesmo alerta a cada minuto ate arrumar.
    if full and not mark.get("disco_cheio"):
        deps.notify(conn, "disco-cheio",
                      Message("alert.disk_almost_full", name=server["name"]),
                      Message("alert.disk_detail", mount=worst["mount"],
                               pct=worst["pct"],
                               used=deps.human_size(worst["used"]),
                               total=deps.human_size(worst["total"])))
    mark["disco_cheio"] = full


def memory_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    mem = data.get("mem")
    if not mem or mem.get("pct") is None:
        return
    full = mem["pct"] >= cfg["memory"]
    mark = deps.monitor_state.setdefault(sid, {})
    # So avisa na virada
    if full and not mark.get("memoria_alta"):
        deps.notify(
            conn, "memoria-alta",
            Message("alert.memory_almost_full", name=server["name"]),
            Message("alert.memory_detail", pct=mem["pct"],
                     used=deps.human_size(mem["used"]),
                     total=deps.human_size(mem["total"])))
    mark["memoria_alta"] = full


def cpu_alert(deps: AlertDeps, conn: Any, server: ServerLike, cfg: dict) -> None:
    sid = int(server["id"])
    data = deps.server_metrics(server)
    if data.get("error"):
        return
    cpu = data.get("cpu_pct")
    if cpu is None:
        return
    tall = cpu >= cfg["cpu"]
    mark = deps.monitor_state.setdefault(sid, {})
    # So avisa na virada
    if tall and not mark.get("cpu_alta"):
        cores = data.get("cores", 1)
        proc = data.get("proc", {})
        proc_cpu = proc.get("cpu_pct")
        detail = str(Message("alert.cpu_detail_one" if cores == 1
                               else "alert.cpu_detail_many", pct=cpu, cores=cores))
        if proc_cpu is not None:
            detail += str(Message("alert.cpu_game_part", pct=proc_cpu))
        deps.notify(conn, "cpu-alta",
                      Message("alert.cpu_high", name=server["name"]), detail)
    mark["cpu_alta"] = tall


# ------------------------------------------------------------- jogadores

def players_alert(deps: AlertDeps, conn: Any, server: ServerLike, service: str,
                        previous: dict, cfg: dict) -> None:
    """Avisa quando jogadores entram ou saem do servidor.

    Compara a lista de jogadores atual com a da verificacao anterior. Se o jogo
    tiver nomes (pelo log com (?P<name>...), API HTTP ou A2S), cita o nome de quem
    entrou ou saiu. Se o jogo so devolver a contagem, avisa a variacao numerica.

    Recebe o `servico` (string) em vez do estado inteiro de proposito: a volta rapida do
    monitor nao consulta o systemd, e passa aqui o ultimo estado ja conhecido. Pedir o
    dicionario obrigaria a pagar um SSH so para preencher um campo que ja se sabe.
    """
    sid, name = int(server["id"]), server["name"]
    if not deps.player_source(server):
        return

    # Se o servico nao estiver ativo ou tiver job recente (restart, update),
    # reseta o estado para nao disparar alertas falsos de desconexao.
    if service != "active" or deps.recent_job(conn, sid):
        previous["jogadores_nomes"] = None
        previous["jogadores_count"] = None
        return

    data = deps.server_players(server)
    if not data.get("configured") or data.get("error"):
        return

    current_names, current_count = players_reading(data)

    # Primeira olhada deste servidor: so estabelece a linha de base
    if previous.get("jogadores_nomes") is None and previous.get("jogadores_count") is None:
        previous["jogadores_nomes"] = current_names
        previous["jogadores_count"] = current_count
        return

    previous_names = previous.get("jogadores_nomes") or set()
    previous_count = int(previous.get("jogadores_count") or 0)

    if current_names or previous_names:
        # O jogo da os nomes (exatos ou aproximados): o aviso cita quem foi.
        _warn_by_name(deps, conn, name, cfg, current_names, previous_names, current_count)
    else:
        # So a contagem: o aviso fala da variacao.
        _warn_by_count(deps, conn, name, cfg, current_count, previous_count)

    previous["jogadores_nomes"] = current_names
    previous["jogadores_count"] = current_count


def players_reading(data: dict) -> tuple[set, int]:
    """Normaliza a resposta da consulta em (nomes, contagem).

    Jogo que so devolve numero vem com a lista vazia; jogo que so devolve nomes vem
    sem contagem. Os dois casos saem daqui com a mesma forma, e e isso que permite ao
    resto da funcao nao repetir `or 0` e `or []` a cada linha.
    """
    listing = data.get("list") or []
    names = {p["name"].strip() for p in listing if p.get("name") and p["name"].strip()}
    count = data.get("players")
    if count is None and names:
        count = len(names)
    return names, max(0, int(count or 0))


def online_text(count: int) -> str:
    """"3 jogadores online", "1 jogador online", "nenhum jogador online".

    Existia em quatro lugares desta tela, com uma diferenca sutil entre eles: um dos
    quatro nao tratava o zero e podia dizer "0 jogadores online". Um lugar so.
    """
    if count == 0:
        return Message("alert.nobody_online")
    return Message("alert.players_online_one" if count == 1
                    else "alert.players_online_many", n=count)


def _warn_by_name(deps: AlertDeps, conn: Any, name: str, cfg: dict, current_names: set,
                    previous_names: set, count: int) -> None:
    """Um aviso por pessoa que entrou ou saiu."""
    detail = online_text(count)
    if "jogador-entrou" in cfg["events"]:
        for player in sorted(current_names - previous_names):
            deps.notify(conn, "jogador-entrou",
                          Message("alert.player_joined", name=name,
                                   player=player), detail)
    if "jogador-saiu" in cfg["events"]:
        for player in sorted(previous_names - current_names):
            deps.notify(conn, "jogador-saiu",
                          Message("alert.player_left", name=name,
                                   player=player), detail)


def _warn_by_count(deps: AlertDeps, conn: Any, name: str, cfg: dict, current: int,
                        previous: int) -> None:
    """Um aviso por variacao, para o jogo que nao publica nomes."""
    if current == previous:
        return
    detail = online_text(current)
    if current > previous and "jogador-entrou" in cfg["events"]:
        diff = current - previous
        deps.notify(conn, "jogador-entrou",
                      Message("alert.joined_one" if diff == 1 else "alert.joined_many",
                               name=name, n=diff), detail)
    elif current < previous and "jogador-saiu" in cfg["events"]:
        diff = previous - current
        deps.notify(conn, "jogador-saiu",
                      Message("alert.left_one" if diff == 1 else "alert.left_many",
                               name=name, n=diff), detail)
