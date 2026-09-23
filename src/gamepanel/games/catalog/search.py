#!/usr/bin/env python3
"""Busca de jogo por nome ou App ID, para preencher o formulario "Adicionar jogo".

Le `sugestoes_de_jogos.py` (gerado por tools/import-linuxgsm.py, entra no repositorio): o
painel em producao nao consulta nada na internet, entao nao ha SSRF nem dependencia de terceiro
em tempo de uso. Puro como `ui.py`: sem Flask, sem banco.

O resultado e SUGESTAO. Quem valida e o broker quando o formulario e enviado.
"""
from __future__ import annotations

import re
import unicodedata

from gamepanel.games.catalog import suggestions as sugestoes_de_jogos

SOURCE = sugestoes_de_jogos.SOURCE
DEFAULT_LIMIT = 8
QUERY_MAX = 60


def _normalize(text: str) -> str:
    """Sem acento, minusculo, so letras e numeros: 'Counter-Strike' casa 'counter strike'."""
    without_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


_INDEX = tuple((s, _normalize(f"{s['name']} {s['key']}")) for s in sugestoes_de_jogos.SUGGESTIONS)


def search(query: str | None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Numero puro = App ID exato. Texto = todas as palavras aparecem no nome; quem COMECA
    pela primeira palavra vem antes ('pal' acha Palworld antes de 'Space Pals')."""
    q = (query or "").strip()[:QUERY_MAX]
    if not q:
        return []
    if q.isdigit():
        return [s for s in sugestoes_de_jogos.SUGGESTIONS if str(s["appid"]) == q][:limit]
    terms = _normalize(q).split()
    if not terms:
        return []
    found = [(s, text) for s, text in _INDEX if all(t in text for t in terms)]
    found.sort(key=lambda par: (not _normalize(par[0]["name"]).startswith(terms[0]),
                                  par[0]["name"].lower()))
    return [s for s, _ in found[:limit]]


def to_form(s: dict) -> dict[str, str]:
    """Os valores nas chaves que sao os `name=` dos campos. TODAS as chaves sempre, mesmo
    vazias: escolher outro jogo tem de limpar o que o anterior deixou (script, portas)."""
    return {
        "key": s["key"], "name": s["name"], "app_id": str(s["appid"]),
        "ports": s["ports"], "game_port": str(s["game_port"] or ""),
        "query_port": str(s["query_port"] or ""), "extra_port": str(s.get("extra_port") or ""),
        "start_script": s["start_script"], "start_args": s["start_args"],
        "shiftable": "1" if s["shiftable"] else "",
    }


def result(s: dict) -> dict:
    return {"appid": s["appid"], "name": s["name"], "values": to_form(s),
            "warnings": list(s["warnings"])}
