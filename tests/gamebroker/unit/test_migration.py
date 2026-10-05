"""Broker database migration: tables and columns that were renamed.

A migration only runs on the database of whoever ALREADY had the broker installed, and the
other tests live in a fresh database -- where it does not even happen. The only way to
exercise it is to build the old schema by hand, with data inside, and let `Db()` run over it.

What is at stake here is not a screen: it is the game instance the broker created, the
CTID/IP it reserves and the audit trail of who did what.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamebroker.persistence.db import Db

# The schema BEFORE the English names, written out in full. Copying from today's `SCHEMA`
# would make the test agree with itself.
OLD_SCHEMA = """
CREATE TABLE instancias (
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
CREATE UNIQUE INDEX instancias_nome ON instancias(nome);
CREATE TABLE portas (
  instancia_id INTEGER NOT NULL REFERENCES instancias(id) ON DELETE CASCADE,
  base INTEGER NOT NULL,
  numero INTEGER NOT NULL,
  proto TEXT NOT NULL,
  papel TEXT NOT NULL,
  PRIMARY KEY (instancia_id, numero, proto)
);
CREATE UNIQUE INDEX portas_externas ON portas(numero, proto);
CREATE TABLE operacoes (
  id TEXT PRIMARY KEY,
  instancia_id INTEGER,
  tipo TEXT NOT NULL,
  estado TEXT NOT NULL,
  log TEXT NOT NULL DEFAULT '',
  resultado TEXT NOT NULL DEFAULT '',
  iniciada_em TEXT NOT NULL,
  terminada_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE auditoria (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quando TEXT NOT NULL,
  ator TEXT NOT NULL,
  verbo TEXT NOT NULL,
  alvo TEXT NOT NULL,
  resultado TEXT NOT NULL,
  detalhe TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER auditoria_sem_update BEFORE UPDATE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria e append-only'); END;
CREATE TRIGGER auditoria_sem_delete BEFORE DELETE ON auditoria
BEGIN SELECT RAISE(ABORT, 'auditoria e append-only'); END;
"""


@pytest.fixture
def old_database(tmp_path):
    """A broker as it was before the translation, with a real instance."""
    path = tmp_path / "broker.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO instancias (ctid, ip, jogo, nome, hostname, estado,"
                " criado_por, criado_em, detalhe) VALUES"
                " (302, '10.0.0.30', 'palworld', 'Servidor do Zeca', 'palworld-302',"
                " 'ativa', 'zeca', '2026-01-01T10:00:00', '')")
    con.executemany("INSERT INTO portas (instancia_id, base, numero, proto, papel)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [(1, 8211, 31000, "udp", "jogo"), (1, 27015, 31001, "udp", "query")])
    # The id goes as a PARAMETER: inside SQL, `'a' * 32` is text multiplied by a number,
    # which in SQLite is 0 -- the operation would go in with id zero and the test would be
    # looking for something else.
    con.execute("INSERT INTO operacoes (id, instancia_id, tipo, estado, log, resultado,"
                " iniciada_em, terminada_em)"
                " VALUES (?, 1, 'criar', 'ok', 'instalado\n', '{}',"
                " '2026-01-01T10:00:00', '2026-01-01T10:09:00')", ("a" * 32,))
    con.execute("INSERT INTO auditoria (quando, ator, verbo, alvo, resultado, detalhe)"
                " VALUES ('2026-01-01T10:00:00', 'zeca', 'criar', 'Servidor do Zeca', 'ok', '')")
    con.commit()
    con.close()
    return path


def test_a_instancia_sobrevive_ao_rename_de_tabela_e_coluna(old_database):
    db = Db(str(old_database))
    inst = db.instances()[0]
    assert inst["name"] == "Servidor do Zeca"
    assert inst["game"] == "palworld"
    assert inst["state"] == "ativa"
    # `handle` and not `ctid`, and the VALUE comes back as a number: `RENAME COLUMN` keeps
    # the old column's INTEGER affinity, so in a migrated database the old CTID is still an
    # int in the SELECT. `db.taken` and `wire.instance` normalize it with `str()` -- this test
    # looks at the raw value on purpose, so the trap stays recorded here.
    assert (inst["handle"], inst["ip"]) == (302, "10.0.0.30")
    assert inst["backend"] == "proxmox", "coluna nova nasce com padrao, sem adivinhacao"
    assert inst["created_by"] == "zeca"
    # The ports come from the OTHER table, through the foreign key the rename had to keep.
    assert [(p["number"], p["proto"], p["role"]) for p in inst["ports"]] == [
        (31000, "udp", "jogo"), (31001, "udp", "query")]


def test_o_handle_novo_entra_como_TEXTO_no_banco_migrado(old_database):
    """INTEGER affinity converts back what LOOKS like a number, and only that.

    That is what lets a future backend use `palworld-1` without rebuilding the table: the
    column accepts text normally; only the numeric handle comes back as int. Without this
    distinction, `{"307"} | {307}` would not deduplicate and the taken-handle check would
    pass when it should not.
    """
    import sqlite3
    db = Db(str(old_database))
    with sqlite3.connect(str(old_database)) as con:
        con.execute("INSERT INTO instances (handle, backend, ip, game, name, hostname, state,"
                    " created_by, created_at) VALUES ('palworld-1', 'docker', '10.0.0.31',"
                    " 'palworld', 'Outro', 'palworld-1', 'ativa', 'zeca', '2026-01-01')")
    handles, _ips, _ports = db.taken()
    assert handles == {"302", "palworld-1"}, "o `str()` do `taken` uniformiza os dois"


def test_a_operacao_e_a_auditoria_sobrevivem(old_database):
    db = Db(str(old_database))
    op = db.operation("a" * 32)
    assert (op["kind"], op["state"]) == ("criar", "ok")
    assert op["log"] == "instalado\n"
    line = db.audit_trail()[0]
    assert (line["actor"], line["verb"], line["target"]) == ("zeca", "criar", "Servidor do Zeca")


def test_a_chave_estrangeira_continua_valendo(old_database):
    """`RENAME TO` rewrites the `REFERENCES` of whoever points at the renamed table.
    If that stopped holding, deleting the instance would leave an orphan port -- and an
    orphan port in the database becomes a port the allocator considers taken forever."""
    db = Db(str(old_database))
    db.delete_instance(1)
    con = sqlite3.connect(old_database)
    try:
        assert con.execute("SELECT COUNT(*) FROM ports").fetchone()[0] == 0
    finally:
        con.close()


def test_a_auditoria_continua_append_only(old_database):
    """The trigger has the table name inside it: renaming the table without recreating it
    would leave the audit trail editable, the opposite of what it exists to guarantee."""
    Db(str(old_database))
    con = sqlite3.connect(old_database)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute("UPDATE audit SET result = 'adulterado'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            con.execute("DELETE FROM audit")
    finally:
        con.close()


def test_rodar_de_novo_nao_faz_nada(old_database):
    """The broker instantiates `Db` on every start."""
    Db(str(old_database))
    before = Db(str(old_database)).instances()
    assert Db(str(old_database)).instances() == before


def test_banco_novo_nao_passa_por_migration(tmp_path):
    db = Db(str(tmp_path / "novo.db"))
    con = sqlite3.connect(tmp_path / "novo.db")
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"instances", "ports", "operations", "audit"} <= tables
        assert not tables & {"instancias", "portas", "operacoes", "auditoria"}
    finally:
        con.close()
    assert db.instances() == []
