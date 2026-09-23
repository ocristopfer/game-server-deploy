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
    failures: list[str] = []
    payload: dict = {}
    for field in TEXT_FIELDS:
        value = (form.get(field) or "").strip()
        if value:
            payload[field] = value
    for field, label in NUMERIC_FIELDS:
        raw_text = (form.get(field) or "").strip()
        if not raw_text:
            continue
        if NUMBER_RE.fullmatch(raw_text):
            payload[field] = int(raw_text)
        else:
            failures.append(f"{label} deve ser um numero.")
    payload["ports"] = [p for p in re.split(r"[\s,]+", (form.get("ports") or "").strip()) if p]
    payload["config_files"] = lines_of(form.get("config_files", ""))
    payload["backup_paths"] = lines_of(form.get("backup_paths", ""))
    payload["recipes"] = [r for r in form.getlist("recipes") if r in BROKER_RECIPES]
    payload["shiftable"] = form.get("shiftable") == "1"
    return payload, failures
