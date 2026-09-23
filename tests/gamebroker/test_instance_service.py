"""Servico: reserva, criacao, desfazer em falha, cotas, desativar e remover."""
from __future__ import annotations

import sqlite3

import pytest

from gamebroker.domain.exceptions import Conflict, NotFound, OutOfResources, QuotaExceeded, ValidationError
from gamebroker.persistence.db import OP_FAILED, OP_OK, STATE_ACTIVE, STATE_DEACTIVATED, STATE_FAILED
from gamebroker.services.allocator import ips_in_range


def _create(amb, game="alfa", name="Meu servidor", actor="admin"):
    return amb.servico.create(game, name, actor)


# --- caminho feliz ----------------------------------------------------------

def test_criar_percorre_o_fluxo_inteiro(environment):
    response = _create(environment)
    op = environment.servico.operation(response["operation_id"])
    assert op["state"] == OP_OK
    assert "abrindo as portas" in op["log"]
    inst = environment.db.instance(response["instance_id"])
    assert inst["state"] == STATE_ACTIVE
    assert (inst["ctid"], inst["ip"]) == (300, "10.0.0.30")
    assert inst["hostname"] == "alfa-300"
    assert environment.proxmox.calls == [("criar_ct", 300), ("iniciar", 300)]
    assert environment.installer.installed == [("10.0.0.30", "alfa")]
    assert environment.opnsense.rules[300] == [("10.0.0.30", 7001, "udp"), ("10.0.0.30", 7002, "udp")]


def test_resultado_traz_o_que_o_painel_precisa_para_cadastrar(environment):
    response = _create(environment, name="Servidor do Zeca")
    result = environment.servico.operation(response["operation_id"])["result"]
    assert result["name"] == "Servidor do Zeca"
    assert result["host"] == "10.0.0.30"
    assert result["service"] == "alfa.service"
    assert (result["game_port"], result["query_port"]) == (7001, 7002)
    assert result["broker_id"] == response["instance_id"]


def test_firewall_so_abre_depois_da_instalacao(environment):
    order = []
    install, open_ports = environment.installer.install, environment.opnsense.open_ports
    environment.installer.install = lambda *a, **k: (order.append("instalar"), install(*a, **k))
    environment.opnsense.open_ports = lambda *a, **k: (order.append("abrir"), open_ports(*a, **k))
    _create(environment)
    assert order == ["instalar", "abrir"]


def test_segunda_instancia_pega_outro_ctid_e_ip(environment):
    _create(environment, "beta", "um")
    response = _create(environment, "beta", "dois")
    inst = environment.db.instance(response["instance_id"])
    assert (inst["ctid"], inst["ip"]) == (301, "10.0.0.31")


def test_jogo_deslocavel_recebe_portas_da_faixa_do_broker(environment):
    response = _create(environment, "beta", "um")
    ports = environment.db.instance(response["instance_id"])["ports"]
    assert [p["number"] for p in ports] == [9000, 9001], "faixa propria, nao as portas padrao 8001/8002"
    result = environment.servico.operation(response["operation_id"])["result"]
    assert (result["game_port"], result["query_port"]) == (9000, 9001)


def test_mesmo_jogo_deslocavel_duas_vezes_pega_o_proximo_bloco(environment):
    _create(environment, "beta", "um")
    response = _create(environment, "beta", "dois")
    ports = environment.db.instance(response["instance_id"])["ports"]
    assert [p["number"] for p in ports] == [9002, 9003]


def test_faixa_do_broker_pula_porta_que_o_opnsense_ja_redireciona(environment):
    environment.opnsense.outside = {(9000, "udp")}
    ports = environment.db.instance(_create(environment, "beta")["instance_id"])["ports"]
    assert [p["number"] for p in ports] == [9001, 9002]


# --- CTID que acompanha o IP ---------------------------------------------------

def test_ctid_sai_do_ip_quando_ha_base(environment):
    environment.with_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    inst = environment.db.instance(_create(environment)["instance_id"])
    assert (inst["ip"], inst["ctid"], inst["hostname"]) == ("10.0.0.102", 302, "alfa-302")
    assert environment.proxmox.calls == [("criar_ct", 302), ("iniciar", 302)]


def test_com_base_a_segunda_instancia_segue_o_ip(environment):
    environment.with_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    _create(environment, "beta", "um")
    inst = environment.db.instance(_create(environment, "beta", "dois")["instance_id"])
    assert (inst["ip"], inst["ctid"]) == ("10.0.0.103", 303)


def test_com_base_ctid_ocupado_no_proxmox_pula_o_ip_inteiro(environment):
    environment.with_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    environment.proxmox.outside_ctids = {302}
    inst = environment.db.instance(_create(environment)["instance_id"])
    assert (inst["ip"], inst["ctid"]) == ("10.0.0.103", 303)


# --- ocupacao vinda de fora do broker ----------------------------------------

def test_pula_ctid_e_ip_que_o_proxmox_ja_usa(environment):
    environment.proxmox.outside_ctids = {300, 301}
    environment.proxmox.outside_ips = {"10.0.0.30"}
    inst = environment.db.instance(_create(environment)["instance_id"])
    assert (inst["ctid"], inst["ip"]) == (302, "10.0.0.31")


def test_pula_ip_que_responde_na_rede(environment):
    environment.network.taken = {"10.0.0.30"}
    assert environment.db.instance(_create(environment)["instance_id"])["ip"] == "10.0.0.31"


def test_conflito_de_porta_entre_jogos_diferentes(environment):
    _create(environment, "alfa", "um")
    with pytest.raises(OutOfResources, match="7002/udp"):
        _create(environment, "delta", "dois")
    assert environment.db.count_instances() == 1, "recusa nao deixa reserva para tras"


def test_porta_ja_redirecionada_no_opnsense_bloqueia(environment):
    environment.opnsense.outside = {(7001, "udp")}
    with pytest.raises(OutOfResources, match="7001/udp"):
        _create(environment, "alfa")


def test_sem_ip_livre(environment):
    environment.network.taken = set(environment.config.ips)
    with pytest.raises(OutOfResources, match="IP"):
        _create(environment)


# --- validacao do pedido ------------------------------------------------------

@pytest.mark.parametrize("name", ["", "a;b", "$(id)", "x" * 41, None, 7, "../x"])
def test_nome_invalido(environment, name):
    with pytest.raises(ValidationError):
        environment.servico.create("alfa", name, "admin")


def test_jogo_inexistente(environment):
    with pytest.raises(NotFound):
        _create(environment, "nao-existe")


def test_jogo_que_exige_conta_steam_nao_e_criavel_pela_api(environment):
    with pytest.raises(Conflict, match="conta Steam"):
        _create(environment, "conta")


def test_nome_repetido_e_conflito(environment):
    _create(environment, "beta", "igual")
    with pytest.raises(Conflict):
        _create(environment, "beta", "igual")


# --- cotas ----------------------------------------------------------------------

def test_limite_de_instancias(environment):
    environment.with_config(max_instances=1)
    _create(environment, "beta", "um")
    with pytest.raises(QuotaExceeded, match="1 instancias"):
        _create(environment, "beta", "dois")


def test_limite_por_hora_libera_depois_de_uma_hora(environment):
    environment.with_config(max_creations_per_hour=2)
    _create(environment, "beta", "um")
    _create(environment, "beta", "dois")
    with pytest.raises(QuotaExceeded, match="por hora"):
        _create(environment, "beta", "tres")
    environment.clock.advance(61)
    _create(environment, "beta", "tres")


def test_so_uma_criacao_por_vez(environment):
    environment.defer = True
    _create(environment, "beta", "um")
    with pytest.raises(QuotaExceeded, match="em andamento"):
        _create(environment, "beta", "dois")
    environment.pending.pop()()
    _create(environment, "beta", "dois")


def test_falha_de_validacao_nao_gasta_cota(environment):
    environment.with_config(max_creations_per_hour=1)
    with pytest.raises(ValidationError):
        environment.servico.create("alfa", "a;b", "admin")
    _create(environment, "beta", "ok")


# --- desfazer em caso de falha ---------------------------------------------------

def test_falha_na_instalacao_destroi_o_ct_e_libera_a_reserva(environment):
    environment.installer.failure = True
    response = _create(environment)
    op = environment.servico.operation(response["operation_id"])
    assert op["state"] == OP_FAILED
    assert "steamcmd falhou" in op["log"]
    assert "reserva liberada" in op["log"]
    assert environment.proxmox.cts == {}
    assert environment.opnsense.rules == {}
    assert environment.db.count_instances() == 0
    assert environment.db.taken() == (set(), set(), set()), "IP, CTID e portas voltam para o pool"


def test_falha_ao_criar_o_ct_nao_tenta_destruir_o_que_nao_existe(environment):
    environment.proxmox.fail_on = "criar_ct"
    _create(environment)
    assert ("destruir", 300) not in environment.proxmox.calls
    assert environment.db.count_instances() == 0


def test_falha_no_firewall_desfaz_tudo(environment):
    environment.opnsense.fail_on = "abrir"
    _create(environment)
    assert environment.proxmox.cts == {}
    assert environment.db.count_instances() == 0


def test_se_nem_o_desfazer_funciona_a_reserva_fica_como_falhou(environment):
    environment.installer.failure = True
    environment.proxmox.fail_on = None

    def broken_destroy(_ctid):
        raise RuntimeError("proxmox fora do ar")

    environment.proxmox.destroy = broken_destroy
    response = _create(environment)
    inst = environment.db.instance(response["instance_id"])
    assert inst["state"] == STATE_FAILED
    assert "nao consegui desfazer" in environment.servico.operation(response["operation_id"])["log"]
    # IP e portas continuam bloqueados: um novo pedido nao pode pisar em cima.
    environment.network.taken = set()
    fresh = environment.db.instance(_create(environment, "beta", "outro")["instance_id"])
    assert fresh["ip"] != inst["ip"]


# --- desativar e remover ------------------------------------------------------------

def test_desativar_fecha_o_firewall_e_para_o_ct(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    assert environment.opnsense.rules == {}
    assert 300 in environment.proxmox.stopped
    assert environment.db.instance(response["instance_id"])["state"] == STATE_DEACTIVATED


def test_desativar_duas_vezes_e_conflito(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    with pytest.raises(Conflict):
        environment.servico.deactivate(response["instance_id"], "admin")


def test_remover_exige_desativar_antes(environment):
    response = _create(environment)
    with pytest.raises(Conflict, match="desative"):
        environment.servico.remove(response["instance_id"], "Meu servidor", "admin")


def test_remover_exige_o_nome_exato(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    with pytest.raises(ValidationError, match="nome exato"):
        environment.servico.remove(response["instance_id"], "meu servidor", "admin")
    assert environment.proxmox.cts, "nada foi destruido"


def test_remover_destroi_e_libera_ip_ctid_e_portas(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    environment.servico.remove(response["instance_id"], "Meu servidor", "admin")
    assert environment.proxmox.cts == {}
    assert environment.db.taken() == (set(), set(), set())
    assert environment.db.instance(response["instance_id"]) is None


def test_remover_recusa_ct_que_nao_e_do_broker(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    environment.proxmox.belongs_to_broker = lambda _ctid: False
    with pytest.raises(Conflict, match="nao pertence ao broker"):
        environment.servico.remove(response["instance_id"], "Meu servidor", "admin")
    assert environment.proxmox.cts, "o CT de outro dono nao foi tocado"


def test_ct_que_sumiu_do_pool_nao_e_esquecido_sem_pedido_explicito(environment):
    """Sumido e movido de pool sao indistinguiveis para o token: nao libera CTID/IP sozinho."""
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    environment.proxmox.cts.clear()
    with pytest.raises(Conflict, match="db_only"):
        environment.servico.remove(response["instance_id"], "Meu servidor", "admin")
    assert environment.db.instance(response["instance_id"]) is not None


def test_somente_banco_limpa_o_registro_sem_tocar_no_proxmox(environment):
    response = _create(environment)
    environment.servico.deactivate(response["instance_id"], "admin")
    environment.proxmox.calls.clear()
    environment.servico.remove(response["instance_id"], "Meu servidor", "admin", db_only=True)
    assert environment.db.instance(response["instance_id"]) is None
    assert environment.proxmox.calls == []
    assert environment.proxmox.cts, "o CT continua la: so o registro foi esquecido"
    assert "esquecer" in {a["verb"] for a in environment.db.audit_trail()}


def test_somente_banco_tambem_exige_desativar_e_o_nome(environment):
    response = _create(environment)
    with pytest.raises(Conflict, match="desative"):
        environment.servico.remove(response["instance_id"], "Meu servidor", "admin", db_only=True)
    environment.servico.deactivate(response["instance_id"], "admin")
    with pytest.raises(ValidationError):
        environment.servico.remove(response["instance_id"], "errado", "admin", db_only=True)


def test_remover_instancia_que_falhou_nao_exige_desativar(environment):
    environment.installer.failure = True
    environment.proxmox.destroy = lambda _ctid: (_ for _ in ()).throw(RuntimeError("fora"))
    response = _create(environment)
    del environment.proxmox.destroy
    environment.servico.remove(response["instance_id"], "Meu servidor", "admin")
    assert environment.db.instance(response["instance_id"]) is None


def test_instancia_desconhecida(environment):
    with pytest.raises(NotFound):
        environment.servico.deactivate(999, "admin")
    with pytest.raises(NotFound):
        environment.servico.remove(999, "x", "admin")


# --- auditoria ------------------------------------------------------------------------

def test_auditoria_registra_quem_fez_o_que(environment):
    response = _create(environment, actor="zeca")
    environment.servico.deactivate(response["instance_id"], "zeca")
    verbs = [(a["actor"], a["verb"], a["result"]) for a in environment.db.audit_trail()]
    assert ("zeca", "criar", "aceito") in verbs
    assert ("zeca", "criar", "ok") in verbs
    assert ("zeca", "desativar", "ok") in verbs


def test_ator_estranho_vira_desconhecido(environment):
    _create(environment, actor="a b; DROP TABLE")
    assert {a["actor"] for a in environment.db.audit_trail()} == {"desconhecido"}


def test_auditoria_e_append_only(environment):
    _create(environment)
    with sqlite3.connect(environment.db._path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE audit SET result = 'adulterado'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM audit")


def test_banco_recusa_reserva_duplicada_mesmo_sem_a_trava(environment):
    """UNIQUE e a segunda linha de defesa: dois processos poderiam ignorar a trava."""
    _create(environment, "beta", "um")
    with pytest.raises(Conflict):
        environment.db.reserve(300, "10.0.0.99", "beta", "outro", "beta-300", "x", [])
