"""Alocador: CTID, IP e portas escolhidos a partir do que ja esta ocupado."""
from __future__ import annotations

import pytest

import gamebroker.services.allocator as alocador
from gamebroker.domain.exceptions import SemRecurso
from gamebroker.services.catalog import validar_dinamico


def _jogo(dados_de_jogo, **mudancas):
    dados_de_jogo.update(mudancas)
    return validar_dinamico(dados_de_jogo)


def test_ctid_pula_os_usados():
    assert alocador.escolher_ctid(range(300, 305), {300, 301}) == 302


def test_ctid_esgotado():
    with pytest.raises(SemRecurso, match="CTID"):
        alocador.escolher_ctid(range(300, 302), {300, 301})


def test_ip_pula_usados_e_quem_responde_na_rede():
    candidatos = ("10.0.0.30", "10.0.0.31", "10.0.0.32")
    ip = alocador.escolher_ip(candidatos, {"10.0.0.30"}, lambda ip: ip == "10.0.0.31")
    assert ip == "10.0.0.32"


def test_ip_esgotado():
    with pytest.raises(SemRecurso, match="IP"):
        alocador.escolher_ip(("10.0.0.30",), set(), lambda _ip: True)


def test_faixa_de_ips_valida():
    assert alocador.ips_da_faixa("192.168.2", 30, 32) == ("192.168.2.30", "192.168.2.31", "192.168.2.32")


@pytest.mark.parametrize(("prefixo", "ini", "fim"), [("192.168.2", 0, 5), ("192.168.2", 9, 3), ("192.168.2", 1, 255), ("nao-ip", 1, 5)])
def test_faixa_de_ips_invalida(prefixo, ini, fim):
    with pytest.raises(ValueError):
        alocador.ips_da_faixa(prefixo, ini, fim)


FAIXA = range(31000, 31010)


def test_ctid_acompanha_o_ultimo_numero_do_ip():
    ip, ctid = alocador.escolher_ip_e_ctid(("10.0.0.102", "10.0.0.103"), 200, set(), set(), lambda _ip: False)
    assert (ip, ctid) == ("10.0.0.102", 302)


def test_ip_e_pulado_se_o_ctid_dele_esta_ocupado():
    # O CTID 302 existe (criado na mao): o .102 nao serve, mesmo com o IP livre.
    ip, ctid = alocador.escolher_ip_e_ctid(("10.0.0.102", "10.0.0.103"), 200, {302}, set(), lambda _ip: False)
    assert (ip, ctid) == ("10.0.0.103", 303)


def test_ip_e_ctid_pulam_ip_usado_e_quem_responde():
    candidatos = ("10.0.0.102", "10.0.0.103", "10.0.0.104")
    ip, ctid = alocador.escolher_ip_e_ctid(candidatos, 200, set(), {"10.0.0.102"}, lambda ip: ip == "10.0.0.103")
    assert (ip, ctid) == ("10.0.0.104", 304)


def test_ip_e_ctid_esgotados():
    with pytest.raises(SemRecurso, match="IP/CTID"):
        alocador.escolher_ip_e_ctid(("10.0.0.102",), 200, {302}, set(), lambda _ip: False)


def test_jogo_fixo_usa_as_portas_padrao_e_ganha_papel(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=False), set(), FAIXA)
    assert [(p.numero, p.proto, p.papel) for p in portas] == [
        (7777, "udp", "jogo"), (27016, "udp", "query")]


def test_jogo_fixo_com_porta_ocupada_e_recusado(dados_de_jogo):
    jogo = _jogo(dados_de_jogo, deslocavel=False)
    with pytest.raises(SemRecurso, match="27016/udp.*nao aceita mudar"):
        alocador.alocar_portas(jogo, {(27016, "udp")}, FAIXA)


def test_jogo_deslocavel_ignora_as_portas_padrao_e_usa_a_faixa(dados_de_jogo):
    # As portas padrao nem estao ocupadas: mesmo assim o jogo anda para a faixa do broker.
    portas = alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=True), set(), FAIXA)
    assert [(p.numero, p.papel) for p in portas] == [(31000, "jogo"), (31001, "query")]
    assert [p.base for p in portas] == [7777, 27016]


def test_jogo_deslocavel_pega_o_primeiro_bloco_inteiro_livre(dados_de_jogo):
    ocupadas = {(31000, "udp"), (31003, "udp")}
    portas = alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=True), ocupadas, FAIXA)
    assert [p.numero for p in portas] == [31001, 31002]


def test_mesma_porta_em_udp_e_tcp_fica_com_o_mesmo_numero(dados_de_jogo):
    jogo = _jogo(dados_de_jogo, portas=["7777/udp", "7777/tcp"], porta_query=0, deslocavel=True,
                 start_args="-port={PORT}")
    portas = alocador.alocar_portas(jogo, set(), FAIXA)
    assert [(p.numero, p.proto) for p in portas] == [(31000, "udp"), (31000, "tcp")]


def test_faixa_cheia_e_recusada_com_a_faixa_na_mensagem(dados_de_jogo):
    ocupadas = {(n, "udp") for n in FAIXA}
    with pytest.raises(SemRecurso, match="31000-31009.*cheia"):
        alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=True), ocupadas, FAIXA)


def test_bloco_nao_atravessa_o_fim_da_faixa(dados_de_jogo):
    # So sobra a ultima porta da faixa: um bloco de duas portas nao cabe.
    ocupadas = {(n, "udp") for n in range(31000, 31009)}
    with pytest.raises(SemRecurso, match="cheia"):
        alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=True), ocupadas, FAIXA)


def test_protocolo_diferente_nao_conflita(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=False), {(7777, "tcp")}, FAIXA)
    assert portas[0].numero == 7777


def test_porta_do_papel(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo), set(), FAIXA)
    assert alocador.porta_do_papel(portas, alocador.PAPEL_JOGO) == 31000
    assert alocador.porta_do_papel(portas, alocador.PAPEL_QUERY) == 31001
    assert alocador.porta_do_papel(portas, "inexistente") == 0
