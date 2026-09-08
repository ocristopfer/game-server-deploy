#!/usr/bin/env python3
"""Testes dos alertas por webhook.

    docker compose exec panel python3 /opt/gamepanel/test_alerts.py

O envio de verdade e trocado por um capturador: o que se testa aqui e QUANDO o painel
decide avisar, que e onde mora a chance de errar. Alerta a mais vira ruido e o canal
deixa de ser lido; alerta a menos e um servidor caido as 3h que ninguem descobre.
"""
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

os.environ["GAMEPANEL_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")

import app as panel  # noqa: E402

falhas = []


def check(nome, condicao, detalhe=""):
    if condicao:
        print(f"  ok   {nome}")
    else:
        print(f"  FALHOU {nome} {detalhe}")
        falhas.append(nome)


def igual(nome, obtido, esperado):
    check(nome, obtido == esperado, f"(obtido {obtido!r}, esperado {esperado!r})")


# ------------------------------------------------------------- capturador
enviadas = []


def captura(url, texto):
    enviadas.append((url, texto))
    return ""


envia_real = panel.envia_webhook          # guardado para o teste do fim
panel.envia_webhook = captura             # nada sai para a rede nestes testes


def limpa():
    enviadas.clear()
    panel._estado_monitor.clear()


def relogios_vencidos():
    """Poe os relogios do monitor num passado que vence qualquer limite.

    Zera-los nao serve: time.monotonic() conta desde o boot da MAQUINA, e num container
    recem-subido o zero pode estar a menos de um minuto de distancia — ai o monitor sai
    cedo e o teste falha por causa do uptime de quem rodou, nao do codigo.
    """
    panel._ultimo_monitor = panel._ultimo_estado = time.monotonic() - 3600


URL = "http://exemplo.invalid/hook"
conn = panel._connect()


def destino(url, eventos, nome="Teste", ativo=1):
    """Cadastra um destino e devolve o id."""
    with conn:
        cur = conn.execute(
            "INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
            " VALUES (?, ?, ?, ?, ?)",
            (nome, url, ",".join(eventos), ativo, panel.now_iso()))
    return cur.lastrowid


def liga(eventos, disco=90, memoria=90, cpu=90):
    """Deixa UM destino cadastrado, com estes eventos. O padrao dos testes antigos."""
    with conn:
        conn.execute("DELETE FROM webhooks")
    destino(URL, eventos)
    panel.config_set(conn, "webhook_disk_pct", str(disco))
    panel.config_set(conn, "webhook_mem_pct", str(memoria))
    panel.config_set(conn, "webhook_cpu_pct", str(cpu))


servidor = {"id": 1, "name": "Palworld", "host": "10.0.0.9", "ssh_user": "root",
            "service": "palworld.service"}


def estado(reachable=True, service="active", error="", restarts=0, result="", sub=""):
    return {"reachable": reachable, "service": service, "error": error,
            "restarts": restarts, "result": result, "sub": sub}


print("Configuracao")
liga(["caiu"])
cfg = panel.webhook_config(conn)
igual("destino lido do banco", [d["url"] for d in cfg["ativos"]], [URL])
igual("evento lido do banco", cfg["eventos"], {"caiu"})
# Evento inventado (banco mexido a mao, versao antiga) nao pode virar chave desconhecida.
with conn:
    conn.execute("UPDATE webhooks SET eventos = 'caiu,formatar-o-disco'")
igual("evento desconhecido e descartado", panel.webhook_config(conn)["eventos"], {"caiu"})
panel.config_set(conn, "webhook_disk_pct", "5")
igual("limite de disco tem piso", panel.webhook_config(conn)["disco"], 50)
panel.config_set(conn, "webhook_disk_pct", "nao e numero")
igual("limite ilegivel cai no padrao", panel.webhook_config(conn)["disco"],
      panel.DISK_PCT_DEFAULT)
panel.config_set(conn, "webhook_mem_pct", "5")
igual("limite de memoria tem piso", panel.webhook_config(conn)["memoria"], 50)
panel.config_set(conn, "webhook_cpu_pct", "vazio")
igual("limite de CPU ilegivel cai no padrao", panel.webhook_config(conn)["cpu"],
      panel.CPU_PCT_DEFAULT)


print("Varios destinos")
# O ponto do recurso: dois canais, listas diferentes. Cada evento tem de sair para quem
# pediu por ele, e so para esses.
with conn:
    conn.execute("DELETE FROM webhooks")
equipe = destino("http://equipe.invalid/hook", ["caiu", "voltou"], "Equipe")
geral = destino("http://geral.invalid/hook", ["caiu"], "Geral")
mudo = destino("http://mudo.invalid/hook", ["caiu"], "Desligado", ativo=0)

limpa()
igual("evento pedido pelos dois sai duas vezes",
      (panel.notifica(conn, "caiu", "caiu"), len(enviadas)), (True, 2))
igual("cada um recebe na sua URL", sorted(u for u, _ in enviadas),
      ["http://equipe.invalid/hook", "http://geral.invalid/hook"])
check("destino desligado nao recebe",
      all("mudo.invalid" not in u for u, _ in enviadas))

limpa()
panel.notifica(conn, "voltou", "voltou")
igual("evento de um so sai uma vez", [u for u, _ in enviadas],
      ["http://equipe.invalid/hook"])

limpa()
igual("evento que ninguem pediu nao sai",
      (panel.notifica(conn, "disco-cheio", "disco"), len(enviadas)), (False, 0))

igual("a uniao dos destinos ligados e o que o monitor observa",
      panel.webhook_config(conn)["eventos"], {"caiu", "voltou"})

# Um destino fora do ar nao pode calar os outros: o Discord de pe continua recebendo
# mesmo com o Slack recusando a conexao.
limpa()
panel.envia_webhook = lambda url, texto: (
    captura(url, texto) if "equipe" in url else "recusou a conexao")
igual("um destino quebrado nao impede os outros",
      (panel.notifica(conn, "caiu", "caiu"), len(enviadas)), (True, 1))
panel.envia_webhook = captura

limpa()
with conn:
    conn.execute("UPDATE webhooks SET ativo = 0")
igual("todos desligados, nada sai",
      (panel.notifica(conn, "caiu", "caiu"), len(enviadas)), (False, 0))
with conn:
    conn.execute("DELETE FROM webhooks WHERE id IN (?, ?, ?)", (equipe, geral, mudo))


print("A URL nao aparece inteira na tela")
# Ela e uma credencial: quem le a tela por cima do ombro nao pode sair de la podendo
# escrever no canal.
mascarada = panel.mascara_url(
    "https://discord.com/api/webhooks/1544786528700604457/segredo-que-nao-pode-vazar")
check("o token some", "segredo-que-nao-pode-vazar" not in mascarada, mascarada)
check("o id continua visivel para reconhecer o canal",
      "1544786528700604457" in mascarada, mascarada)
check("o host continua visivel", mascarada.startswith("discord.com"), mascarada)
igual("URL vazia nao vira mascara", panel.mascara_url(""), "")


print("Quando o painel decide avisar")
liga(["caiu", "voltou", "inacessivel", "acessivel"])

limpa()
panel._alerta_de_estado(conn, servidor, estado(service="inactive"),
                        estado(service="active"), panel.webhook_config(conn))
igual("queda avisa", len(enviadas), 1)
check("a mensagem diz o nome e o servico",
      "Palworld" in enviadas[0][1] and "palworld.service" in enviadas[0][1])

limpa()
panel._alerta_de_estado(conn, servidor, estado(service="active"),
                        estado(service="inactive"), panel.webhook_config(conn))
igual("volta avisa", len(enviadas), 1)

limpa()
panel._alerta_de_estado(conn, servidor, estado(service="active"),
                        estado(service="active"), panel.webhook_config(conn))
igual("nada mudou, nada sai", len(enviadas), 0)

limpa()
panel._alerta_de_estado(conn, servidor, estado(reachable=False, service="inacessivel",
                                               error="timeout"),
                        estado(service="active"), panel.webhook_config(conn))
igual("perder contato avisa", len(enviadas), 1)
check("a mensagem leva o motivo", "timeout" in enviadas[0][1])

# Sem contato, o painel nao sabe o que o servico esta fazendo: avisar 'caiu' junto seria
# inventar. Sai UMA mensagem, a do contato.
limpa()
panel._alerta_de_estado(conn, servidor, estado(reachable=False, service="inacessivel"),
                        estado(reachable=True, service="active"),
                        panel.webhook_config(conn))
igual("sem contato nao acumula alerta de servico", len(enviadas), 1)

limpa()
panel._alerta_de_estado(conn, servidor, estado(reachable=False, service="inacessivel"),
                        estado(reachable=False, service="inacessivel"),
                        panel.webhook_config(conn))
igual("continua sem contato, nao repete", len(enviadas), 0)

# Evento desligado na tela nao sai, mesmo acontecendo.
limpa()
liga(["voltou"])
panel._alerta_de_estado(conn, servidor, estado(service="inactive"),
                        estado(service="active"), panel.webhook_config(conn))
igual("evento desligado nao sai", len(enviadas), 0)

# Sem nenhum destino nada sai, nem com todos os eventos ligados.
limpa()
with conn:
    conn.execute("DELETE FROM webhooks")
igual("sem destino nao sai nada",
      panel.notifica(conn, "caiu", "titulo", "detalhe"), False)


print("Acao do painel nao vira susto")
liga(["caiu"])
with conn:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('Palworld', '10.0.0.9', 22, 'root', 'palworld.service', ?)",
        (panel.now_iso(),))
sid = conn.execute("SELECT id FROM servers").fetchone()["id"]
alvo = dict(servidor, id=sid)

check("sem job recente, a queda e queda", not panel._job_recente(conn, sid))
with conn:
    conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (sid, "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
check("restart pelo painel abre a janela de silencio", panel._job_recente(conn, sid))

limpa()
panel._alerta_de_estado(conn, alvo, estado(service="inactive"),
                        estado(service="active"), panel.webhook_config(conn))
igual("reiniciar pelo botao nao vira alerta", len(enviadas), 0)

# Job velho nao segura o alerta para sempre.
antigo = (datetime.now(timezone.utc) - timedelta(seconds=panel.ALERT_QUIET + 60)).isoformat()
with conn:
    conn.execute("DELETE FROM jobs")
    conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (sid, "root@10.0.0.9", "restart", "ok", "admin", antigo))
check("job antigo ja nao silencia", not panel._job_recente(conn, sid))
limpa()
panel._alerta_de_estado(conn, alvo, estado(service="inactive"),
                        estado(service="active"), panel.webhook_config(conn))
igual("passada a janela, a queda avisa", len(enviadas), 1)


# ------------------------------------------------------- o jogo, nao o servico
# O buraco que estes tres cobrem: "servico rodando" nao e "jogo funcionando". Um jogo
# pode estar travado, caindo em loop ou cuspindo erro no log com o systemd achando que
# esta tudo bem — e ate aqui nada disso virava alerta.

print("O jogo quebrou (failed)")
liga(["caiu", "quebrou"])
with conn:
    conn.execute("DELETE FROM jobs")

limpa()
panel._alerta_de_estado(conn, alvo, estado(service="failed", result="exit-code"),
                        estado(service="active"), panel.webhook_config(conn))
igual("servico em failed avisa", len(enviadas), 1)
check("e a mensagem diz que QUEBROU, nao que pararam",
      "quebrou" in enviadas[0][1] and "exit-code" in enviadas[0][1], enviadas[0][1])

# Parar pelo painel e 'inactive' e cai na janela de silencio. Terminar em 'failed' logo
# depois de uma acao e outra coisa: foi a acao que quebrou o jogo, e e o caso em que mais
# se quer saber.
with conn:
    conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, username, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (sid, "root@10.0.0.9", "restart", "ok", "admin", panel.now_iso()))
limpa()
panel._alerta_de_estado(conn, alvo, estado(service="inactive"),
                        estado(service="active"), panel.webhook_config(conn))
igual("parar pelo painel continua silencioso", len(enviadas), 0)
panel._alerta_de_estado(conn, alvo, estado(service="failed"),
                        estado(service="active"), panel.webhook_config(conn))
igual("mas quebrar logo apos a acao avisa", len(enviadas), 1)
with conn:
    conn.execute("DELETE FROM jobs")


print("Loop de restart")
liga(["reiniciando"])
anterior = {"reachable": True, "service": "active", "restarts": 2}

limpa()
panel._alerta_de_restart(conn, alvo, estado(restarts=5), anterior)
igual("o contador subiu, avisa", len(enviadas), 1)
check("a mensagem diz quantas vezes", "3x" in enviadas[0][1], enviadas[0][1])

# Enquanto o contador continua subindo e o MESMO episodio: avisar a cada volta seria o
# spam que a regra da mudanca existe para evitar.
limpa()
panel._alerta_de_restart(conn, alvo, estado(restarts=8), anterior)
igual("continua subindo, nao repete", len(enviadas), 0)

# Uma volta inteira sem restart novo fecha o episodio.
panel._alerta_de_restart(conn, alvo, estado(restarts=8), anterior)
check("volta sem restart destrava o alerta", not anterior["loop_avisado"])
limpa()
panel._alerta_de_restart(conn, alvo, estado(restarts=11), anterior)
igual("um loop novo volta a avisar", len(enviadas), 1)

# `systemctl restart` na mao zera o NRestarts. Isso e linha de base nova, nao um loop.
limpa()
panel._alerta_de_restart(conn, alvo, estado(restarts=0), anterior)
igual("contador zerado nao vira alerta", len(enviadas), 0)
igual("e a linha de base acompanha", anterior["restarts"], 0)


print("Jogo de pe, mas mudo")
liga(["travou", "respondeu"])
# So quem responde a uma sondagem de verdade pode ficar mudo.
sondado = dict(alvo, player_source="a2s", query_port=27015)
resposta = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
panel.server_players = lambda server, force=False: resposta
mudez = {"reachable": True, "service": "active", "restarts": 0}

limpa()
for _ in range(panel.MUTE_ROUNDS - 1):
    panel._alerta_de_mudez(conn, sondado, estado(), mudez)
igual("nao avisa no primeiro silencio (UDP perde pacote)", len(enviadas), 0)
panel._alerta_de_mudez(conn, sondado, estado(), mudez)
igual(f"avisa na volta {panel.MUTE_ROUNDS}", len(enviadas), 1)
check("a mensagem separa 'rodando' de 'respondendo'",
      "nao responde" in enviadas[0][1], enviadas[0][1])

limpa()
panel._alerta_de_mudez(conn, sondado, estado(), mudez)
igual("continua mudo, nao repete", len(enviadas), 0)

limpa()
resposta = {"configured": True, "error": "", "players": 4, "list": []}
panel._alerta_de_mudez(conn, sondado, estado(), mudez)
igual("voltou a responder, avisa uma vez", len(enviadas), 1)
panel._alerta_de_mudez(conn, sondado, estado(), mudez)
igual("e nao fica repetindo o alivio", len(enviadas), 1)

# Jogo carregando mapa nao responde e nao pode virar alerta: a contagem so comeca com o
# servico ativo e fora da janela de silencio.
resposta = {"configured": True, "error": "tempo esgotado", "players": None, "list": []}
limpa()
mudez["mudo"] = 0
for _ in range(panel.MUTE_ROUNDS + 2):
    panel._alerta_de_mudez(conn, sondado, estado(service="activating"), mudez)
igual("servico subindo nao conta como mudez", len(enviadas), 0)

# Contagem por log nao pergunta nada ao jogo: nao ha o que ficar mudo.
limpa()
por_log = dict(alvo, player_source="log", query_port=0)
for _ in range(panel.MUTE_ROUNDS + 2):
    panel._alerta_de_mudez(conn, por_log, estado(), {"service": "active"})
igual("contagem por log nao gera alerta de mudez", len(enviadas), 0)


print("Entrada e saida de jogadores")
liga(["jogador-entrou", "jogador-saiu"])
cfg_jog = panel.webhook_config(conn)
srv_jogadores = dict(alvo, player_source="log", query_port=0)

res_players = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
panel.server_players = lambda server, force=False: res_players
memoria_jog = {"reachable": True, "service": "active"}

limpa()
# Primeira olhada: estabelece linha de base, nao avisa quem ja estava jogando
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_jog, cfg_jog)
igual("primeira olhada so anota (linha de base)", len(enviadas), 0)
igual("guardou o jogador online", memoria_jog["jogadores_nomes"], {"Cristopfer"})

# Segunda olhada sem mudanca: nada sai
limpa()
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_jog, cfg_jog)
igual("sem mudanca de jogadores, nao avisa", len(enviadas), 0)

# Jogador novo entra
limpa()
res_players = {"configured": True, "error": "", "players": 2, "list": [{"name": "Cristopfer"}, {"name": "Ana"}]}
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_jog, cfg_jog)
igual("jogador novo avisa entrada", len(enviadas), 1)
check("mensagem diz quem entrou", "Ana entrou no jogo" in enviadas[0][1], enviadas[0][1])
check("mensagem mostra contagem", "2 jogadores online" in enviadas[0][1], enviadas[0][1])

# Jogador sai
limpa()
res_players = {"configured": True, "error": "", "players": 1, "list": [{"name": "Cristopfer"}]}
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_jog, cfg_jog)
igual("jogador saindo avisa saida", len(enviadas), 1)
check("mensagem diz quem saiu", "Ana saiu do jogo" in enviadas[0][1], enviadas[0][1])

# Ultimo jogador sai
limpa()
res_players = {"configured": True, "error": "", "players": 0, "list": []}
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_jog, cfg_jog)
igual("ultimo jogador saindo avisa", len(enviadas), 1)
check("detalhe diz nenhum jogador", "nenhum jogador online" in enviadas[0][1], enviadas[0][1])

# Servidor so com contagem (sem nomes)
limpa()
res_players = {"configured": True, "error": "", "players": 0, "list": []}
memoria_count = {"reachable": True, "service": "active"}
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_count, cfg_jog)
res_players = {"configured": True, "error": "", "players": 3, "list": []}
panel._alerta_de_jogadores(conn, srv_jogadores, "active", memoria_count, cfg_jog)
igual("contagem numerica subindo avisa", len(enviadas), 1)
check("detalhe avisa variacao", "3 jogadores conectaram" in enviadas[0][1], enviadas[0][1])

# Servico parado / reiniciando nao manda alerta falso de saida
limpa()
memoria_jog = {"reachable": True, "service": "active", "jogadores_nomes": {"Cristopfer"}, "jogadores_count": 1}
panel._alerta_de_jogadores(conn, srv_jogadores, "failed", memoria_jog, cfg_jog)
igual("servico parado nao dispara alerta de saida", len(enviadas), 0)
igual("e a memoria reseta", memoria_jog["jogadores_nomes"], None)

# --------------------------------------------------- a volta rapida do monitor
# Jogador entrando precisa chegar em segundos, nao no minuto seguinte: quem recebe o
# aviso costuma querer entrar junto. A volta rapida existe para isso — e ela nao pode
# custar SSH, senao acelerar o alerta multiplicaria a conta de todo o resto.
print("Volta rapida so para jogadores")
liga(["jogador-entrou", "jogador-saiu", "caiu"])
with conn:
    conn.execute("DELETE FROM jobs")
    conn.execute("UPDATE servers SET player_source = 'log', query_port = 0")

idas_de_ssh = []


def status_contado(server, force=False):
    idas_de_ssh.append(int(server["id"]))
    return estado()


panel.server_status = status_contado
panel.server_metrics = lambda server, force=False: {"disks": []}
res_players = {"configured": True, "error": "", "players": 0, "list": []}

limpa()
with panel.app.app_context():
    # Relogios vencidos = volta COMPLETA. Sao precisas duas: a primeira anota o
    # estado do servidor, a segunda a linha de base dos jogadores.
    relogios_vencidos()
    panel.monitora_servidores()
    relogios_vencidos()
    panel.monitora_servidores()
igual("a volta completa consultou o systemd", len(idas_de_ssh), 2)

# Agora a volta RAPIDA. Os relogios recuam 20s: o do estado (60s) ainda nao venceu, o
# dos jogadores (15s) sim — que e exatamente a situacao no meio de dois minutos.
idas_de_ssh.clear()
panel._ultimo_monitor = panel._ultimo_estado = time.monotonic() - 20
res_players = {"configured": True, "error": "", "players": 1, "list": [{"name": "Ana"}]}
with panel.app.app_context():
    panel.monitora_servidores()
check("a entrada chega na volta rapida",
      any("Ana entrou no jogo" in t for _, t in enviadas), enviadas)
igual("e ela nao gastou nenhuma ida de SSH", idas_de_ssh, [])

# O passo curto so existe por causa do evento de jogador. Sem ele os mesmos 20s nao
# bastam, e o monitor continua no ritmo de antes — ninguem paga SSH a mais de graca.
liga(["caiu"])
panel._ultimo_monitor = panel._ultimo_estado = time.monotonic() - 20
with panel.app.app_context():
    igual("sem alerta de jogador, 20s ainda nao e hora",
          panel.monitora_servidores(), 0)


print("Erro no log do jogo")
liga(["erro-no-log"])
linhas = ["tudo bem por aqui", "Fatal error: world corrupted", "seguindo"]
panel.read_log_lines = lambda server, limite=0: linhas
com_regex = dict(alvo, error_re="Fatal error")
memoria = {}

limpa()
panel._alerta_de_log(conn, com_regex, memoria)
igual("erro no log avisa", len(enviadas), 1)
check("e leva a linha inteira", "world corrupted" in enviadas[0][1], enviadas[0][1])

# A mesma linha continua no rabo do log na volta seguinte. Avisar de novo seria um
# alerta por minuto ate alguem arrumar.
limpa()
panel._alerta_de_log(conn, com_regex, memoria)
igual("a mesma linha nao avisa duas vezes", len(enviadas), 0)

# Cooldown: mesmo com linha nova, o canal nao leva uma enxurrada de uma expressao larga.
limpa()
linhas = ["Fatal error: outra coisa"]
panel._alerta_de_log(conn, com_regex, memoria)
igual("linha nova dentro da janela nao passa", len(enviadas), 0)
check("mas a memoria acompanha a linha nova",
      "outra coisa" in memoria["ultimo_erro"], memoria["ultimo_erro"])

# Passada a janela, um erro novo volta a avisar.
memoria["erro_em"] = 0
limpa()
linhas = ["Fatal error: mais uma"]
panel._alerta_de_log(conn, com_regex, memoria)
igual("passado o cooldown, avisa de novo", len(enviadas), 1)

limpa()
linhas = ["nada de mais aqui"]
panel._alerta_de_log(conn, com_regex, memoria)
igual("log limpo nao avisa", len(enviadas), 0)
igual("e a memoria do erro e esquecida", memoria["ultimo_erro"], "")

limpa()
panel._alerta_de_log(conn, alvo, {})
igual("servidor sem expressao nem chega a ler o log", len(enviadas), 0)

# Expressao torta e problema de cadastro, nao motivo para derrubar a volta do monitor.
limpa()
panel._alerta_de_log(conn, dict(alvo, error_re="("), {})
igual("expressao invalida nao estoura", len(enviadas), 0)


print("Disco cheio")
liga(["disco-cheio"], disco=90)
discos = {"disks": [{"mount": "/", "pct": 40.0, "used": 4, "total": 10},
                    {"mount": "/opt/game", "pct": 95.0, "used": 95, "total": 100}]}
panel.server_metrics = lambda server, force=False: discos

# Aqui a memoria do monitor NAO pode ser zerada entre as chamadas: e justamente ela que
# guarda "este disco ja estava cheio da ultima vez".
limpa()
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("passou do limite, avisa", len(enviadas), 1)
check("avisa sobre o disco MAIS cheio, nao o primeiro", "/opt/game" in enviadas[0][1])

# Um disco a 95% continua a 95% no minuto seguinte: avisar de novo seria spam ate alguem
# arrumar, e o canal deixaria de ser lido.
enviadas.clear()
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("continua cheio, nao repete", len(enviadas), 0)

# Depois de liberar espaco a marca cai, e uma nova subida volta a avisar.
discos = {"disks": [{"mount": "/opt/game", "pct": 40.0, "used": 40, "total": 100}]}
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("voltar ao normal nao avisa (esse evento nao existe)", len(enviadas), 0)
discos = {"disks": [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]}
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("encheu de novo, avisa de novo", len(enviadas), 1)

# Medidor que falhou nao pode virar alerta de disco vazio nem estourar.
discos = {"error": "tempo esgotado"}
enviadas.clear()
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("medidor com erro nao avisa nada", len(enviadas), 0)
# ...e nao pode apagar a marca de que o disco estava cheio.
discos = {"disks": [{"mount": "/opt/game", "pct": 97.0, "used": 97, "total": 100}]}
panel._alerta_de_disco(conn, alvo, panel.webhook_config(conn))
igual("depois de um erro no medidor, o disco cheio nao vira alerta repetido",
      len(enviadas), 0)


print("Memoria quase cheia")
liga(["memoria-alta"], memoria=90)
GIB = 1024 ** 3
memoria = {"mem": {"pct": 95.0, "used": 3.8 * GIB, "total": 4.0 * GIB}}
panel.server_metrics = lambda server, force=False: memoria

# Como no disco, a memoria do monitor NAO pode ser zerada entre as chamadas: e ela que
# guarda "isto ja estava cheio da ultima vez".
limpa()
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("passou do limite, avisa", len(enviadas), 1)
check("a mensagem traz a porcentagem e o tamanho legivel",
      "95.0%" in enviadas[0][1] and "3.8 GB" in enviadas[0][1] and
      "4.0 GB" in enviadas[0][1], enviadas)

enviadas.clear()
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("continua cheia, nao repete", len(enviadas), 0)

# Liberou memoria: a marca cai e uma nova subida volta a avisar.
memoria = {"mem": {"pct": 40.0, "used": 1.6 * GIB, "total": 4.0 * GIB}}
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("baixou, nao avisa (esse evento nao existe)", len(enviadas), 0)
memoria = {"mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}}
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("encheu de novo, avisa de novo", len(enviadas), 1)

# Medidor que falhou nao pode virar alerta nem estourar...
memoria = {"error": "tempo esgotado"}
enviadas.clear()
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("medidor com erro nao avisa nada", len(enviadas), 0)
# ...e nao pode apagar a marca de que a memoria estava cheia.
memoria = {"mem": {"pct": 97.0, "used": 3.9 * GIB, "total": 4.0 * GIB}}
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("depois de um erro no medidor, a memoria cheia nao vira alerta repetido",
      len(enviadas), 0)

# Container sem teto de memoria legivel devolve pct None. Comparar None com o limite
# estouraria a volta inteira do monitor, e tratar como 0 esconderia o problema.
memoria = {"mem": {"pct": None, "used": 0, "total": 0}}
limpa()
panel._alerta_de_memoria(conn, alvo, panel.webhook_config(conn))
igual("sem medida de memoria nao avisa", len(enviadas), 0)


print("CPU alta")
liga(["cpu-alta"], cpu=90)
uso = {"cpu_pct": 94.5, "cores": 4, "proc": {"cpu_pct": 92.1}}
panel.server_metrics = lambda server, force=False: uso

limpa()
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("passou do limite, avisa", len(enviadas), 1)
# Sem os nucleos, "94.5%" nao diz se e uma maquina afogada ou um nucleo de quatro; e sem
# a fatia do jogo nao da para saber se o culpado e o servidor ou outra coisa no container.
check("a mensagem traz os nucleos e a fatia do jogo",
      "94.5%" in enviadas[0][1] and "4 nucleos" in enviadas[0][1] and
      "jogo: 92.1%" in enviadas[0][1], enviadas)

enviadas.clear()
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("continua alta, nao repete", len(enviadas), 0)

uso = {"cpu_pct": 12.0, "cores": 4, "proc": {}}
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("baixou, nao avisa (esse evento nao existe)", len(enviadas), 0)
uso = {"cpu_pct": 99.0, "cores": 1, "proc": {}}
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("subiu de novo, avisa de novo", len(enviadas), 1)
check("um nucleo so nao vira plural", "em 1 nucleo" in enviadas[0][1] and
      "nucleos" not in enviadas[0][1], enviadas)
# Sem PID do jogo o medidor nao tem a fatia dele; a mensagem so omite esse pedaco.
check("sem a fatia do jogo, a mensagem nao inventa", "jogo:" not in enviadas[0][1],
      enviadas)

# Duas amostras sao o minimo para calcular uso de CPU; com uma so o medidor devolve None.
uso = {"cpu_pct": None, "cores": 4, "proc": {}}
limpa()
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("sem amostra de CPU nao avisa", len(enviadas), 0)

uso = {"error": "tempo esgotado"}
panel._alerta_de_cpu(conn, alvo, panel.webhook_config(conn))
igual("medidor com erro nao avisa nada", len(enviadas), 0)


print("O monitor liga os tres medidores")
# Disco, memoria e CPU saem da mesma leitura e correm no mesmo relogio. E facil ligar o
# evento na tela e esquecer o fio dentro da volta do monitor: entao a volta e testada.
apertado = {"disks": [{"mount": "/", "pct": 99.0, "used": 99, "total": 100}],
            "mem": {"pct": 99.0, "used": 99, "total": 100},
            "cpu_pct": 99.0, "cores": 2, "proc": {}}
panel.server_metrics = lambda server, force=False: apertado
panel.server_status = lambda server, force=False: estado()

liga(["disco-cheio", "memoria-alta", "cpu-alta"])
limpa()
with panel.app.app_context():
    panel.monitora_servidores(forcar=True)   # a primeira volta so anota
    panel.monitora_servidores(forcar=True)
texto = "\n".join(t for _, t in enviadas)
check("a volta do monitor dispara os tres",
      "disco quase cheio" in texto and "memoria quase cheia" in texto and
      "uso de CPU alto" in texto, enviadas)

# E o contrario: evento desmarcado na tela nao pode sair de carona nos outros.
liga(["disco-cheio"])
limpa()
with panel.app.app_context():
    panel.monitora_servidores(forcar=True)
    panel.monitora_servidores(forcar=True)
texto = "\n".join(t for _, t in enviadas)
check("so o disco esta ligado, so o disco sai",
      "disco quase cheio" in texto and "memoria quase cheia" not in texto and
      "uso de CPU alto" not in texto, enviadas)


print("Diario de alertas")
# O diario e a resposta para "nao chega nada no Discord": sem ele, alerta que nao
# aconteceu e alerta que nao saiu sao a mesma tela vazia.
liga(["caiu"])
with conn:
    conn.execute("DELETE FROM alert_log")
limpa()
panel.notifica(conn, "caiu", "Palworld: parou", "detalhe")
diario = panel.alertas_recentes(conn)
igual("o envio vira uma linha", len(diario), 1)
igual("com o destino e o estado", (diario[0]["evento"], diario[0]["status"]),
      ("caiu", "enviado"))

# Evento que ninguem marcou: e o caso mais comum de canal mudo, e precisa ficar
# registrado com essa cara — senao a pessoa procura defeito onde nao ha.
panel.notifica(conn, "cpu-alta", "Palworld: CPU alta", "99%")
diario = panel.alertas_recentes(conn)
igual("alerta sem ninguem escutando tambem e registrado", diario[0]["status"],
      "sem-destino")
igual("e diz qual evento se perdeu", diario[0]["evento"], "cpu-alta")

# Webhook fora do ar tem de aparecer como falha, com o motivo junto.
panel.envia_webhook = lambda url, texto: "500 Internal Server Error"
panel.notifica(conn, "caiu", "Palworld: parou de novo", "")
panel.envia_webhook = captura
diario = panel.alertas_recentes(conn)
igual("envio que falhou fica marcado", diario[0]["status"], "falhou")
check("com o motivo do lado", "500" in diario[0]["erro"], diario[0])

# O diario nao pode crescer para sempre nem apagar o que interessa.
guardado = panel.ALERT_LOG_KEEP
panel.ALERT_LOG_KEEP = 3
for i in range(6):
    panel.notifica(conn, "caiu", f"alerta {i}", "")
with panel.app.app_context():
    panel.limpa_historico(forcar=True)
diario = panel.alertas_recentes(conn)
igual("a limpeza segura o tamanho", len(diario), 3)
check("e guarda os mais NOVOS", "alerta 5" in diario[0]["titulo"], diario[0])
panel.ALERT_LOG_KEEP = guardado


print("Uma tarefa quebrada nao cala as outras")
# O bug que fez tudo emudecer: as quatro tarefas do relogio dividiam um try so, entao
# uma excecao em roda_agendamentos matava o monitor no mesmo tique — para sempre, porque
# a tarefa quebrada quebrava de novo a cada volta.
liga(["caiu"])
with conn:
    conn.execute("DELETE FROM alert_log")
    # Job recente de um teste anterior abriria a janela de silencio e engoliria o alerta
    # de queda — o que se quer medir aqui e a tarefa quebrada, nao a janela.
    conn.execute("DELETE FROM jobs")
limpa()
agendamentos_real = panel.roda_agendamentos


def explode():
    raise RuntimeError("agenda quebrada de proposito")


panel.roda_agendamentos = explode
panel.server_metrics = lambda server, force=False: {"disks": []}
panel.server_status = lambda server, force=False: estado()
# Relogios vencidos: cada tique vale uma volta COMPLETA, com consulta de estado.
relogios_vencidos()
with panel.app.app_context():
    panel._scheduler_tick()                       # linha de base
panel.server_status = lambda server, force=False: estado(service="inactive")
relogios_vencidos()
with panel.app.app_context():
    panel._scheduler_tick()
panel.roda_agendamentos = agendamentos_real

texto = "\n".join(t for _, t in enviadas)
check("o monitor roda mesmo com a agenda quebrada", "parou de rodar" in texto, enviadas)
falhas_no_diario = [a for a in panel.alertas_recentes(conn)
                    if a["status"] == "erro-interno"]
check("e a quebra fica visivel no diario", falhas_no_diario, "nada registrado")
check("dizendo qual tarefa caiu", "agendamentos" in falhas_no_diario[0]["titulo"],
      falhas_no_diario[0] if falhas_no_diario else "")


print("Linha de base ao subir o painel")
liga(["caiu", "inacessivel"])
panel.server_metrics = lambda server, force=False: {"disks": []}
panel.server_status = lambda server, force=False: {"reachable": True,
                                                   "service": "inactive", "error": ""}
limpa()
with panel.app.app_context():
    panel.monitora_servidores(forcar=True)
igual("primeira olhada so anota", len(enviadas), 0)
igual("o estado ficou guardado", panel._estado_monitor[sid]["service"], "inactive")

# Agora que ha linha de base, a mudanca avisa.
panel.server_status = lambda server, force=False: {"reachable": False,
                                                   "service": "inacessivel", "error": "x"}
with panel.app.app_context():
    panel.monitora_servidores(forcar=True)
igual("a partir dai, a mudanca avisa", len(enviadas), 1)

# Servidor removido do painel nao pode ficar guardando estado para sempre.
with conn:
    conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
with panel.app.app_context():
    panel.monitora_servidores(forcar=True)
check("servidor removido sai da memoria do monitor", sid not in panel._estado_monitor)


print("URL invalida nao chega a sair")
panel.envia_webhook = envia_real
# A checagem acontece ANTES de qualquer socket: URL torta nao vira tentativa de conexao
# (nem espera de timeout) escondida atras de uma mensagem de rede.
check("recusa o que nao e http(s)",
      envia_real("nao-e-url", "oi").startswith("URL invalida"))
check("recusa endereco vazio", envia_real("", "oi").startswith("URL invalida"))
check("recusa esquema estranho",
      envia_real("file:///etc/passwd", "oi").startswith("URL invalida"))


print("A tela de alertas")
# Daqui para baixo o teste e do fluxo da tela: cadastrar, editar, testar e remover
# destinos. Nada sai para a rede — o capturador volta no lugar do envio.
panel.envia_webhook = captura
with conn:
    conn.execute("DELETE FROM webhooks")
panel._login_fails.clear()
panel.ensure_admin_user("chefe", "senha-do-chefe")

cli = panel.app.test_client()
cli.get("/login")
with cli.session_transaction() as sess:
    entrada = sess.get("csrf", "")
resp = cli.post("/login", data={"username": "chefe", "password": "senha-do-chefe",
                                "csrf": entrada}, follow_redirects=False)
if resp.status_code != 302:
    raise SystemExit(f"login falhou (status {resp.status_code})")


def postar(url, dados=None):
    d = dict(dados or {})
    with cli.session_transaction() as sess:
        d["csrf"] = sess.get("csrf", "")
    return cli.post(url, data=d, follow_redirects=False)


def tela():
    return cli.get("/alertas").get_data(as_text=True)


igual("a tela sem destino nenhum abre", cli.get("/alertas").status_code, 200)
check("e diz que nao ha nada ligado", "nenhum destino ligado" in tela())

SEGREDO = "https://discord.com/api/webhooks/123/tok-que-nao-pode-vazar"
igual("cadastra destino",
      postar("/alertas/destinos", {"nome": "Equipe", "ativo": "1", "url": SEGREDO,
                                   "eventos": ["caiu", "disco-cheio"]}).status_code, 302)
postar("/alertas/destinos", {"nome": "Torto", "url": "nao-e-url"})
igual("URL torta nao vira destino", len(panel.webhooks_lista(conn)), 1)

html = tela()
check("o destino aparece pelo nome", "Equipe" in html)
check("o token NAO chega ao HTML", "tok-que-nao-pode-vazar" not in html)
check("o id fica visivel para reconhecer o canal", "discord.com/.../123" in html)

hid = panel.webhooks_lista(conn)[0]["id"]
# O caminho normal e mexer so nos eventos: a URL fica mascarada e o campo de troca vem
# vazio, entao um POST sem URL NAO pode limpar a que esta salva.
postar(f"/alertas/destinos/{hid}",
       {"nome": "Equipe", "url": "", "ativo": "1", "eventos": ["caiu"]})
atual = panel.webhooks_lista(conn)[0]
igual("salvar com o campo vazio mantem a URL", atual["url"], SEGREDO)
igual("e os eventos mudam", atual["eventos"], {"caiu"})

postar(f"/alertas/destinos/{hid}", {"nome": "Equipe", "url": "", "eventos": ["caiu"]})
igual("sem a caixa 'ativo' o destino desliga",
      panel.webhooks_lista(conn)[0]["ativo"], False)
postar(f"/alertas/destinos/{hid}",
       {"nome": "Equipe", "url": "", "ativo": "1", "eventos": ["caiu"]})

postar("/alertas/destinos", {"nome": "Geral", "ativo": "1",
                             "url": "https://discord.com/api/webhooks/999/outro",
                             "eventos": ["caiu"]})
html = tela()
check("a lista mostra os dois", "Equipe" in html and "Geral" in html)
# Cada destino precisa do seu proprio id de caixa: repetido, clicar no rotulo de um
# marcaria o evento do outro.
check("cada destino tem o seu grupo de caixas",
      'id="h%d-caiu"' % hid in html and 'id="h%d-caiu"' % (hid + 1) in html)

# Testar serve para conferir uma URL ANTES de salvar: se ha uma digitada, e ela que vai.
limpa()
postar(f"/alertas/destinos/{hid}/testar", {"url": "https://novo.invalid/hook"})
igual("testar usa a URL digitada", [u for u, _ in enviadas],
      ["https://novo.invalid/hook"])
limpa()
postar(f"/alertas/destinos/{hid}/testar", {"url": ""})
igual("sem nada digitado, testa a que esta salva", [u for u, _ in enviadas], [SEGREDO])

postar("/alertas", {"disk_pct": "80"})
igual("o limite do disco salva", panel.webhook_config(conn)["disco"], 80)
postar("/alertas", {"disk_pct": "10"})
igual("limite fora da faixa e recusado e o anterior fica",
      panel.webhook_config(conn)["disco"], 80)

postar("/alertas", {"disk_pct": "80", "mem_pct": "85", "cpu_pct": "70"})
igual("o limite da memoria salva", panel.webhook_config(conn)["memoria"], 85)
igual("o limite da CPU salva", panel.webhook_config(conn)["cpu"], 70)
# Um limite recusado nao pode deixar os outros dois ja gravados: a tela volta dizendo
# "recusado" e o operador nao teria como saber que metade da mudanca passou.
postar("/alertas", {"disk_pct": "75", "mem_pct": "10", "cpu_pct": "95"})
igual("memoria fora da faixa e recusada e a anterior fica",
      panel.webhook_config(conn)["memoria"], 85)
igual("e nada e salvo junto com a recusada (disco)",
      panel.webhook_config(conn)["disco"], 80)
igual("e nada e salvo junto com a recusada (CPU)",
      panel.webhook_config(conn)["cpu"], 70)

html = tela()
check("a tela traz os campos de memoria e CPU",
      'name="mem_pct"' in html and 'name="cpu_pct"' in html)
check("com os valores salvos", 'value="85"' in html and 'value="70"' in html)
check("e as caixas dos eventos novos", 'memoria-alta' in html and 'cpu-alta' in html)

postar(f"/alertas/destinos/{hid}/remover")
igual("remover tira da lista", len(panel.webhooks_lista(conn)), 1)

# Evento ligado sem nenhum servidor onde olhar: a tela tem de dizer isso em voz alta.
# Alerta ligado e mudo e pior que desligado — o canal calado passa por "esta tudo bem".
with conn:
    conn.execute("DELETE FROM servers")
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('Sem consulta', '10.0.0.7', 22, 'root', 'x.service', ?)",
        (panel.now_iso(),))
    conn.execute("UPDATE webhooks SET eventos = 'travou,erro-no-log', ativo = 1")
faltando = panel.alertas_sem_base(conn)
igual("acusa os dois eventos sem base", sorted(faltando), ["erro-no-log", "travou"])
html = tela()
check("e a tela mostra o aviso", "Ligado, mas sem onde olhar" in html)

# Configurado o que faltava, o aviso some.
with conn:
    conn.execute("UPDATE servers SET player_source = 'a2s', query_port = 27015,"
                 " error_re = 'Fatal error'")
igual("configurado, nao sobra pendencia", panel.alertas_sem_base(conn), {})
check("e o aviso sai da tela", "Ligado, mas sem onde olhar" not in tela())

# O cadastro precisa gravar a expressao de erro: sem isso o alerta de log nunca liga.
sid_novo = conn.execute("SELECT id FROM servers").fetchone()["id"]
resp = postar(f"/servers/{sid_novo}/edit", {
    "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
    "service": "x.service", "player_source": "none", "error_re": "Out of memory",
})
igual("o cadastro grava a expressao de erro",
      conn.execute("SELECT error_re FROM servers WHERE id = ?",
                   (sid_novo,)).fetchone()["error_re"], "Out of memory")
postar(f"/servers/{sid_novo}/edit", {
    "name": "Sem consulta", "host": "10.0.0.7", "ssh_port": "22", "ssh_user": "root",
    "service": "x.service", "player_source": "none", "error_re": "(",
})
igual("expressao que nao compila e recusada no cadastro",
      conn.execute("SELECT error_re FROM servers WHERE id = ?",
                   (sid_novo,)).fetchone()["error_re"], "Out of memory")

form = cli.get(f"/servers/{sid_novo}/edit").get_data(as_text=True)
check("o cadastro mostra o campo com o valor salvo",
      'name="error_re"' in form and "Out of memory" in form)
check("e o cadastro novo tambem tem o campo",
      'name="error_re"' in cli.get("/servers/new").get_data(as_text=True))

# A tela mexe em credenciais: operador nao entra.
panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERADOR)
outro = panel.app.test_client()
outro.get("/login")
with outro.session_transaction() as sess:
    e2 = sess.get("csrf", "")
outro.post("/login", data={"username": "peao", "password": "senha-do-peao", "csrf": e2})
check("operador nao chega em Alertas",
      outro.get("/alertas").status_code in (302, 403))

conn.close()

print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
