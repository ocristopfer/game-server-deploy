"""The single-command console: the most powerful route of the panel, and the one with no suite.

It runs a shell line as ROOT inside the game container. The Phase 1 analysis
(`docs/architecture-analysis.md`, section 4.1) listed it among the gaps together with files,
backups and terminal - the other three got a suite and this one was left behind.

What is tested here is what the panel DECIDES, not what bash does: who can open it, what
becomes a job, how the command reaches its destination and what the screen shows back. `start_job`
is swapped for a spy, because firing real SSH in a test would be testing sshd.
"""
from __future__ import annotations

import pytest

from gamepanel import app as panel


@pytest.fixture
def server(database, admin) -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root',"
            " 'jogo.service', ?)", (panel.now_iso(),))
    return database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


@pytest.fixture
def spy(monkeypatch):
    """Captures what the console WOULD send to run, without opening any SSH."""
    seen: list[dict] = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None):
        seen.append({"action": action, "server_id": target["id"], "username": username,
                     "remote_cmd": remote_cmd, "command": command, "timeout": timeout})
        return 4242

    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return seen


# ------------------------------------------------------------------ who gets in

def test_operador_nao_abre_o_console(server, operator):
    """An ad-hoc command as root is exactly the power that separates admin from operator."""
    assert operator.get(f"/servers/{server}/console").status_code == 403


def test_operador_nao_dispara_comando(server, operator, post, spy):
    response = post(operator, f"/servers/{server}/console", {"command": "id"})
    assert response.status_code == 403
    assert spy == [], "nem o job pode nascer"


def test_admin_abre(server, admin):
    assert admin.get(f"/servers/{server}/console").status_code == 200


def test_sem_sessao_vai_para_o_login(server, client):
    response = client.get(f"/servers/{server}/console")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_servidor_que_nao_existe_e_404(admin):
    assert admin.get("/servers/9999/console").status_code == 404


def test_desligado_por_configuracao_e_403(server, admin, monkeypatch):
    """`GAMEPANEL_ALLOW_SHELL=0` is the switch that takes this power away from the whole panel."""
    monkeypatch.setattr(panel, "ALLOW_SHELL", False)
    assert admin.get(f"/servers/{server}/console").status_code == 403


def test_desligado_por_configuracao_nao_deixa_POSTAR(server, admin, post, monkeypatch):
    """The GET's 403 is not enough: whoever has the POST URL calls it directly."""
    monkeypatch.setattr(panel, "ALLOW_SHELL", False)
    response = post(admin, f"/servers/{server}/console", {"command": "rm -rf /"})
    assert response.status_code == 403


def test_sem_csrf_nada_roda(server, admin, spy):
    """A POST without a token is blocked BEFORE any decision about the command."""
    response = admin.post(f"/servers/{server}/console", data={"command": "id"})
    assert response.status_code == 400
    assert spy == []


# ------------------------------------------------- what reaches the container

def test_o_comando_vai_como_UM_argumento_de_bash_lc(server, admin, post, spy):
    """Pipes, quotes and `&&` must arrive intact: ssh's LOCAL shell must not interpret
    them. That is why the whole command becomes a single argument of `bash -lc`."""
    typed = "ls -la /opt | grep 'jogo' && echo " + chr(34) + "fim" + chr(34)
    post(admin, f"/servers/{server}/console", {"command": typed})
    assert len(spy) == 1
    sent = spy[0]
    assert sent["action"] == "shell"
    assert sent["command"] == typed, "o historico guarda o que a pessoa digitou"
    assert sent["remote_cmd"] == panel.q("bash", "-lc", typed)
    assert sent["timeout"] == panel.SHELL_TIMEOUT


def test_o_job_nasce_com_o_nome_de_quem_clicou(server, admin, post, spy):
    """The console output quotes the command: the history has to say WHO ran it."""
    post(admin, f"/servers/{server}/console", {"command": "id"})
    assert spy[0]["username"] == "chefe"


def test_depois_de_disparar_redireciona_para_o_job(server, admin, post, spy):
    """Without `?job=`, the screen would reload without showing the output of what just ran."""
    response = post(admin, f"/servers/{server}/console", {"command": "id"})
    assert response.status_code == 302
    assert f"/servers/{server}/console?job=4242" in response.headers["Location"]


@pytest.mark.parametrize("typed", ["", "   ", "\t\n"])
def test_comando_vazio_nao_vira_job(server, admin, post, spy, typed):
    response = post(admin, f"/servers/{server}/console", {"command": typed})
    assert response.status_code == 200, "volta para a tela, nao redireciona"
    assert spy == []


def test_comando_comprido_demais_nao_vira_job(server, admin, post, spy):
    """Size cap: the line goes into a `bash -lc` argument and from there into the job's
    command column."""
    post(admin, f"/servers/{server}/console", {"command": "x" * (panel.SHELL_MAX_LEN + 1)})
    assert spy == []


def test_no_limite_exato_ainda_roda(server, admin, post, spy):
    post(admin, f"/servers/{server}/console", {"command": "x" * panel.SHELL_MAX_LEN})
    assert len(spy) == 1


# --------------------------------------------------------------- the history

def _shell_job(conn, sid: int, command: str, username: str = "chefe") -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username,"
            " created_at, output) VALUES (?, 'alvo', 'shell', 'ok', ?, ?, ?, 'saida')",
            (sid, command, username, panel.now_iso()))
    return int(cur.lastrowid)


def test_o_historico_mostra_o_comando_avulso_daquele_servidor(server, admin, database):
    _shell_job(database, server, "uptime-do-teste")
    html = admin.get(f"/servers/{server}/console").get_data(as_text=True)
    assert "uptime-do-teste" in html


def test_o_historico_nao_mostra_job_que_nao_e_avulso(server, admin, database):
    """The screen lists `action = 'shell'`: a restart of the same server is not an ad-hoc command."""
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username,"
            " created_at) VALUES (?, 'alvo', 'restart', 'ok', 'restart-do-teste', 'chefe', ?)",
            (server, panel.now_iso()))
    html = admin.get(f"/servers/{server}/console").get_data(as_text=True)
    assert "restart-do-teste" not in html


def test_job_de_OUTRO_servidor_nao_abre_por_id(server, admin, database):
    """`?job=` comes from the URL. Without matching the server, changing the number in the address
    bar would show the output of a command run in another container."""
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('outro', 'outro.invalid', 22, 'root', 'jogo.service', ?)",
            (panel.now_iso(),))
    other = database.execute("SELECT id FROM servers WHERE name = 'outro'").fetchone()["id"]
    alien = _shell_job(database, other, "cat-etc-shadow-do-teste")
    html = admin.get(f"/servers/{server}/console?job={alien}").get_data(as_text=True)
    assert "cat-etc-shadow-do-teste" not in html


@pytest.mark.parametrize("raw", ["abc", "-1", "9e9", "", "1;2", "../3"])
def test_job_que_nao_e_numero_nao_derruba_a_tela(server, admin, raw):
    """`?job=` comes from the address bar: garbage there becomes a screen with no job, not a 500."""
    assert admin.get(f"/servers/{server}/console?job={raw}").status_code == 200
