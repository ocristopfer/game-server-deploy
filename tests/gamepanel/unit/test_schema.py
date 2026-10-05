"""Panel database migrations: a new column and a column that changed name.

This file exists because a migration is the only code here that runs just ONCE, on the
database of someone who already had the panel installed - and on a new database, which is
where the other tests live, it is not even exercised. The way to test it is to build the
OLD schema by hand, with data in it, and have `init_db` run over it.

What is lost when it is wrong is not a screen: it is the alert history and the list of
destinations of whoever was already using the panel.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamepanel.persistence import schema

# The schema of both tables BEFORE the English names. Written out in full on purpose:
# copying from today's `SCHEMA` would make the test agree with itself.
OLD_SCHEMA = """
CREATE TABLE webhooks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL,
  eventos TEXT NOT NULL DEFAULT '',
  ativo INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT NOT NULL DEFAULT ''
);
CREATE TABLE alert_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  criado_em TEXT NOT NULL,
  evento TEXT NOT NULL DEFAULT '',
  titulo TEXT NOT NULL DEFAULT '',
  detalhe TEXT NOT NULL DEFAULT '',
  destino TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  erro TEXT NOT NULL DEFAULT ''
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@pytest.fixture
def old_database(tmp_path):
    """A panel as it was before the translation, with one row in each table."""
    path = tmp_path / "panel.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
                " VALUES ('Canal da equipe', 'https://exemplo/x', 'caiu,voltou', 1, '2026-01-01')")
    con.execute("INSERT INTO alert_log (criado_em, evento, titulo, detalhe, destino, status, erro)"
                " VALUES ('2026-01-01T10:00:00', 'caiu', 'Servidor parou', 'o detalhe',"
                " 'Canal da equipe', 'enviado', '')")
    # Without this mark `_migrate_single_webhook` would create an extra destination and the
    # test would end up being about something else.
    con.execute("INSERT INTO settings (key, value) VALUES ('webhooks_migrado', '1')")
    con.commit()
    con.close()
    return path


def _line(path, table: str) -> dict:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        return dict(con.execute(f"SELECT * FROM {table}").fetchone())
    finally:
        con.close()


def test_a_coluna_muda_de_nome_e_o_dado_fica(old_database):
    """`RENAME COLUMN` keeps the content; recreating the table and copying does not."""
    schema.init_db(str(old_database), "", "", lambda: "2026-01-02")

    hook = _line(old_database, "webhooks")
    assert set(hook) == {"id", "name", "url", "events", "enabled", "created_at"}
    assert hook["name"] == "Canal da equipe"
    assert hook["events"] == "caiu,voltou"
    assert hook["enabled"] == 1
    assert hook["created_at"] == "2026-01-01"

    alert = _line(old_database, "alert_log")
    assert set(alert) == {"id", "created_at", "event", "title", "detail", "target",
                           "status", "error"}
    assert (alert["event"], alert["title"], alert["target"]) == (
        "caiu", "Servidor parou", "Canal da equipe")


def test_rodar_de_novo_nao_faz_nada(old_database):
    """The panel calls `init_db` on every start: the second pass must not break."""
    schema.init_db(str(old_database), "", "", lambda: "2026-01-02")
    before = _line(old_database, "webhooks")
    schema.init_db(str(old_database), "", "", lambda: "2026-01-03")
    assert _line(old_database, "webhooks") == before


def test_banco_novo_ja_nasce_com_o_nome_novo(tmp_path):
    """A fresh install goes through no migration at all: SCHEMA is already right."""
    path = tmp_path / "novo.db"
    schema.init_db(str(path), "", "", lambda: "2026-01-02")
    con = sqlite3.connect(path)
    try:
        for table, expected_ones in (
            ("webhooks", {"id", "name", "url", "events", "enabled", "created_at"}),
            ("alert_log", {"id", "created_at", "event", "title", "detail", "target",
                           "status", "error"}),
        ):
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            assert cols == expected_ones, table
    finally:
        con.close()


def test_toda_renomeacao_aponta_para_uma_coluna_que_o_schema_tem():
    """A new name with a typo would become an orphan column, and would only show up in production."""
    for table, _old, fresh in schema.RENAMES:
        assert f"  {fresh} " in schema.SCHEMA or f"  {fresh}\n" in schema.SCHEMA, \
            f"{table}.{fresh} nao existe no SCHEMA"
