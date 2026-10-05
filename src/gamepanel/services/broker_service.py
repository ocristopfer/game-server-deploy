"""The "new game" form of the broker catalog.

It only converts types and gathers the lists: the real VALIDATION is done by the broker,
which rejects unknown fields, paths outside /opt/game and hidden commands. Checking again
here would mean keeping two lists of what is allowed, and one of them would fall behind.
"""
from __future__ import annotations

import re
from typing import Any

from gamepanel.i18n import Message

# Mirror of gamebroker.catalogo.RECEITAS: only used to draw the form's checkboxes. Proton
# comes before wine on purpose: it is the preferred runtime for a server without a Linux
# build (fsync and ntsync, which the distro's wine lacks), and wine is for when Proton
# does not work.
BROKER_RECIPES = ("proton", "wine", "xvfb", "steamclient-sdk64")
NUMBER_RE = re.compile(r"[0-9]{1,10}", re.ASCII)

# Fields that go in as text, when filled in.
TEXT_FIELDS = ("key", "name", "platform", "start_script", "start_args",
               "config_path", "log_path", "join_re", "leave_re", "player_source")
# Numeric fields, with the catalog KEY of the label that shows up in the error. A key and not
# the text: the error goes into a `Message`, and `translate` renders the label in the same
# language as the phrase around it - a literal label would stay Portuguese on the English screen.
NUMERIC_FIELDS = (
    ("app_id", "broker_form.app_id"), ("game_port", "catalog.game_port"),
    ("query_port", "catalog.query_port"), ("extra_port", "catalog.extra_port"),
    ("memory_mb", "broker_form.memory"), ("cores", "catalog.cpus"), ("disk_gb", "metrics.disk"),
)


def lines_of(text: str) -> list[str]:
    """One entry per line (a comma also separates), without empty ones."""
    return [p.strip() for p in (text or "").replace(",", "\n").splitlines() if p.strip()]


def game_from_form(form: Any) -> tuple[dict, list[str]]:
    """Reads the new game form: returns what to send to the broker, and the type errors.

    The errors are `Message`s: whoever flashes them passes each one through `translate`.
    """
    failures: list[str] = []
    payload: dict = {}
    for field in TEXT_FIELDS:
        value = (form.get(field) or "").strip()
        if value:
            payload[field] = value
    for field, label_key in NUMERIC_FIELDS:
        raw_text = (form.get(field) or "").strip()
        if not raw_text:
            continue
        if NUMBER_RE.fullmatch(raw_text):
            payload[field] = int(raw_text)
        else:
            failures.append(Message("broker_form.must_be_number", label=Message(label_key)))
    payload["ports"] = [p for p in re.split(r"[\s,]+", (form.get("ports") or "").strip()) if p]
    payload["config_files"] = lines_of(form.get("config_files", ""))
    payload["backup_paths"] = lines_of(form.get("backup_paths", ""))
    payload["recipes"] = [r for r in form.getlist("recipes") if r in BROKER_RECIPES]
    payload["shiftable"] = form.get("shiftable") == "1"
    return payload, failures
