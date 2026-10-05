"""Broker state in SQLite: instances, ports, operations and audit.

The database is the source of truth for who holds which CTID/IP/port. UNIQUE on the three
columns makes SQLite itself refuse a concurrent reservation, even if the service's in-memory
lock fails (for example, two processes pointing at the same file).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from gamebroker.domain.exceptions import Conflict
from gamebroker.services.allocator import AllocatedPort

# The VALUES are what is stored in the `state` column and what the panel receives in the JSON:
# translating them would rename the state of every instance already created. Only the names are English.
STATE_RESERVED = "reservada"
STATE_ACTIVE = "ativa"
STATE_DEACTIVATED = "desativada"
STATE_FAILED = "falhou"

OP_RUNNING = "executando"
OP_OK = "ok"
OP_FAILED = "erro"

LOG_MAX = 20000

SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  -- Opaque on purpose: on Proxmox it is the CTID as text ("307"), and a future backend may
  -- use something else. TEXT and not INTEGER for the same reason.
  handle TEXT NOT NULL UNIQUE,
  -- Which backend created this instance. It has a default so existing databases stay valid
  -- without guessing: everything that existed was created on Proxmox.
  backend TEXT NOT NULL DEFAULT 'proxmox',
  ip TEXT NOT NULL UNIQUE,
  game TEXT NOT NULL,
  name TEXT NOT NULL,
  hostname TEXT NOT NULL,
  state TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS instances_name ON instances(name);
CREATE TABLE IF NOT EXISTS ports (
  instance_id INTEGER NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
  base INTEGER NOT NULL,
  number INTEGER NOT NULL,
  proto TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (instance_id, number, proto)
);
CREATE UNIQUE INDEX IF NOT EXISTS ports_external ON ports(number, proto);
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  instance_id INTEGER,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  log TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  verb TEXT NOT NULL,
  target TEXT NOT NULL,
  result TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'a auditoria e append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'a auditoria e append-only'); END;
"""

# The broker database BEFORE it spoke English. The migration runs at startup, once.
#
# Here the TABLES also change names. The order does NOT matter: SQLite's `RENAME TO`
# rewrites the `REFERENCES` of whoever points at the renamed table, before or after it
# (checked in both directions, and there is a test for the foreign key to keep working).
# This only holds with `legacy_alter_table` off, which is the default since 3.25.
_RENAME_TABLES = (
    ("instancias", "instances"),
    ("portas", "ports"),
    ("operacoes", "operations"),
    ("auditoria", "audit"),
)
_RENAME_COLUMNS = (
    ("instances", "jogo", "game"),
    ("instances", "nome", "name"),
    ("instances", "estado", "state"),
    ("instances", "criado_por", "created_by"),
    ("instances", "criado_em", "created_at"),
    ("instances", "detalhe", "detail"),
    ("ports", "instancia_id", "instance_id"),
    ("ports", "numero", "number"),
    ("ports", "papel", "role"),
    ("operations", "instancia_id", "instance_id"),
    ("operations", "tipo", "kind"),
    ("operations", "estado", "state"),
    ("operations", "resultado", "result"),
    ("operations", "iniciada_em", "started_at"),
    ("operations", "terminada_em", "finished_at"),
    ("audit", "quando", "at"),
    ("audit", "ator", "actor"),
    ("audit", "verbo", "verb"),
    ("audit", "alvo", "target"),
    ("audit", "resultado", "result"),
    ("audit", "detalhe", "detail"),
)
# Indexes and triggers carry the old name in their body: renaming the table does not rewrite
# them entirely, and keeping both alive would give a duplicate index.
_DROP_OLD = (
    "DROP INDEX IF EXISTS instancias_nome",
    "DROP INDEX IF EXISTS portas_externas",
    "DROP TRIGGER IF EXISTS auditoria_sem_update",
    "DROP TRIGGER IF EXISTS auditoria_sem_delete",
)


# The second migration: `ctid` (Proxmox number) becomes `handle` (opaque text), and the column
# saying WHO created the instance is born. The question for `_migrate_names` is "does the table
# still have the old name?"; the one here is "does the `ctid` column still exist?".
def _migrate_handle(conn: sqlite3.Connection) -> None:
    """`instances.ctid` -> `instances.handle`, plus the `backend` column.

    **`RENAME COLUMN` keeps the AFFINITY, and that bites.** The column stays declared
    `INTEGER`, so in a migrated database the old CTID comes back from SELECT as `int` and not
    as `str` - and a `CAST(... AS TEXT)` does not help, the affinity converts it back on write
    (checked in this machine's sqlite3). A non-numeric handle, like `palworld-1`, goes in as
    text normally: the affinity only converts what LOOKS like a number. The result would be a
    mixed-type column, and `{"307"} | {307}` does not deduplicate - the taken-handle check
    would pass when it should not.

    Rebuilding the table would fix the declaration, and it is expensive: `ports` has
    `REFERENCES instances(id) ON DELETE CASCADE`, so dropping `instances` takes the ports
    with it. The way out is normalizing on READ (see `taken` and `instance`), which is one
    line and loses no data. A new database is born with the column as `TEXT`.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(instances)")}
    if not cols:
        return                      # new database: the SCHEMA creates everything right below
    if "ctid" in cols and "handle" not in cols:
        conn.execute("ALTER TABLE instances RENAME COLUMN ctid TO handle")
    if "backend" not in cols:
        conn.execute("ALTER TABLE instances ADD COLUMN backend TEXT NOT NULL DEFAULT 'proxmox'")


def _migrate_names(conn: sqlite3.Connection) -> None:
    """Moves an old database to the English names. Does nothing on a new database."""
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not tables & {old_one for old_one, _ in _RENAME_TABLES}:
        return
    for command in _DROP_OLD:
        conn.execute(command)
    for old_one, fresh in _RENAME_TABLES:
        if old_one in tables and fresh not in tables:
            conn.execute(f"ALTER TABLE {old_one} RENAME TO {fresh}")
    for table, old_one, fresh in _RENAME_COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if old_one in cols and fresh not in cols:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old_one} TO {fresh}")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Db:
    def __init__(self, path: str, clock: Callable[[], str] = now):
        self._path = path
        self._clock = clock
        with self._connection() as conn:
            # The migration comes BEFORE the SCHEMA: with the old tables still up, the
            # `CREATE TABLE IF NOT EXISTS` would create the new ones EMPTY alongside, and the
            # rename afterwards would have nowhere to go.
            _migrate_names(conn)
            _migrate_handle(conn)
            conn.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: transactions are explicit (BEGIN IMMEDIATE), not the ones
        # the module opens on its own before each INSERT.
        conn = sqlite3.connect(self._path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # --- occupancy --------------------------------------------------------

    def taken(self) -> tuple[set[str], set[str], set[tuple[int, str]]]:
        with self._connection() as conn:
            # `str()` and not the raw value: in a migrated database the column still has INTEGER
            # affinity and returns the old CTID as a number (see `_migrate_handle`).
            handles = {str(r["handle"]) for r in conn.execute("SELECT handle FROM instances")}
            ips = {r["ip"] for r in conn.execute("SELECT ip FROM instances")}
            ports = {(r["number"], r["proto"]) for r in conn.execute("SELECT number, proto FROM ports")}
        return handles, ips, ports

    def reserve(self, handle: str, ip: str, game: str, name: str, hostname: str, actor: str,
                 ports: Sequence[AllocatedPort], backend: str = "proxmox") -> int:
        try:
            with self._transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO instances (handle, backend, ip, game, name, hostname, state,"
                    " created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (handle, backend, ip, game, name, hostname, STATE_RESERVED, actor, self._clock()))
                instance_id = int(cur.lastrowid or 0)
                conn.executemany(
                    "INSERT INTO ports (instance_id, base, number, proto, role) VALUES (?, ?, ?, ?, ?)",
                    [(instance_id, p.base, p.number, p.proto, p.role) for p in ports])
        except sqlite3.IntegrityError as error:
            raise Conflict(f"reserva recusada pelo banco (nome, CTID, IP ou porta ja em uso): {error}") from None
        return instance_id

    # --- instances --------------------------------------------------------

    def instance(self, instance_id: int) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
            return self._with_ports(conn, row) if row else None

    def instances(self) -> list[dict]:
        with self._connection() as conn:
            return [self._with_ports(conn, r) for r in conn.execute("SELECT * FROM instances ORDER BY id")]

    @staticmethod
    def _with_ports(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["ports"] = [dict(p) for p in conn.execute(
            "SELECT base, number, proto, role FROM ports WHERE instance_id = ? ORDER BY number, proto",
            (row["id"],))]
        return data

    def set_state(self, instance_id: int, state_dir: str, detail: str = "") -> None:
        with self._transaction() as conn:
            conn.execute("UPDATE instances SET state = ?, detail = ? WHERE id = ?",
                         (state_dir, detail[:300], instance_id))

    def delete_instance(self, instance_id: int) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM instances WHERE id = ?", (instance_id,))

    def count_instances(self) -> int:
        with self._connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0])

    # --- operations -------------------------------------------------------

    def create_operation(self, instance_id: int | None, kind: str) -> str:
        op_id = uuid.uuid4().hex
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO operations (id, instance_id, kind, state, started_at) VALUES (?, ?, ?, ?, ?)",
                (op_id, instance_id, kind, OP_RUNNING, self._clock()))
        return op_id

    def append_log(self, op_id: str, row: str) -> None:
        with self._transaction() as conn:
            current_one = conn.execute("SELECT log FROM operations WHERE id = ?", (op_id,)).fetchone()
            if current_one is None:
                return
            # Tail: a game installation can produce MBs of output, and the panel only needs the end.
            fresh = (current_one["log"] + row.rstrip("\n") + "\n")[-LOG_MAX:]
            conn.execute("UPDATE operations SET log = ? WHERE id = ?", (fresh, op_id))

    def finish_operation(self, op_id: str, state_dir: str, result: dict | None = None) -> None:
        with self._transaction() as conn:
            conn.execute("UPDATE operations SET state = ?, result = ?, finished_at = ? WHERE id = ?",
                         (state_dir, json.dumps(result or {}, ensure_ascii=True), self._clock(), op_id))

    def operation(self, op_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM operations WHERE id = ?", (op_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["result"] = json.loads(data["result"] or "{}")
        return data

    def operation_in_progress(self) -> bool:
        with self._connection() as conn:
            return conn.execute("SELECT 1 FROM operations WHERE state = ? LIMIT 1",
                                (OP_RUNNING,)).fetchone() is not None

    def creations_since(self, since: str) -> int:
        with self._connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM operations WHERE kind = 'criar' AND started_at >= ?",
                                    (since,)).fetchone()[0])

    # --- audit ------------------------------------------------------------

    def audit(self, actor: str, verb: str, target: str, result: str, detail: str = "") -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO audit (at, actor, verb, target, result, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (self._clock(), actor, verb, target, result, detail[:300]))

    def audit_trail(self, limit: int = 100) -> list[dict]:
        with self._connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
