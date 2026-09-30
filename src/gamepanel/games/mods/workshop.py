"""IDs da Steam Workshop: o que a pessoa cola e o que o painel devolve como link.

A lista chega do jeito que circula entre jogadores - link por link, com nome e hora de chat
na frente (`[14:48] Fulano: https://steamcommunity.com/...?id=3132251325`). Por isso o
leitor procura o `id=` de cada linha e aceita tambem o numero sozinho, em vez de exigir um
formato. Um numero curto no meio da conversa (a hora, "1.61") nao e ID: os da Workshop tem
de 6 digitos para cima.
"""
from __future__ import annotations

import re

_URL_ID = re.compile(r"[?&]id=(\d{6,20})", re.ASCII)
_BARE_ID = re.compile(r"^\s*(\d{6,20})\s*$", re.ASCII)
# Teto do que se aceita colar: a lista e de mods de um servidor, nao um dump.
MAX_IDS = 200


def parse_ids(text: str) -> list[int]:
    """Os IDs, na ordem em que aparecem e sem repetir."""
    found: list[int] = []
    for line in (text or "").splitlines():
        ids = _URL_ID.findall(line) or _BARE_ID.findall(line)
        found.extend(int(i) for i in ids)
    return list(dict.fromkeys(found))[:MAX_IDS]


def url(workshop_id: int) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
