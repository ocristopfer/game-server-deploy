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

FUSO = timezone.utc


def quando(dia, hora, minuto=0):
    """Uma quarta-feira (2026-08-19) as HH:MM, para as contas terem um chao fixo."""
    return datetime(2026, 8, dia, hora, minuto, tzinfo=FUSO)


def tarefa(**kw):
    base = {"action": "restart", "kind": "diario", "hour": 5, "minute": 0,
            "weekday": 0, "every_hours": 6, "enabled": 1, "last_run": ""}
    base.update(kw)
    return base


# --------------------------------------------------------- ocorrencia anterior

@pytest.mark.parametrize("rotulo, sched, agora, esperado", [
    ("diario, ja passou hoje", tarefa(hour=5), quando(19, 14), quando(19, 5)),
    ("diario, ainda nao chegou hoje -> foi ontem",
     tarefa(hour=23), quando(19, 2), quando(18, 23)),
    # weekday 0 = segunda; de quarta olhando para tras, a segunda foi 17/08.
    ("semanal, dia ja passou nesta semana",
     tarefa(kind="semanal", weekday=0, hour=4), quando(19, 10), quando(17, 4)),
    # weekday 4 = sexta; de quarta, a sexta anterior foi 14/08.
    ("semanal, dia ainda nao chegou -> semana passada",
     tarefa(kind="semanal", weekday=4, hour=4), quando(19, 10), quando(14, 4)),
    # No proprio dia, antes da hora, tem de recuar uma semana inteira.
    ("semanal, hoje e o dia mas a hora nao chegou",
     tarefa(kind="semanal", weekday=2, hour=23), quando(19, 1), quando(12, 23)),
    ("intervalo nao tem ocorrencia fixa", tarefa(kind="intervalo"), quando(19, 10), None),
])
def test_ocorrencia_anterior(rotulo, sched, agora, esperado):
    assert panel.previous_occurrence(sched, agora) == esperado, rotulo


# ------------------------------------------------------------- quando vence

def test_diario_dispara_na_hora_e_nao_antes():
    assert panel.is_due(tarefa(hour=5), quando(19, 5, 0))
    assert not panel.is_due(tarefa(hour=6), quando(19, 5, 59))


def test_nao_repete_a_mesma_ocorrencia():
    """O relogio acorda a cada 30s e nao pode repetir um disparo ja feito."""
    ja_rodou = tarefa(hour=5, last_run=quando(19, 5, 0).isoformat())
    assert not panel.is_due(ja_rodou, quando(19, 5, 30))
    assert panel.is_due(ja_rodou, quando(20, 5, 1)), "no dia seguinte volta a valer"


def test_atraso_alem_da_tolerancia_nao_dispara():
    """Painel fora do ar a noite inteira: as 14h ninguem quer o restart das 5h no meio
    da partida. A tolerancia e GRACE (1h por padrao)."""
    assert not panel.is_due(tarefa(hour=5), quando(19, 14))
    assert panel.is_due(tarefa(hour=5), quando(19, 5, 30)), "dentro da tolerancia ainda dispara"


def test_intervalo_conta_a_partir_do_ultimo_disparo():
    assert panel.is_due(tarefa(kind="intervalo"), quando(19, 5)), "sem last_run, dispara"
    nao_completou = tarefa(kind="intervalo", every_hours=6, last_run=quando(19, 2).isoformat())
    assert not panel.is_due(nao_completou, quando(19, 5))
    completou = tarefa(kind="intervalo", every_hours=6, last_run=quando(19, 2).isoformat())
    assert panel.is_due(completou, quando(19, 8))


def test_last_run_ilegivel_nao_trava_a_tarefa():
    """Banco mexido a mao nao pode fazer uma tarefa nunca mais disparar."""
    torto = tarefa(hour=5, last_run="isto nao e uma data")
    assert panel.is_due(torto, quando(19, 5))


# -------------------------------------------------------------------- rotulos

@pytest.mark.parametrize("rotulo, sched, esperado", [
    ("diario", tarefa(hour=5, minute=30), "todo dia as 05:30"),
    # Concordancia: "toda segunda" (de segunda-feira) mas "todo domingo".
    ("semanal, dia feminino",
     tarefa(kind="semanal", weekday=0, hour=3), "toda segunda as 03:00"),
    ("semanal, dia masculino",
     tarefa(kind="semanal", weekday=6, hour=3), "todo domingo as 03:00"),
    ("semanal, sabado tambem",
     tarefa(kind="semanal", weekday=5, hour=3), "todo sabado as 03:00"),
    ("intervalo", tarefa(kind="intervalo", every_hours=6), "a cada 6h"),
    ("intervalo de uma hora", tarefa(kind="intervalo", every_hours=1), "a cada hora"),
])
def test_rotulo_agendamento(rotulo, sched, esperado):
    assert panel.schedule_label(sched) == esperado, rotulo


# --------------------------------------------------------- retencao do historico

def test_jobs_antigos_saem_na_limpeza(banco):
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service',"
            " '/opt/game/Saved', ?)", (panel.now_iso(),))
    sid = banco.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]
    velho = (datetime.now(timezone.utc) - timedelta(days=panel.JOBS_KEEP_DAYS + 5)).isoformat()
    novo = panel.now_iso()
    with banco:
        for quantos, carimbo in ((4, velho), (3, novo)):
            for _ in range(quantos):
                banco.execute(
                    "INSERT INTO jobs (server_id, target, action, status, output, username,"
                    " created_at) VALUES (?,?,?,?,?,?,?)",
                    (sid, "root@alvo", "start", "ok", "", "chefe", carimbo))

    with panel.app.app_context():
        apagados = panel.limpa_historico(forcar=True)
    assert apagados == 4
    assert banco.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3


# ------------------------------------------------------------ agendar pelas telas

@pytest.fixture
def servidor(banco) -> int:
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service',"
            " '/opt/game/Saved', ?)", (panel.now_iso(),))
    return banco.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


def test_operador_ve_a_tela_mas_nao_agenda(servidor, chefe, peao, postar):
    assert peao.get(f"/servers/{servidor}/agendamentos").status_code == 200
    resp = postar(peao, f"/servers/{servidor}/agendamentos",
                  {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    assert resp.status_code == 403


def test_admin_agenda_uma_tarefa_diaria(servidor, chefe, banco, postar):
    resp = postar(chefe, f"/servers/{servidor}/agendamentos",
                  {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    assert resp.status_code == 302

    t = banco.execute("SELECT * FROM schedules WHERE server_id = ?", (servidor,)).fetchone()
    assert (t["action"], t["kind"], t["hour"]) == ("restart", "diario", 5)
    assert t["last_run"] == "", "diario comeca sem last_run (a ocorrencia de hoje ainda vale)"


def test_intervalo_nasce_com_o_relogio_zerado(servidor, chefe, banco, postar):
    """Sem isto 'a cada 6h' dispararia no instante em que fosse salvo."""
    postar(chefe, f"/servers/{servidor}/agendamentos",
           {"action": "backup", "kind": "intervalo", "every_hours": "6"})
    inter = banco.execute("SELECT * FROM schedules WHERE kind = 'intervalo'").fetchone()
    assert inter["last_run"] != ""


@pytest.mark.parametrize("ruim", [
    {"action": "restart", "kind": "diario", "hour": "99", "minute": "0"},
    {"action": "restart", "kind": "diario", "hour": "5", "minute": "-3"},
    {"action": "formatar-tudo", "kind": "diario", "hour": "5", "minute": "0"},
    {"action": "restart", "kind": "quando-der", "hour": "5", "minute": "0"},
    {"action": "backup", "kind": "intervalo", "every_hours": "0"},
    {"action": "backup", "kind": "intervalo", "every_hours": "99999"},
])
def test_valores_fora_da_faixa_nao_entram_no_banco(servidor, chefe, banco, postar, ruim):
    postar(chefe, f"/servers/{servidor}/agendamentos", ruim)
    assert banco.execute(
        "SELECT COUNT(*) FROM schedules WHERE server_id = ?", (servidor,)
    ).fetchone()[0] == 0


@pytest.fixture
def tarefa_agendada(servidor, chefe, banco, postar) -> int:
    """Uma tarefa diaria ja salva, para os testes de alternar/rodar/remover."""
    postar(chefe, f"/servers/{servidor}/agendamentos",
           {"action": "restart", "kind": "diario", "hour": "5", "minute": "0"})
    return banco.execute(
        "SELECT id FROM schedules WHERE server_id = ?", (servidor,)).fetchone()["id"]


def test_operador_nao_altera_agendamento_alheio(tarefa_agendada, peao, postar):
    assert postar(peao, f"/agendamentos/{tarefa_agendada}/alternar").status_code == 403
    assert postar(peao, f"/agendamentos/{tarefa_agendada}/remover").status_code == 403
    assert postar(peao, f"/agendamentos/{tarefa_agendada}/rodar").status_code == 403


def test_admin_desliga_e_ela_some_do_laco_do_relogio(tarefa_agendada, chefe, banco, postar):
    postar(chefe, f"/agendamentos/{tarefa_agendada}/alternar")
    assert banco.execute(
        "SELECT enabled FROM schedules WHERE id = ?", (tarefa_agendada,)
    ).fetchone()[0] == 0

    # Tarefa desligada some do laco do relogio: e o que 'desligar' tem de significar.
    with panel.app.app_context():
        ligadas = panel.db().execute(
            "SELECT COUNT(*) FROM schedules WHERE enabled = 1").fetchone()[0]
    assert ligadas == 0


def test_admin_remove_a_tarefa(tarefa_agendada, chefe, banco, postar):
    postar(chefe, f"/agendamentos/{tarefa_agendada}/remover")
    assert banco.execute(
        "SELECT COUNT(*) FROM schedules WHERE id = ?", (tarefa_agendada,)
    ).fetchone()[0] == 0


def test_apagar_o_servidor_leva_as_tarefas_dele(servidor, tarefa_agendada, banco):
    """ON DELETE CASCADE: senao o relogio tentaria disparar para um servidor sumido."""
    with banco:
        banco.execute("DELETE FROM servers WHERE id = ?", (servidor,))
    assert banco.execute(
        "SELECT COUNT(*) FROM schedules WHERE server_id = ?", (servidor,)
    ).fetchone()[0] == 0


# ------------------------------------------------------------------ historico global

@pytest.mark.parametrize("qs", ["", "?usuario=chefe", "?acao=start", "?servidor=abc",
                                "?p=-5", "?acao=formatar"])
def test_historico_global_nunca_quebra(chefe, qs):
    assert chefe.get(f"/historico{qs}").status_code == 200


def test_console_nao_aparece_no_historico_global_para_operador(banco, chefe, peao):
    """O corte de papel do historico por servidor vale igual no global."""
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('outro', 'outro.invalid', 22, 'root', 'jogo.service', ?)",
            (panel.now_iso(),))
    sid2 = banco.execute("SELECT id FROM servers WHERE name = 'outro'").fetchone()["id"]
    with banco:
        banco.execute(
            "INSERT INTO jobs (server_id, target, action, status, output, command, username,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid2, "root@outro", "shell", "ok", "SEGREDO-NO-GLOBAL", "SEGREDO-NO-GLOBAL",
             "chefe", panel.now_iso()))

    assert "SEGREDO-NO-GLOBAL" not in peao.get("/historico").get_data(as_text=True)
    assert "SEGREDO-NO-GLOBAL" in chefe.get("/historico").get_data(as_text=True)
