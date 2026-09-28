#!/usr/bin/env python3
"""Busca de jogo por nome ou App ID, para preencher o formulario "Adicionar jogo".

Le duas listas, as duas no repositorio: `suggestions.py` (gerado por tools/import-linuxgsm.py)
e `manual_suggestions.py` (escrita a mao, para o servidor so de Windows que o LinuxGSM nao
cobre, como o do V Rising antes de virar curado). O painel em producao nao consulta nada na
internet, entao nao ha SSRF nem dependencia de terceiro em tempo de uso. Puro como
`navigation.py`: sem Flask, sem banco.

O resultado e SUGESTAO. Quem valida e o broker quando o formulario e enviado.
"""
from __future__ import annotations

import re
import unicodedata

from gamepanel.games.catalog import manual_suggestions
from gamepanel.games.catalog import suggestions as sugestoes_de_jogos

SOURCE = f"{sugestoes_de_jogos.SOURCE}; {manual_suggestions.SOURCE}"
DEFAULT_LIMIT = 8
QUERY_MAX = 60


def _normalize(text: str) -> str:
    """Sem acento, minusculo, so letras e numeros: 'Counter-Strike' casa 'counter strike'."""
    without_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).strip()


# A fonte de cada sugestao vai junto, e a tela a mostra: "LinuxGSM" e "curadoria do painel" sao
# graus de confianca diferentes, e quem confere o formulario precisa saber qual esta vendo.
_ALL = (tuple((s, sugestoes_de_jogos.SOURCE) for s in sugestoes_de_jogos.SUGGESTIONS)
        + tuple((s, manual_suggestions.SOURCE) for s in manual_suggestions.SUGGESTIONS))
_SOURCE_OF = {id(s): source for s, source in _ALL}
_INDEX = tuple((s, _normalize(f"{s['name']} {s['key']}")) for s, _ in _ALL)


def search(query: str | None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Numero puro = App ID exato. Texto = todas as palavras aparecem no nome; quem COMECA
    pela primeira palavra vem antes ('pal' acha Palworld antes de 'Space Pals')."""
    q = (query or "").strip()[:QUERY_MAX]
    if not q:
        return []
    if q.isdigit():
        return [s for s, _ in _ALL if str(s["appid"]) == q][:limit]
    terms = _normalize(q).split()
    if not terms:
        return []
    found = [(s, text) for s, text in _INDEX if all(t in text for t in terms)]
    # `str(...)`: cada sugestao e um `dict` de valores mistos (numero do App ID, texto do
    # nome), entao para o verificador de tipo `s["name"]` e `object`. O `str` diz o que
    # este campo E, em vez de espalhar `cast` pelas duas linhas de ordenacao.
    found.sort(key=lambda par: (not _normalize(str(par[0]["name"])).startswith(terms[0]),
                                  str(par[0]["name"]).lower()))
    return [s for s, _ in found[:limit]]


def to_form(s: dict) -> dict[str, str]:
    """Os valores nas chaves que sao os `name=` dos campos. TODAS as chaves sempre, mesmo
    vazias: escolher outro jogo tem de limpar o que o anterior deixou (script, portas, a
    pasta de config e o padrao de log de um jogo que nao e este)."""
    return {
        "key": s["key"], "name": s["name"], "app_id": str(s["appid"]),
        "ports": s["ports"], "game_port": str(s["game_port"] or ""),
        "query_port": str(s["query_port"] or ""), "extra_port": str(s.get("extra_port") or ""),
        "start_script": s["start_script"], "start_args": s["start_args"],
        "shiftable": "1" if s["shiftable"] else "",
        "config_path": s.get("config_path", ""),
        "config_files": "\n".join(s.get("config_files") or []),
        "player_source": s.get("player_source") or "log",
        # O LinuxGSM nao diz onde fica o save, o que o log escreve nem quanto o jogo pede de
        # maquina: fica em branco, e nao com o que sobrou do jogo escolhido antes. A lista
        # manual diz, e entao vai.
        "backup_paths": "\n".join(s.get("backup_paths") or []),
        "join_re": s.get("join_re", ""), "leave_re": s.get("leave_re", ""),
        "memory_mb": str(s.get("memory_mb") or ""), "cores": str(s.get("cores") or ""),
        "disk_gb": str(s.get("disk_gb") or ""),
        # Jogo do LinuxGSM e sempre Linux: plataforma e receitas vazias LIMPAM o Windows e o
        # Proton de uma sugestao anterior, que virariam uma instalacao de Wine sem motivo.
        "platform": s.get("platform", ""), "recipes": " ".join(s.get("recipes") or []),
    }


def result(s: dict) -> dict:
    return {"appid": s["appid"], "name": s["name"], "values": to_form(s),
            "warnings": list(s["warnings"]), "source": _SOURCE_OF.get(id(s), "")}
