"""Leitura e escrita de `webhooks` (para onde o alerta vai) e `alert_log` (o diario)."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

# Cortes de tamanho: um alerta vai para um canal de chat, e detalhe alem disto e ruido
# na tela de quem le. Cortar AQUI mantem o banco pequeno tambem.
TITLE_MAX = 200
DETAIL_MAX = 500
TARGET_MAX = 80
ERROR_MAX = 300

DEFAULT_NAME = "Destino"


# --- webhooks -----------------------------------------------------------------------

def all_webhooks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, url, events, enabled FROM webhooks ORDER BY id").fetchall()


def count_webhooks(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM webhooks").fetchone()["n"]


def webhook_by_id(conn: sqlite3.Connection, hid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM webhooks WHERE id = ?", (hid,)).fetchone()


def insert_webhook(conn: sqlite3.Connection, data: Mapping[str, Any],
                   created_at: str) -> None:
    conn.execute(
        "INSERT INTO webhooks (name, url, events, enabled, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (data["name"] or DEFAULT_NAME, data["url"], data["events"],
         data["enabled"], created_at))


def update_webhook(conn: sqlite3.Connection, hid: int, name: str, url: str,
                   events: str, enabled: int) -> None:
    conn.execute(
        "UPDATE webhooks SET name = ?, url = ?, events = ?, enabled = ? WHERE id = ?",
        (name or DEFAULT_NAME, url, events, enabled, hid))


def delete_webhook(conn: sqlite3.Connection, hid: int) -> None:
    conn.execute("DELETE FROM webhooks WHERE id = ?", (hid,))


# --- diario -------------------------------------------------------------------------

def log(conn: sqlite3.Connection, at: str, event: str, title: str, detail: str,
        target: str, status: str, error: str) -> None:
    conn.execute(
        "INSERT INTO alert_log (created_at, event, title, detail, target,"
        " status, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (at, event, title[:TITLE_MAX], detail[:DETAIL_MAX], target[:TARGET_MAX],
         status, error[:ERROR_MAX]))


def recent(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def trim_log(conn: sqlite3.Connection, keep: int) -> None:
    """O diario se mede em LINHAS, nao em dias: o que se quer dele e "as ultimas N", e um
    prazo em dias deixaria a tela vazia justo num painel quieto — que e quando a duvida
    "sera que isso ainda funciona?" aparece."""
    conn.execute(
        "DELETE FROM alert_log WHERE id <= "
        "(SELECT MIN(id) FROM (SELECT id FROM alert_log ORDER BY id DESC LIMIT ?)) - 1",
        (keep,))
