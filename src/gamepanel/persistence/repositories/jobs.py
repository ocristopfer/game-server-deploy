"""Leitura e escrita da tabela `jobs` — o historico de tudo que o painel executou."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

# Um servidor chega como linha do SQLite (leitura normal) ou como dict (a thread de um
# job copia a linha, porque a Row esta presa a conexao do request).
ServerLike = sqlite3.Row | Mapping[str, Any]

# O painel guarda a saida inteira de um comando; um `apt upgrade` passa facil de um mega
# e enche o banco por linha. O corte e aqui, e nao na tela, para o disco nao crescer.
OUTPUT_MAX = 200_000
BROKER_TARGET = "broker"

# Acoes que DERRUBAM o servico de proposito. Uma queda logo depois de uma
# delas nao e queda: e o botao que a pessoa acabou de clicar.
DISRUPTIVE_ACTIONS = ("start", "stop", "restart", "update", "restore-backup")


def _row_id(cur: sqlite3.Cursor) -> int:
    """O id da linha recem-inserida.

    `lastrowid` e Optional no tipo porque um cursor pode nao ter inserido nada; depois de
    um INSERT que deu certo, nunca. Falhar alto aqui e melhor do que devolver 0 e deixar
    o job apontando para uma linha que nao existe.
    """
    if cur.lastrowid is None:
        raise RuntimeError("INSERT em jobs nao devolveu id")
    return cur.lastrowid


# --- leitura ------------------------------------------------------------------------

def by_id(conn: sqlite3.Connection, jid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()


def by_id_and_server(conn: sqlite3.Connection, jid: int, sid: int) -> sqlite3.Row | None:
    """O id sozinho nao basta: a tela do console so pode mostrar job DAQUELE servidor."""
    return conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND server_id = ?", (jid, sid)).fetchone()


def of_server(conn: sqlite3.Connection, sid: int, limit: int,
              role_cut: str = "", role_values: Sequence[Any] = ()) -> list[sqlite3.Row]:
    """Historico de um servidor. `role_cut` e o pedaco de WHERE que esconde do operador
    as acoes restritas — vem pronto de quem sabe o papel de quem esta olhando."""
    return conn.execute(
        f"SELECT * FROM jobs WHERE server_id = ?{role_cut} ORDER BY id DESC LIMIT ?",  # noqa: S608
        (sid, *role_values, limit),
    ).fetchall()


def shell_history(conn: sqlite3.Connection, sid: int, limit: int) -> list[sqlite3.Row]:
    """Os comandos avulsos mais recentes daquele servidor (tela Console)."""
    return conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? AND action = 'shell'"
        " ORDER BY id DESC LIMIT ?", (sid, limit)).fetchall()


def page(conn: sqlite3.Connection, where: str, values: Sequence[Any],
         limit: int, offset: int) -> list[sqlite3.Row]:
    """Uma pagina do historico geral. O `where` e montado por quem aplica os filtros da
    tela; aqui so a paginacao."""
    return conn.execute(
        f"SELECT * FROM jobs WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",  # noqa: S608
        (*values, limit, offset),
    ).fetchall()


def usernames(conn: sqlite3.Connection, role_cut: str = "",
              role_values: Sequence[Any] = ()) -> list[str]:
    """Quem aparece no historico — alimenta o filtro da tela."""
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT username FROM jobs WHERE username <> '' {role_cut}"  # noqa: S608
        " ORDER BY username",
        tuple(role_values),
    ).fetchall()]


def acted_since(conn: sqlite3.Connection, sid: int, since: str,
                actions: Sequence[str] = DISRUPTIVE_ACTIONS) -> bool:
    """Houve acao do painel neste servidor depois de `since`?

    Reiniciar pelo botao derruba o servico por alguns segundos, e isso NAO e uma queda.
    Sem esta janela, todo restart e todo update viraria alerta.
    """
    marks = ", ".join("?" * len(actions))
    return conn.execute(
        f"SELECT 1 FROM jobs WHERE server_id = ? AND created_at >= ?"  # noqa: S608
        f" AND action IN ({marks}) LIMIT 1",
        (sid, since, *actions),
    ).fetchone() is not None


def running_broker_ops(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Operacoes do broker que ficaram 'running' — o painel reiniciou no meio delas."""
    return conn.execute(
        "SELECT id, broker_op FROM jobs WHERE status = 'running' AND broker_op != ''"
    ).fetchall()


# --- escrita ------------------------------------------------------------------------

def target_of(server: ServerLike) -> str:
    """Como um job identifica o que ele mexeu. O formato e um so, aqui: escrito em cada
    chamador, um deles um dia fica sem a porta ou com o usuario errado."""
    return f"{server['ssh_user']}@{server['host']}"


def start(conn: sqlite3.Connection, server: ServerLike, action: str,
          command: str, username: str, created_at: str) -> int:
    """Job que COMECOU: fica 'running' ate alguem chamar `finish`."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, command, username,"
        " created_at) VALUES (?,?,?,?,?,?,?)",
        (server["id"], target_of(server), action, "running", command, username, created_at))
    return _row_id(cur)


def record(conn: sqlite3.Connection, server: ServerLike, action: str, status: str,
           output: str, command: str, username: str, at: str) -> int:
    """Job que JA ACONTECEU (edicao de arquivo, sessao de terminal): nasce terminado."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
        " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (server["id"], target_of(server), action, status, 0 if status == "ok" else None,
         output[-OUTPUT_MAX:], command, username, at, at))
    return _row_id(cur)


def start_broker(conn: sqlite3.Connection, action: str, command: str, username: str,
                 created_at: str, op_id: str) -> int:
    """Sem servidor: a instancia ainda nao existe quando a criacao comeca."""
    cur = conn.execute(
        "INSERT INTO jobs (server_id, target, action, status, command, username,"
        " created_at, broker_op) VALUES (NULL, ?, ?, 'running', ?, ?, ?, ?)",
        (BROKER_TARGET, action, command, username, created_at, op_id))
    return _row_id(cur)


def record_broker(conn: sqlite3.Connection, action: str, status: str, output: str,
                  command: str, username: str, at: str) -> int:
    """Acao curta do broker (desativar, remover, jogo novo): nasce terminada."""
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
    """Escreve so as colunas dadas — usado pelo acompanhamento do broker, que grava o
    log a cada volta. Os NOMES vem de quem chama (fixos no codigo); os VALORES viajam
    como parametro."""
    if not fields:
        return
    columns = ", ".join(f"{c}=?" for c in fields)
    conn.execute(f"UPDATE jobs SET {columns} WHERE id=?",  # noqa: S608
                 (*fields.values(), jid))


def delete_older_than(conn: sqlite3.Connection, cut: str) -> int:
    cur = conn.execute("DELETE FROM jobs WHERE created_at < ?", (cut,))
    return cur.rowcount or 0
