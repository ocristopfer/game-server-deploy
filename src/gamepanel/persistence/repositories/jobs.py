"""Reads and writes the `jobs` table - the history of everything the panel ran."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

# A server arrives as an SQLite row (normal read) or as a dict (a job's thread copies the
# row, because the Row is bound to the request's connection).
ServerLike = sqlite3.Row | Mapping[str, Any]

# The panel stores a command's whole output; an `apt upgrade` easily passes a megabyte and
# bloats the database per row. The cut is here, not on the screen, so the disk does not grow.
OUTPUT_MAX = 200_000
BROKER_TARGET = "broker"

# Actions that bring the service DOWN on purpose. A drop right after one of them is not an
# outage: it is the button the person just clicked.
DISRUPTIVE_ACTIONS = ("start", "stop", "restart", "update", "restore-backup")


def _row_id(cur: sqlite3.Cursor) -> int:
    """The id of the row just inserted.

    `lastrowid` is Optional in the type because a cursor may not have inserted anything;
    after a successful INSERT, never. Failing loudly here beats returning 0 and leaving the
    job pointing at a row that does not exist.
    """
    if cur.lastrowid is None:
        raise RuntimeError("INSERT em jobs nao devolveu id")
    return cur.lastrowid


# --- reading ------------------------------------------------------------------------

def by_id(conn: sqlite3.Connection, jid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()


def by_id_and_server(conn: sqlite3.Connection, jid: int, sid: int) -> sqlite3.Row | None:
    """The id alone is not enough: the console screen may only show jobs of THAT server."""
    return conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND server_id = ?", (jid, sid)).fetchone()


def of_server(conn: sqlite3.Connection, sid: int, limit: int,
              role_cut: str = "", role_values: Sequence[Any] = ()) -> list[sqlite3.Row]:
    """A server's history. `role_cut` is the WHERE fragment that hides restricted actions
    from the operator - it comes ready-made from whoever knows the viewer's role."""
    return conn.execute(
        f"SELECT * FROM jobs WHERE server_id = ?{role_cut} ORDER BY id DESC LIMIT ?",  # noqa: S608
        (sid, *role_values, limit),
    ).fetchall()


def shell_history(conn: sqlite3.Connection, sid: int, limit: int) -> list[sqlite3.Row]:
    """The most recent ad hoc commands of that server (Console screen)."""
    return conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? AND action = 'shell'"
        " ORDER BY id DESC LIMIT ?", (sid, limit)).fetchall()


def page(conn: sqlite3.Connection, where: str, values: Sequence[Any],
         limit: int, offset: int) -> list[sqlite3.Row]:
    """One page of the general history. The `where` is built by whoever applies the
    screen's filters; here only the pagination."""
    return conn.execute(
        f"SELECT * FROM jobs WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",  # noqa: S608
        (*values, limit, offset),
    ).fetchall()


def usernames(conn: sqlite3.Connection, role_cut: str = "",
              role_values: Sequence[Any] = ()) -> list[str]:
    """Who appears in the history - feeds the screen's filter."""
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT username FROM jobs WHERE username <> '' {role_cut}"  # noqa: S608
        " ORDER BY username",
        tuple(role_values),
    ).fetchall()]


def acted_since(conn: sqlite3.Connection, sid: int, since: str,
                actions: Sequence[str] = DISRUPTIVE_ACTIONS) -> bool:
    """Did the panel act on this server after `since`?

    Restarting through the button takes the service down for a few seconds, and that is
    NOT an outage. Without this window, every restart and every update would become an alert.
    """
    marks = ", ".join("?" * len(actions))
    return conn.execute(
        f"SELECT 1 FROM jobs WHERE server_id = ? AND created_at >= ?"  # noqa: S608
        f" AND action IN ({marks}) LIMIT 1",
        (sid, since, *actions),
    ).fetchone() is not None


def running_broker_ops(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Broker operations left 'running' - the panel restarted in the middle of them."""
    return conn.execute(
        "SELECT id, broker_op FROM jobs WHERE status = 'running' AND broker_op != ''"
    ).fetchall()


def running_creations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Instance creations in progress: the instances screen shows them with the way back to
    the log, which used to exist only in the redirect right after the click."""
    return conn.execute(
        "SELECT id, command, username, created_at FROM jobs"
        " WHERE status = 'running' AND action = 'broker-criar' AND broker_op != '' ORDER BY id DESC"
    ).fetchall()


# --- writing ------------------------------------------------------------------------

def target_of(server: ServerLike) -> str:
    """How a job identifies what it touched. There is one format, here: written in each
    caller, one of them would someday lose the port or get the wrong user."""
    return f"{server['ssh_user']}@{server['host']}"


def start(conn: sqlite3.Connection, server: ServerLike, action: str,
          command: str, username: str, created_at: str) -> int:
    """A job that STARTED: stays 'running' until someone calls `finish`."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, command, username,"
        " created_at) VALUES (?,?,?,?,?,?,?)",
        (server["id"], target_of(server), action, "running", command, username, created_at))
    return _row_id(cur)


def record(conn: sqlite3.Connection, server: ServerLike, action: str, status: str,
           output: str, command: str, username: str, at: str) -> int:
    """A job that ALREADY HAPPENED (file edit, terminal session): born finished."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
        " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (server["id"], target_of(server), action, status, 0 if status == "ok" else None,
         output[-OUTPUT_MAX:], command, username, at, at))
    return _row_id(cur)


def start_broker(conn: sqlite3.Connection, action: str, command: str, username: str,
                 created_at: str, op_id: str) -> int:
    """No server: the instance does not exist yet when the creation starts."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, command, username,"
        " created_at, broker_op) VALUES (NULL, ?, ?, 'running', ?, ?, ?, ?)",
        (BROKER_TARGET, action, command, username, created_at, op_id))
    return _row_id(cur)


def record_broker(conn: sqlite3.Connection, action: str, status: str, output: str,
                  command: str, username: str, at: str) -> int:
    """A short broker action (deactivate, remove, new game): born finished."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, exit_code, output, command,"
        " username, created_at, finished_at) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (BROKER_TARGET, action, status, 0 if status == "ok" else 1,
         output[-OUTPUT_MAX:], command, username, at, at))
    return _row_id(cur)


def finish(conn: sqlite3.Connection, jid: int, status: str, exit_code: int | None,
           output: str, finished_at: str) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, exit_code=?, output=?, finished_at=? WHERE id=?",
        (status, exit_code, output.strip()[-OUTPUT_MAX:], finished_at, jid))


def set_fields(conn: sqlite3.Connection, jid: int, fields: Mapping[str, Any]) -> None:
    """Write only the given columns - used by the broker follow-up, which writes the log
    every round. The NAMES come from the caller (fixed in code); the VALUES travel as
    parameters."""
    if not fields:
        return
    columns = ", ".join(f"{c}=?" for c in fields)
    conn.execute(f"UPDATE jobs SET {columns} WHERE id=?",  # noqa: S608
                 (*fields.values(), jid))


def delete_older_than(conn: sqlite3.Connection, cut: str) -> int:
    cur = conn.execute("DELETE FROM jobs WHERE created_at < ?", (cut,))
    return cur.rowcount or 0
