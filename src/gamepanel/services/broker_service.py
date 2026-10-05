"""The "new game" form of the broker catalog.

It only converts types and gathers the lists: the real VALIDATION is done by the broker,
which rejects unknown fields, paths outside /opt/game and hidden commands. Checking again
here would mean keeping two lists of what is allowed, and one of them would fall behind.
"""
from __future__ import annotations

import re
from typing import Any

# Mirror of gamebroker.catalogo.RECEITAS: only used to draw the form's checkboxes. Proton
# comes before wine on purpose: it is the preferred runtime for a server without a Linux
# build (fsync and ntsync, which the distro's wine lacks), and wine is for when Proton
# does not work.
BROKER_RECIPES = ("proton", "wine", "xvfb", "steamclient-sdk64")
NUMBER_RE = re.compile(r"[0-9]{1,10}", re.ASCII)

# Fields that go in as text, when filled in.
TEXT_FIELDS = ("key", "name", "platform", "start_script", "start_args",
               "config_path", "log_path", "join_re", "leave_re", "player_source")
# Numeric fields, with the label that shows up in the error.
NUMERIC_FIELDS = (
    ("app_id", "App ID"), ("game_port", "Porta do jogo"),
    ("query_port", "Porta de consulta"), ("extra_port", "Porta extra"),
    ("memory_mb", "Memoria"), ("cores", "CPUs"), ("disk_gb", "Disco"),
)


def lines_of(text: str) -> list[str]:
    """One entry per line (a comma also separates), without empty ones."""
    return [p.strip() for p in (text or "").replace(",", "\n").splitlines() if p.strip()]


def game_from_form(form: Any) -> tuple[dict, list[str]]:
    """Reads the new game form: returns what to send to the broker, and the type errors."""
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
