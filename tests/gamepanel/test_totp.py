"""TOTP e codigos de recuperacao (totp.py): a conta em si, contra os vetores do RFC 6238."""
from __future__ import annotations

import base64

import pytest

from gamepanel.security import totp

# Apendice B do RFC 6238: o segredo ASCII "12345678901234567890" e os codigos de 8 digitos para
# SHA-1; os de 6 digitos sao os 6 ultimos (o resto da divisao por 10^6).
SEGREDO_DO_RFC = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
VETORES = [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
           (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")]


@pytest.mark.parametrize(("instante", "esperado"), VETORES)
def test_codigo_bate_com_os_vetores_do_rfc_6238(instante, esperado):
    assert totp.code(SEGREDO_DO_RFC, totp.step_of(instante)) == esperado


def test_segredo_novo_tem_160_bits_em_base32_e_nunca_repete():
    a, b = totp.new_secret(), totp.new_secret()
    assert a != b
    assert len(a) == 32
    assert len(base64.b32decode(a)) == 20


def test_aceita_o_codigo_do_passo_atual_e_devolve_o_passo():
    assert totp.verify(SEGREDO_DO_RFC, "287082", now=59) == 1


def test_tolera_um_passo_para_cada_lado_e_nao_mais():
    codigo = totp.code(SEGREDO_DO_RFC, 10)
    assert totp.verify(SEGREDO_DO_RFC, codigo, now=9 * 30) == 10       # 1 passo antes
    assert totp.verify(SEGREDO_DO_RFC, codigo, now=11 * 30) == 10      # 1 passo depois
    assert totp.verify(SEGREDO_DO_RFC, codigo, now=13 * 30) is None    # 3 passos: fora
    assert totp.verify(SEGREDO_DO_RFC, codigo, now=7 * 30) is None


def test_codigo_ja_usado_nao_vale_de_novo():
    passo = totp.verify(SEGREDO_DO_RFC, "287082", now=59)
    assert totp.verify(SEGREDO_DO_RFC, "287082", now=59, last_step=passo) is None


def test_codigo_de_passo_mais_antigo_que_o_ultimo_usado_tambem_e_recusado():
    """Sem isto, usar o codigo NOVO e depois repetir o ANTIGO (ainda na janela) funcionaria."""
    velho = totp.code(SEGREDO_DO_RFC, 9)
    assert totp.verify(SEGREDO_DO_RFC, velho, now=10 * 30, last_step=10) is None


@pytest.mark.parametrize("digitado", ["", "12345", "1234567", "abcdef", "12 34 5x", None, "000000"])
def test_lixo_e_recusado(digitado):
    assert totp.verify(SEGREDO_DO_RFC, digitado, now=59) is None


def test_espaco_e_hifen_no_codigo_digitado_sao_ignorados():
    assert totp.verify(SEGREDO_DO_RFC, "287 082", now=59) == 1
    assert totp.verify(SEGREDO_DO_RFC, "287-082", now=59) == 1


def test_segredo_agrupado_com_espacos_ainda_e_lido():
    assert totp.code(totp.group(SEGREDO_DO_RFC), 1) == totp.code(SEGREDO_DO_RFC, 1)


def test_uri_carrega_o_que_o_aplicativo_precisa():
    endereco = totp.uri("ABCDEFGH", "ze maria", "Painel de Jogos")
    assert endereco.startswith("otpauth://totp/Painel%20de%20Jogos%3Aze%20maria?")
    for trecho in ("secret=ABCDEFGH", "issuer=Painel%20de%20Jogos", "algorithm=SHA1",
                   "digits=6", "period=30"):
        assert trecho in endereco


# --- recuperacao -------------------------------------------------------------------------------

def test_codigos_de_recuperacao_tem_o_formato_e_sao_todos_diferentes():
    codigos = totp.new_recovery_codes()
    assert len(codigos) == totp.RECOVERY_CODES
    assert len(set(codigos)) == len(codigos)
    assert all(totp.looks_like_recovery_code(c) for c in codigos)
    assert all(len(c) == 11 and c[5] == "-" for c in codigos)


def test_recuperacao_serve_uma_vez_e_so_o_hash_fica_guardado():
    codigos = totp.new_recovery_codes(3)
    guardados = [totp.hash_recovery_code(c) for c in codigos]
    assert not any(c.replace("-", "") in "".join(guardados) for c in codigos)
    sobra = totp.consume(codigos[1], guardados)
    assert sobra == [guardados[0], guardados[2]]
    assert totp.consume(codigos[1], sobra) is None, "o mesmo codigo nao serve duas vezes"


def test_recuperacao_ignora_hifen_espaco_e_caixa():
    codigo = totp.new_recovery_codes(1)[0]
    guardados = [totp.hash_recovery_code(codigo)]
    assert totp.consume(codigo.replace("-", "").upper(), guardados) == []
    assert totp.consume(" " + codigo + " ", guardados) == []


@pytest.mark.parametrize("digitado", ["", "123456", "zzzzz-zzzzz", "abc", None, "abcde-1234"])
def test_recuperacao_recusa_o_que_nao_tem_o_formato(digitado):
    assert totp.consume(digitado, [totp.hash_recovery_code("abcde-12345")]) is None


def test_codigo_totp_nunca_e_confundido_com_recuperacao():
    assert not totp.looks_like_recovery_code("287082")
    assert totp.looks_like_recovery_code("abcde-12345")
