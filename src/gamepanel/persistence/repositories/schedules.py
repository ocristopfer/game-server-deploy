"""Leitura e escrita da tabela `schedules` — reinicio e backup na hora marcada."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

# As colunas que a tela preenche. A ordem e a mesma do INSERT.
FIELDS = ("action", "kind", "hour", "minute", "weekday", "every_hours")


def by_id(conn: sqlite3.Connection, aid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM schedules WHERE id = ?", (aid,)).fetchone()


def of_server(conn: sqlite3.Connection, sid: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM schedules WHERE server_id = ? ORDER BY id", (sid,)).fetchall()


def enabled(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """As que o relogio precisa olhar. Desligada nao entra: e o jeito de pausar uma
    tarefa sem perder a configuracao dela."""
    return conn.execute("SELECT * FROM schedules WHERE enabled = 1").fetchall()


def insert(conn: sqlite3.Connection, sid: int, data: Mapping[str, Any],
           last_run: str, created_at: str) -> None:
    """Nasce LIGADA e com `last_run` preenchido: sem isso a primeira volta do relogio
    acharia que ela esta vencida desde sempre e dispararia na hora."""
    conn.execute(
        f"INSERT INTO schedules (server_id, {', '.join(FIELDS)},"  # noqa: S608
        " enabled, last_run, created_at)"
        f" VALUES ({', '.join('?' * (len(FIELDS) + 1))}, 1, ?, ?)",
        (sid, *[data[c] for c in FIELDS], last_run, created_at))


def mark_run(conn: sqlite3.Connection, aid: int, when: str) -> None:
    """Marca ANTES de disparar: se o job demorar (um update leva quase uma hora), a
    proxima volta do relogio nao pode achar que a tarefa ainda esta vencida."""
    conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (when, aid))


def set_enabled(conn: sqlite3.Connection, aid: int, on: bool) -> None:
    conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (1 if on else 0, aid))


def delete(conn: sqlite3.Connection, aid: int) -> None:
    conn.execute("DELETE FROM schedules WHERE id = ?", (aid,))
