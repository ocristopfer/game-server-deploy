"""Reads and writes the `settings` table - the panel's key/value configuration."""
from __future__ import annotations

import sqlite3


def get(conn: sqlite3.Connection, key: str, fallback: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else fallback


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """UPSERT: the key may or may not exist, and a SELECT first would open a window between
    reading and writing."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))
