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


def papel(banco, username: str) -> str:
    row = banco.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    return row["role"] if row else ""


def existe(banco, username: str) -> bool:
    return banco.execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None


def id_de(banco, username: str) -> int:
    return banco.execute(
        "SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


# --------------------------------------------------------- bootstrap pela CLI

def test_usuario_criado_pela_cli_e_admin(banco):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    assert papel(banco, "chefe") == panel.ROLE_ADMIN


def test_redefinir_senha_pela_cli_nao_mexe_no_papel(banco):
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    panel.ensure_admin_user("chefe", "outra-senha")  # so redefine a senha
    assert papel(banco, "chefe") == panel.ROLE_ADMIN


def test_papel_escolhido_na_cli_vale(banco):
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERADOR)
    assert papel(banco, "peao") == panel.ROLE_OPERADOR


# ---------------------------------------------- operador nao chega no que da root

def test_operador_abre_as_telas_proprias(peao):
    assert peao.get("/").status_code == 200
    assert peao.get("/ssh-key").status_code == 200
    assert peao.get("/account").status_code == 200


@pytest.mark.parametrize("rota", [
    "/usuarios", "/servers/new", "/servers/1/edit", "/servers/1/terminal",
    "/servers/1/console", "/servers/1/files", "/servers/1/players/descobrir",
])
def test_operador_leva_403_no_que_da_root(peao, rota):
    """`admin_required` barra pelo papel ANTES de olhar se o servidor existe -
    por isso o 403 vale mesmo com o banco vazio (nao precisa existir servidor 1)."""
    assert peao.get(rota).status_code == 403


def test_operador_nao_cria_usuario_nem_remove_servidor(peao, banco, postar):
    resp = postar(peao, "/usuarios", {"username": "invasor", "new": "senha12345",
                                      "confirm": "senha12345", "role": "admin"})
    assert resp.status_code == 403
    assert not existe(banco, "invasor")
    assert postar(peao, "/servers/1/delete").status_code == 403


# ------------------------------------------------------- admin gerencia usuarios

def test_admin_abre_a_tela_de_usuarios(chefe):
    assert chefe.get("/usuarios").status_code == 200


def test_admin_cria_usuario_pela_tela(chefe, banco, postar):
    postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    assert papel(banco, "ana") == panel.ROLE_OPERADOR


def test_senha_curta_nao_cria_usuario(chefe, banco, postar):
    postar(chefe, "/usuarios", {"username": "bob", "new": "curta",
                                "confirm": "curta", "role": "operador"})
    assert not existe(banco, "bob")


def test_confirmacao_errada_nao_cria_usuario(chefe, banco, postar):
    postar(chefe, "/usuarios", {"username": "bob", "new": "senha12345",
                                "confirm": "outra12345", "role": "operador"})
    assert not existe(banco, "bob")


def test_nome_invalido_nao_cria_usuario(chefe, banco, postar):
    postar(chefe, "/usuarios", {"username": "Bob Silva", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    assert not existe(banco, "Bob Silva")


def test_nome_repetido_nao_sobrescreve_o_papel_de_quem_ja_existe(chefe, banco, postar):
    postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "admin"})
    assert papel(banco, "ana") == panel.ROLE_OPERADOR


@pytest.fixture
def ana(chefe, banco, postar) -> int:
    """Uma operadora cadastrada pela tela. Devolve o id dela."""
    postar(chefe, "/usuarios", {"username": "ana", "new": "senha12345",
                                "confirm": "senha12345", "role": "operador"})
    return id_de(banco, "ana")


def test_promover_funciona(ana, chefe, banco, postar):
    postar(chefe, f"/usuarios/{ana}/papel", {"role": "admin"})
    assert papel(banco, "ana") == panel.ROLE_ADMIN


def test_ninguem_rebaixa_a_si_mesmo(chefe, banco, postar):
    chefe_id = id_de(banco, "chefe")
    postar(chefe, f"/usuarios/{chefe_id}/papel", {"role": "operador"})
    assert papel(banco, "chefe") == panel.ROLE_ADMIN


def test_rebaixar_outro_admin_funciona_quando_sobra_admin(ana, chefe, banco, postar):
    postar(chefe, f"/usuarios/{ana}/papel", {"role": "admin"})
    postar(chefe, f"/usuarios/{ana}/papel", {"role": "operador"})
    assert papel(banco, "ana") == panel.ROLE_OPERADOR


def test_ninguem_remove_a_propria_conta(chefe, banco, postar):
    chefe_id = id_de(banco, "chefe")
    postar(chefe, f"/usuarios/{chefe_id}/remover")
    assert existe(banco, "chefe")


def test_reset_de_senha_pelo_admin_funciona(ana, chefe, postar, entrar):
    postar(chefe, f"/usuarios/{ana}/senha", {"new": "senha-nova-1", "confirm": "senha-nova-1"})
    entrar("ana", "senha-nova-1")  # levanta AssertionError se a senha nao tiver valido


# ------------------------------------------------------- ultimo admin nao some

def test_ultimo_administrador_nao_pode_ser_rebaixado(chefe, peao, banco, postar, entrar):
    """So sobrou o chefe: nem outro admin promovido consegue tirar o ultimo que resta
    (nem o dele proprio, nem o do colega - ver os dois testes anteriores)."""
    peao_id = id_de(banco, "peao")

    # Promove o operador para poder testar "admin rebaixa admin colega".
    postar(chefe, f"/usuarios/{peao_id}/papel", {"role": "admin"})
    assert papel(banco, "peao") == panel.ROLE_ADMIN
    postar(chefe, f"/usuarios/{peao_id}/papel", {"role": "operador"})
    assert papel(banco, "peao") == panel.ROLE_OPERADOR  # ainda sobra o chefe, entao vale

    # Agora promove de novo e SOBE so ele: com dois admins, nenhum comando further deve
    # deixar o painel com zero. Confere que o piso e sempre respeitado por baixo.
    postar(chefe, f"/usuarios/{peao_id}/papel", {"role": "admin"})
    peao_admin = entrar("peao", "senha-do-peao")
    chefe_id = id_de(banco, "chefe")
    postar(peao_admin, f"/usuarios/{peao_id}/papel", {"role": "operador"})
    postar(peao_admin, f"/usuarios/{chefe_id}/papel", {"role": "operador"})
    assert peao_admin.get("/usuarios").status_code == 200

    sobraram = banco.execute(
        "SELECT COUNT(*) FROM users WHERE role = ?", (panel.ROLE_ADMIN,)).fetchone()[0]
    assert sobraram >= 1, f"o painel nunca pode ficar sem administrador (sobraram {sobraram})"


# --------------------------------------------------- sessao morre com a conta

def test_sessao_morre_junto_com_a_conta(ana, chefe, banco, postar, entrar):
    descartavel = entrar("ana", "senha12345")
    assert descartavel.get("/").status_code == 200, "logada, ve o painel"

    postar(chefe, f"/usuarios/{ana}/remover")
    assert not existe(banco, "ana")
    assert descartavel.get("/").status_code == 302, "a sessao dela cai no proximo clique"


# ---------------------------------------------- historico de jobs respeita o papel

SEGREDO = "SENHA-QUE-SO-O-ADMIN-PODE-VER"
ROTINA = "acao-de-rotina-do-operador"


@pytest.fixture
def servidor_com_jobs(banco, chefe):
    """Um servidor com um job de cada acao - metade restrita, metade nao.

    O job guarda a saida INTEIRA do que rodou. Como o operador leva 403 no console e no
    editor de arquivos, ele tambem nao pode ler o RESULTADO deles - nem abrindo o job
    pelo id, nem de relance no historico da tela do servidor.
    """
    with banco:
        # Host que nao resolve: a tela do servidor tenta SSH e volta rapido com
        # "inacessivel" - o que se testa aqui e o historico, nao a conexao.
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root', 'jogo.service', ?)",
            (panel.now_iso(),))
    sid = banco.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]

    jobs = {}
    with banco:
        for action in ("shell", "terminal", "edit-file", "delete-file", "download-file",
                     "start", "edit-config"):
            marca = SEGREDO if action in panel.JOB_ACTIONS_ADMIN else ROTINA
            cur = banco.execute(
                "INSERT INTO jobs (server_id, target, action, status, exit_code, output,"
                " command, username, created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "root@alvo", action, "ok", 0, marca, marca, "chefe",
                 panel.now_iso(), panel.now_iso()))
            jobs[action] = cur.lastrowid
    return sid, jobs


@pytest.mark.parametrize("action", ["shell", "terminal", "edit-file", "delete-file",
                                  "download-file", "start", "edit-config"])
def test_apenas_admin_le_jobs_de_acao_restrita(servidor_com_jobs, chefe, peao, action):
    _sid, jobs = servidor_com_jobs
    jid = jobs[action]
    esperado = 403 if action in panel.JOB_ACTIONS_ADMIN else 200
    assert peao.get(f"/jobs/{jid}").status_code == esperado
    assert peao.get(f"/api/jobs/{jid}").status_code == esperado
    assert chefe.get(f"/jobs/{jid}").status_code == 200


def test_admin_continua_lendo_a_saida_do_console(servidor_com_jobs, chefe):
    _sid, jobs = servidor_com_jobs
    corpo = chefe.get(f"/jobs/{jobs['shell']}").get_data(as_text=True)
    assert SEGREDO in corpo


def test_historico_na_tela_do_servidor_esconde_o_restrito_do_operador(servidor_com_jobs, peao):
    sid, _jobs = servidor_com_jobs
    resp = peao.get(f"/servers/{sid}")
    assert resp.status_code == 200
    pagina = resp.get_data(as_text=True)
    assert SEGREDO not in pagina, "comando do console nao aparece no historico do operador"
    assert ROTINA in pagina, "o que ele pode fazer continua visivel"


def test_historico_na_tela_do_servidor_e_completo_para_o_admin(servidor_com_jobs, chefe):
    sid, _jobs = servidor_com_jobs
    pagina = chefe.get(f"/servers/{sid}").get_data(as_text=True)
    assert SEGREDO in pagina


# -------------------------------------------- backup e upload seguem o mesmo corte

@pytest.fixture
def servidor_alvo(banco, chefe) -> int:
    with banco:
        banco.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, config_path,"
            " created_at) VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root',"
            " 'jogo.service', '/opt/game/Saved', ?)", (panel.now_iso(),))
    return banco.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


def test_sem_backup_paths_vale_a_pasta_de_configuracao(servidor_alvo, banco):
    alvo = banco.execute("SELECT * FROM servers WHERE id = ?", (servidor_alvo,)).fetchone()
    assert panel.backup_paths(alvo) == ["/opt/game/Saved"]
    assert panel.backup_prefix(alvo) == "jogo", "o prefixo sai da unidade systemd"


def test_backup_paths_preenchido_manda_no_config_path(servidor_alvo, banco):
    with banco:
        banco.execute(
            "UPDATE servers SET backup_paths = ? WHERE id = ?",
            ("/opt/game/Saved/SaveGames\n/opt/game/config.ini", servidor_alvo))
    alvo = banco.execute("SELECT * FROM servers WHERE id = ?", (servidor_alvo,)).fetchone()
    assert panel.backup_paths(alvo) == [
        "/opt/game/Saved/SaveGames", "/opt/game/config.ini"]


def test_operador_ve_backups_e_dispara_mas_nao_gerencia(servidor_alvo, peao, postar):
    """Criar copia e operacao (o operador pode). Restaurar, apagar e baixar destroem
    dado ou tiram o save do container - sao de administrador, como console e editor."""
    assert peao.get(f"/servers/{servidor_alvo}/backups").status_code == 200
    assert postar(peao, f"/servers/{servidor_alvo}/backups/criar").status_code == 302

    name = {"nome": "jogo-20260101-000000.tar.gz"}
    assert postar(peao, f"/servers/{servidor_alvo}/backups/restaurar", name).status_code == 403
    assert postar(peao, f"/servers/{servidor_alvo}/backups/remover", name).status_code == 403
    assert peao.get(
        f"/servers/{servidor_alvo}/backups/baixar?nome=jogo-20260101-000000.tar.gz"
    ).status_code == 403
    assert postar(peao, f"/servers/{servidor_alvo}/files/upload").status_code == 403


@pytest.mark.parametrize("ruim", [
    "../../etc/passwd", "/etc/shadow", "x.tar.gz; rm -rf /", "sem-extensao",
    "..-..tar.gz", "",
])
def test_nome_de_backup_torto_e_recusado_mesmo_para_admin(servidor_alvo, chefe, postar, ruim):
    """O nome volta da tela e entra num comando remoto: o que nao casar com
    "<algo>.tar.gz" tem de morrer no painel, antes de chegar no shell do container."""
    resp = postar(chefe, f"/servers/{servidor_alvo}/backups/remover", {"nome": ruim})
    assert resp.status_code == 400


# --------------------------------------------- moderar jogador e operacao, nao admin

def test_operador_modera_jogador_sem_precisar_de_admin(servidor_alvo, peao, postar):
    """Expulsar/banir nao dao acesso ao container: quem ja pode reiniciar o servidor
    pode moderar quem esta nele. 302 (e nao 403) prova que o operador passou do papel -
    o que sobrar de erro daqui em diante e da validacao da acao, nao da permissao."""
    resp = postar(peao, f"/servers/{servidor_alvo}/players/acao",
                  {"acao": "kick", "jogador": "x"})
    assert resp.status_code == 302


def test_admin_tambem_modera_jogador(servidor_alvo, chefe, postar):
    resp = postar(chefe, f"/servers/{servidor_alvo}/players/acao",
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


@pytest.mark.parametrize("raw", ["/servers/1/config", "/usuarios", "/"])
def test_destino_de_login_aceita_caminho_interno(raw):
    assert panel.safe_target(raw) == raw
