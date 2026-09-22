"""Migrations do banco do painel: coluna nova e coluna que mudou de nome.

Este arquivo existe porque migration e o unico codigo aqui que so roda UMA vez, no
banco de quem ja tinha o painel instalado — e num banco novo, que e onde os outros
testes vivem, ela nem e exercitada. O jeito de testa-la e construir o esquema ANTIGO a
mao, com dado dentro, e mandar o `init_db` passar por cima.

O que se perde quando ela esta errada nao e uma tela: e o historico de alertas e a lista
de destinos de quem ja usava o painel.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamepanel.persistence import schema

# O esquema das duas tabelas ANTES dos nomes em ingles. Escrito por extenso de
# proposito: copiar do `SCHEMA` de hoje faria o teste concordar consigo mesmo.
ESQUEMA_ANTIGO = """
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
def banco_antigo(tmp_path):
    """Um painel como ele estava antes da traducao, com uma linha em cada tabela."""
    caminho = tmp_path / "panel.db"
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA_ANTIGO)
    con.execute("INSERT INTO webhooks (nome, url, eventos, ativo, criado_em)"
                " VALUES ('Canal da equipe', 'https://exemplo/x', 'caiu,voltou', 1, '2026-01-01')")
    con.execute("INSERT INTO alert_log (criado_em, evento, titulo, detalhe, destino, status, erro)"
                " VALUES ('2026-01-01T10:00:00', 'caiu', 'Servidor parou', 'o detalhe',"
                " 'Canal da equipe', 'enviado', '')")
    # Sem esta marca o `_migra_webhook_unico` criaria um destino extra e o teste passaria
    # a falar de outra coisa.
    con.execute("INSERT INTO settings (key, value) VALUES ('webhooks_migrado', '1')")
    con.commit()
    con.close()
    return caminho


def _linha(caminho, tabela: str) -> dict:
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    try:
        return dict(con.execute(f"SELECT * FROM {tabela}").fetchone())
    finally:
        con.close()


def test_a_coluna_muda_de_nome_e_o_dado_fica(banco_antigo):
    """`RENAME COLUMN` preserva o conteudo; recriar a tabela e copiar, nao."""
    schema.init_db(str(banco_antigo), "", "", lambda: "2026-01-02")

    hook = _linha(banco_antigo, "webhooks")
    assert set(hook) == {"id", "name", "url", "events", "enabled", "created_at"}
    assert hook["name"] == "Canal da equipe"
    assert hook["events"] == "caiu,voltou"
    assert hook["enabled"] == 1
    assert hook["created_at"] == "2026-01-01"

    alerta = _linha(banco_antigo, "alert_log")
    assert set(alerta) == {"id", "created_at", "event", "title", "detail", "target",
                           "status", "error"}
    assert (alerta["event"], alerta["title"], alerta["target"]) == (
        "caiu", "Servidor parou", "Canal da equipe")


def test_rodar_de_novo_nao_faz_nada(banco_antigo):
    """O painel chama `init_db` em todo start: a segunda volta nao pode quebrar."""
    schema.init_db(str(banco_antigo), "", "", lambda: "2026-01-02")
    antes = _linha(banco_antigo, "webhooks")
    schema.init_db(str(banco_antigo), "", "", lambda: "2026-01-03")
    assert _linha(banco_antigo, "webhooks") == antes


def test_banco_novo_ja_nasce_com_o_nome_novo(tmp_path):
    """Instalacao nova nao passa por migration nenhuma: o SCHEMA ja esta certo."""
    caminho = tmp_path / "novo.db"
    schema.init_db(str(caminho), "", "", lambda: "2026-01-02")
    con = sqlite3.connect(caminho)
    try:
        for tabela, esperadas in (
            ("webhooks", {"id", "name", "url", "events", "enabled", "created_at"}),
            ("alert_log", {"id", "created_at", "event", "title", "detail", "target",
                           "status", "error"}),
        ):
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
            assert cols == esperadas, tabela
    finally:
        con.close()


def test_toda_renomeacao_aponta_para_uma_coluna_que_o_schema_tem():
    """Nome novo com erro de digitacao viraria coluna orfa, e so apareceria em producao."""
    for tabela, _velho, novo in schema.RENAMES:
        assert f"  {novo} " in schema.SCHEMA or f"  {novo}\n" in schema.SCHEMA, \
            f"{tabela}.{novo} nao existe no SCHEMA"
