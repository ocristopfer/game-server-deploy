"""Codificador QR (qr.py): propriedades matematicas que nao precisam de um leitor de verdade.

O leitor de verdade (camera de celular via OpenCV) e uma verificacao MANUAL, separada
(`tools/verificar-qr.py`), porque a biblioteca pesa dezenas de MB e o painel/`.venv` ficam
so com Flask de proposito. Esta suite prova a matematica por baixo: Reed-Solomon tem resto
zero nas raizes do gerador (a definicao de "codigo corrigivel"), e o codigo de formato tem a
distancia minima de 7 que o BCH(15,5) da ISO 18004 exige. As duas seguram um bug real de
verdade sem precisar decodificar imagem nenhuma.
"""
from __future__ import annotations

import pytest

import qr


def _avalia(poly: list[int], x: int) -> int:
    """Horner em GF(256): poly[0] e o coeficiente de maior grau (mesma ordem de `_correcao`)."""
    resultado = 0
    for coef in poly:
        resultado = qr._mul(resultado, x) ^ coef
    return resultado


# ---------------------------------------------------------------- Reed-Solomon (GF(256))

def test_tabelas_de_log_sao_inversas_uma_da_outra():
    for x in (1, 2, 3, 100, 255):
        assert qr._EXP[qr._LOG[x]] == x


def test_multiplicacao_por_zero_e_zero_e_por_um_e_identidade():
    for x in (0, 1, 7, 200, 255):
        assert qr._mul(x, 0) == 0
        assert qr._mul(x, 1) == x


@pytest.mark.parametrize("grau", [7, 10, 13, 16, 18, 22, 24, 26, 30])
def test_gerador_tem_raiz_em_cada_potencia_de_alpha_ate_o_grau(grau):
    """Definicao do polinomio gerador de Reed-Solomon: g(x) = produto (x - alfa^i), i=0..grau-1.
    Cada alfa^i tem de ser raiz — se a construcao errar um fator, uma dessas raizes falha."""
    gerador = qr._gerador(grau)
    assert len(gerador) == grau + 1
    for i in range(grau):
        assert _avalia(gerador, qr._EXP[i]) == 0


@pytest.mark.parametrize(("tamanho", "correcao"), [(16, 10), (28, 16), (32, 18), (43, 24), (27, 16)])
def test_correcao_faz_o_resto_da_divisao_pelo_gerador_ser_zero(tamanho, correcao):
    """A prova de que _correcao devolve um resto de verdade: dados+resto, como POLINOMIO, e
    multiplo do gerador — ou seja, se avalia a zero em toda raiz dele. E exatamente a
    propriedade que faz o decodificador (fora deste arquivo) saber corrigir erros."""
    dados = [(37 * i + 5) % 256 for i in range(tamanho)]
    resto = qr._correcao(dados, correcao)
    assert len(resto) == correcao
    codigo = dados + resto
    for i in range(correcao):
        assert _avalia(codigo, qr._EXP[i]) == 0


def test_correcao_de_tudo_zero_e_zero():
    assert qr._correcao([0] * 16, 10) == [0] * 10


# ---------------------------------------------------------------------- bits de formato (BCH)

def _distancia(a: int, b: int, bits: int = 15) -> int:
    return bin((a ^ b) & ((1 << bits) - 1)).count("1")


def test_bits_de_formato_tem_15_bits_e_e_deterministico():
    for m in range(8):
        valor = qr.bits_de_formato(m)
        assert 0 <= valor < (1 << 15)
        assert qr.bits_de_formato(m) == valor


def test_bits_de_formato_distingue_as_8_mascaras():
    valores = [qr.bits_de_formato(m) for m in range(8)]
    assert len(set(valores)) == 8


def test_bits_de_formato_tem_a_distancia_minima_que_o_bch_da_iso_18004_promete():
    """BCH(15,5) com distancia minima 7: quaisquer dois codigos de formato validos diferem em
    pelo menos 7 bits. E o que deixa o leitor corrigir ate 3 bits de sujeira na imagem sem
    confundir uma mascara com outra."""
    valores = [qr.bits_de_formato(m) for m in range(8)]
    menor = min(_distancia(a, b) for i, a in enumerate(valores) for b in valores[i + 1:])
    assert menor >= 7


# --------------------------------------------------------------------------- versao e capacidade

def test_capacidade_cresce_a_cada_versao():
    capacidades = [qr.capacidade(v) for v in range(1, 11)]
    assert capacidades == sorted(capacidades)
    assert len(set(capacidades)) == len(capacidades)


def test_texto_no_limite_da_versao_1_nao_precisa_da_versao_2():
    limite = qr.capacidade(1)
    assert len(qr.matriz("a" * limite)) == 21          # versao 1: 17 + 4*1
    assert len(qr.matriz("a" * (limite + 1))) == 25     # um byte a mais: versao 2


def test_213_bytes_cabe_e_214_estoura():
    assert qr.capacidade(10) == 213
    qr.matriz("a" * 213)
    with pytest.raises(qr.TextoGrandeDemais):
        qr.matriz("a" * 214)


def test_texto_vazio_produz_a_menor_matriz():
    assert len(qr.matriz("")) == 21


def test_unicode_conta_em_bytes_utf8_nao_em_caracteres():
    """'ç' sao 2 bytes em UTF-8: 1 caractere acentuado pode custar 2 do limite de 213."""
    texto = "ç" * 106       # 212 bytes: cabe
    qr.matriz(texto)
    with pytest.raises(qr.TextoGrandeDemais):
        qr.matriz("ç" * 107)  # 214 bytes: estoura


# ------------------------------------------------------------------------- estrutura da matriz

@pytest.mark.parametrize("versao", range(1, 11))
def test_tamanho_da_matriz_segue_a_formula_da_iso(versao):
    texto = "a" * qr.capacidade(versao) if versao == 1 else "a" * (qr.capacidade(versao - 1) + 1)
    assert len(qr.matriz(texto)) == 17 + 4 * versao


def test_localizador_do_canto_superior_esquerdo_tem_o_desenho_do_padrao():
    """O 7x7 documentado na ISO 18004: borda preta, anel branco, miolo 3x3 solido preto."""
    m = qr.matriz("teste")
    quadro = [linha[0:7] for linha in m[0:7]]
    padrao_iso = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    assert [[int(c) for c in linha] for linha in quadro] == padrao_iso


def test_padrao_de_temporizacao_alterna():
    m = qr.matriz("teste")
    linha = [m[6][x] for x in range(8, len(m) - 8)]
    assert linha == [i % 2 == 0 for i in range(len(linha))]


def test_matriz_e_deterministica_para_o_mesmo_texto():
    # Duas CHAMADAS separadas, de proposito: prova que nao ha estado escondido entre elas
    # (cache, contador de mascara...) que faria a segunda gerar algo diferente da primeira.
    primeira = qr.matriz("mesmo texto")
    segunda = qr.matriz("mesmo texto")
    assert primeira == segunda


def test_textos_diferentes_dao_matrizes_diferentes():
    assert qr.matriz("um texto") != qr.matriz("outro texto")


# ------------------------------------------------------------------------------------ SVG

def test_svg_tem_viewbox_do_tamanho_da_matriz_mais_a_borda():
    m = qr.matriz("abc")
    saida = qr.svg("abc", borda=4)
    assert f'viewBox="0 0 {len(m) + 8} {len(m) + 8}"' in saida


def test_svg_so_tem_caracteres_de_path_no_traco():
    saida = qr.svg("abc")
    trecho = saida.split('d="')[1].split('"')[0]
    assert set(trecho) <= set("Mhvz0123456789.,-")


def test_svg_escapa_o_rotulo():
    saida = qr.svg("abc", rotulo='"><script>alert(1)</script>')
    assert "<script>" not in saida
    assert ' aria-label="' in saida
