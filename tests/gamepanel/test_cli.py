"""Linha de comando do painel (gamepanel.cli).

Nao tinha teste nenhum: o bloco morava dentro de um `if __name__ == "__main__"` no
rodape do app.py, onde nada consegue chamar. E ali esta a saida de emergencia do
segundo fator — o comando que alguem roda justamente quando perdeu o acesso ao painel,
e que portanto nao pode falhar em silencio.

As dependencias entram por `CliDeps`, entao aqui nao sobe Flask nem relogio: o banco e
um sqlite de arquivo temporario e o resto sao dublês que so anotam o que foi chamado.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamepanel import cli


@pytest.fixture
def banco_cli(tmp_path):
    """Um banco com a tabela de usuarios e um admin com 2FA ligado."""
    caminho = tmp_path / "painel.db"
    con = sqlite3.connect(caminho)
    con.execute("""CREATE TABLE users (
        id INTEGER PRIMARY KEY, username TEXT, totp_secret TEXT DEFAULT '',
        totp_enabled INTEGER DEFAULT 0, totp_last_step INTEGER DEFAULT 0,
        totp_recovery TEXT DEFAULT '')""")
    con.execute("INSERT INTO users (username, totp_secret, totp_enabled, totp_last_step,"
                " totp_recovery) VALUES ('chefe', 'SEGREDO', 1, 999, 'hashes')")
    con.commit()
    con.close()

    def connect():
        c = sqlite3.connect(caminho)
        c.row_factory = sqlite3.Row
        return c

    return connect


def deps(connect=None, **trocas) -> cli.CliDeps:
    chamadas: dict = trocas.pop("_chamadas", {})
    padrao = {
        "init_db": lambda: chamadas.setdefault("init_db", 0),
        "connect": connect or (lambda: sqlite3.connect(":memory:")),
        "ensure_admin_user": lambda *a: chamadas.__setitem__("usuario", a),
        "ensure_server": lambda d: chamadas.__setitem__("servidor", d) or True,
        "deploy_server": dict,
        "start_scheduler": lambda: chamadas.__setitem__("relogio", True),
        "resume_broker_jobs": lambda: chamadas.__setitem__("broker", True),
        "app": _AppFalso(chamadas),
        "roles": ("admin", "operador"),
    }
    return cli.CliDeps(**{**padrao, **trocas})


class _AppFalso:
    def __init__(self, chamadas: dict):
        self._chamadas = chamadas

    def run(self, host, port):
        self._chamadas["run"] = (host, port)


# --------------------------------------------------------------- 2FA

def test_reset_2fa_limpa_as_quatro_colunas(banco_cli, capsys):
    """Meia limpeza deixaria o usuario trancado do mesmo jeito."""
    cli.main(deps(connect=banco_cli), ["--reset-2fa", "chefe"])
    linha = dict(banco_cli().execute("SELECT * FROM users").fetchone())
    assert linha["totp_secret"] == ""
    assert linha["totp_enabled"] == 0
    assert linha["totp_last_step"] == 0
    assert linha["totp_recovery"] == ""
    assert "desligado" in capsys.readouterr().out


def test_reset_2fa_de_quem_nao_existe_falha_dizendo(banco_cli):
    with pytest.raises(SystemExit, match="ninguem"):
        cli.main(deps(connect=banco_cli), ["--reset-2fa", "ninguem"])


def test_reset_2fa_nao_mexe_nos_outros_usuarios(banco_cli):
    con = banco_cli()
    with con:
        con.execute("INSERT INTO users (username, totp_secret, totp_enabled)"
                    " VALUES ('outra', 'DELA', 1)")
    cli.main(deps(connect=banco_cli), ["--reset-2fa", "chefe"])
    outra = dict(banco_cli().execute(
        "SELECT * FROM users WHERE username='outra'").fetchone())
    assert outra["totp_enabled"] == 1
    assert outra["totp_secret"] == "DELA"


def test_reset_2fa_sobe_o_banco_antes(banco_cli):
    """Roda no CT logo depois do deploy: a tabela pode nem existir ainda."""
    feitos: list[str] = []
    d = deps(connect=banco_cli, init_db=lambda: feitos.append("init_db"))
    cli.main(d, ["--reset-2fa", "chefe"])
    assert feitos == ["init_db"]


# ------------------------------------------------------------ usuario

def test_create_user_repassa_nome_senha_e_papel():
    vistos: list = []
    d = deps(ensure_admin_user=lambda *a: vistos.append(a))
    cli.main(d, ["--create-user", "ana", "--password", "segredo", "--role", "admin"])
    assert vistos == [("ana", "segredo", "admin")]


def test_create_user_sem_senha_e_recusado():
    with pytest.raises(SystemExit, match="--password"):
        cli.main(deps(), ["--create-user", "ana"])


def test_papel_fora_da_lista_e_recusado_pelo_parser():
    with pytest.raises(SystemExit):
        cli.main(deps(), ["--create-user", "ana", "--password", "x", "--role", "dono"])


# ----------------------------------------------------- servidor pelo deploy

def test_register_server_exige_host_e_servico():
    with pytest.raises(SystemExit, match="--server-host"):
        cli.main(deps(), ["--register-server", "Palworld"])


def test_register_server_monta_o_cadastro():
    vistos: list = []
    d = deps(ensure_server=lambda data: vistos.append(data) or True)
    cli.main(d, ["--register-server", "Palworld", "--server-host", "10.0.0.5",
                 "--service", "palworld.service", "--query-port", "27015"])
    data = vistos[0]
    assert data["name"] == "Palworld"
    assert data["host"] == "10.0.0.5"
    assert data["query_port"] == 27015
    assert data["ssh_port"] == 22, "o padrao continua 22"


def test_listas_vem_por_virgula_e_saem_uma_por_linha():
    """A linha de comando nao aceita quebra de linha com conforto."""
    vistos: list = []
    d = deps(ensure_server=lambda data: vistos.append(data) or True)
    cli.main(d, ["--register-server", "X", "--server-host", "h", "--service", "s",
                 "--config-files", "/opt/a.ini, /opt/b.ini", "--backup-paths", "/save"])
    assert vistos[0]["config_files"] == "/opt/a.ini\n/opt/b.ini"
    assert vistos[0]["backup_paths"] == "/save"


@pytest.mark.parametrize(("raw", "esperado"), [
    ("", ""), ("  ", ""), ("/a", "/a"), ("/a,,/b", "/a\n/b"), (" /a , /b ", "/a\n/b"),
])
def test_por_virgula(raw, esperado):
    assert cli.by_comma(raw) == esperado


# ----------------------------------------------------------- servidor web

def test_sem_argumentos_sobe_o_painel_com_o_relogio():
    chamadas: dict = {}
    d = deps(_chamadas=chamadas, start_scheduler=lambda: chamadas.__setitem__("relogio", True),
             resume_broker_jobs=lambda: chamadas.__setitem__("broker", True),
             app=_AppFalso(chamadas))
    cli.main(d, [])
    assert chamadas["relogio"] is True
    assert chamadas["broker"] is True, "os jobs do broker voltam a ser acompanhados"
    assert chamadas["run"] == ("0.0.0.0", 8080)


def test_cadastrar_usuario_nao_sobe_o_relogio():
    """Pela linha de comando o relogio NAO pode comecar a mexer nos containers."""
    chamadas: dict = {}
    d = deps(_chamadas=chamadas,
             start_scheduler=lambda: chamadas.__setitem__("relogio", True),
             ensure_admin_user=lambda *a: None, app=_AppFalso(chamadas))
    cli.main(d, ["--create-user", "ana", "--password", "x"])
    assert "relogio" not in chamadas
    assert "run" not in chamadas


def test_host_e_porta_podem_ser_trocados():
    chamadas: dict = {}
    d = deps(_chamadas=chamadas, app=_AppFalso(chamadas))
    cli.main(d, ["--host", "127.0.0.1", "--port", "9999"])
    assert chamadas["run"] == ("127.0.0.1", 9999)
