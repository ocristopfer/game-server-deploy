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


# Arma Reforger: o workshop e da Bohemia, e o ID e um GUID de 16 hex. O link da pagina traz o
# nome depois do GUID (`/workshop/5965550F24A0C152-WhereAmI`); a linha colada pode trazer o nome
# depois dele (`5965550F24A0C152 Where Am I`), que e como ele aparece na config.
_GUID = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{16})(?![0-9A-Fa-f])(?:-([A-Za-z0-9_]+))?(.*)$", re.ASCII)
# Nome vai para o JSON e para o log do servidor: texto curto, sem caractere de controle.
_NAME_JUNK = re.compile(r"[\x00-\x1f\x7f=]")
NAME_MAX = 80


def parse_guids(text: str) -> list[tuple[str, str]]:
    """(GUID em maiusculas, nome) de cada linha, na ordem e sem repetir o GUID."""
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _GUID.search(line)
        if not m:
            continue
        guid, slug, rest = m.group(1).upper(), m.group(2) or "", m.group(3)
        name = _NAME_JUNK.sub("", rest).strip(" -:\t") or slug
        found.setdefault(guid, name[:NAME_MAX].strip())
    return list(found.items())[:MAX_IDS]


def reforger_url(guid: str) -> str:
    return f"https://reforger.armaplatform.com/workshop/{guid}"


def url(workshop_id: int) -> str:
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
