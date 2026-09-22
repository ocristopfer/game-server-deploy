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
TEXT_FIELDS = ("key", "name", "platform", "start_script", "start_args",
               "config_path", "log_path", "join_re", "leave_re", "player_source")
# Campos numericos, com o rotulo que aparece no erro.
NUMERIC_FIELDS = (
    ("app_id", "App ID"), ("game_port", "Porta do jogo"),
    ("query_port", "Porta de consulta"), ("extra_port", "Porta extra"),
    ("memory_mb", "Memoria"), ("cores", "CPUs"), ("disk_gb", "Disco"),
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
    dados["ports"] = [p for p in re.split(r"[\s,]+", (form.get("ports") or "").strip()) if p]
    dados["config_files"] = lines_of(form.get("config_files", ""))
    dados["backup_paths"] = lines_of(form.get("backup_paths", ""))
    dados["recipes"] = [r for r in form.getlist("recipes") if r in BROKER_RECIPES]
    dados["shiftable"] = form.get("shiftable") == "1"
    return dados, erros
