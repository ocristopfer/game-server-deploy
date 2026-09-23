"""Leitura e escrita da tabela `samples` — CPU, memoria e jogadores ao longo do tempo."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

# A ordem das colunas do INSERT em lote. Quem monta as linhas segue esta lista.
FIELDS = ("server_id", "taken_at", "cpu_pct", "mem_pct", "players")


def insert_many(conn: sqlite3.Connection, rows: Iterable[Sequence[Any]]) -> None:
    """Uma volta do monitor grava todos os servidores de uma vez: sao N linhas por
    minuto, e um INSERT por servidor seria N transacoes onde cabe uma."""
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
