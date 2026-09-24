"""O console de comando unico: a rota mais poderosa do painel, e a que nao tinha suite.

Ela roda uma linha de shell como ROOT dentro do container do jogo. A analise da Fase 1
(`docs/architecture-analysis.md`, secao 4.1) a listou entre as lacunas junto de arquivos,
backups e terminal — as outras tres ganharam suite e esta ficou para tras.

O que se testa aqui e o que o painel DECIDE, nao o que o bash faz: quem pode abrir, o que
vira job, como o comando chega ao destino e o que a tela mostra de volta. O `start_job` e
trocado por um espiao, porque disparar SSH de verdade num teste seria testar o sshd.
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
    """Captura o que o console MANDARIA rodar, sem abrir SSH nenhum."""
    seen: list[dict] = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None):
        seen.append({"action": action, "server_id": target["id"], "username": username,
                     "remote_cmd": remote_cmd, "command": command, "timeout": timeout})
        return 4242

    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return seen


# ------------------------------------------------------------------ quem entra

def test_operador_nao_abre_o_console(server, operator):
    """Comando avulso como root e justamente o poder que separa admin de operador."""
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
    """`GAMEPANEL_ALLOW_SHELL=0` e a chave que tira esse poder do painel inteiro."""
    monkeypatch.setattr(panel, "ALLOW_SHELL", False)
    assert admin.get(f"/servers/{server}/console").status_code == 403


def test_desligado_por_configuracao_nao_deixa_POSTAR(server, admin, post, monkeypatch):
    """O 403 do GET nao basta: quem tem a URL do POST a chama direto."""
    monkeypatch.setattr(panel, "ALLOW_SHELL", False)
    response = post(admin, f"/servers/{server}/console", {"command": "rm -rf /"})
    assert response.status_code == 403


def test_sem_csrf_nada_roda(server, admin, spy):
    """O POST sem token e barrado ANTES de qualquer decisao sobre o comando."""
    response = admin.post(f"/servers/{server}/console", data={"command": "id"})
    assert response.status_code == 400
    assert spy == []


# ------------------------------------------------- o que chega ao container

def test_o_comando_vai_como_UM_argumento_de_bash_lc(server, admin, post, spy):
    """Pipe, aspas e `&&` tem de chegar intactos: o shell LOCAL do ssh nao pode
    interpreta-los. Por isso o comando inteiro vira um argumento so de `bash -lc`."""
    typed = "ls -la /opt | grep 'jogo' && echo " + chr(34) + "fim" + chr(34)
    post(admin, f"/servers/{server}/console", {"command": typed})
    assert len(spy) == 1
    sent = spy[0]
    assert sent["action"] == "shell"
    assert sent["command"] == typed, "o historico guarda o que a pessoa digitou"
    assert sent["remote_cmd"] == panel.q("bash", "-lc", typed)
    assert sent["timeout"] == panel.SHELL_TIMEOUT


def test_o_job_nasce_com_o_nome_de_quem_clicou(server, admin, post, spy):
    """A saida do console cita o comando: o historico tem de dizer QUEM o rodou."""
    post(admin, f"/servers/{server}/console", {"command": "id"})
    assert spy[0]["username"] == "chefe"


def test_depois_de_disparar_redireciona_para_o_job(server, admin, post, spy):
    """Sem o `?job=`, a tela recarregaria sem mostrar a saida do que acabou de rodar."""
    response = post(admin, f"/servers/{server}/console", {"command": "id"})
    assert response.status_code == 302
    assert f"/servers/{server}/console?job=4242" in response.headers["Location"]


@pytest.mark.parametrize("typed", ["", "   ", "\t\n"])
def test_comando_vazio_nao_vira_job(server, admin, post, spy, typed):
    response = post(admin, f"/servers/{server}/console", {"command": typed})
    assert response.status_code == 200, "volta para a tela, nao redireciona"
    assert spy == []


def test_comando_comprido_demais_nao_vira_job(server, admin, post, spy):
    """Teto de tamanho: a linha entra num argumento de `bash -lc` e de la na coluna de
    comando do job."""
    post(admin, f"/servers/{server}/console", {"command": "x" * (panel.SHELL_MAX_LEN + 1)})
    assert spy == []


def test_no_limite_exato_ainda_roda(server, admin, post, spy):
    post(admin, f"/servers/{server}/console", {"command": "x" * panel.SHELL_MAX_LEN})
    assert len(spy) == 1


# --------------------------------------------------------------- o historico

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
    """A tela lista `action = 'shell'`: restart do mesmo servidor nao e comando avulso."""
    with database:
        database.execute(
            "INSERT INTO jobs (server_id, target, action, status, command, username,"
            " created_at) VALUES (?, 'alvo', 'restart', 'ok', 'restart-do-teste', 'chefe', ?)",
            (server, panel.now_iso()))
    html = admin.get(f"/servers/{server}/console").get_data(as_text=True)
    assert "restart-do-teste" not in html


def test_job_de_OUTRO_servidor_nao_abre_por_id(server, admin, database):
    """`?job=` vem da URL. Sem casar o servidor, trocar o numero na barra de enderecos
    mostraria a saida de um comando rodado em outro container."""
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
    """O `?job=` chega da barra de enderecos: lixo ali vira tela sem job, nao 500."""
    assert admin.get(f"/servers/{server}/console?job={raw}").status_code == 200
