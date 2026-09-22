#!/usr/bin/env python3
"""QR code (ISO/IEC 18004) so com a stdlib: modo byte, correcao de erro M, versoes 1 a 10.

Existe para a tela de ativacao do segundo fator: o painel nao baixa nada e nao tem pip, entao
nao ha biblioteca de QR. O `otpauth://` de um usuario tem uns 130 bytes, o que cabe na versao 8
(correcao M leva ate 213 bytes na versao 10 — de sobra para o que o painel gera).

Puro (sem Flask), como `ui.py` e `totp.py`. A saida e um SVG proprio, so de numeros: pode entrar
na pagina sem escape. Preto sobre branco com a zona de silencio de 4 modulos, mesmo no tema
escuro: e o contraste que o leitor da camera espera.

Foi conferido contra um leitor de verdade (OpenCV) e contra a biblioteca `segno` — ver
`test_qr.py` para o que fica travado no repositorio.
"""
from __future__ import annotations

# versao -> (bytes de correcao por bloco, [(quantidade de blocos, bytes de dados por bloco), ...])
# Nivel M (~15% de perda tolerada). Tabela da ISO 18004, secao 7.5.1.
_BLOCOS_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
_ALINHAMENTO = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_BITS_DE_FORMATO_M = 0b00           # nivel de correcao M
_PAD = (0xEC, 0x11)


class TextoGrandeDemais(ValueError):
    """Nao cabe na versao 10 com correcao M (213 bytes)."""


def capacidade(versao: int) -> int:
    """Bytes de texto que a versao comporta em modo byte."""
    dados = sum(n * d for n, d in _BLOCOS_M[versao][1])
    return dados - (2 if versao < 10 else 3)   # 4 bits de modo + 8 ou 16 de contagem


def _versao_para(tamanho: int) -> int:
    for versao in _BLOCOS_M:
        if tamanho <= capacidade(versao):
            return versao
    raise TextoGrandeDemais(f"{tamanho} bytes: o maximo e {capacidade(10)}")


# --------------------------------------------------------------------- Reed-Solomon (GF(256))

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _gerador(grau: int) -> list[int]:
    poly = [1]
    for i in range(grau):
        proximo = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            proximo[j] ^= coef
            proximo[j + 1] ^= _mul(coef, _EXP[i])
        poly = proximo
    return poly


def _correcao(dados: list[int], quantidade: int) -> list[int]:
    gerador = _gerador(quantidade)
    resto = list(dados) + [0] * quantidade
    for i in range(len(dados)):
        fator = resto[i]
        if fator:
            for j, coef in enumerate(gerador):
                resto[i + j] ^= _mul(coef, fator)
    return resto[len(dados):]


# ------------------------------------------------------------------- dados -> palavras-codigo

def _palavras(dados: bytes, versao: int) -> list[int]:
    bits: list[int] = []

    def escreve(valor: int, quantos: int) -> None:
        bits.extend((valor >> i) & 1 for i in range(quantos - 1, -1, -1))

    escreve(0b0100, 4)                                    # modo byte
    escreve(len(dados), 8 if versao < 10 else 16)
    for byte in dados:
        escreve(byte, 8)
    total_de_bits = sum(n * d for n, d in _BLOCOS_M[versao][1]) * 8
    bits.extend([0] * min(4, total_de_bits - len(bits)))  # terminador
    bits.extend([0] * (-len(bits) % 8))
    palavras = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    i = 0
    while len(palavras) < total_de_bits // 8:
        palavras.append(_PAD[i % 2])
        i += 1
    return palavras


def _intercala(palavras: list[int], versao: int) -> list[int]:
    ec_por_bloco, grupos = _BLOCOS_M[versao]
    blocos: list[list[int]] = []
    inicio = 0
    for quantidade, tamanho in grupos:
        for _ in range(quantidade):
            blocos.append(palavras[inicio:inicio + tamanho])
            inicio += tamanho
    correcoes = [_correcao(b, ec_por_bloco) for b in blocos]
    saida: list[int] = []
    for i in range(max(len(b) for b in blocos)):
        saida.extend(b[i] for b in blocos if i < len(b))
    for i in range(ec_por_bloco):
        saida.extend(c[i] for c in correcoes)
    return saida


# ----------------------------------------------------------------------------- matriz

def _bch(dados: int, gerador: int, bits_de_correcao: int) -> int:
    resto = dados
    for _ in range(bits_de_correcao):
        resto = (resto << 1) ^ ((resto >> (bits_de_correcao - 1)) * gerador)
    return resto


def bits_de_formato(mascara: int) -> int:
    dados = (_BITS_DE_FORMATO_M << 3) | mascara
    return ((dados << 10) | _bch(dados, 0x537, 10)) ^ 0x5412


def _bits_de_versao(versao: int) -> int:
    return (versao << 12) | _bch(versao, 0x1F25, 12)


class _Matriz:
    def __init__(self, versao: int):
        self.versao = versao
        self.n = 17 + 4 * versao
        self.m = [[False] * self.n for _ in range(self.n)]
        self.fixo = [[False] * self.n for _ in range(self.n)]
        self._desenha_padroes()

    def _define(self, x: int, y: int, escuro: bool) -> None:      # x = coluna, y = linha
        self.m[y][x] = escuro
        self.fixo[y][x] = True

    def _desenha_padroes(self) -> None:
        n = self.n
        for i in range(n):                                          # temporizacao
            self._define(6, i, i % 2 == 0)
            self._define(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):             # tres localizadores + separadores
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        distancia = max(abs(dx), abs(dy))
                        self._define(x, y, distancia not in (2, 4))
        posicoes = _ALINHAMENTO[self.versao]
        for i, cy in enumerate(posicoes):
            for j, cx in enumerate(posicoes):
                if (i == 0 and j == 0) or (i == 0 and j == len(posicoes) - 1) \
                        or (i == len(posicoes) - 1 and j == 0):
                    continue                                        # cai em cima de um localizador
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._define(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self._formato(0)                                            # reserva a area (o valor vem depois)
        if self.versao >= 7:
            bits = _bits_de_versao(self.versao)
            for i in range(18):
                escuro = bool((bits >> i) & 1)
                a, b = n - 11 + i % 3, i // 3
                self._define(a, b, escuro)
                self._define(b, a, escuro)

    def _formato(self, mascara: int) -> None:
        bits, n = bits_de_formato(mascara), self.n
        bit = lambda i: bool((bits >> i) & 1)  # noqa: E731
        for i in range(0, 6):
            self._define(8, i, bit(i))
        self._define(8, 7, bit(6))
        self._define(8, 8, bit(7))
        self._define(7, 8, bit(8))
        for i in range(9, 15):
            self._define(14 - i, 8, bit(i))
        for i in range(0, 8):
            self._define(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._define(8, n - 15 + i, bit(i))
        self._define(8, n - 8, True)                                # o modulo escuro fixo

    def coloca(self, palavras: list[int]) -> None:
        bits = [(p >> i) & 1 for p in palavras for i in range(7, -1, -1)]
        k, n = 0, self.n
        for direita in range(n - 1, 0, -2):
            if direita == 6:
                direita = 5                                          # a coluna 6 e so temporizacao
            for vertical in range(n):
                for j in (0, 1):
                    x = direita - j
                    subindo = ((direita + 1) & 2) == 0
                    y = n - 1 - vertical if subindo else vertical
                    if not self.fixo[y][x]:
                        self.m[y][x] = bool(bits[k]) if k < len(bits) else False
                        k += 1

    def mascara(self, numero: int) -> None:
        for y in range(self.n):
            for x in range(self.n):
                if not self.fixo[y][x] and _MASCARAS[numero](y, x):
                    self.m[y][x] = not self.m[y][x]


_MASCARAS = (
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
)


def _penalidade(m: list[list[bool]]) -> int:
    n = len(m)
    total = 0
    linhas = [[c for c in linha] for linha in m]
    colunas = [[m[y][x] for y in range(n)] for x in range(n)]
    for grupo in (linhas, colunas):                                  # N1 e N3
        for linha in grupo:
            corrida = 1
            for a, b in zip(linha, linha[1:]):
                corrida = corrida + 1 if a == b else 1
                if a == b and corrida == 5:
                    total += 3
                elif a == b and corrida > 5:
                    total += 1
            texto = "".join("1" if c else "0" for c in linha)
            for padrao in ("10111010000", "00001011101"):
                total += 40 * sum(texto.startswith(padrao, i) for i in range(len(texto) - 10))
    for y in range(n - 1):                                           # N2: blocos 2x2 da mesma cor
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                total += 3
    escuros = sum(map(sum, m))                                       # N4: equilibrio de escuros
    total += 10 * (((abs(escuros * 20 - n * n * 10) + n * n - 1) // (n * n)) - 1)
    return total


def matriz(texto: str) -> list[list[bool]]:
    """A matriz de modulos (True = escuro), sem a zona de silencio."""
    dados = texto.encode("utf-8")
    versao = _versao_para(len(dados))
    palavras = _intercala(_palavras(dados, versao), versao)
    melhor: list[list[bool]] | None = None
    menor = -1
    for numero in range(8):
        candidata = _Matriz(versao)
        candidata.coloca(palavras)
        candidata.mascara(numero)
        candidata._formato(numero)
        pontos = _penalidade(candidata.m)
        if melhor is None or pontos < menor:
            melhor, menor = candidata.m, pontos
    assert melhor is not None
    return melhor


def svg(texto: str, rotulo: str = "QR code", borda: int = 4) -> str:
    """O QR como SVG inline. So digitos e letras fixas: seguro para `|safe` no template."""
    m = matriz(texto)
    lado = len(m) + 2 * borda
    tracos = "".join(f"M{x + borda},{y + borda}h1v1h-1z"
                     for y, linha in enumerate(m) for x, escuro in enumerate(linha) if escuro)
    seguro = "".join(c for c in rotulo if c.isalnum() or c in " -_.,")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" role="img" '
            f'aria-label="{seguro}" shape-rendering="crispEdges">'
            f'<rect width="{lado}" height="{lado}" fill="#fff"/><path d="{tracos}" fill="#000"/></svg>')
