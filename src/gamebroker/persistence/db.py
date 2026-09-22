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
from datetime import datetime, timezone

from gamebroker.domain.exceptions import Conflito
from gamebroker.services.allocator import AllocatedPort

ESTADO_RESERVADA = "reservada"
ESTADO_ATIVA = "ativa"
ESTADO_DESATIVADA = "desativada"
ESTADO_FALHOU = "falhou"

OP_EXECUTANDO = "executando"
OP_OK = "ok"
OP_ERRO = "erro"

LOG_MAX = 20000

SCHEMA = """
CREATE TABLE IF NOT EXISTS instancias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ctid INTEGER NOT NULL UNIQUE,
  ip TEXT NOT NULL UNIQUE,
  jogo TEXT NOT NULL,
  nome TEXT NOT NULL,
  hostname TEXT NOT NULL,
  estado TEXT NOT NULL,
  criado_por TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  detalhe TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS instancias_nome ON instancias(nome);
CREATE TABLE IF NOT EXISTS portas (
  instancia_id INTEGER NOT NULL REFERENCES instancias(id) ON DELETE CASCADE,
  base INTEGER NOT NULL,
  numero INTEGER NOT NULL,
  proto TEXT NOT NULL,
  papel TEXT NOT NULL,
  PRIMARY KEY (instancia_id, numero, proto)
);
CREATE UNIQUE INDEX IF NOT EXISTS portas_externas ON portas(numero, proto);
CREATE TABLE IF NOT EXISTS operacoes (
  id TEXT PRIMARY KEY,
  instancia_id INTEGER,
  tipo TEXT NOT NULL,
  estado TEXT NOT NULL,
  log TEXT NOT NULL DEFAULT '',
  resultado TEXT NOT NULL DEFAULT '',
  iniciada_em TEXT NOT NULL,
  terminada_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS auditoria (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quando TEXT NOT NULL,
  ator TEXT NOT NULL,
  verbo TEXT NOT NULL,
  alvo TEXT NOT NULL,
  resultado TEXT NOT NULL,
  detalhe TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS auditoria_sem_update BEFORE UPDATE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria e append-only'); END;
CREATE TRIGGER IF NOT EXISTS auditoria_sem_delete BEFORE DELETE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria e append-only'); END;
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Db:
    def __init__(self, path: str, clock: Callable[[], str] = now):
        self._caminho = path
        self._relogio = clock
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: as transacoes sao explicitas (BEGIN IMMEDIATE), nao as
        # que o modulo abre por conta propria antes de cada INSERT.
        conn = sqlite3.connect(self._caminho, timeout=10, isolation_level=None)
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

    def taken(self) -> tuple[set[int], set[str], set[tuple[int, str]]]:
        with self._connection() as conn:
            ctids = {r["ctid"] for r in conn.execute("SELECT ctid FROM instancias")}
            ips = {r["ip"] for r in conn.execute("SELECT ip FROM instancias")}
            ports = {(r["numero"], r["proto"]) for r in conn.execute("SELECT numero, proto FROM portas")}
        return ctids, ips, ports

    def reserve(self, ctid: int, ip: str, jogo: str, name: str, hostname: str, actor: str,
                 ports: Sequence[AllocatedPort]) -> int:
        try:
            with self._transaction() as conn:
                cur = conn.execute(
                    "INSERT INTO instancias (ctid, ip, jogo, nome, hostname, estado, criado_por, criado_em)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ctid, ip, jogo, name, hostname, ESTADO_RESERVADA, actor, self._relogio()))
                instance_id = int(cur.lastrowid or 0)
                conn.executemany(
                    "INSERT INTO portas (instancia_id, base, numero, proto, papel) VALUES (?, ?, ?, ?, ?)",
                    [(instance_id, p.base, p.number, p.proto, p.role) for p in ports])
        except sqlite3.IntegrityError as erro:
            raise Conflito(f"reserva recusada pelo banco (nome, CTID, IP ou porta ja em uso): {erro}") from None
        return instance_id

    # --- instancias -------------------------------------------------------

    def instance(self, instance_id: int) -> dict | None:
        with self._connection() as conn:
            linha = conn.execute("SELECT * FROM instancias WHERE id = ?", (instance_id,)).fetchone()
            return self._with_ports(conn, linha) if linha else None

    def instances(self) -> list[dict]:
        with self._connection() as conn:
            return [self._with_ports(conn, r) for r in conn.execute("SELECT * FROM instancias ORDER BY id")]

    @staticmethod
    def _with_ports(conn: sqlite3.Connection, linha: sqlite3.Row) -> dict:
        dados = dict(linha)
        dados["portas"] = [dict(p) for p in conn.execute(
            "SELECT base, numero, proto, papel FROM portas WHERE instancia_id = ? ORDER BY numero, proto",
            (linha["id"],))]
        return dados

    def set_state(self, instance_id: int, estado: str, detail: str = "") -> None:
        with self._transaction() as conn:
            conn.execute("UPDATE instancias SET estado = ?, detalhe = ? WHERE id = ?",
                         (estado, detail[:300], instance_id))

    def delete_instance(self, instance_id: int) -> None:
        with self._transaction() as conn:
            conn.execute("DELETE FROM instancias WHERE id = ?", (instance_id,))

    def count_instances(self) -> int:
        with self._connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM instancias").fetchone()[0])

    # --- operacoes --------------------------------------------------------

    def create_operation(self, instance_id: int | None, kind: str) -> str:
        op_id = uuid.uuid4().hex
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO operacoes (id, instancia_id, tipo, estado, iniciada_em) VALUES (?, ?, ?, ?, ?)",
                (op_id, instance_id, kind, OP_EXECUTANDO, self._relogio()))
        return op_id

    def append_log(self, op_id: str, linha: str) -> None:
        with self._transaction() as conn:
            atual = conn.execute("SELECT log FROM operacoes WHERE id = ?", (op_id,)).fetchone()
            if atual is None:
                return
            # Cauda: instalacao de jogo pode gerar MB de saida, e o painel so precisa do fim.
            novo = (atual["log"] + linha.rstrip("\n") + "\n")[-LOG_MAX:]
            conn.execute("UPDATE operacoes SET log = ? WHERE id = ?", (novo, op_id))

    def finish_operation(self, op_id: str, estado: str, result: dict | None = None) -> None:
        with self._transaction() as conn:
            conn.execute("UPDATE operacoes SET estado = ?, resultado = ?, terminada_em = ? WHERE id = ?",
                         (estado, json.dumps(result or {}, ensure_ascii=True), self._relogio(), op_id))

    def operation(self, op_id: str) -> dict | None:
        with self._connection() as conn:
            linha = conn.execute("SELECT * FROM operacoes WHERE id = ?", (op_id,)).fetchone()
        if linha is None:
            return None
        dados = dict(linha)
        dados["resultado"] = json.loads(dados["resultado"] or "{}")
        return dados

    def operation_in_progress(self) -> bool:
        with self._connection() as conn:
            return conn.execute("SELECT 1 FROM operacoes WHERE estado = ? LIMIT 1",
                                (OP_EXECUTANDO,)).fetchone() is not None

    def creations_since(self, since: str) -> int:
        with self._connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM operacoes WHERE tipo = 'criar' AND iniciada_em >= ?",
                                    (since,)).fetchone()[0])

    # --- auditoria --------------------------------------------------------

    def audit(self, actor: str, verb: str, target: str, result: str, detail: str = "") -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO auditoria (quando, ator, verbo, alvo, resultado, detalhe) VALUES (?, ?, ?, ?, ?, ?)",
                (self._relogio(), actor, verb, target, result, detail[:300]))

    def audit_trail(self, limit: int = 100) -> list[dict]:
        with self._connection() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limit,))]
