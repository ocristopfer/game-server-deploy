"""QR encoder (qr.py): mathematical properties that do not need a real reader.

The real reader (a phone camera via OpenCV) is a separate MANUAL check
(`tools/verify-qr.py`), because the library weighs tens of MB and the panel/`.venv` stay
with only Flask on purpose. This suite proves the math underneath: Reed-Solomon has a zero
remainder at the generator's roots (the definition of "correctable code"), and the format code
has the minimum distance of 7 that ISO 18004's BCH(15,5) requires. Both catch a real bug
without having to decode any image.
"""
from __future__ import annotations

import pytest

from gamepanel.security import qr


def _evaluate(poly: list[int], x: int) -> int:
    """Horner in GF(256): poly[0] is the highest-degree coefficient (same order as `_correcao`)."""
    result = 0
    for coef in poly:
        result = qr._mul(result, x) ^ coef
    return result


# ------------------------------- Reed-Solomon over the finite field of 256 elements

def test_tabelas_de_log_sao_inversas_uma_da_outra():
    for x in (1, 2, 3, 100, 255):
        assert qr._EXP[qr._LOG[x]] == x


def test_multiplicacao_por_zero_e_zero_e_por_um_e_identidade():
    for x in (0, 1, 7, 200, 255):
        assert qr._mul(x, 0) == 0
        assert qr._mul(x, 1) == x


@pytest.mark.parametrize("degree", [7, 10, 13, 16, 18, 22, 24, 26, 30])
def test_gerador_tem_raiz_em_cada_potencia_de_alpha_ate_o_grau(degree):
    """Definition of the Reed-Solomon generator polynomial: g(x) = product (x - alpha^i), i=0..degree-1.
    Every alpha^i must be a root - if the construction gets a factor wrong, one of these roots fails."""
    generator = qr._generator(degree)
    assert len(generator) == degree + 1
    for i in range(degree):
        assert _evaluate(generator, qr._EXP[i]) == 0


@pytest.mark.parametrize(("size", "correction"), [(16, 10), (28, 16), (32, 18), (43, 24), (27, 16)])
def test_correcao_faz_o_resto_da_divisao_pelo_gerador_ser_zero(size, correction):
    """Proof that _correcao returns a real remainder: data+remainder, as a POLYNOMIAL, is a
    multiple of the generator - that is, it evaluates to zero at each of its roots. It is exactly
    the property that lets the decoder (outside this file) correct errors."""
    data = [(37 * i + 5) % 256 for i in range(size)]
    rest = qr._correction(data, correction)
    assert len(rest) == correction
    code = data + rest
    for i in range(correction):
        assert _evaluate(code, qr._EXP[i]) == 0


def test_correcao_de_tudo_zero_e_zero():
    assert qr._correction([0] * 16, 10) == [0] * 10


# ---------------------------------------------------------------------- format bits (BCH)

def _distance(a: int, b: int, bits: int = 15) -> int:
    return bin((a ^ b) & ((1 << bits) - 1)).count("1")


def test_bits_de_formato_tem_15_bits_e_e_deterministico():
    for m in range(8):
        value = qr.format_bits(m)
        assert 0 <= value < (1 << 15)
        assert qr.format_bits(m) == value


def test_bits_de_formato_distingue_as_8_mascaras():
    values = [qr.format_bits(m) for m in range(8)]
    assert len(set(values)) == 8


def test_bits_de_formato_tem_a_distancia_minima_que_o_bch_da_iso_18004_promete():
    """BCH(15,5) with minimum distance 7: any two valid format codes differ in at least
    7 bits. That is what lets the reader correct up to 3 bits of dirt in the image without
    mistaking one mask for another."""
    values = [qr.format_bits(m) for m in range(8)]
    smaller = min(_distance(a, b) for i, a in enumerate(values) for b in values[i + 1:])
    assert smaller >= 7


# --------------------------------------------------------------------------- version and capacity

def test_capacidade_cresce_a_cada_versao():
    capabilities = [qr.capacity(v) for v in range(1, 11)]
    assert capabilities == sorted(capabilities)
    assert len(set(capabilities)) == len(capabilities)


def test_texto_no_limite_da_versao_1_nao_precisa_da_versao_2():
    limit = qr.capacity(1)
    assert len(qr.matrix("a" * limit)) == 21          # version 1: 17 + 4*1
    assert len(qr.matrix("a" * (limit + 1))) == 25     # one byte more: version 2


def test_213_bytes_cabe_e_214_estoura():
    assert qr.capacity(10) == 213
    qr.matrix("a" * 213)
    with pytest.raises(qr.TextTooLarge):
        qr.matrix("a" * 214)


def test_texto_vazio_produz_a_menor_matriz():
    assert len(qr.matrix("")) == 21


def test_unicode_conta_em_bytes_utf8_nao_em_caracteres():
    """A c-cedilla is 2 bytes in UTF-8: 1 accented character can cost 2 of the 213 limit."""
    text = "ç" * 106       # 212 bytes: fits
    qr.matrix(text)
    with pytest.raises(qr.TextTooLarge):
        qr.matrix("ç" * 107)  # 214 bytes: overflows


# ------------------------------------------------------------------------- matrix structure

@pytest.mark.parametrize("version", range(1, 11))
def test_tamanho_da_matriz_segue_a_formula_da_iso(version):
    text = "a" * qr.capacity(version) if version == 1 else "a" * (qr.capacity(version - 1) + 1)
    assert len(qr.matrix(text)) == 17 + 4 * version


def test_localizador_do_canto_superior_esquerdo_tem_o_desenho_do_padrao():
    """The 7x7 documented in ISO 18004: black border, white ring, solid black 3x3 core."""
    m = qr.matrix("teste")
    frame = [line[0:7] for line in m[0:7]]
    iso_pattern = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    assert [[int(c) for c in line] for line in frame] == iso_pattern


def test_padrao_de_temporizacao_alterna():
    m = qr.matrix("teste")
    line = [m[6][x] for x in range(8, len(m) - 8)]
    assert line == [i % 2 == 0 for i in range(len(line))]


def test_matriz_e_deterministica_para_o_mesmo_texto():
    # Two separate CALLS, on purpose: proves there is no hidden state between them
    # (cache, mask counter...) that would make the second produce something different from the first.
    first_one = qr.matrix("mesmo texto")
    second_one = qr.matrix("mesmo texto")
    assert first_one == second_one


def test_textos_diferentes_dao_matrizes_diferentes():
    assert qr.matrix("um texto") != qr.matrix("outro texto")


# ------------------------------------------------------------------------------------ SVG

def test_svg_tem_viewbox_do_tamanho_da_matriz_mais_a_borda():
    m = qr.matrix("abc")
    output = qr.svg("abc", border=4)
    assert f'viewBox="0 0 {len(m) + 8} {len(m) + 8}"' in output


def test_svg_so_tem_caracteres_de_path_no_traco():
    output = qr.svg("abc")
    chunk_of = output.split('d="')[1].split('"')[0]
    assert set(chunk_of) <= set("Mhvz0123456789.,-")


def test_svg_escapa_o_rotulo():
    output = qr.svg("abc", label='"><script>alert(1)</script>')
    assert "<script>" not in output
    assert ' aria-label="' in output
