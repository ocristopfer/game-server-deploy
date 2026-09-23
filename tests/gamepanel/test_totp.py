"""TOTP e codigos de recuperacao (totp.py): a conta em si, contra os vetores do RFC 6238."""
from __future__ import annotations

import base64

import pytest

from gamepanel.security import totp

# Apendice B do RFC 6238: o segredo ASCII "12345678901234567890" e os codigos de 8 digitos para
# SHA-1; os de 6 digitos sao os 6 ultimos (o resto da divisao por 10^6).
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
VECTORS = [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
           (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")]


@pytest.mark.parametrize(("moment", "expected"), VECTORS)
def test_codigo_bate_com_os_vetores_do_rfc_6238(moment, expected):
    assert totp.code(RFC_SECRET, totp.step_of(moment)) == expected


def test_segredo_novo_tem_160_bits_em_base32_e_nunca_repete():
    a, b = totp.new_secret(), totp.new_secret()
    assert a != b
    assert len(a) == 32
    assert len(base64.b32decode(a)) == 20


def test_aceita_o_codigo_do_passo_atual_e_devolve_o_passo():
    assert totp.verify(RFC_SECRET, "287082", now=59) == 1


def test_tolera_um_passo_para_cada_lado_e_nao_mais():
    code = totp.code(RFC_SECRET, 10)
    assert totp.verify(RFC_SECRET, code, now=9 * 30) == 10       # 1 passo antes
    assert totp.verify(RFC_SECRET, code, now=11 * 30) == 10      # 1 passo depois
    assert totp.verify(RFC_SECRET, code, now=13 * 30) is None    # 3 passos: fora
    assert totp.verify(RFC_SECRET, code, now=7 * 30) is None


def test_codigo_ja_usado_nao_vale_de_novo():
    step = totp.verify(RFC_SECRET, "287082", now=59)
    assert totp.verify(RFC_SECRET, "287082", now=59, last_step=step) is None


def test_codigo_de_passo_mais_antigo_que_o_ultimo_usado_tambem_e_recusado():
    """Sem isto, usar o codigo NOVO e depois repetir o ANTIGO (ainda na janela) funcionaria."""
    old_one = totp.code(RFC_SECRET, 9)
    assert totp.verify(RFC_SECRET, old_one, now=10 * 30, last_step=10) is None


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", "12 34 5x", None, "000000"])
def test_lixo_e_recusado(typed):
    assert totp.verify(RFC_SECRET, typed, now=59) is None


def test_espaco_e_hifen_no_codigo_digitado_sao_ignorados():
    assert totp.verify(RFC_SECRET, "287 082", now=59) == 1
    assert totp.verify(RFC_SECRET, "287-082", now=59) == 1


def test_segredo_agrupado_com_espacos_ainda_e_lido():
    assert totp.code(totp.group(RFC_SECRET), 1) == totp.code(RFC_SECRET, 1)


def test_uri_carrega_o_que_o_aplicativo_precisa():
    address = totp.uri("ABCDEFGH", "ze maria", "Painel de Jogos")
    assert address.startswith("otpauth://totp/Painel%20de%20Jogos%3Aze%20maria?")
    for chunk_of in ("secret=ABCDEFGH", "issuer=Painel%20de%20Jogos", "algorithm=SHA1",
                   "digits=6", "period=30"):
        assert chunk_of in address


# --- recuperacao -------------------------------------------------------------------------------

def test_codigos_de_recuperacao_tem_o_formato_e_sao_todos_diferentes():
    codes = totp.new_recovery_codes()
    assert len(codes) == totp.RECOVERY_CODES
    assert len(set(codes)) == len(codes)
    assert all(totp.looks_like_recovery_code(c) for c in codes)
    assert all(len(c) == 11 and c[5] == "-" for c in codes)


def test_recuperacao_serve_uma_vez_e_so_o_hash_fica_guardado():
    codes = totp.new_recovery_codes(3)
    stored = [totp.hash_recovery_code(c) for c in codes]
    assert not any(c.replace("-", "") in "".join(stored) for c in codes)
    leftover = totp.consume(codes[1], stored)
    assert leftover == [stored[0], stored[2]]
    assert totp.consume(codes[1], leftover) is None, "o mesmo codigo nao serve duas vezes"


def test_recuperacao_ignora_hifen_espaco_e_caixa():
    code = totp.new_recovery_codes(1)[0]
    stored = [totp.hash_recovery_code(code)]
    assert totp.consume(code.replace("-", "").upper(), stored) == []
    assert totp.consume(" " + code + " ", stored) == []


@pytest.mark.parametrize("typed", ["", "123456", "zzzzz-zzzzz", "abc", None, "abcde-1234"])
def test_recuperacao_recusa_o_que_nao_tem_o_formato(typed):
    assert totp.consume(typed, [totp.hash_recovery_code("abcde-12345")]) is None


def test_codigo_totp_nunca_e_confundido_com_recuperacao():
    assert not totp.looks_like_recovery_code("287082")
    assert totp.looks_like_recovery_code("abcde-12345")
