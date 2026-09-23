#!/usr/bin/env python3
"""Testes dos papeis (admin/operador) e da tela de usuarios.

    pytest admin/test_users.py

O que estes testes garantem: um operador consegue operar os servidores ja cadastrados e
NAO consegue chegar em nada que da shell de root no container (terminal, console,
navegador de arquivos) nem em quem tem acesso ao painel. E que o painel nunca fica sem
nenhum administrador.
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


# --------------------------------------------------------- bootstrap pela CLI

def test_usuario_criado_pela_cli_e_admin(database):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    assert role_of(database, "chefe") == panel.ROLE_ADMIN


def test_redefinir_senha_pela_cli_nao_mexe_no_papel(database):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    panel.ensure_admin_user("chefe", "outra-senha")  # so redefine a senha
    assert role_of(database, "chefe") == panel.ROLE_ADMIN


def test_papel_escolhido_na_cli_vale(database):
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERATOR)
    assert role_of(database, "peao") == panel.ROLE_OPERATOR


# ---------------------------------------------- operador nao chega no que da root

def test_operador_abre_as_telas_proprias(operator):
    assert operator.get("/").status_code == 200
    assert operator.get("/ssh-key").status_code == 200
    assert operator.get("/account").status_code == 200


@pytest.mark.parametrize("rota", [
    "/users", "/servers/new", "/servers/1/edit", "/servers/1/terminal",
    "/servers/1/console", "/servers/1/files", "/servers/1/players/discover",
])
def test_operador_leva_403_no_que_da_root(operator, rota):
    """`admin_required` barra pelo papel ANTES de olhar se o servidor existe -
    por isso o 403 vale mesmo com o banco vazio (nao precisa existir servidor 1)."""
    assert operator.get(rota).status_code == 403


def test_operador_nao_cria_usuario_nem_remove_servidor(operator, database, post):
    resp = post(operator, "/users", {"username": "invasor", "new": "senha12345",
                                      "confirm": "senha12345", "role": "admin"})
    assert resp.status_code == 403
    assert not exists(database, "invasor")
    assert post(operator, "/servers/1/delete").status_code == 403


# ------------------------------------------------------- admin gerencia usuarios

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
    """Uma operadora cadastrada pela tela. Devolve o id dela."""
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
    login("ana", "senha-nova-1")  # levanta AssertionError se a senha nao tiver valido


# ------------------------------------------------------- ultimo admin nao some

def test_ultimo_administrador_nao_pode_ser_rebaixado(admin, operator, database, post, login):
    """So sobrou o chefe: nem outro admin promovido consegue tirar o ultimo que resta
    (nem o dele proprio, nem o do colega - ver os dois testes anteriores)."""
    peao_id = id_of(database, "peao")

    # Promove o operador para poder testar "admin rebaixa admin colega".
    post(admin, f"/users/{peao_id}/role", {"role": "admin"})
    assert role_of(database, "peao") == panel.ROLE_ADMIN
    post(admin, f"/users/{peao_id}/role", {"role": "operador"})
    assert role_of(database, "peao") == panel.ROLE_OPERATOR  # ainda sobra o chefe, entao vale

    # Agora promove de novo e SOBE so ele: com dois admins, nenhum comando further deve
    # deixar o painel com zero. Confere que o piso e sempre respeitado por baixo.
    post(admin, f"/users/{peao_id}/role", {"role": "admin"})
    peao_admin = login("peao", "senha-do-peao")
    chefe_id = id_of(database, "chefe")
    post(peao_admin, f"/users/{peao_id}/role", {"role": "operador"})
    post(peao_admin, f"/users/{chefe_id}/role", {"role": "operador"})
    assert peao_admin.get("/users").status_code == 200

    were_left = database.execute(
        "SELECT COUNT(*) FROM users WHERE role = ?", (panel.ROLE_ADMIN,)).fetchone()[0]
    assert were_left >= 1, f"o painel nunca pode ficar sem administrador (sobraram {were_left})"


# --------------------------------------------------- sessao morre com a conta

def test_sessao_morre_junto_com_a_conta(ana, admin, database, post, login):
    throwaway = login("ana", "senha12345")
    assert throwaway.get("/").status_code == 200, "logada, ve o painel"

    post(admin, f"/users/{ana}/delete")
    assert not exists(database, "ana")
    assert throwaway.get("/").status_code == 302, "a sessao dela cai no proximo clique"


# ---------------------------------------------- historico de jobs respeita o papel

SECRET = "SENHA-QUE-SO-O-ADMIN-PODE-VER"
ROTINA = "acao-de-rotina-do-operador"


@pytest.fixture
def server_with_jobs(database, admin):
    """Um servidor com um job de cada acao - metade restrita, metade nao.

    O job guarda a saida INTEIRA do que rodou. Como o operador leva 403 no console e no
    editor de arquivos, ele tambem nao pode ler o RESULTADO deles - nem abrindo o job
    pelo id, nem de relance no historico da tela do servidor.
    """
    with database:
        # Host que nao resolve: a tela do servidor tenta SSH e volta rapido com
        # "inacessivel" - o que se testa aqui e o historico, nao a conexao.
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


# -------------------------------------------- backup e upload seguem o mesmo corte

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
    """Criar copia e operacao (o operador pode). Restaurar, apagar e baixar destroem
    dado ou tiram o save do container - sao de administrador, como console e editor."""
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
    """O nome volta da tela e entra num comando remoto: o que nao casar com
    "<algo>.tar.gz" tem de morrer no painel, antes de chegar no shell do container."""
    resp = post(admin, f"/servers/{target_server}/backups/delete", {"nome": bad})
    assert resp.status_code == 400


# --------------------------------------------- moderar jogador e operacao, nao admin

def test_operador_modera_jogador_sem_precisar_de_admin(target_server, operator, post):
    """Expulsar/banir nao dao acesso ao container: quem ja pode reiniciar o servidor
    pode moderar quem esta nele. 302 (e nao 403) prova que o operador passou do papel -
    o que sobrar de erro daqui em diante e da validacao da acao, nao da permissao."""
    resp = post(operator, f"/servers/{target_server}/players/action",
                  {"acao": "kick", "jogador": "x"})
    assert resp.status_code == 302


def test_admin_tambem_modera_jogador(target_server, admin, post):
    resp = post(admin, f"/servers/{target_server}/players/action",
                  {"acao": "announce", "mensagem": "oi"})
    assert resp.status_code == 302


# -------------------------------------------- volta do login aceita so destino interno

@pytest.mark.parametrize("raw", [
    "//evil.example.com/x", "/\\evil.example.com", "https://evil.example.com",
    "http://evil.example.com", "evil", "", "/conta\r\nSet-Cookie: x=1",
])
def test_destino_de_login_recusa_endereco_de_fora(raw):
    """"/" no comeco nao basta: para o navegador "//host" e "/\\host" sao enderecos
    absolutos, e mandariam quem acabou de logar para outro site."""
    assert panel.safe_target(raw) == ""


@pytest.mark.parametrize("raw", ["/servers/1/config", "/users", "/"])
def test_destino_de_login_aceita_caminho_interno(raw):
    assert panel.safe_target(raw) == raw
