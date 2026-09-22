"""Servico: reserva, criacao, desfazer em falha, cotas, desativar e remover."""
from __future__ import annotations

import sqlite3

import pytest

from gamebroker.domain.exceptions import Conflict, NotFound, OutOfResources, QuotaExceeded, ValidationError
from gamebroker.persistence.db import ESTADO_ATIVA, ESTADO_DESATIVADA, ESTADO_FALHOU, OP_ERRO, OP_OK
from gamebroker.services.allocator import ips_in_range


def _criar(amb, game="alfa", name="Meu servidor", actor="admin"):
    return amb.servico.create(game, name, actor)


# --- caminho feliz ----------------------------------------------------------

def test_criar_percorre_o_fluxo_inteiro(ambiente):
    resposta = _criar(ambiente)
    op = ambiente.servico.operation(resposta["operation_id"])
    assert op["state"] == OP_OK
    assert "abrindo as portas" in op["log"]
    inst = ambiente.db.instance(resposta["instance_id"])
    assert inst["estado"] == ESTADO_ATIVA
    assert (inst["ctid"], inst["ip"]) == (300, "10.0.0.30")
    assert inst["hostname"] == "alfa-300"
    assert ambiente.proxmox.chamadas == [("criar_ct", 300), ("iniciar", 300)]
    assert ambiente.installer.instalados == [("10.0.0.30", "alfa")]
    assert ambiente.opnsense.regras[300] == [("10.0.0.30", 7001, "udp"), ("10.0.0.30", 7002, "udp")]


def test_resultado_traz_o_que_o_painel_precisa_para_cadastrar(ambiente):
    resposta = _criar(ambiente, name="Servidor do Zeca")
    resultado = ambiente.servico.operation(resposta["operation_id"])["result"]
    assert resultado["name"] == "Servidor do Zeca"
    assert resultado["host"] == "10.0.0.30"
    assert resultado["service"] == "alfa.service"
    assert (resultado["game_port"], resultado["query_port"]) == (7001, 7002)
    assert resultado["broker_id"] == resposta["instance_id"]


def test_firewall_so_abre_depois_da_instalacao(ambiente):
    ordem = []
    install, open_ports = ambiente.installer.install, ambiente.opnsense.open_ports
    ambiente.installer.install = lambda *a, **k: (ordem.append("instalar"), install(*a, **k))
    ambiente.opnsense.open_ports = lambda *a, **k: (ordem.append("abrir"), open_ports(*a, **k))
    _criar(ambiente)
    assert ordem == ["instalar", "abrir"]


def test_segunda_instancia_pega_outro_ctid_e_ip(ambiente):
    _criar(ambiente, "beta", "um")
    resposta = _criar(ambiente, "beta", "dois")
    inst = ambiente.db.instance(resposta["instance_id"])
    assert (inst["ctid"], inst["ip"]) == (301, "10.0.0.31")


def test_jogo_deslocavel_recebe_portas_da_faixa_do_broker(ambiente):
    resposta = _criar(ambiente, "beta", "um")
    ports = ambiente.db.instance(resposta["instance_id"])["portas"]
    assert [p["numero"] for p in ports] == [9000, 9001], "faixa propria, nao as portas padrao 8001/8002"
    resultado = ambiente.servico.operation(resposta["operation_id"])["result"]
    assert (resultado["game_port"], resultado["query_port"]) == (9000, 9001)


def test_mesmo_jogo_deslocavel_duas_vezes_pega_o_proximo_bloco(ambiente):
    _criar(ambiente, "beta", "um")
    resposta = _criar(ambiente, "beta", "dois")
    ports = ambiente.db.instance(resposta["instance_id"])["portas"]
    assert [p["numero"] for p in ports] == [9002, 9003]


def test_faixa_do_broker_pula_porta_que_o_opnsense_ja_redireciona(ambiente):
    ambiente.opnsense.externas = {(9000, "udp")}
    ports = ambiente.db.instance(_criar(ambiente, "beta")["instance_id"])["portas"]
    assert [p["numero"] for p in ports] == [9001, 9002]


# --- CTID que acompanha o IP ---------------------------------------------------

def test_ctid_sai_do_ip_quando_ha_base(ambiente):
    ambiente.com_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    inst = ambiente.db.instance(_criar(ambiente)["instance_id"])
    assert (inst["ip"], inst["ctid"], inst["hostname"]) == ("10.0.0.102", 302, "alfa-302")
    assert ambiente.proxmox.chamadas == [("criar_ct", 302), ("iniciar", 302)]


def test_com_base_a_segunda_instancia_segue_o_ip(ambiente):
    ambiente.com_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    _criar(ambiente, "beta", "um")
    inst = ambiente.db.instance(_criar(ambiente, "beta", "dois")["instance_id"])
    assert (inst["ip"], inst["ctid"]) == ("10.0.0.103", 303)


def test_com_base_ctid_ocupado_no_proxmox_pula_o_ip_inteiro(ambiente):
    ambiente.com_config(ctid_base=200, ips=ips_in_range("10.0.0", 102, 110))
    ambiente.proxmox.externos_ctids = {302}
    inst = ambiente.db.instance(_criar(ambiente)["instance_id"])
    assert (inst["ip"], inst["ctid"]) == ("10.0.0.103", 303)


# --- ocupacao vinda de fora do broker ----------------------------------------

def test_pula_ctid_e_ip_que_o_proxmox_ja_usa(ambiente):
    ambiente.proxmox.externos_ctids = {300, 301}
    ambiente.proxmox.externos_ips = {"10.0.0.30"}
    inst = ambiente.db.instance(_criar(ambiente)["instance_id"])
    assert (inst["ctid"], inst["ip"]) == (302, "10.0.0.31")


def test_pula_ip_que_responde_na_rede(ambiente):
    ambiente.network.ocupados = {"10.0.0.30"}
    assert ambiente.db.instance(_criar(ambiente)["instance_id"])["ip"] == "10.0.0.31"


def test_conflito_de_porta_entre_jogos_diferentes(ambiente):
    _criar(ambiente, "alfa", "um")
    with pytest.raises(OutOfResources, match="7002/udp"):
        _criar(ambiente, "delta", "dois")
    assert ambiente.db.count_instances() == 1, "recusa nao deixa reserva para tras"


def test_porta_ja_redirecionada_no_opnsense_bloqueia(ambiente):
    ambiente.opnsense.externas = {(7001, "udp")}
    with pytest.raises(OutOfResources, match="7001/udp"):
        _criar(ambiente, "alfa")


def test_sem_ip_livre(ambiente):
    ambiente.network.ocupados = set(ambiente.config.ips)
    with pytest.raises(OutOfResources, match="IP"):
        _criar(ambiente)


# --- validacao do pedido ------------------------------------------------------

@pytest.mark.parametrize("name", ["", "a;b", "$(id)", "x" * 41, None, 7, "../x"])
def test_nome_invalido(ambiente, name):
    with pytest.raises(ValidationError):
        ambiente.servico.create("alfa", name, "admin")


def test_jogo_inexistente(ambiente):
    with pytest.raises(NotFound):
        _criar(ambiente, "nao-existe")


def test_jogo_que_exige_conta_steam_nao_e_criavel_pela_api(ambiente):
    with pytest.raises(Conflict, match="conta Steam"):
        _criar(ambiente, "conta")


def test_nome_repetido_e_conflito(ambiente):
    _criar(ambiente, "beta", "igual")
    with pytest.raises(Conflict):
        _criar(ambiente, "beta", "igual")


# --- cotas ----------------------------------------------------------------------

def test_limite_de_instancias(ambiente):
    ambiente.com_config(max_instances=1)
    _criar(ambiente, "beta", "um")
    with pytest.raises(QuotaExceeded, match="1 instancias"):
        _criar(ambiente, "beta", "dois")


def test_limite_por_hora_libera_depois_de_uma_hora(ambiente):
    ambiente.com_config(max_creations_per_hour=2)
    _criar(ambiente, "beta", "um")
    _criar(ambiente, "beta", "dois")
    with pytest.raises(QuotaExceeded, match="por hora"):
        _criar(ambiente, "beta", "tres")
    ambiente.clock.avancar(61)
    _criar(ambiente, "beta", "tres")


def test_so_uma_criacao_por_vez(ambiente):
    ambiente.adiar = True
    _criar(ambiente, "beta", "um")
    with pytest.raises(QuotaExceeded, match="em andamento"):
        _criar(ambiente, "beta", "dois")
    ambiente.pendentes.pop()()
    _criar(ambiente, "beta", "dois")


def test_falha_de_validacao_nao_gasta_cota(ambiente):
    ambiente.com_config(max_creations_per_hour=1)
    with pytest.raises(ValidationError):
        ambiente.servico.create("alfa", "a;b", "admin")
    _criar(ambiente, "beta", "ok")


# --- desfazer em caso de falha ---------------------------------------------------

def test_falha_na_instalacao_destroi_o_ct_e_libera_a_reserva(ambiente):
    ambiente.installer.failure = True
    resposta = _criar(ambiente)
    op = ambiente.servico.operation(resposta["operation_id"])
    assert op["state"] == OP_ERRO
    assert "steamcmd falhou" in op["log"]
    assert "reserva liberada" in op["log"]
    assert ambiente.proxmox.cts == {}
    assert ambiente.opnsense.regras == {}
    assert ambiente.db.count_instances() == 0
    assert ambiente.db.taken() == (set(), set(), set()), "IP, CTID e portas voltam para o pool"


def test_falha_ao_criar_o_ct_nao_tenta_destruir_o_que_nao_existe(ambiente):
    ambiente.proxmox.falha_em = "criar_ct"
    _criar(ambiente)
    assert ("destruir", 300) not in ambiente.proxmox.chamadas
    assert ambiente.db.count_instances() == 0


def test_falha_no_firewall_desfaz_tudo(ambiente):
    ambiente.opnsense.falha_em = "abrir"
    _criar(ambiente)
    assert ambiente.proxmox.cts == {}
    assert ambiente.db.count_instances() == 0


def test_se_nem_o_desfazer_funciona_a_reserva_fica_como_falhou(ambiente):
    ambiente.installer.failure = True
    ambiente.proxmox.falha_em = None

    def destruir_quebrado(_ctid):
        raise RuntimeError("proxmox fora do ar")

    ambiente.proxmox.destroy = destruir_quebrado
    resposta = _criar(ambiente)
    inst = ambiente.db.instance(resposta["instance_id"])
    assert inst["estado"] == ESTADO_FALHOU
    assert "nao consegui desfazer" in ambiente.servico.operation(resposta["operation_id"])["log"]
    # IP e portas continuam bloqueados: um novo pedido nao pode pisar em cima.
    ambiente.network.ocupados = set()
    novo = ambiente.db.instance(_criar(ambiente, "beta", "outro")["instance_id"])
    assert novo["ip"] != inst["ip"]


# --- desativar e remover ------------------------------------------------------------

def test_desativar_fecha_o_firewall_e_para_o_ct(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    assert ambiente.opnsense.regras == {}
    assert 300 in ambiente.proxmox.parados
    assert ambiente.db.instance(resposta["instance_id"])["estado"] == ESTADO_DESATIVADA


def test_desativar_duas_vezes_e_conflito(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    with pytest.raises(Conflict):
        ambiente.servico.deactivate(resposta["instance_id"], "admin")


def test_remover_exige_desativar_antes(ambiente):
    resposta = _criar(ambiente)
    with pytest.raises(Conflict, match="desative"):
        ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin")


def test_remover_exige_o_nome_exato(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    with pytest.raises(ValidationError, match="nome exato"):
        ambiente.servico.remove(resposta["instance_id"], "meu servidor", "admin")
    assert ambiente.proxmox.cts, "nada foi destruido"


def test_remover_destroi_e_libera_ip_ctid_e_portas(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin")
    assert ambiente.proxmox.cts == {}
    assert ambiente.db.taken() == (set(), set(), set())
    assert ambiente.db.instance(resposta["instance_id"]) is None


def test_remover_recusa_ct_que_nao_e_do_broker(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    ambiente.proxmox.belongs_to_broker = lambda _ctid: False
    with pytest.raises(Conflict, match="nao pertence ao broker"):
        ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin")
    assert ambiente.proxmox.cts, "o CT de outro dono nao foi tocado"


def test_ct_que_sumiu_do_pool_nao_e_esquecido_sem_pedido_explicito(ambiente):
    """Sumido e movido de pool sao indistinguiveis para o token: nao libera CTID/IP sozinho."""
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    ambiente.proxmox.cts.clear()
    with pytest.raises(Conflict, match="db_only"):
        ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin")
    assert ambiente.db.instance(resposta["instance_id"]) is not None


def test_somente_banco_limpa_o_registro_sem_tocar_no_proxmox(ambiente):
    resposta = _criar(ambiente)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    ambiente.proxmox.chamadas.clear()
    ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin", db_only=True)
    assert ambiente.db.instance(resposta["instance_id"]) is None
    assert ambiente.proxmox.chamadas == []
    assert ambiente.proxmox.cts, "o CT continua la: so o registro foi esquecido"
    assert "esquecer" in {a["verbo"] for a in ambiente.db.audit_trail()}


def test_somente_banco_tambem_exige_desativar_e_o_nome(ambiente):
    resposta = _criar(ambiente)
    with pytest.raises(Conflict, match="desative"):
        ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin", db_only=True)
    ambiente.servico.deactivate(resposta["instance_id"], "admin")
    with pytest.raises(ValidationError):
        ambiente.servico.remove(resposta["instance_id"], "errado", "admin", db_only=True)


def test_remover_instancia_que_falhou_nao_exige_desativar(ambiente):
    ambiente.installer.failure = True
    ambiente.proxmox.destroy = lambda _ctid: (_ for _ in ()).throw(RuntimeError("fora"))
    resposta = _criar(ambiente)
    del ambiente.proxmox.destroy
    ambiente.servico.remove(resposta["instance_id"], "Meu servidor", "admin")
    assert ambiente.db.instance(resposta["instance_id"]) is None


def test_instancia_desconhecida(ambiente):
    with pytest.raises(NotFound):
        ambiente.servico.deactivate(999, "admin")
    with pytest.raises(NotFound):
        ambiente.servico.remove(999, "x", "admin")


# --- auditoria ------------------------------------------------------------------------

def test_auditoria_registra_quem_fez_o_que(ambiente):
    resposta = _criar(ambiente, actor="zeca")
    ambiente.servico.deactivate(resposta["instance_id"], "zeca")
    verbos = [(a["ator"], a["verbo"], a["resultado"]) for a in ambiente.db.audit_trail()]
    assert ("zeca", "criar", "aceito") in verbos
    assert ("zeca", "criar", "ok") in verbos
    assert ("zeca", "desativar", "ok") in verbos


def test_ator_estranho_vira_desconhecido(ambiente):
    _criar(ambiente, actor="a b; DROP TABLE")
    assert {a["ator"] for a in ambiente.db.audit_trail()} == {"desconhecido"}


def test_auditoria_e_append_only(ambiente):
    _criar(ambiente)
    with sqlite3.connect(ambiente.db._caminho) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE auditoria SET resultado = 'adulterado'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM auditoria")


def test_banco_recusa_reserva_duplicada_mesmo_sem_a_trava(ambiente):
    """UNIQUE e a segunda linha de defesa: dois processos poderiam ignorar a trava."""
    _criar(ambiente, "beta", "um")
    with pytest.raises(Conflict):
        ambiente.db.reserve(300, "10.0.0.99", "beta", "outro", "beta-300", "x", [])
