"""Estado do broker em SQLite: instancias, portas, operacoes e auditoria.

O banco e a fonte de verdade de quem ocupa qual CTID/IP/porta. UNIQUE nas tres colunas
faz o proprio SQLite recusar uma reserva concorrente, mesmo se a trava em memoria do
servico falhar (por exemplo, dois processos apontando para o mesmo arquivo).
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

# Os VALORES sao o que esta gravado na coluna `state` e o que o painel recebe no JSON:
# traduzi-los renomearia o estado de toda instancia ja criada. So os nomes sao ingleses.
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
  -- Opaco de proposito: no Proxmox e o CTID em texto ("307"), e um backend futuro pode
  -- usar outra coisa. TEXT e nao INTEGER pelo mesmo motivo.
  handle TEXT NOT NULL UNIQUE,
  -- Quem criou esta instancia. Tem padrao para o banco de quem ja rodava continuar valido
  -- sem adivinhacao: tudo que existia foi criado no Proxmox.
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

# O banco do broker ANTES de falar ingles. A migration corre no start, uma vez.
#
# Aqui as TABELAS tambem mudam de nome. A ordem NAO importa: o `RENAME TO` do SQLite
# reescreve a `REFERENCES` de quem aponta para a tabela renomeada, venha antes ou depois
# (conferido nos dois sentidos, e ha teste para a chave estrangeira continuar valendo).
# Isso so e verdade com `legacy_alter_table` desligado, que e o padrao desde o 3.25.
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
# Indices e triggers carregam o nome velho no corpo: renomear a tabela nao os reescreve
# por inteiro, e deixar os dois lados vivos daria indice duplicado.
_DROP_OLD = (
    "DROP INDEX IF EXISTS instancias_nome",
    "DROP INDEX IF EXISTS portas_externas",
    "DROP TRIGGER IF EXISTS auditoria_sem_update",
    "DROP TRIGGER IF EXISTS auditoria_sem_delete",
)


# A segunda migration: `ctid` (numero do Proxmox) vira `handle` (texto opaco), e nasce a
# coluna que diz QUEM criou a instancia. A pergunta do `_migrate_names` e "a tabela ainda
# tem o nome velho?"; a daqui e "ainda existe a coluna `ctid`?".
def _migrate_handle(conn: sqlite3.Connection) -> None:
    """`instances.ctid` -> `instances.handle`, mais a coluna `backend`.

    **`RENAME COLUMN` preserva a AFINIDADE, e isso morde.** A coluna continua declarada
    `INTEGER`, entao num banco migrado o CTID antigo volta do SELECT como `int` e nao como
    `str` — e um `CAST(... AS TEXT)` nao adianta, a afinidade converte de volta na hora de
    gravar (conferido no sqlite3 desta maquina). Um handle nao-numerico, como
    `palworld-1`, entra como texto normalmente: a afinidade so converte o que PARECE
    numero. O resultado seria uma coluna de tipo misto, e `{"307"} | {307}` nao se
    deduplica — a checagem de handle ocupado passaria quando nao devia.

    Reconstruir a tabela corrigiria a declaracao e custa caro: `ports` tem
    `REFERENCES instances(id) ON DELETE CASCADE`, entao derrubar `instances` leva as portas
    junto. A saida e normalizar na LEITURA (ver `taken` e `instance`), que e uma linha e
    nao perde dado. Banco novo ja nasce com a coluna `TEXT`.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(instances)")}
    if not cols:
        return                      # banco novo: o SCHEMA cria tudo certo logo abaixo
    if "ctid" in cols and "handle" not in cols:
        conn.execute("ALTER TABLE instances RENAME COLUMN ctid TO handle")
    if "backend" not in cols:
        conn.execute("ALTER TABLE instances ADD COLUMN backend TEXT NOT NULL DEFAULT 'proxmox'")


def _migrate_names(conn: sqlite3.Connection) -> None:
    """Leva um banco antigo para os nomes em ingles. Nao faz nada num banco novo."""
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
            # A migration vem ANTES do SCHEMA: com as tabelas velhas ainda de pe, o
            # `CREATE TABLE IF NOT EXISTS` criaria as novas VAZIAS ao lado, e o rename
            # depois nao teria para onde ir.
            _migrate_names(conn)
            _migrate_handle(conn)
            conn.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: as transacoes sao explicitas (BEGIN IMMEDIATE), nao as
        # que o modulo abre por conta propria antes de cada INSERT.
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

    # --- ocupacao ---------------------------------------------------------

    def taken(self) -> tuple[set[str], set[str], set[tuple[int, str]]]:
        with self._connection() as conn:
            # `str()` e nao o valor cru: num banco migrado a coluna ainda tem afinidade
            # INTEGER e devolve o CTID antigo como numero (ver `_migrate_handle`).
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

    # --- instancias -------------------------------------------------------

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

    # --- operacoes --------------------------------------------------------

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
            # Cauda: instalacao de jogo pode gerar MB de saida, e o painel so precisa do fim.
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

    # --- auditoria --------------------------------------------------------

    def audit(self, actor: str, verb: str, target: str, result: str, detail: str = "") -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO audit (at, actor, verb, target, result, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (self._clock(), actor, verb, target, result, detail[:300]))

    def audit_trail(self, limit: int = 100) -> list[dict]:
        with self._connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]
