"""Leitura e escrita da tabela `servers`."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# As colunas que o formulario de servidor preenche. A MESMA lista serve ao INSERT, ao
# UPDATE e a leitura do formulario: escrever as tres a mao e onde uma coluna nova entra
# em duas e some da terceira.
HTTP_FIELDS = ("http_url", "http_auth", "http_body", "http_list_path", "http_count_path",
               "http_login_url", "http_login_body", "http_token_path")
EDITABLE_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "backup_paths", "query_port", "player_source",
    "join_re", "leave_re", "log_path", "error_re",
    *HTTP_FIELDS,
)

# Colunas que o DEPLOY traz — subconjunto das editaveis, mais `broker_id`. O deploy nao
# conhece as de contagem por HTTP nem o `error_re`: quem as preenche e a tela.
DEPLOY_FIELDS = (
    "name", "host", "ssh_port", "ssh_user", "service", "game_port", "notes",
    "config_path", "config_files", "backup_paths", "query_port", "player_source",
    "join_re", "leave_re", "log_path", "broker_id",
)
# O que um redeploy NAO sobrescreve esta fora desta lista (`host` e `ssh_port` sao a
# identidade; `error_re` e as de HTTP sao afinadas na tela).
DEPLOY_UPDATE_FIELDS = (
    "name", "ssh_user", "service", "game_port", "notes", "config_path", "config_files",
    "backup_paths", "query_port", "player_source", "join_re", "leave_re", "log_path",
)

# As quatro instrucoes sao MONTADAS a partir das listas acima, e nao escritas a mao: a
# alternativa e repetir os nomes das colunas quatro vezes e descobrir a divergencia em
# runtime. Nada aqui vem de fora — sao as constantes deste arquivo —, e todo VALOR
# continua parametrizado.
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


# --- leitura ------------------------------------------------------------------------

def by_id(conn: sqlite3.Connection, sid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()


def all_ordered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM servers ORDER BY name").fetchall()


def by_address(conn: sqlite3.Connection, host: str, ssh_port: int) -> sqlite3.Row | None:
    """O endereco e a identidade de um servidor: `(host, ssh_port)` e UNIQUE no esquema."""
    return conn.execute(
        "SELECT * FROM servers WHERE host = ? AND ssh_port = ?", (host, ssh_port)).fetchone()


def id_by_host(conn: sqlite3.Connection, host: str) -> sqlite3.Row | None:
    """O servidor na porta SSH padrao daquele endereco — o que o broker acabou de criar."""
    return conn.execute(
        "SELECT id FROM servers WHERE host = ? AND ssh_port = 22", (host,)).fetchone()


def from_broker(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Os que o broker criou: os unicos com `broker_id` preenchido."""
    return conn.execute(
        "SELECT id, name, broker_id FROM servers WHERE broker_id > 0").fetchall()


# --- escrita pela tela ---------------------------------------------------------------

def insert(conn: sqlite3.Connection, data: Mapping[str, Any], created_at: str) -> None:
    conn.execute(_INSERT, (*[data[c] for c in EDITABLE_FIELDS], created_at))


def update(conn: sqlite3.Connection, data: Mapping[str, Any], sid: int) -> None:
    conn.execute(_UPDATE, (*[data[c] for c in EDITABLE_FIELDS], sid))


def delete(conn: sqlite3.Connection, sid: int) -> None:
    conn.execute("DELETE FROM servers WHERE id = ?", (sid,))


def delete_by_broker_id(conn: sqlite3.Connection, broker_id: int) -> None:
    conn.execute("DELETE FROM servers WHERE broker_id = ?", (broker_id,))


# --- escrita pelo assistente de contagem de jogadores ---------------------------------
#
# Cada fonte grava o que so ela usa E liga o `player_source` na mesma instrucao: sao a
# mesma decisao, e separa-las deixaria um servidor apontando para uma fonte sem os
# campos dela preenchidos.

def use_query_port(conn: sqlite3.Connection, sid: int, port: int) -> None:
    conn.execute(
        "UPDATE servers SET query_port = ?, player_source = 'a2s' WHERE id = ?", (port, sid))


def use_http(conn: sqlite3.Connection, sid: int, fields: Mapping[str, Any]) -> None:
    """O token guardado ZERA ao salvar: se a URL ou a credencial mudou, o antigo nao vale
    mais, e a proxima consulta ja faz login com o que ficou."""
    columns = ", ".join(f"{c}=?" for c in HTTP_FIELDS)
    # Sao os nomes de coluna deste arquivo, nunca um valor de fora; os VALORES seguem
    # parametrizados.
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


# --- escrita pelo deploy (sem tela) ---------------------------------------------------

def deploy_insert(conn: sqlite3.Connection, values: Sequence[Any], created_at: str) -> None:
    conn.execute(_DEPLOY_INSERT, (*values, created_at))


def deploy_update(conn: sqlite3.Connection, values: Sequence[Any], sid: int) -> None:
    conn.execute(_DEPLOY_UPDATE, (*values, sid))
