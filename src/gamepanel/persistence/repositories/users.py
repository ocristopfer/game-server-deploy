"""Reads and writes the `users` table, including the second-factor state."""
from __future__ import annotations

import sqlite3

# What the session needs to know about who is logged in. Never the password hash nor the
# 2FA secret: those only leave the table in the functions that actually check them.
SESSION_FIELDS = "id, username, role, created_at, totp_enabled, lang"
LIST_FIELDS = "id, username, role, created_at, totp_enabled"


def by_id(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def id_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()


def for_session(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    """Only the fields the session uses - no password hash or 2FA secret."""
    return conn.execute(
        f"SELECT {SESSION_FIELDS} FROM users WHERE id = ?", (uid,)).fetchone()  # noqa: S608


def identity(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, role FROM users WHERE id = ?", (uid,)).fetchone()


def all_ordered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {LIST_FIELDS} FROM users ORDER BY role, username").fetchall()  # noqa: S608


def two_factor_state(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT totp_enabled, totp_recovery FROM users WHERE id = ?", (uid,)).fetchone()


def count_admins_besides(conn: sqlite3.Connection, admin_role: str, uid: int) -> int:
    """How many administrators remain if this one leaves. Zero is the road to a panel with
    nobody able to administer it."""
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = ? AND id <> ?", (admin_role, uid),
    ).fetchone()[0]


# --- writing ------------------------------------------------------------------------

def insert(conn: sqlite3.Connection, username: str, password_hash: str, role: str,
           created_at: str) -> None:
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at)"
        " VALUES (?, ?, ?, ?)", (username, password_hash, role, created_at))


def set_password(conn: sqlite3.Connection, uid: int, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, uid))


def set_password_and_role(conn: sqlite3.Connection, uid: int, password_hash: str,
                          role: str) -> None:
    conn.execute("UPDATE users SET password_hash = ?, role = ? WHERE id = ?",
                 (password_hash, role, uid))


def set_role(conn: sqlite3.Connection, uid: int, role: str) -> None:
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))


def set_language(conn: sqlite3.Connection, uid: int, lang: str) -> None:
    conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, uid))


def delete(conn: sqlite3.Connection, uid: int) -> None:
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))


# --- second factor --------------------------------------------------------------------

def spend_step(conn: sqlite3.Connection, uid: int, step: int) -> bool:
    """Spend a TOTP step, and return whether THIS call got it.

    The `WHERE totp_last_step < ?` makes the UPDATE the gate: two requests with the SAME
    code at the same time do not both pass - the second finds no row with a lower step.
    Checking first and writing afterwards would leave the window open between the two.
    """
    return conn.execute(
        "UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?",
        (step, uid, step)).rowcount == 1


def spend_recovery(conn: sqlite3.Connection, uid: int, remaining: str,
                   previous: str) -> bool:
    """Same gate, for the recovery codes: only writes if the list is still the one that was
    read, so two requests cannot spend the same code."""
    return conn.execute(
        "UPDATE users SET totp_recovery = ? WHERE id = ? AND totp_recovery = ?",
        (remaining, uid, previous)).rowcount == 1


def enable_two_factor(conn: sqlite3.Connection, uid: int, secret: str, step: int,
                      recovery: str) -> None:
    conn.execute(
        "UPDATE users SET totp_secret = ?, totp_enabled = 1, totp_last_step = ?,"
        " totp_recovery = ? WHERE id = ?", (secret, step, recovery, uid))


def set_recovery(conn: sqlite3.Connection, uid: int, recovery: str) -> None:
    conn.execute("UPDATE users SET totp_recovery = ? WHERE id = ?", (recovery, uid))


def disable_two_factor(conn: sqlite3.Connection, uid: int) -> None:
    """Clear EVERYTHING of the second factor, including the step and the recovery codes:
    leaving the secret behind would let an old app keep generating valid codes once 2FA is
    turned back on."""
    conn.execute(
        "UPDATE users SET totp_secret = '', totp_enabled = 0, totp_last_step = 0,"
        " totp_recovery = '' WHERE id = ?", (uid,))
