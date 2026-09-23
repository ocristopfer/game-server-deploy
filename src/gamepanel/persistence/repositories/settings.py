"""Leitura e escrita da tabela `settings` — chave/valor de configuracao do painel."""
from __future__ import annotations

import sqlite3


def get(conn: sqlite3.Connection, key: str, fallback: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else fallback


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """UPSERT: a chave pode ou nao existir, e um SELECT antes abriria uma janela entre
    ler e gravar."""
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value))
