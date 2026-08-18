#!/usr/bin/env python3
"""Testes dos alertas por webhook.

    docker compose exec panel python3 /opt/gamepanel/test_alerts.py

O envio de verdade e trocado por um capturador: o que se testa aqui e QUANDO o painel
decide avisar, que e onde mora a chance de errar. Alerta a mais vira ruido e o canal
deixa de ser lido; alerta a menos e um servidor caido as 3h que ninguem descobre.
"""
import os
import tempfile
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


URL = "http://exemplo.invalid/hook"
conn = panel._connect()


def liga(eventos, disco=90):
    panel.config_set(conn, "webhook_url", URL)
    panel.config_set(conn, "webhook_events", ",".join(eventos))
    panel.config_set(conn, "webhook_disk_pct", str(disco))


servidor = {"id": 1, "name": "Palworld", "host": "10.0.0.9", "ssh_user": "root",
            "service": "palworld.service"}


def estado(reachable=True, service="active", error=""):
    return {"reachable": reachable, "service": service, "error": error}


print("Configuracao")
liga(["caiu"])
cfg = panel.webhook_config(conn)
igual("url lida do banco", cfg["url"], URL)
igual("evento lido do banco", cfg["eventos"], {"caiu"})
# Evento inventado (banco mexido a mao, versao antiga) nao pode virar chave desconhecida.
panel.config_set(conn, "webhook_events", "caiu,formatar-o-disco")
igual("evento desconhecido e descartado", panel.webhook_config(conn)["eventos"], {"caiu"})
panel.config_set(conn, "webhook_disk_pct", "5")
igual("limite de disco tem piso", panel.webhook_config(conn)["disco"], 50)
panel.config_set(conn, "webhook_disk_pct", "nao e numero")
igual("limite ilegivel cai no padrao", panel.webhook_config(conn)["disco"],
      panel.DISK_PCT_DEFAULT)


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

# Sem URL nada sai, nem com todos os eventos ligados.
limpa()
panel.config_set(conn, "webhook_url", "")
igual("sem URL nao sai nada",
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

conn.close()

print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
