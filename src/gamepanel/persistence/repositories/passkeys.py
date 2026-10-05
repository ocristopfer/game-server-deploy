"""Reads and writes the `passkeys` table (signing in with the device's biometrics)."""
from __future__ import annotations

import sqlite3

# What the account screen lists: never the public key (not a secret, but useless to anyone there).
LIST_FIELDS = "id, label, created_at, last_used_at"


def by_id(conn: sqlite3.Connection, credential_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM passkeys WHERE id = ?", (credential_id,)).fetchone()


def for_user(conn: sqlite3.Connection, uid: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {LIST_FIELDS} FROM passkeys WHERE user_id = ? ORDER BY created_at", (uid,)).fetchall()  # noqa: S608


def ids_for_user(conn: sqlite3.Connection, uid: int) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM passkeys WHERE user_id = ?", (uid,)).fetchall()]


def handle_for_user(conn: sqlite3.Connection, uid: int) -> str:
    """The user handle this person's devices already store ('' if none yet)."""
    row = conn.execute("SELECT user_handle FROM passkeys WHERE user_id = ? LIMIT 1", (uid,)).fetchone()
    return row["user_handle"] if row else ""


def insert(conn: sqlite3.Connection, credential_id: str, uid: int, user_handle: str, public_key: bytes,
           sign_count: int, label: str, created_at: str) -> None:
    conn.execute(
        "INSERT INTO passkeys (id, user_id, user_handle, public_key, sign_count, label, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (credential_id, uid, user_handle, public_key, sign_count, label, created_at))


def mark_used(conn: sqlite3.Connection, credential_id: str, sign_count: int, used_at: str) -> None:
    conn.execute("UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?",
                 (sign_count, used_at, credential_id))


def delete(conn: sqlite3.Connection, uid: int, credential_id: str) -> int:
    """Delete a device of THIS person; the `user_id` in the WHERE prevents deleting another's."""
    return conn.execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (credential_id, uid)).rowcount
