"""Reads and writes the `servers` table."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# The columns the server form fills in. The SAME list serves the INSERT, the UPDATE and
# reading the form: writing all three by hand is where a new column lands in two and goes
# missing from the third.
HTTP_FIELDS = ("http_url", "http_auth", "http_body", "http_list_path", "http_count_path",
               "http_login_url", "http_login_body", "http_token_path")
EDITABLE_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "backup_paths", "query_port", "player_source",
    "join_re", "leave_re", "log_path", "error_re", "max_players",
    *HTTP_FIELDS,
)

# Columns the DEPLOY brings - a subset of the editable ones, plus `broker_id`. The deploy
# knows neither the HTTP count columns nor `error_re`: the screen fills those in.
DEPLOY_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "backup_paths", "query_port", "player_source",
    "join_re", "leave_re", "log_path", "broker_id", "max_players",
)
# What a redeploy does NOT overwrite is left out of this list (`host` and `ssh_port` are
# the identity; `error_re` and the HTTP ones are tuned on the screen).
DEPLOY_UPDATE_FIELDS = (
    "name", "ssh_user", "service", "game_port", "notes", "config_path", "config_files",
    "backup_paths", "query_port", "player_source", "join_re", "leave_re", "log_path",
    "max_players",
)

# The four statements are BUILT from the lists above, not written by hand: the
# alternative is repeating the column names four times and finding the divergence at
# runtime. Nothing here comes from outside - these are this file's constants - and every
# VALUE stays parameterized.
_INSERT = (
    f"INSERT INTO servers ({', '.join(EDITABLE_FIELDS)}, created_at)"  # noqa: S608
    f" VALUES ({', '.join('?' * (len(EDITABLE_FIELDS) + 1))})"
)
_UPDATE = f"UPDATE servers SET {', '.join(c + '=?' for c in EDITABLE_FIELDS)} WHERE id=?"  # noqa: S608
_DEPLOY_INSERT = (
    f"INSERT INTO servers ({', '.join(DEPLOY_FIELDS)}, created_at)"  # noqa: S608
    f" VALUES ({', '.join('?' * (len(DEPLOY_FIELDS) + 1))})"
)
_DEPLOY_UPDATE = (
    f"UPDATE servers SET {', '.join(c + '=?' for c in DEPLOY_UPDATE_FIELDS)} WHERE id=?"  # noqa: S608
)


# --- reading ------------------------------------------------------------------------

def by_id(conn: sqlite3.Connection, sid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()


def all_ordered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM servers ORDER BY name").fetchall()


def by_address(conn: sqlite3.Connection, host: str, ssh_port: int) -> sqlite3.Row | None:
    """The address is a server's identity: `(host, ssh_port)` is UNIQUE in the schema."""
    return conn.execute(
        "SELECT * FROM servers WHERE host = ? AND ssh_port = ?", (host, ssh_port)).fetchone()


def id_by_host(conn: sqlite3.Connection, host: str) -> sqlite3.Row | None:
    """The server on that address's default SSH port - the one the broker just created."""
    return conn.execute(
        "SELECT id FROM servers WHERE host = ? AND ssh_port = 22", (host,)).fetchone()


def from_broker(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The ones the broker created: the only ones with `broker_id` filled in."""
    return conn.execute(
        "SELECT id, name, broker_id, service FROM servers WHERE broker_id > 0").fetchall()


def by_broker_id(conn: sqlite3.Connection, broker_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM servers WHERE broker_id = ?", (broker_id,)).fetchone()


# --- writes from the screen ---------------------------------------------------------------

def insert(conn: sqlite3.Connection, data: Mapping[str, Any], created_at: str) -> None:
    conn.execute(_INSERT, (*[data[c] for c in EDITABLE_FIELDS], created_at))


def update(conn: sqlite3.Connection, data: Mapping[str, Any], sid: int) -> None:
    conn.execute(_UPDATE, (*[data[c] for c in EDITABLE_FIELDS], sid))


def delete(conn: sqlite3.Connection, sid: int) -> None:
    conn.execute("DELETE FROM servers WHERE id = ?", (sid,))


def delete_by_broker_id(conn: sqlite3.Connection, broker_id: int) -> None:
    conn.execute("DELETE FROM servers WHERE broker_id = ?", (broker_id,))


# --- writes from the player-count wizard ---------------------------------
#
# Each source writes what only it uses AND sets `player_source` in the same statement:
# they are the same decision, and splitting them would leave a server pointing at a
# source without its fields filled in.

def use_query_port(conn: sqlite3.Connection, sid: int, port: int) -> None:
    conn.execute(
        "UPDATE servers SET query_port = ?, player_source = 'a2s' WHERE id = ?", (port, sid))


def use_presence(conn: sqlite3.Connection, sid: int) -> None:
    # No field of its own: the source reads the set that the CT's firewall maintains.
    conn.execute("UPDATE servers SET player_source = 'net' WHERE id = ?", (sid,))


def use_http(conn: sqlite3.Connection, sid: int, fields: Mapping[str, Any]) -> None:
    """The stored token is CLEARED on save: if the URL or the credential changed, the old
    one is no longer valid, and the next query logs in with what was saved."""
    columns = ", ".join(f"{c}=?" for c in HTTP_FIELDS)
    # These are this file's column names, never an outside value; the VALUES stay
    # parameterized.
    conn.execute(
        f"UPDATE servers SET {columns}, http_token='', player_source='http'"  # noqa: S608
        " WHERE id=?",
        (*[fields[c] for c in HTTP_FIELDS], sid))


def use_log(conn: sqlite3.Connection, sid: int, join_re: str, leave_re: str,
            log_path: str) -> None:
    conn.execute(
        "UPDATE servers SET join_re = ?, leave_re = ?, log_path = ?,"
        " player_source = 'log' WHERE id = ?", (join_re, leave_re, log_path, sid))


def set_http_token(conn: sqlite3.Connection, sid: int, token: str) -> None:
    conn.execute("UPDATE servers SET http_token = ? WHERE id = ?", (token, sid))


def set_config_files(conn: sqlite3.Connection, sid: int, paths: Iterable[str]) -> None:
    conn.execute("UPDATE servers SET config_files = ? WHERE id = ?", ("\n".join(paths), sid))


def set_mods_expected(conn: sqlite3.Connection, sid: int, workshop_ids: Iterable[int]) -> None:
    conn.execute("UPDATE servers SET mods_expected = ? WHERE id = ?",
                 ("\n".join(str(i) for i in workshop_ids), sid))


# --- writes from the deploy (no screen) ---------------------------------------------------

def deploy_insert(conn: sqlite3.Connection, values: Sequence[Any], created_at: str) -> None:
    conn.execute(_DEPLOY_INSERT, (*values, created_at))


def deploy_update(conn: sqlite3.Connection, values: Sequence[Any], sid: int) -> None:
    conn.execute(_DEPLOY_UPDATE, (*values, sid))
