#!/usr/bin/env python3
"""Tests for the roles (admin/operator) and the users screen.

    pytest admin/test_users.py

What these tests guarantee: an operator can operate the servers already registered and
CANNOT reach anything that gives a root shell in the container (terminal, console,
file browser) nor who has access to the panel. And that the panel is never left without
any administrator.
"""
import pytest

from gamepanel import app as panel


def role_of(database, username: str) -> str:
    row = database.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    return row["role"] if row else ""


def exists(database, username: str) -> bool:
    return database.execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None


def id_of(database, username: str) -> int:
    return database.execute(
        "SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


# --------------------------------------------------------- bootstrap through the CLI

def test_usuario_criado_pela_cli_e_admin(database):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    assert role_of(database, "chefe") == panel.ROLE_ADMIN


def test_redefinir_senha_pela_cli_nao_mexe_no_papel(database):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    panel.ensure_admin_user("chefe", "outra-senha")  # only resets the password
    assert role_of(database, "chefe") == panel.ROLE_ADMIN


def test_papel_escolhido_na_cli_vale(database):
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERATOR)
    assert role_of(database, "peao") == panel.ROLE_OPERATOR


# ---------------------------------------------- operator does not reach what gives root

def test_operador_abre_as_telas_proprias(operator):
    assert operator.get("/").status_code == 200
    assert operator.get("/ssh-key").status_code == 200
    assert operator.get("/account").status_code == 200


@pytest.mark.parametrize("rota", [
    "/users", "/servers/new", "/servers/1/edit", "/servers/1/terminal",
    "/servers/1/console", "/servers/1/files", "/servers/1/players/discover",
])
def test_operador_leva_403_no_que_da_root(operator, rota):
    """`admin_required` blocks by role BEFORE checking whether the server exists -
    that is why the 403 holds even with an empty database (server 1 need not exist)."""
    assert operator.get(rota).status_code == 403


def test_operador_nao_cria_usuario_nem_remove_servidor(operator, database, post):
    resp = post(operator, "/users", {"username": "invasor", "new": "senha12345",
                                      "confirm": "senha12345", "role": "admin"})
    assert resp.status_code == 403
    assert not exists(database, "invasor")
    assert post(operator, "/servers/1/delete").status_code == 403


# ------------------------------------------------------- admin manages users

def test_admin_abre_a_tela_de_usuarios(admin):
    assert admin.get("/users").status_code == 200


def test_admin_cria_usuario_pela_tela(admin, database, post):
    post(admin, "/users", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    assert role_of(database, "ana") == panel.ROLE_OPERATOR


def test_senha_curta_nao_cria_usuario(admin, database, post):
    post(admin, "/users", {"username": "bob", "new": "curta",
                                "confirm": "curta", "role": "operador"})
    assert not exists(database, "bob")


def test_confirmacao_errada_nao_cria_usuario(admin, database, post):
    post(admin, "/users", {"username": "bob", "new": "senha12345",
                                "confirm": "outra12345", "role": "operador"})
    assert not exists(database, "bob")


def test_nome_invalido_nao_cria_usuario(admin, database, post):
    post(admin, "/users", {"username": "Bob Silva", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    assert not exists(database, "Bob Silva")


def test_nome_repetido_nao_sobrescreve_o_papel_de_quem_ja_existe(admin, database, post):
    post(admin, "/users", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    post(admin, "/users", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "admin"})
    assert role_of(database, "ana") == panel.ROLE_OPERATOR


@pytest.fixture
def ana(admin, database, post) -> int:
    """An operator registered through the screen. Returns her id."""
    post(admin, "/users", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    return id_of(database, "ana")


def test_promover_funciona(ana, admin, database, post):
    post(admin, f"/users/{ana}/role", {"role": "admin"})
    assert role_of(database, "ana") == panel.ROLE_ADMIN


def test_ninguem_rebaixa_a_si_mesmo(admin, database, post):
    chefe_id = id_of(database, "chefe")
    post(admin, f"/users/{chefe_id}/role", {"role": "operador"})
    assert role_of(database, "chefe") == panel.ROLE_ADMIN


def test_rebaixar_outro_admin_funciona_quando_sobra_admin(ana, admin, database, post):
    post(admin, f"/users/{ana}/role", {"role": "admin"})
    post(admin, f"/users/{ana}/role", {"role": "operador"})
    assert role_of(database, "ana") == panel.ROLE_OPERATOR


def test_ninguem_remove_a_propria_conta(admin, database, post):
    chefe_id = id_of(database, "chefe")
    post(admin, f"/users/{chefe_id}/delete")
    assert exists(database, "chefe")


def test_reset_de_senha_pelo_admin_funciona(ana, admin, post, login):
    post(admin, f"/users/{ana}/password", {"new": "senha-nova-1", "confirm": "senha-nova-1"})
    login("ana", "senha-nova-1")  # raises AssertionError if the password did not take effect


# ------------------------------------------------------- last admin does not vanish

def test_ultimo_administrador_nao_pode_ser_rebaixado(admin, operator, database, post, login):
    """Only chefe is left: not even another promoted admin can remove the last one remaining
    (neither his own role nor the colleague's - see the two previous tests)."""
    peao_id = id_of(database, "peao")

    # Promotes the operator to be able to test "admin demotes fellow admin".
    post(admin, f"/users/{peao_id}/role", {"role": "admin"})
    assert role_of(database, "peao") == panel.ROLE_ADMIN
    post(admin, f"/users/{peao_id}/role", {"role": "operador"})
    assert role_of(database, "peao") == panel.ROLE_OPERATOR  # chefe still remains, so it works

    # Now promote again and raise only him: with two admins, no further command should
    # leave the panel with zero. Checks that the floor is always respected underneath.
    post(admin, f"/users/{peao_id}/role", {"role": "admin"})
    peao_admin = login("peao", "senha-do-peao")
    chefe_id = id_of(database, "chefe")
    post(peao_admin, f"/users/{peao_id}/role", {"role": "operador"})
    post(peao_admin, f"/users/{chefe_id}/role", {"role": "operador"})
    assert peao_admin.get("/users").status_code == 200

    were_left = database.execute(
        "SELECT COUNT(*) FROM users WHERE role = ?", (panel.ROLE_ADMIN,)).fetchone()[0]
    assert were_left >= 1, f"o painel nunca pode ficar sem administrador (sobraram {were_left})"


# --------------------------------------------------- session dies with the account

def test_sessao_morre_junto_com_a_conta(ana, admin, database, post, login):
    throwaway = login("ana", "senha12345")
    assert throwaway.get("/").status_code == 200, "logada, ve o painel"

    post(admin, f"/users/{ana}/delete")
    assert not exists(database, "ana")
    assert throwaway.get("/").status_code == 302, "a sessao dela cai no proximo clique"


# ---------------------------------------------- job history respects the role

SECRET = "SENHA-QUE-SO-O-ADMIN-PODE-VER"
ROTINA = "acao-de-rotina-do-operador"


@pytest.fixture
def server_with_jobs(database, admin):
    """A server with one job of each action - half restricted, half not.

    The job stores the WHOLE output of what ran. Since the operator gets 403 on the console and
    the file editor, they also cannot read their RESULT - neither by opening the job
    by id, nor at a glance in the history on the server screen.
    """
    with database:
        # Host that does not resolve: the server screen tries SSH and comes back quickly with
        # "inacessivel" - what is tested here is the history, not the connection.
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root', 'jogo.service', ?)",
            (panel.now_iso(),))
    sid = database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]

    jobs = {}
    with database:
        for action in ("shell", "terminal", "edit-file", "delete-file", "download-file",
                     "start", "edit-config"):
            mark = SECRET if action in panel.JOB_ACTIONS_ADMIN else ROTINA
            cur = database.execute(
                "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
                " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "root@alvo", action, "ok", 0, mark, mark, "chefe",
                 panel.now_iso(), panel.now_iso()))
            jobs[action] = cur.lastrowid
    return sid, jobs


@pytest.mark.parametrize("action", ["shell", "terminal", "edit-file", "delete-file",
                                  "download-file", "start", "edit-config"])
def test_apenas_admin_le_jobs_de_acao_restrita(server_with_jobs, admin, operator, action):
    _sid, jobs = server_with_jobs
    jid = jobs[action]
    expected = 403 if action in panel.JOB_ACTIONS_ADMIN else 200
    assert operator.get(f"/jobs/{jid}").status_code == expected
    assert operator.get(f"/api/v1/jobs/{jid}").status_code == expected
    assert admin.get(f"/jobs/{jid}").status_code == 200


def test_admin_continua_lendo_a_saida_do_console(server_with_jobs, admin):
    _sid, jobs = server_with_jobs
    body = admin.get(f"/jobs/{jobs['shell']}").get_data(as_text=True)
    assert SECRET in body


def test_historico_na_tela_do_servidor_esconde_o_restrito_do_operador(server_with_jobs, operator):
    sid, _jobs = server_with_jobs
    resp = operator.get(f"/servers/{sid}")
    assert resp.status_code == 200
    page = resp.get_data(as_text=True)
    assert SECRET not in page, "comando do console nao aparece no historico do operador"
    assert ROTINA in page, "o que ele pode fazer continua visivel"


def test_historico_na_tela_do_servidor_e_completo_para_o_admin(server_with_jobs, admin):
    sid, _jobs = server_with_jobs
    page = admin.get(f"/servers/{sid}").get_data(as_text=True)
    assert SECRET in page


# -------------------------------------------- backup and upload follow the same cut

@pytest.fixture
def target_server(database, admin) -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root',"
            " 'jogo.service', '/opt/game/Saved', ?)", (panel.now_iso(),))
    return database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


def test_sem_backup_paths_vale_a_pasta_de_configuracao(target_server, database):
    target = database.execute("SELECT * FROM servers WHERE id = ?", (target_server,)).fetchone()
    assert panel.backup_paths(target) == ["/opt/game/Saved"]
    assert panel.backup_prefix(target) == "jogo", "o prefixo sai da unidade systemd"


def test_backup_paths_preenchido_manda_no_config_path(target_server, database):
    with database:
        database.execute(
            "UPDATE servers SET backup_paths = ? WHERE id = ?",
            ("/opt/game/Saved/SaveGames\n/opt/game/config.ini", target_server))
    target = database.execute("SELECT * FROM servers WHERE id = ?", (target_server,)).fetchone()
    assert panel.backup_paths(target) == [
        "/opt/game/Saved/SaveGames", "/opt/game/config.ini"]


def test_operador_ve_backups_e_dispara_mas_nao_gerencia(target_server, operator, post):
    """Creating a copy is an operation (the operator may). Restoring, deleting and downloading
    destroy data or take the save out of the container - they are admin-only, like console and editor."""
    assert operator.get(f"/servers/{target_server}/backups").status_code == 200
    assert post(operator, f"/servers/{target_server}/backups/create").status_code == 302

    name = {"nome": "jogo-20260101-000000.tar.gz"}
    assert post(operator, f"/servers/{target_server}/backups/restore", name).status_code == 403
    assert post(operator, f"/servers/{target_server}/backups/delete", name).status_code == 403
    assert operator.get(
        f"/servers/{target_server}/backups/download?nome=jogo-20260101-000000.tar.gz"
    ).status_code == 403
    assert post(operator, f"/servers/{target_server}/files/upload").status_code == 403


@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "/etc/shadow", "x.tar.gz; rm -rf /", "sem-extensao",
    "..-..tar.gz", "",
])
def test_nome_de_backup_torto_e_recusado_mesmo_para_admin(target_server, admin, post, bad):
    """The name comes back from the screen and goes into a remote command: whatever does not match
    "<algo>.tar.gz" has to die in the panel, before reaching the container's shell."""
    resp = post(admin, f"/servers/{target_server}/backups/delete", {"nome": bad})
    assert resp.status_code == 400


# --------------------------------------------- moderating players is operation, not admin

def test_operador_modera_jogador_sem_precisar_de_admin(target_server, operator, post):
    """Kicking/banning gives no access to the container: whoever can already restart the server
    can moderate who is on it. 302 (and not 403) proves the operator got past the role check -
    any error left from here on is from validating the action, not from permission."""
    resp = post(operator, f"/servers/{target_server}/players/action",
                  {"action": "kick", "player": "x"})
    assert resp.status_code == 302


def test_admin_tambem_modera_jogador(target_server, admin, post):
    resp = post(admin, f"/servers/{target_server}/players/action",
                  {"acao": "announce", "mensagem": "oi"})
    assert resp.status_code == 302


# -------------------------------------------- return after login accepts only internal targets

@pytest.mark.parametrize("raw", [
    "//evil.example.com/x", "/\\evil.example.com", "https://evil.example.com",
    "http://evil.example.com", "evil", "", "/conta\r\nSet-Cookie: x=1",
])
def test_destino_de_login_recusa_endereco_de_fora(raw):
    """"/" at the start is not enough: to the browser "//host" and "/\\host" are absolute
    addresses, and would send whoever just logged in to another site."""
    assert panel.safe_target(raw) == ""


@pytest.mark.parametrize("raw", ["/servers/1/config", "/users", "/"])
def test_destino_de_login_aceita_caminho_interno(raw):
    assert panel.safe_target(raw) == raw
