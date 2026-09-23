#!/usr/bin/env python3
"""Testes do agendamento, da retencao do historico e da tela de historico global.

    pytest admin/test_schedules.py

O que estes testes garantem: uma tarefa dispara na hora certa, NAO dispara duas vezes na
mesma ocorrencia, nao dispara atrasada quando o painel passou a noite fora do ar, e o
historico nao cresce para sempre. A conta do relogio e testada aqui como funcao pura -
sem thread, sem esperar o tempo passar.
"""
from datetime import datetime, timedelta, timezone

import pytest

from gamepanel import app as panel

TZ = timezone.utc


def when_at(day, clock_at, minute=0):
    """Uma quarta-feira (2026-08-19) as HH:MM, para as contas terem um chao fixo."""
    return datetime(2026, 8, day, clock_at, minute, tzinfo=TZ)


def task(**kw):
    base = {"action": "restart", "kind": "diario", "hour": 5, "minute": 0,
            "weekday": 0, "every_hours": 6, "enabled": 1, "last_run": ""}
    base.update(kw)
    return base


# --------------------------------------------------------- ocorrencia anterior

@pytest.mark.parametrize("label,sched,now,expected", [
    ("diario, ja passou hoje", task(hour=5), when_at(19, 14), when_at(19, 5)),
    ("diario, ainda nao chegou hoje -> foi ontem",
     task(hour=23), when_at(19, 2), when_at(18, 23)),
    # weekday 0 = segunda; de quarta olhando para tras, a segunda foi 17/08.
    ("semanal, dia ja passou nesta semana",
     task(kind="semanal", weekday=0, hour=4), when_at(19, 10), when_at(17, 4)),
    # weekday 4 = sexta; de quarta, a sexta anterior foi 14/08.
    ("semanal, dia ainda nao chegou -> semana passada",
     task(kind="semanal", weekday=4, hour=4), when_at(19, 10), when_at(14, 4)),
    # No proprio dia, antes da hora, tem de recuar uma semana inteira.
    ("semanal, hoje e o dia mas a hora nao chegou",
     task(kind="semanal", weekday=2, hour=23), when_at(19, 1), when_at(12, 23)),
    ("intervalo nao tem ocorrencia fixa", task(kind="intervalo"), when_at(19, 10), None),
])
def test_ocorrencia_anterior(label, sched, now, expected):
    assert panel.previous_occurrence(sched, now) == expected, label


# ------------------------------------------------------------- quando vence

def test_diario_dispara_na_hora_e_nao_antes():
    assert panel.is_due(task(hour=5), when_at(19, 5, 0))
    assert not panel.is_due(task(hour=6), when_at(19, 5, 59))


def test_nao_repete_a_mesma_ocorrencia():
    """O relogio acorda a cada 30s e nao pode repetir um disparo ja feito."""
    already_ran = task(hour=5, last_run=when_at(19, 5, 0).isoformat())
    assert not panel.is_due(already_ran, when_at(19, 5, 30))
    assert panel.is_due(already_ran, when_at(20, 5, 1)), "no dia seguinte volta a valer"


def test_atraso_alem_da_tolerancia_nao_dispara():
    """Painel fora do ar a noite inteira: as 14h ninguem quer o restart das 5h no meio
    da partida. A tolerancia e GRACE (1h por padrao)."""
    assert not panel.is_due(task(hour=5), when_at(19, 14))
    assert panel.is_due(task(hour=5), when_at(19, 5, 30)), "dentro da tolerancia ainda dispara"


def test_intervalo_conta_a_partir_do_ultimo_disparo():
    assert panel.is_due(task(kind="intervalo"), when_at(19, 5)), "sem last_run, dispara"
    did_not_finish = task(kind="intervalo", every_hours=6, last_run=when_at(19, 2).isoformat())
    assert not panel.is_due(did_not_finish, when_at(19, 5))
    completed = task(kind="intervalo", every_hours=6, last_run=when_at(19, 2).isoformat())
    assert panel.is_due(completed, when_at(19, 8))


def test_last_run_ilegivel_nao_trava_a_tarefa():
    """Banco mexido a mao nao pode fazer uma tarefa nunca mais disparar."""
    crooked = task(hour=5, last_run="isto nao e uma data")
    assert panel.is_due(crooked, when_at(19, 5))


# -------------------------------------------------------------------- rotulos

@pytest.mark.parametrize("label,sched,expected", [
    ("diario", task(hour=5, minute=30), "todo dia as 05:30"),
    # Concordancia: "toda segunda" (de segunda-feira) mas "todo domingo".
    ("semanal, dia feminino",
     task(kind="semanal", weekday=0, hour=3), "toda segunda as 03:00"),
    ("semanal, dia masculino",
     task(kind="semanal", weekday=6, hour=3), "todo domingo as 03:00"),
    ("semanal, sabado tambem",
     task(kind="semanal", weekday=5, hour=3), "todo sabado as 03:00"),
    ("intervalo", task(kind="intervalo", every_hours=6), "a cada 6h"),
    ("intervalo de uma hora", task(kind="intervalo", every_hours=1), "a cada hora"),
])
def test_rotulo_agendamento(label, sched, expected):
    assert panel.schedule_label(sched) == expected, label


# --------------------------------------------------------- retencao do historico

def test_jobs_antigos_saem_na_limpeza(database):
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service',"
            " '/opt/game/Saved', ?)", (panel.now_iso(),))
    sid = database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]
    old_one = (datetime.now(timezone.utc) - timedelta(days=panel.JOBS_KEEP_DAYS + 5)).isoformat()
    fresh = panel.now_iso()
    with database:
        for how_many, stamp in ((4, old_one), (3, fresh)):
            for _ in range(how_many):
                database.execute(
                    "INSERT INTO jobs (server_id, target, action, status, output, username,"
                    " created_at) VALUES (?,?,?,?,?,?,?)",
                    (sid, "root@alvo", "start", "ok", "", "chefe", stamp))

    with panel.app.app_context():
        deleted = panel.clean_history(force=True)
    assert deleted == 4
    assert database.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3


# ------------------------------------------------------------ agendar pelas telas

@pytest.fixture
def server(database) -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service',"
            " '/opt/game/Saved', ?)", (panel.now_iso(),))
    return database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


def test_operador_ve_a_tela_mas_nao_agenda(server, admin, operator, post):
    assert operator.get(f"/servers/{server}/schedules").status_code == 200
    resp = post(operator, f"/servers/{server}/schedules",
                  {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    assert resp.status_code == 403


def test_admin_agenda_uma_tarefa_diaria(server, admin, database, post):
    resp = post(admin, f"/servers/{server}/schedules",
                  {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    assert resp.status_code == 302

    t = database.execute("SELECT * FROM schedules WHERE server_id = ?", (server,)).fetchone()
    assert (t["action"], t["kind"], t["hour"]) == ("restart", "diario", 5)
    assert t["last_run"] == "", "diario comeca sem last_run (a ocorrencia de hoje ainda vale)"


def test_intervalo_nasce_com_o_relogio_zerado(server, admin, database, post):
    """Sem isto 'a cada 6h' dispararia no instante em que fosse salvo."""
    post(admin, f"/servers/{server}/schedules",
           {"action": "backup", "kind": "intervalo", "every_hours": "6"})
    inter = database.execute("SELECT * FROM schedules WHERE kind = 'intervalo'").fetchone()
    assert inter["last_run"] != ""


@pytest.mark.parametrize("bad", [
    {"action": "restart", "kind": "diario", "hour": "99", "minute": "0"},
    {"action": "restart", "kind": "diario", "hour": "5", "minute": "-3"},
    {"action": "formatar-tudo", "kind": "diario", "hour": "5", "minute": "0"},
    {"action": "restart", "kind": "quando-der", "hour": "5", "minute": "0"},
    {"action": "backup", "kind": "intervalo", "every_hours": "0"},
    {"action": "backup", "kind": "intervalo", "every_hours": "99999"},
])
def test_valores_fora_da_faixa_nao_entram_no_banco(server, admin, database, post, bad):
    post(admin, f"/servers/{server}/schedules", bad)
    assert database.execute(
        "SELECT COUNT(*) FROM schedules WHERE server_id = ?", (server,)
    ).fetchone()[0] == 0


@pytest.fixture
def scheduled_task(server, admin, database, post) -> int:
    """Uma tarefa diaria ja salva, para os testes de alternar/rodar/remover."""
    post(admin, f"/servers/{server}/schedules",
           {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    return database.execute(
        "SELECT id FROM schedules WHERE server_id = ?", (server,)).fetchone()["id"]


def test_operador_nao_altera_agendamento_alheio(scheduled_task, operator, post):
    assert post(operator, f"/schedules/{scheduled_task}/toggle").status_code == 403
    assert post(operator, f"/schedules/{scheduled_task}/delete").status_code == 403
    assert post(operator, f"/schedules/{scheduled_task}/run").status_code == 403


def test_admin_desliga_e_ela_some_do_laco_do_relogio(scheduled_task, admin, database, post):
    post(admin, f"/schedules/{scheduled_task}/toggle")
    assert database.execute(
        "SELECT enabled FROM schedules WHERE id = ?", (scheduled_task,)
    ).fetchone()[0] == 0

    # Tarefa desligada some do laco do relogio: e o que 'desligar' tem de significar.
    with panel.app.app_context():
        enabled_ones = panel.db().execute(
            "SELECT COUNT(*) FROM schedules WHERE enabled = 1").fetchone()[0]
    assert enabled_ones == 0


def test_admin_remove_a_tarefa(scheduled_task, admin, database, post):
    post(admin, f"/schedules/{scheduled_task}/delete")
    assert database.execute(
        "SELECT COUNT(*) FROM schedules WHERE id = ?", (scheduled_task,)
    ).fetchone()[0] == 0


def test_apagar_o_servidor_leva_as_tarefas_dele(server, scheduled_task, database):
    """ON DELETE CASCADE: senao o relogio tentaria disparar para um servidor sumido."""
    with database:
        database.execute("DELETE FROM servers WHERE id = ?", (server,))
    assert database.execute(
        "SELECT COUNT(*) FROM schedules WHERE server_id = ?", (server,)
    ).fetchone()[0] == 0


# ------------------------------------------------------------------ historico global

@pytest.mark.parametrize("qs", ["", "?usuario=chefe", "?acao=start", "?servidor=abc",
                                "?p=-5", "?acao=formatar"])
def test_historico_global_nunca_quebra(admin, qs):
    assert admin.get(f"/history{qs}").status_code == 200


def test_console_nao_aparece_no_historico_global_para_operador(database, admin, operator):
    """O corte de papel do historico por servidor vale igual no global."""
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('outro', 'outro.invalid', 22, 'root', 'jogo.service', ?)",
            (panel.now_iso(),))
    sid2 = database.execute("SELECT id FROM servers WHERE name = 'outro'").fetchone()["id"]
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, output, command, username,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid2, "root@outro", "shell", "ok", "SEGREDO-NO-GLOBAL", "SEGREDO-NO-GLOBAL",
             "chefe", panel.now_iso()))

    assert "SEGREDO-NO-GLOBAL" not in operator.get("/history").get_data(as_text=True)
    assert "SEGREDO-NO-GLOBAL" in admin.get("/history").get_data(as_text=True)
