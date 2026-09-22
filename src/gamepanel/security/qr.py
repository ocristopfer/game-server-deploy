#!/usr/bin/env python3
"""QR code (ISO/IEC 18004) so com a stdlib: modo byte, correcao de erro M, versoes 1 a 10.

Existe para a tela de ativacao do segundo fator: o painel nao baixa nada e nao tem pip, entao
nao ha biblioteca de QR. O `otpauth://` de um usuario tem uns 130 bytes, o que cabe na versao 8
(correcao M leva ate 213 bytes na versao 10 — de sobra para o que o painel gera).

Puro (sem Flask), como `navigation.py` e `totp.py`. A saida e um SVG proprio, so de numeros:
pode entrar na pagina sem escape. Preto sobre branco com a zona de silencio de 4 modulos,
mesmo no tema escuro: e o contraste que o leitor da camera espera.

Foi conferido contra um leitor de verdade (OpenCV) e contra a biblioteca `segno` — ver
`test_qr.py` para o que fica travado no repositorio.
"""
from __future__ import annotations

import itertools

# versao -> (bytes de correcao por bloco, [(quantidade de blocos, bytes de dados por bloco), ...])
# Nivel M (~15% de perda tolerada). Tabela da ISO 18004, secao 7.5.1.
_BLOCKS_M = {
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
_ALIGNMENT = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_FORMAT_BITS_M = 0b00           # nivel de correcao M
_PAD = (0xEC, 0x11)
_LARGE_VERSION = 10             # a partir daqui a contagem de caracteres usa 16 bits, nao 8
_VERSIONED_FORMAT = 7           # a partir daqui o QR carrega os proprios bits de versao
_TIMING_COLUMN = 6              # coluna/linha reservada ao padrao de temporizacao


class TextTooLarge(ValueError):
    """Nao cabe na versao 10 com correcao M (213 bytes)."""


def capacity(version: int) -> int:
    """Bytes de texto que a versao comporta em modo byte."""
    data = sum(n * d for n, d in _BLOCKS_M[version][1])
    return data - (2 if version < _LARGE_VERSION else 3)   # 4 bits de modo + 8 ou 16 de contagem


def _version_for(size: int) -> int:
    for version in _BLOCKS_M:
        if size <= capacity(version):
            return version
    raise TextTooLarge(f"{size} bytes: o maximo e {capacity(10)}")


# --------------------------------------------------------------------- Reed-Solomon no campo de Galois de 256 elementos

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


def _generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        next_poly = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            next_poly[j] ^= coef
            next_poly[j + 1] ^= _mul(coef, _EXP[i])
        poly = next_poly
    return poly


def _correction(data: list[int], count: int) -> list[int]:
    generator = _generator(count)
    remainder = list(data) + [0] * count
    for i in range(len(data)):
        factor = remainder[i]
        if factor:
            for j, coef in enumerate(generator):
                remainder[i + j] ^= _mul(coef, factor)
    return remainder[len(data):]


# ------------------------------------------------------------------- dados -> palavras-codigo

def _codewords(data: bytes, version: int) -> list[int]:
    bits: list[int] = []

    def write(value: int, how_many: int) -> None:
        bits.extend((value >> i) & 1 for i in range(how_many - 1, -1, -1))

    write(0b0100, 4)                                    # modo byte
    write(len(data), 8 if version < _LARGE_VERSION else 16)
    for byte in data:
        write(byte, 8)
    total_bits = sum(n * d for n, d in _BLOCKS_M[version][1]) * 8
    bits.extend([0] * min(4, total_bits - len(bits)))  # terminador
    bits.extend([0] * (-len(bits) % 8))
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    i = 0
    while len(words) < total_bits // 8:
        words.append(_PAD[i % 2])
        i += 1
    return words


def _interleave(codewords: list[int], version: int) -> list[int]:
    ec_per_block, groups = _BLOCKS_M[version]
    blocks: list[list[int]] = []
    start = 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(codewords[start:start + size])
            start += size
    corrections = [_correction(b, ec_per_block) for b in blocks]
    output: list[int] = []
    for i in range(max(len(b) for b in blocks)):
        output.extend(b[i] for b in blocks if i < len(b))
    for i in range(ec_per_block):
        output.extend(c[i] for c in corrections)
    return output


# ----------------------------------------------------------------------------- matriz

def _bch(data: int, generator: int, correction_bits: int) -> int:
    remainder = data
    for _ in range(correction_bits):
        remainder = (remainder << 1) ^ ((remainder >> (correction_bits - 1)) * generator)
    return remainder


def format_bits(mask: int) -> int:
    data = (_FORMAT_BITS_M << 3) | mask
    return ((data << 10) | _bch(data, 0x537, 10)) ^ 0x5412


def _version_bits(version: int) -> int:
    return (version << 12) | _bch(version, 0x1F25, 12)


class _Matrix:
    def __init__(self, version: int):
        self.version = version
        self.n = 17 + 4 * version
        self.m = [[False] * self.n for _ in range(self.n)]
        self.fixed = [[False] * self.n for _ in range(self.n)]
        self._draw_patterns()

    def _set(self, x: int, y: int, dark: bool) -> None:      # x e a coluna; y, a linha
        self.m[y][x] = dark
        self.fixed[y][x] = True

    def _draw_patterns(self) -> None:
        self._draw_timing_pattern()
        self._draw_finder_patterns()
        self._draw_alignment_patterns()
        self._format(0)                                            # reserva a area (o valor vem depois)
        self._draw_version_info()

    def _draw_timing_pattern(self) -> None:
        for i in range(self.n):
            self._set(_TIMING_COLUMN, i, i % 2 == 0)
            self._set(i, _TIMING_COLUMN, i % 2 == 0)

    def _draw_finder_patterns(self) -> None:
        n = self.n
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):             # tres localizadores + separadores
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        distance = max(abs(dx), abs(dy))
                        self._set(x, y, distance not in (2, 4))

    def _draw_alignment_patterns(self) -> None:
        positions = _ALIGNMENT[self.version]
        for i, cy in enumerate(positions):
            for j, cx in enumerate(positions):
                if self._overlaps_finder_pattern(i, j, len(positions)):
                    continue                                        # cai em cima de um localizador
                self._draw_one_alignment_pattern(cx, cy)

    @staticmethod
    def _overlaps_finder_pattern(i: int, j: int, count: int) -> bool:
        return (i == 0 and j == 0) or (i == 0 and j == count - 1) or (i == count - 1 and j == 0)

    def _draw_one_alignment_pattern(self, cx: int, cy: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self._set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def _draw_version_info(self) -> None:
        if self.version < _VERSIONED_FORMAT:
            return
        n = self.n
        bits = _version_bits(self.version)
        for i in range(18):
            dark = bool((bits >> i) & 1)
            a, b = n - 11 + i % 3, i // 3
            self._set(a, b, dark)
            self._set(b, a, dark)

    def _format(self, mask: int) -> None:
        bits, n = format_bits(mask), self.n

        def bit(i: int) -> bool:
            return bool((bits >> i) & 1)

        for i in range(0, 6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(0, 8):
            self._set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, bit(i))
        self._set(8, n - 8, True)                                # o modulo escuro fixo

    def place(self, codewords: list[int]) -> None:
        bits = [(p >> i) & 1 for p in codewords for i in range(7, -1, -1)]
        for k, (x, y) in enumerate(self._free_positions_zigzag()):
            self.m[y][x] = bool(bits[k]) if k < len(bits) else False

    def _free_positions_zigzag(self):
        """As posicoes ainda livres (nao fixas), na ordem de ziguezague do QR.

        Sobe e desce em pares de colunas, da direita para a esquerda, pulando a
        coluna de temporizacao (6) - e assim que o padrao preenche a matriz inteira
        sem se sobrepor aos padroes ja fixos.
        """
        n = self.n
        for right in range(n - 1, 0, -2):
            if right == _TIMING_COLUMN:
                right = _TIMING_COLUMN - 1
            going_up = ((right + 1) & 2) == 0
            for vertical in range(n):
                y = n - 1 - vertical if going_up else vertical
                for j in (0, 1):
                    x = right - j
                    if not self.fixed[y][x]:
                        yield x, y

    def apply_mask(self, number: int) -> None:
        for y in range(self.n):
            for x in range(self.n):
                if not self.fixed[y][x] and _MASKS[number](y, x):
                    self.m[y][x] = not self.m[y][x]


_MASKS = (
    lambda i, j: (i + j) % 2 == 0,
    lambda i, j: i % 2 == 0,
    lambda i, j: j % 3 == 0,
    lambda i, j: (i + j) % 3 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j) % 2 + (i * j) % 3 == 0,
    lambda i, j: ((i * j) % 2 + (i * j) % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + (i * j) % 3) % 2 == 0,
)


_RUN_PENALTY_LENGTH = 5
_FINDER_LIKE_PATTERNS = ("10111010000", "00001011101")


def _run_penalty(line: list[bool]) -> int:
    """N1: sequencias de 5+ modulos da mesma cor em seguida."""
    total = 0
    run = 1
    for a, b in itertools.pairwise(line):
        run = run + 1 if a == b else 1
        if a == b and run == _RUN_PENALTY_LENGTH:
            total += 3
        elif a == b and run > _RUN_PENALTY_LENGTH:
            total += 1
    return total


def _finder_like_penalty(line: list[bool]) -> int:
    """N3: trecho parecido demais com o padrao localizador (falso positivo pro leitor)."""
    text = "".join("1" if c else "0" for c in line)
    return sum(
        40 * sum(text.startswith(pattern, i) for i in range(len(text) - 10))
        for pattern in _FINDER_LIKE_PATTERNS
    )


def _block_penalty(m: list[list[bool]]) -> int:
    """N2: blocos 2x2 da mesma cor."""
    n = len(m)
    total = 0
    for y in range(n - 1):
        for x in range(n - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                total += 3
    return total


def _balance_penalty(m: list[list[bool]]) -> int:
    """N4: equilibrio entre modulos claros e escuros (quanto mais longe de 50%, pior)."""
    n = len(m)
    dark_count = sum(map(sum, m))
    return 10 * (((abs(dark_count * 20 - n * n * 10) + n * n - 1) // (n * n)) - 1)


def _penalty(m: list[list[bool]]) -> int:
    n = len(m)
    rows = [list(row) for row in m]
    columns = [[m[y][x] for y in range(n)] for x in range(n)]
    line_penalty = sum(_run_penalty(line) + _finder_like_penalty(line) for line in rows + columns)
    return line_penalty + _block_penalty(m) + _balance_penalty(m)


def matrix(text: str) -> list[list[bool]]:
    """A matriz de modulos (True = escuro), sem a zona de silencio."""
    data = text.encode("utf-8")
    version = _version_for(len(data))
    codewords = _interleave(_codewords(data, version), version)
    best: list[list[bool]] | None = None
    lowest = -1
    for number in range(8):
        candidate = _Matrix(version)
        candidate.place(codewords)
        candidate.apply_mask(number)
        candidate._format(number)
        points = _penalty(candidate.m)
        if best is None or points < lowest:
            best, lowest = candidate.m, points
    if best is None:
        raise AssertionError("nenhuma mascara candidata foi avaliada")
    return best


def svg(text: str, label: str = "QR code", border: int = 4) -> str:
    """O QR como SVG inline. So digitos e letras fixas: seguro para `|safe` no template."""
    m = matrix(text)
    side = len(m) + 2 * border
    path = "".join(f"M{x + border},{y + border}h1v1h-1z"
                   for y, row in enumerate(m) for x, dark in enumerate(row) if dark)
    safe_label = "".join(c for c in label if c.isalnum() or c in " -_.,")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" role="img" '
            f'aria-label="{safe_label}" shape-rendering="crispEdges">'
            f'<rect width="{side}" height="{side}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
