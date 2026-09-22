#!/usr/bin/env python3
"""Busca de jogo por nome ou App ID, para preencher o formulario "Adicionar jogo".

Le `sugestoes_de_jogos.py` (gerado por tools/importar-linuxgsm.py, entra no repositorio): o
painel em producao nao consulta nada na internet, entao nao ha SSRF nem dependencia de terceiro
em tempo de uso. Puro como `ui.py`: sem Flask, sem banco.

O resultado e SUGESTAO. Quem valida e o broker quando o formulario e enviado.
"""
from __future__ import annotations

import re
import unicodedata

import sugestoes_de_jogos

FONTE = sugestoes_de_jogos.FONTE
LIMITE_PADRAO = 8
CONSULTA_MAX = 60


def _normaliza(texto: str) -> str:
    """Sem acento, minusculo, so letras e numeros: 'Counter-Strike' casa 'counter strike'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


_INDICE = tuple((s, _normaliza(f"{s['nome']} {s['chave']}")) for s in sugestoes_de_jogos.SUGESTOES)


def buscar(consulta: str | None, limite: int = LIMITE_PADRAO) -> list[dict]:
    """Numero puro = App ID exato. Texto = todas as palavras aparecem no nome; quem COMECA
    pela primeira palavra vem antes ('pal' acha Palworld antes de 'Space Pals')."""
    q = (consulta or "").strip()[:CONSULTA_MAX]
    if not q:
        return []
    if q.isdigit():
        return [s for s in sugestoes_de_jogos.SUGESTOES if str(s["appid"]) == q][:limite]
    termos = _normaliza(q).split()
    if not termos:
        return []
    achados = [(s, texto) for s, texto in _INDICE if all(t in texto for t in termos)]
    achados.sort(key=lambda par: (not _normaliza(par[0]["nome"]).startswith(termos[0]),
                                  par[0]["nome"].lower()))
    return [s for s, _ in achados[:limite]]


def para_o_formulario(s: dict) -> dict[str, str]:
    """Os valores nas chaves que sao os `name=` dos campos. TODAS as chaves sempre, mesmo
    vazias: escolher outro jogo tem de limpar o que o anterior deixou (script, portas)."""
    return {
        "chave": s["chave"], "nome": s["nome"], "app_id": str(s["appid"]),
        "portas": s["portas"], "porta_jogo": str(s["porta_jogo"] or ""),
        "porta_query": str(s["porta_query"] or ""), "porta_extra": str(s.get("porta_extra") or ""),
        "start_script": s["start_script"], "start_args": s["start_args"],
        "deslocavel": "1" if s["deslocavel"] else "",
    }


def resultado(s: dict) -> dict:
    return {"appid": s["appid"], "nome": s["nome"], "valores": para_o_formulario(s),
            "avisos": list(s["avisos"])}
