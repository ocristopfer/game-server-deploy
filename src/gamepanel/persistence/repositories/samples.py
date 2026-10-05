"""Reads and writes the `samples` table - CPU, memory and players over time."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

# The column order of the batch INSERT. Whoever builds the rows follows this list.
FIELDS = ("server_id", "taken_at", "cpu_pct", "mem_pct", "players")


def insert_many(conn: sqlite3.Connection, rows: Iterable[Sequence[Any]]) -> None:
    """One monitor round writes all servers at once: that is N rows per minute, and one
    INSERT per server would be N transactions where one fits."""
    conn.executemany(
        f"INSERT INTO samples ({', '.join(FIELDS)})"  # noqa: S608
        f" VALUES ({', '.join('?' * len(FIELDS))})",
        rows)


def of_server_since(conn: sqlite3.Connection, sid: int, since: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT taken_at, cpu_pct, mem_pct, players FROM samples"
        " WHERE server_id = ? AND taken_at >= ? ORDER BY taken_at", (sid, since)).fetchall()


def delete_older_than(conn: sqlite3.Connection, cut: str) -> None:
    conn.execute("DELETE FROM samples WHERE taken_at < ?", (cut,))
