#!/usr/bin/env python3
"""MANUAL check of the QR encoder (src/gamepanel/security/qr.py) against a real reader.

It does not run under pytest: opencv-python-headless and segno together exceed 60 MB, and the
panel (and the development .venv) stay with Flask only, on purpose (see CLAUDE.md). Run this by
hand whenever you touch `qr.py`, in a throwaway venv:

    python -m venv /tmp/verifica-qr
    /tmp/verifica-qr/Scripts/pip install opencv-python-headless segno   # only here, never in the repo .venv
    /tmp/verifica-qr/Scripts/python tools/verify-qr.py

What it checks: the SVG drawn by `qr.matrix()` decodes back to the original text through
`cv2.QRCodeDetector` (the same engine as a phone camera) for short texts, long texts, accented
texts and texts at the limit of each version; and that the chosen version matches `segno`'s
(the reference) for text that is not digits only (`qr.py` only does byte mode, so a pure number
uses a larger version than optimal -- not a bug, it is documented in the module).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
from gamepanel.security import qr  # noqa: E402

try:
    import cv2
    import numpy as np
    import segno
except ImportError:
    raise SystemExit(
        "faltam opencv-python-headless e segno: rode numa venv descartavel, ver o cabecalho"
        " deste arquivo. NUNCA instale isto em admin/requirements-dev.txt."
    ) from None


def _rasteriza(matriz: list[list[bool]], escala: int = 6, borda: int = 4):
    n = len(matriz)
    lado = (n + 2 * borda) * escala
    img = np.full((lado, lado), 255, dtype=np.uint8)
    for y, linha in enumerate(matriz):
        for x, escuro in enumerate(linha):
            if escuro:
                a, b = (y + borda) * escala, (x + borda) * escala
                img[a:a + escala, b:b + escala] = 0
    return img


CASOS = [
    "otpauth://totp/Painel%20de%20Jogos%3Aadmin?secret=JBSWY3DPEHPK3PXP&issuer=Painel"
    "%20de%20Jogos&algorithm=SHA1&digits=6&period=30",
    "A", "HELLO WORLD", "acentuacao com ção e ãõ",
    "x" * 1, "x" * 26, "x" * 100, "x" * 150, "x" * 213,
]


def main() -> None:
    detector = cv2.QRCodeDetector()
    falhas = 0
    for texto in CASOS:
        matriz = qr.matrix(texto)
        lido, _pontos, _ = detector.detectAndDecode(_rasteriza(matriz))
        ok = lido == texto
        print(("OK   " if ok else "FALHA"), f"bytes={len(texto.encode()):3d} modulos={len(matriz):3d}",
              repr(texto[:40]))
        falhas += not ok

    try:
        qr.matrix("x" * 214)
        print("FALHA capacidade maxima nao recusou 214 bytes")
        falhas += 1
    except qr.TextTooLarge:
        print("OK   capacidade maxima recusa 214 bytes")

    print("\n--- versao escolhida x segno (texto nao numerico, mesma correcao M) ---")
    for texto in ("HELLO WORLD", CASOS[0], "x" * 100):
        referencia = segno.make(texto, error="m", boost_error=False, micro=False)
        esperado = 4 * int(referencia.version) + 17
        obtido = len(qr.matrix(texto))
        bate = esperado == obtido
        print(("OK   " if bate else "DIFERE"), texto[:30], "segno=", esperado, "qr.py=", obtido)
        falhas += not bate

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    raise SystemExit(1 if falhas else 0)


if __name__ == "__main__":
    main()
