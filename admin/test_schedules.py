#!/usr/bin/env python3
"""Testes do agendamento, da retencao do historico e da tela de historico global.

    docker compose exec panel python3 /opt/gamepanel/test_schedules.py

O que estes testes garantem: uma tarefa dispara na hora certa, NAO dispara duas vezes na
mesma ocorrencia, nao dispara atrasada quando o painel passou a noite fora do ar, e o
historico nao cresce para sempre. A conta do relogio e testada aqui como funcao pura -
sem thread, sem esperar o tempo passar.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

# Banco descartavel: estes testes criam servidores, tarefas e apagam jobs.
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


FUSO = timezone.utc


def quando(dia, hora, minuto=0):
    """Uma quarta-feira (2026-08-19) as HH:MM, para as contas terem um chao fixo."""
    return datetime(2026, 8, dia, hora, minuto, tzinfo=FUSO)


def tarefa(**kw):
    base = {"action": "restart", "kind": "diario", "hour": 5, "minute": 0,
            "weekday": 0, "every_hours": 6, "enabled": 1, "last_run": ""}
    base.update(kw)
    return base


print("Ocorrencia anterior")
# 19/08/2026 e uma quarta-feira.
igual("diario, ja passou hoje",
      panel.ocorrencia_anterior(tarefa(hour=5), quando(19, 14)), quando(19, 5))
igual("diario, ainda nao chegou hoje -> foi ontem",
      panel.ocorrencia_anterior(tarefa(hour=23), quando(19, 2)), quando(18, 23))
# weekday 0 = segunda; de quarta olhando para tras, a segunda foi 17/08.
igual("semanal, dia ja passou nesta semana",
      panel.ocorrencia_anterior(tarefa(kind="semanal", weekday=0, hour=4), quando(19, 10)),
      quando(17, 4))
# weekday 4 = sexta; de quarta, a sexta anterior foi 14/08.
igual("semanal, dia ainda nao chegou -> semana passada",
      panel.ocorrencia_anterior(tarefa(kind="semanal", weekday=4, hour=4), quando(19, 10)),
      quando(14, 4))
# No proprio dia, antes da hora, tem de recuar uma semana inteira.
igual("semanal, hoje e o dia mas a hora nao chegou",
      panel.ocorrencia_anterior(tarefa(kind="semanal", weekday=2, hour=23), quando(19, 1)),
      quando(12, 23))
igual("intervalo nao tem ocorrencia fixa",
      panel.ocorrencia_anterior(tarefa(kind="intervalo"), quando(19, 10)), None)


print("Quando a tarefa vence")
agora = quando(19, 5, 0)
check("diario dispara na hora", panel.venceu(tarefa(hour=5), agora))
check("diario nao dispara antes da hora", not panel.venceu(tarefa(hour=6), quando(19, 5, 59)))
# Ja rodou nesta ocorrencia: o relogio acorda a cada 30s e nao pode repetir.
check("nao repete a mesma ocorrencia",
      not panel.venceu(tarefa(hour=5, last_run=quando(19, 5, 0).isoformat()), quando(19, 5, 30)))
check("no dia seguinte volta a valer",
      panel.venceu(tarefa(hour=5, last_run=quando(19, 5, 0).isoformat()), quando(20, 5, 1)))

# Painel fora do ar a noite inteira: as 14h ninguem quer o restart das 5h caindo no meio
# da partida. A tolerancia e GRACE (1h por padrao).
check("atrasada alem da tolerancia nao dispara",
      not panel.venceu(tarefa(hour=5), quando(19, 14)))
check("atrasada dentro da tolerancia ainda dispara",
      panel.venceu(tarefa(hour=5), quando(19, 5, 30)))

check("intervalo sem last_run dispara", panel.venceu(tarefa(kind="intervalo"), agora))
check("intervalo nao dispara antes de completar",
      not panel.venceu(tarefa(kind="intervalo", every_hours=6,
                              last_run=quando(19, 2).isoformat()), quando(19, 5)))
check("intervalo dispara ao completar",
      panel.venceu(tarefa(kind="intervalo", every_hours=6,
                          last_run=quando(19, 2).isoformat()), quando(19, 8)))
# last_run ilegivel (banco mexido a mao) nao pode travar a tarefa para sempre.
check("last_run invalido nao trava a tarefa",
      panel.venceu(tarefa(hour=5, last_run="isto nao e uma data"), agora))


print("Rotulos")
igual("diario", panel.rotulo_agendamento(tarefa(hour=5, minute=30)), "todo dia as 05:30")
# Concordancia: "toda segunda" (de segunda-feira) mas "todo domingo".
igual("semanal, dia feminino",
      panel.rotulo_agendamento(tarefa(kind="semanal", weekday=0, hour=3)), "toda segunda as 03:00")
igual("semanal, dia masculino",
      panel.rotulo_agendamento(tarefa(kind="semanal", weekday=6, hour=3)), "todo domingo as 03:00")
igual("semanal, sabado tambem",
      panel.rotulo_agendamento(tarefa(kind="semanal", weekday=5, hour=3)), "todo sabado as 03:00")
igual("intervalo", panel.rotulo_agendamento(tarefa(kind="intervalo", every_hours=6)), "a cada 6h")
igual("intervalo de uma hora", panel.rotulo_agendamento(tarefa(kind="intervalo", every_hours=1)),
      "a cada hora")


print("Retencao do historico")
panel.ensure_admin_user("chefe", "senha-do-chefe")
panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERADOR)
conn = panel._connect()
with conn:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
        " created_at) VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service',"
        " '/opt/game/Saved', ?)", (panel.now_iso(),),
    )
    sid = conn.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]
    velho = (datetime.now(timezone.utc) - timedelta(days=panel.JOBS_KEEP_DAYS + 5)).isoformat()
    novo = panel.now_iso()
    for quantos, carimbo in ((4, velho), (3, novo)):
        for _ in range(quantos):
            conn.execute(
                "INSERT INTO jobs (server_id, target, action, status, output, username,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (sid, "root@alvo", "start", "ok", "", "chefe", carimbo),
            )
conn.close()

with panel.app.app_context():
    apagados = panel.limpa_historico(forcar=True)
igual("os antigos sairam", apagados, 4)
conn = panel._connect()
igual("os recentes ficaram",
      conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 3)
conn.close()


print("Agendamento pelas telas")


def cliente():
    return panel.app.test_client()


def entrar(username, senha):
    cli = cliente()
    cli.get("/login")
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    resp = cli.post("/login", data={"username": username, "password": senha, "csrf": token})
    if resp.status_code != 302:
        raise SystemExit(f"login de {username} falhou ({resp.status_code})")
    return cli


def postar(cli, url, dados=None):
    dados = dict(dados or {})
    with cli.session_transaction() as sess:
        dados["csrf"] = sess.get("csrf", "")
    return cli.post(url, data=dados, follow_redirects=False)


panel._login_fails.clear()
chefe = entrar("chefe", "senha-do-chefe")
peao = entrar("peao", "senha-do-peao")

igual("operador ve a tela", peao.get(f"/servers/{sid}/agendamentos").status_code, 200)
igual("operador nao agenda",
      postar(peao, f"/servers/{sid}/agendamentos",
             {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"}).status_code, 403)

igual("admin agenda",
      postar(chefe, f"/servers/{sid}/agendamentos",
             {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"}).status_code, 302)
conn = panel._connect()
t = conn.execute("SELECT * FROM schedules WHERE server_id = ?", (sid,)).fetchone()
conn.close()
igual("tarefa gravada", (t["action"], t["kind"], t["hour"]), ("restart", "diario", 5))
igual("diario comeca sem last_run (a ocorrencia de hoje ainda vale)", t["last_run"], "")

# 'intervalo' comeca a contar de agora: sem isto ele dispararia no instante em que
# fosse salvo, o que ninguem espera de um agendamento.
postar(chefe, f"/servers/{sid}/agendamentos", {"action": "backup", "kind": "intervalo",
                                               "every_hours": "6"})
conn = panel._connect()
inter = conn.execute("SELECT * FROM schedules WHERE kind = 'intervalo'").fetchone()
conn.close()
check("intervalo ja nasce com o relogio zerado", inter["last_run"] != "")

# Valores fora da faixa nao podem entrar no banco (a hora vai para o strftime da tela).
antes = 2
for ruim in ({"action": "restart", "kind": "diario", "hour": "99", "minute": "0"},
             {"action": "restart", "kind": "diario", "hour": "5", "minute": "-3"},
             {"action": "formatar-tudo", "kind": "diario", "hour": "5", "minute": "0"},
             {"action": "restart", "kind": "quando-der", "hour": "5", "minute": "0"},
             {"action": "backup", "kind": "intervalo", "every_hours": "0"},
             {"action": "backup", "kind": "intervalo", "every_hours": "99999"}):
    postar(chefe, f"/servers/{sid}/agendamentos", ruim)
conn = panel._connect()
igual("nenhuma tarefa invalida entrou",
      conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], antes)
conn.close()

igual("operador nao liga/desliga",
      postar(peao, f"/agendamentos/{t['id']}/alternar").status_code, 403)
igual("operador nao remove", postar(peao, f"/agendamentos/{t['id']}/remover").status_code, 403)
igual("operador nao roda na hora", postar(peao, f"/agendamentos/{t['id']}/rodar").status_code, 403)

postar(chefe, f"/agendamentos/{t['id']}/alternar")
conn = panel._connect()
igual("admin desliga", conn.execute(
    "SELECT enabled FROM schedules WHERE id = ?", (t["id"],)).fetchone()[0], 0)
conn.close()

# Tarefa desligada some do laco do relogio: e o que 'desligar' tem de significar.
with panel.app.app_context():
    conn = panel.db()
    ligadas = conn.execute("SELECT COUNT(*) FROM schedules WHERE enabled = 1").fetchone()[0]
igual("a desligada saiu da conta do relogio", ligadas, 1)

postar(chefe, f"/agendamentos/{t['id']}/remover")
conn = panel._connect()
igual("admin remove", conn.execute(
    "SELECT COUNT(*) FROM schedules WHERE id = ?", (t["id"],)).fetchone()[0], 0)

# ON DELETE CASCADE: tirar o servidor do painel tem de levar o que estava agendado junto,
# senao o relogio ficaria tentando disparar para um servidor que nao existe mais.
with conn:
    conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
igual("apagar o servidor leva as tarefas dele",
      conn.execute("SELECT COUNT(*) FROM schedules WHERE server_id = ?", (sid,)).fetchone()[0], 0)
conn.close()


print("Historico global")
igual("a tela abre", chefe.get("/historico").status_code, 200)
igual("filtro por usuario", chefe.get("/historico?usuario=chefe").status_code, 200)
igual("filtro por acao", chefe.get("/historico?acao=start").status_code, 200)
igual("filtro por servidor invalido nao quebra", chefe.get("/historico?servidor=abc").status_code, 200)
igual("pagina invalida nao quebra", chefe.get("/historico?p=-5").status_code, 200)
igual("acao inventada e ignorada", chefe.get("/historico?acao=formatar").status_code, 200)

# O corte de papel do historico por servidor vale igual no global.
conn = panel._connect()
with conn:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('outro', 'outro.invalid', 22, 'root', 'jogo.service', ?)", (panel.now_iso(),))
sid2 = conn.execute("SELECT id FROM servers WHERE name = 'outro'").fetchone()["id"]
with conn:
    conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, output, command, username,"
        " created_at) VALUES (?,?,?,?,?,?,?,?)",
        (sid2, "root@outro", "shell", "ok", "SEGREDO-NO-GLOBAL", "SEGREDO-NO-GLOBAL",
         "chefe", panel.now_iso()),
    )
conn.close()
check("operador nao ve o console no historico global",
      "SEGREDO-NO-GLOBAL" not in peao.get("/historico").get_data(as_text=True))
check("admin ve",
      "SEGREDO-NO-GLOBAL" in chefe.get("/historico").get_data(as_text=True))


print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
