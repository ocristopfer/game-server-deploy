"""Migration do banco do broker: tabelas e colunas que mudaram de nome.

Migration so roda no banco de quem JA tinha o broker instalado, e os outros testes vivem
num banco novo — onde ela nem acontece. A unica forma de exercita-la e montar o esquema
antigo a mao, com dado dentro, e deixar o `Db()` passar por cima.

O que esta em jogo aqui nao e uma tela: e a instancia de jogo que o broker criou, o
CTID/IP que ela reserva e a auditoria de quem fez o que.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamebroker.persistence.db import Db

# O esquema ANTES dos nomes em ingles, escrito por extenso. Copiar do `SCHEMA` de hoje
# faria o teste concordar consigo mesmo.
ESQUEMA_ANTIGO = """
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
    """Um broker como ele estava antes da traducao, com uma instancia de verdade."""
    path = tmp_path / "broker.db"
    con = sqlite3.connect(path)
    con.executescript(ESQUEMA_ANTIGO)
    con.execute("INSERT INTO instancias (ctid, ip, jogo, nome, hostname, estado,"
                " criado_por, criado_em, detalhe) VALUES"
                " (302, '10.0.0.30', 'palworld', 'Servidor do Zeca', 'palworld-302',"
                " 'ativa', 'zeca', '2026-01-01T10:00:00', '')")
    con.executemany("INSERT INTO portas (instancia_id, base, numero, proto, papel)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [(1, 8211, 31000, "udp", "jogo"), (1, 27015, 31001, "udp", "query")])
    # O id vai por PARAMETRO: dentro do SQL, `'a' * 32` e multiplicacao de texto por
    # numero, que no SQLite vale 0 — a operacao entraria com id zero e o teste procuraria
    # outra coisa.
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
    assert (inst["ctid"], inst["ip"]) == (302, "10.0.0.30")
    assert inst["created_by"] == "zeca"
    # As portas vem da OUTRA tabela, pela chave estrangeira que o rename teve de manter.
    assert [(p["number"], p["proto"], p["role"]) for p in inst["ports"]] == [
        (31000, "udp", "jogo"), (31001, "udp", "query")]


def test_a_operacao_e_a_auditoria_sobrevivem(old_database):
    db = Db(str(old_database))
    op = db.operation("a" * 32)
    assert (op["kind"], op["state"]) == ("criar", "ok")
    assert op["log"] == "instalado\n"
    line = db.audit_trail()[0]
    assert (line["actor"], line["verb"], line["target"]) == ("zeca", "criar", "Servidor do Zeca")


def test_a_chave_estrangeira_continua_valendo(old_database):
    """O `RENAME TO` reescreve a `REFERENCES` de quem aponta para a tabela renomeada.
    Se isso deixasse de valer, apagar a instancia deixaria porta orfa — e porta orfa no
    banco vira porta que o alocador acha ocupada para sempre."""
    db = Db(str(old_database))
    db.delete_instance(1)
    con = sqlite3.connect(old_database)
    try:
        assert con.execute("SELECT COUNT(*) FROM ports").fetchone()[0] == 0
    finally:
        con.close()


def test_a_auditoria_continua_append_only(old_database):
    """O trigger tem o nome da tabela dentro: renomear a tabela sem recria-lo deixaria
    a auditoria editavel, que e o oposto do que ela existe para garantir."""
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
    """O broker instancia o `Db` em todo start."""
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
