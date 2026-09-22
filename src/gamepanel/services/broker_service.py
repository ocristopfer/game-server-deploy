"""Formulario de "jogo novo" do catalogo do broker.

So converte tipos e recolhe as listas — quem VALIDA de verdade e o broker, que recusa
campo desconhecido, caminho fora de /opt/game e comando escondido. Conferir aqui de
novo seria manter duas listas do que vale, e uma delas ficaria para tras.
"""
from __future__ import annotations

import re
from typing import Any

# Espelho do gamebroker.catalogo.RECEITAS: so para desenhar as caixas do formulario.
BROKER_RECIPES = ("wine", "proton", "steamclient-sdk64")
NUMBER_RE = re.compile(r"[0-9]{1,10}", re.ASCII)

# Campos que entram como texto, se vierem preenchidos.
TEXT_FIELDS = ("chave", "nome", "plataforma", "start_script", "start_args",
                   "config_path", "log_path", "join_re", "leave_re", "player_source")
# Campos numericos, com o rotulo que aparece no erro.
NUMERIC_FIELDS = (
    ("app_id", "App ID"), ("porta_jogo", "Porta do jogo"),
    ("porta_query", "Porta de consulta"), ("porta_extra", "Porta extra"),
    ("memoria_mb", "Memoria"), ("cores", "CPUs"), ("disco_gb", "Disco"),
)


def lines_of(text: str) -> list[str]:
    """Uma entrada por linha (virgula tambem separa), sem vazios."""
    return [p.strip() for p in (text or "").replace(",", "\n").splitlines() if p.strip()]


def game_from_form(form: Any) -> tuple[dict, list[str]]:
    """Le o formulario de jogo novo: devolve o que mandar ao broker, e os erros de tipo."""
    erros: list[str] = []
    dados: dict = {}
    for campo in TEXT_FIELDS:
        valor = (form.get(campo) or "").strip()
        if valor:
            dados[campo] = valor
    for campo, label in NUMERIC_FIELDS:
        bruto = (form.get(campo) or "").strip()
        if not bruto:
            continue
        if NUMBER_RE.fullmatch(bruto):
            dados[campo] = int(bruto)
        else:
            erros.append(f"{label} deve ser um numero.")
    dados["portas"] = [p for p in re.split(r"[\s,]+", (form.get("portas") or "").strip()) if p]
    dados["config_files"] = lines_of(form.get("config_files", ""))
    dados["backup_paths"] = lines_of(form.get("backup_paths", ""))
    dados["receitas"] = [r for r in form.getlist("receitas") if r in BROKER_RECIPES]
    dados["deslocavel"] = form.get("deslocavel") == "1"
    return dados, erros
