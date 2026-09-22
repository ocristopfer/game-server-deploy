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
from gamebroker.services.allocator import PortaAlocada

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


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: str, relogio: Callable[[], str] = agora):
        self._caminho = caminho
        self._relogio = relogio
        with self._conexao() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
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
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        with self._conexao() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # --- ocupacao ---------------------------------------------------------

    def usados(self) -> tuple[set[int], set[str], set[tuple[int, str]]]:
        with self._conexao() as conn:
            ctids = {r["ctid"] for r in conn.execute("SELECT ctid FROM instancias")}
            ips = {r["ip"] for r in conn.execute("SELECT ip FROM instancias")}
            portas = {(r["numero"], r["proto"]) for r in conn.execute("SELECT numero, proto FROM portas")}
        return ctids, ips, portas

    def reservar(self, ctid: int, ip: str, jogo: str, nome: str, hostname: str, ator: str,
                 portas: Sequence[PortaAlocada]) -> int:
        try:
            with self._transacao() as conn:
                cur = conn.execute(
                    "INSERT INTO instancias (ctid, ip, jogo, nome, hostname, estado, criado_por, criado_em)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ctid, ip, jogo, nome, hostname, ESTADO_RESERVADA, ator, self._relogio()))
                instancia_id = int(cur.lastrowid or 0)
                conn.executemany(
                    "INSERT INTO portas (instancia_id, base, numero, proto, papel) VALUES (?, ?, ?, ?, ?)",
                    [(instancia_id, p.base, p.numero, p.proto, p.papel) for p in portas])
        except sqlite3.IntegrityError as erro:
            raise Conflito(f"reserva recusada pelo banco (nome, CTID, IP ou porta ja em uso): {erro}") from None
        return instancia_id

    # --- instancias -------------------------------------------------------

    def instancia(self, instancia_id: int) -> dict | None:
        with self._conexao() as conn:
            linha = conn.execute("SELECT * FROM instancias WHERE id = ?", (instancia_id,)).fetchone()
            return self._com_portas(conn, linha) if linha else None

    def instancias(self) -> list[dict]:
        with self._conexao() as conn:
            return [self._com_portas(conn, r) for r in conn.execute("SELECT * FROM instancias ORDER BY id")]

    @staticmethod
    def _com_portas(conn: sqlite3.Connection, linha: sqlite3.Row) -> dict:
        dados = dict(linha)
        dados["portas"] = [dict(p) for p in conn.execute(
            "SELECT base, numero, proto, papel FROM portas WHERE instancia_id = ? ORDER BY numero, proto",
            (linha["id"],))]
        return dados

    def mudar_estado(self, instancia_id: int, estado: str, detalhe: str = "") -> None:
        with self._transacao() as conn:
            conn.execute("UPDATE instancias SET estado = ?, detalhe = ? WHERE id = ?",
                         (estado, detalhe[:300], instancia_id))

    def apagar_instancia(self, instancia_id: int) -> None:
        with self._transacao() as conn:
            conn.execute("DELETE FROM instancias WHERE id = ?", (instancia_id,))

    def contar_instancias(self) -> int:
        with self._conexao() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM instancias").fetchone()[0])

    # --- operacoes --------------------------------------------------------

    def criar_operacao(self, instancia_id: int | None, tipo: str) -> str:
        op_id = uuid.uuid4().hex
        with self._transacao() as conn:
            conn.execute(
                "INSERT INTO operacoes (id, instancia_id, tipo, estado, iniciada_em) VALUES (?, ?, ?, ?, ?)",
                (op_id, instancia_id, tipo, OP_EXECUTANDO, self._relogio()))
        return op_id

    def anexar_log(self, op_id: str, linha: str) -> None:
        with self._transacao() as conn:
            atual = conn.execute("SELECT log FROM operacoes WHERE id = ?", (op_id,)).fetchone()
            if atual is None:
                return
            # Cauda: instalacao de jogo pode gerar MB de saida, e o painel so precisa do fim.
            novo = (atual["log"] + linha.rstrip("\n") + "\n")[-LOG_MAX:]
            conn.execute("UPDATE operacoes SET log = ? WHERE id = ?", (novo, op_id))

    def terminar_operacao(self, op_id: str, estado: str, resultado: dict | None = None) -> None:
        with self._transacao() as conn:
            conn.execute("UPDATE operacoes SET estado = ?, resultado = ?, terminada_em = ? WHERE id = ?",
                         (estado, json.dumps(resultado or {}, ensure_ascii=True), self._relogio(), op_id))

    def operacao(self, op_id: str) -> dict | None:
        with self._conexao() as conn:
            linha = conn.execute("SELECT * FROM operacoes WHERE id = ?", (op_id,)).fetchone()
        if linha is None:
            return None
        dados = dict(linha)
        dados["resultado"] = json.loads(dados["resultado"] or "{}")
        return dados

    def operacao_em_andamento(self) -> bool:
        with self._conexao() as conn:
            return conn.execute("SELECT 1 FROM operacoes WHERE estado = ? LIMIT 1",
                                (OP_EXECUTANDO,)).fetchone() is not None

    def criacoes_desde(self, desde: str) -> int:
        with self._conexao() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM operacoes WHERE tipo = 'criar' AND iniciada_em >= ?",
                                    (desde,)).fetchone()[0])

    # --- auditoria --------------------------------------------------------

    def auditar(self, ator: str, verbo: str, alvo: str, resultado: str, detalhe: str = "") -> None:
        with self._transacao() as conn:
            conn.execute(
                "INSERT INTO auditoria (quando, ator, verbo, alvo, resultado, detalhe) VALUES (?, ?, ?, ?, ?, ?)",
                (self._relogio(), ator, verbo, alvo, resultado, detalhe[:300]))

    def auditoria(self, limite: int = 100) -> list[dict]:
        with self._conexao() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,))]
