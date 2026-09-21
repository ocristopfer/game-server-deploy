"""Alocador: CTID, IP e portas escolhidos a partir do que ja esta ocupado."""
from __future__ import annotations

import pytest

from broker import alocador
from broker.catalogo import validar_dinamico
from broker.erros import SemRecurso


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


def test_portas_livres_ficam_como_estao_e_ganham_papel(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo), set())
    assert [(p.numero, p.proto, p.papel) for p in portas] == [
        (7777, "udp", "jogo"), (27016, "udp", "query")]


def test_jogo_fixo_com_porta_ocupada_e_recusado(dados_de_jogo):
    jogo = _jogo(dados_de_jogo, deslocavel=False)
    with pytest.raises(SemRecurso, match="27016/udp.*nao aceita mudar"):
        alocador.alocar_portas(jogo, {(27016, "udp")})


def test_jogo_deslocavel_move_todas_as_portas_juntas(dados_de_jogo):
    jogo = _jogo(dados_de_jogo, deslocavel=True)
    # So a query esta ocupada, mas as DUAS andam: o jogo recebe um unico deslocamento.
    portas = alocador.alocar_portas(jogo, {(27016, "udp")})
    assert [p.numero for p in portas] == [7778, 27017]
    assert [p.base for p in portas] == [7777, 27016]


def test_protocolo_diferente_nao_conflita(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo, deslocavel=False), {(7777, "tcp")})
    assert portas[0].numero == 7777


def test_deslocamento_que_estoura_65535_e_recusado(dados_de_jogo):
    jogo = _jogo(dados_de_jogo, portas=["65535/udp"], porta_jogo=65535, porta_query=0, deslocavel=True)
    with pytest.raises(SemRecurso):
        alocador.alocar_portas(jogo, {(65535, "udp")})


def test_porta_do_papel(dados_de_jogo):
    portas = alocador.alocar_portas(_jogo(dados_de_jogo), set())
    assert alocador.porta_do_papel(portas, alocador.PAPEL_JOGO) == 7777
    assert alocador.porta_do_papel(portas, alocador.PAPEL_QUERY) == 27016
    assert alocador.porta_do_papel(portas, "inexistente") == 0
