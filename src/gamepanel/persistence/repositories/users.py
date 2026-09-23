"""Leitura e escrita da tabela `users`, incluindo o estado do segundo fator."""
from __future__ import annotations

import sqlite3

# O que a sessao precisa saber de quem esta logado. Nunca o hash da senha nem o segredo
# do 2FA: eles so saem da tabela nas funcoes que de fato os conferem.
SESSION_FIELDS = "id, username, role, created_at, totp_enabled, lang"
LIST_FIELDS = "id, username, role, created_at, totp_enabled"


def by_id(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def id_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()


def for_session(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    """So os campos que a sessao usa — sem hash de senha nem segredo do 2FA."""
    return conn.execute(
        f"SELECT {SESSION_FIELDS} FROM users WHERE id = ?", (uid,)).fetchone()  # noqa: S608


def identity(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, role FROM users WHERE id = ?", (uid,)).fetchone()


def all_ordered(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {LIST_FIELDS} FROM users ORDER BY role, username").fetchall()  # noqa: S608


def two_factor_state(conn: sqlite3.Connection, uid: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT totp_enabled, totp_recovery FROM users WHERE id = ?", (uid,)).fetchone()


def count_admins_besides(conn: sqlite3.Connection, admin_role: str, uid: int) -> int:
    """Quantos administradores sobram se este sair. Zero e o caminho para um painel
    sem ninguem que possa administra-lo."""
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = ? AND id <> ?", (admin_role, uid),
    ).fetchone()[0]


# --- escrita ------------------------------------------------------------------------

def insert(conn: sqlite3.Connection, username: str, password_hash: str, role: str,
           created_at: str) -> None:
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at)"
        " VALUES (?, ?, ?, ?)", (username, password_hash, role, created_at))


def set_password(conn: sqlite3.Connection, uid: int, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, uid))


def set_password_and_role(conn: sqlite3.Connection, uid: int, password_hash: str,
                          role: str) -> None:
    conn.execute("UPDATE users SET password_hash = ?, role = ? WHERE id = ?",
                 (password_hash, role, uid))


def set_role(conn: sqlite3.Connection, uid: int, role: str) -> None:
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))


def set_language(conn: sqlite3.Connection, uid: int, lang: str) -> None:
    conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, uid))


def delete(conn: sqlite3.Connection, uid: int) -> None:
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))


# --- segundo fator --------------------------------------------------------------------

def spend_step(conn: sqlite3.Connection, uid: int, step: int) -> bool:
    """Gasta um passo do TOTP, e devolve se ELE conseguiu.

    O `WHERE totp_last_step < ?` faz do UPDATE o portao: dois pedidos com o MESMO codigo
    ao mesmo tempo nao passam os dois — o segundo nao encontra linha com passo menor.
    Conferir antes e gravar depois deixaria a janela aberta entre as duas.
    """
    return conn.execute(
        "UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?",
        (step, uid, step)).rowcount == 1


def spend_recovery(conn: sqlite3.Connection, uid: int, remaining: str,
                   previous: str) -> bool:
    """Mesmo portao, para os codigos de recuperacao: so grava se a lista ainda for a que
    foi lida, entao dois pedidos nao gastam o mesmo codigo."""
    return conn.execute(
        "UPDATE users SET totp_recovery = ? WHERE id = ? AND totp_recovery = ?",
        (remaining, uid, previous)).rowcount == 1


def enable_two_factor(conn: sqlite3.Connection, uid: int, secret: str, step: int,
                      recovery: str) -> None:
    conn.execute(
        "UPDATE users SET totp_secret = ?, totp_enabled = 1, totp_last_step = ?,"
        " totp_recovery = ? WHERE id = ?", (secret, step, recovery, uid))


def set_recovery(conn: sqlite3.Connection, uid: int, recovery: str) -> None:
    conn.execute("UPDATE users SET totp_recovery = ? WHERE id = ?", (recovery, uid))


def disable_two_factor(conn: sqlite3.Connection, uid: int) -> None:
    """Zera TUDO do segundo fator, inclusive o passo e os codigos de recuperacao: deixar
    o segredo para tras faria um app antigo continuar gerando codigo valido ao religar."""
    conn.execute(
        "UPDATE users SET totp_secret = '', totp_enabled = 0, totp_last_step = 0,"
        " totp_recovery = '' WHERE id = ?", (uid,))
