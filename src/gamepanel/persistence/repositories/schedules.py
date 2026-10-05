"""Reads and writes the `schedules` table - restart and backup at the set time."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

# The columns the screen fills in. The order is the same as the INSERT's.
FIELDS = ("action", "kind", "hour", "minute", "weekday", "every_hours")


def by_id(conn: sqlite3.Connection, aid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM schedules WHERE id = ?", (aid,)).fetchone()


def of_server(conn: sqlite3.Connection, sid: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM schedules WHERE server_id = ? ORDER BY id", (sid,)).fetchall()


def enabled(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The ones the clock needs to look at. A disabled one is left out: that is how a task
    is paused without losing its configuration."""
    return conn.execute("SELECT * FROM schedules WHERE enabled = 1").fetchall()


def insert(conn: sqlite3.Connection, sid: int, data: Mapping[str, Any],
           last_run: str, created_at: str) -> None:
    """Born ENABLED and with `last_run` filled in: without that the clock's first round
    would think it had been overdue forever and fire it immediately."""
    conn.execute(
        f"INSERT INTO schedules (server_id, {', '.join(FIELDS)},"  # noqa: S608
        " enabled, last_run, created_at)"
        f" VALUES ({', '.join('?' * (len(FIELDS) + 1))}, 1, ?, ?)",
        (sid, *[data[c] for c in FIELDS], last_run, created_at))


def mark_run(conn: sqlite3.Connection, aid: int, when: str) -> None:
    """Mark BEFORE firing: if the job takes long (an update takes almost an hour), the
    clock's next round must not think the task is still overdue."""
    conn.execute("UPDATE schedules SET last_run = ? WHERE id = ?", (when, aid))


def set_enabled(conn: sqlite3.Connection, aid: int, on: bool) -> None:
    conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?", (1 if on else 0, aid))


def delete(conn: sqlite3.Connection, aid: int) -> None:
    conn.execute("DELETE FROM schedules WHERE id = ?", (aid,))
