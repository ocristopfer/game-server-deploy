"""Segundo fator do login (TOTP): ativar, entrar, recuperar, travar, exigir e resetar.

O que mais importa aqui e o que NAO pode acontecer: senha certa abrindo sessao quando ha 2FA,
codigo servindo duas vezes, chute ilimitado, e uma sessao esquecida desligando a protecao.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gamepanel import app as panel
from gamepanel.security import qr, totp

ADMIN = Path(__file__).resolve().parent
RAIZ = ADMIN.parent.parent
# O subprocesso e um Python novo, sem o sys.path.insert do conftest.py da raiz nem a
# instalacao editavel do `uv sync` necessariamente presente (o container de dev do painel
# so tem python3-pytest do apt) - precisa do PYTHONPATH explicito pra achar `gamepanel`.
ENV_COM_SRC = os.environ | {"PYTHONPATH": str(RAIZ / "src")}
RE_CODIGO = re.compile(r"\b[0-9a-f]{5}-[0-9a-f]{5}\b")


class Clock:
    def __init__(self) -> None:
        self.agora = time.time()

    def advance(self, segundos: float) -> None:
        self.agora += segundos


@pytest.fixture
def clock_at(monkeypatch):
    """Relogio controlado: o TOTP depende do instante, e o teste precisa andar de 30 em 30 s."""
    clock_of = Clock()
    monkeypatch.setattr(panel.time, "time", lambda: clock_of.agora)
    return clock_of


def _code(segredo: str, relogio: Clock) -> str:
    return totp.code(segredo, totp.step_of(relogio.agora))


def _enable_2fa(cli, post, relogio: Clock) -> tuple[str, list[str]]:
    """Ativa o 2FA da conta logada em `cli`. Devolve (segredo, codigos de recuperacao)."""
    assert cli.get("/account/2fa").status_code == 200
    with cli.session_transaction() as sess:
        secret = sess["totp_pendente"]
    response = post(cli, "/account/2fa", {"codigo": _code(secret, relogio)})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    return secret, RE_CODIGO.findall(response.get_data(as_text=True))


def _password(cli, post, user="chefe", senha="senha-do-chefe", proximo=""):
    cli.get("/login")
    url = "/login" + (f"?next={proximo}" if proximo else "")
    return post(cli, url, {"username": user, "password": senha})


def _with_2fa(admin, post, clock_at):
    """Chefe logado ativa o 2FA; devolve (segredo, codigos)."""
    secret, codes = _enable_2fa(admin, post, clock_at)
    clock_at.advance(31)     # o codigo da ativacao ja foi gasto: o proximo login usa outro passo
    return secret, codes


# --- ativar ----------------------------------------------------------------------------------------

def test_tela_de_ativacao_mostra_a_chave_e_o_endereco_para_o_aplicativo(admin, clock_at):
    html = admin.get("/account/2fa").get_data(as_text=True)
    with admin.session_transaction() as sess:
        secret = sess["totp_pendente"]
    assert totp.group(secret) in html
    assert "otpauth://totp/" in html
    assert "secret=" + secret in html


def test_tela_de_ativacao_tem_o_qr_code_do_mesmo_endereco_mostrado(admin, clock_at):
    """Nao testa a matematica do QR (isso e `test_qr.py` + `tools/verify-qr.py`, contra um
    leitor de verdade): so que a ROTA liga o SVG ao mesmo `otpauth://` que a chave e o link
    representam - um bug aqui deixaria a camera cadastrar uma conta diferente da que a
    pessoa confirma logo abaixo."""
    html = admin.get("/account/2fa").get_data(as_text=True)
    with admin.session_transaction() as sess:
        secret = sess["totp_pendente"]
    address = totp.uri(secret, "chefe", "Painel de Jogos")
    assert qr.svg(address, label="QR code da verificacao em duas etapas") in html


def test_usuario_no_limite_de_32_caracteres_nao_quebra_a_tela(post, clock_at):
    panel.ensure_admin_user("a" * 32, "senha-bem-grande-123")
    cli = panel.app.test_client()
    _password(cli, post, "a" * 32, "senha-bem-grande-123")
    response = cli.get("/account/2fa")
    assert response.status_code == 200
    assert "<svg" in response.get_data(as_text=True)


def test_recarregar_a_tela_de_ativacao_mostra_a_mesma_chave(admin, clock_at):
    admin.get("/account/2fa")
    with admin.session_transaction() as sess:
        first_one = sess["totp_pendente"]
    admin.get("/account/2fa")
    with admin.session_transaction() as sess:
        assert sess["totp_pendente"] == first_one


def test_codigo_errado_nao_liga_o_2fa(admin, post, clock_at):
    admin.get("/account/2fa")
    response = post(admin, "/account/2fa", {"codigo": "000000"})
    assert response.status_code == 200
    assert "Codigo incorreto" in response.get_data(as_text=True)
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_codigo_certo_liga_e_mostra_os_codigos_de_recuperacao_uma_vez(admin, post, clock_at):
    secret, codes = _enable_2fa(admin, post, clock_at)
    assert len(codes) == totp.RECOVERY_CODES
    line = panel._connect().execute("SELECT * FROM users WHERE username = 'chefe'").fetchone()
    assert line["totp_enabled"] == 1
    assert line["totp_secret"] == secret
    with admin.session_transaction() as sess:
        assert "totp_pendente" not in sess
    # Nada em texto no banco: so os hashes.
    assert not any(c.replace("-", "") in line["totp_recovery"] for c in codes)
    assert len(json.loads(line["totp_recovery"])) == totp.RECOVERY_CODES
    # E a tela de conta nunca mais mostra a chave nem os codigos.
    account = admin.get("/account").get_data(as_text=True)
    assert secret not in account
    assert not RE_CODIGO.search(account)
    assert "ativada" in account


def test_ja_ativado_a_tela_de_ativacao_volta_para_a_conta(admin, post, clock_at):
    _enable_2fa(admin, post, clock_at)
    assert admin.get("/account/2fa").headers["Location"].endswith("/account")


# --- entrar ------------------------------------------------------------------------------------------

def test_senha_certa_com_2fa_nao_abre_a_sessao(admin, post, clock_at, client):
    _with_2fa(admin, post, clock_at)
    response = _password(client, post)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login/2fa")
    with client.session_transaction() as sess:
        assert "uid" not in sess, "so a senha nao pode virar sessao"
    assert client.get("/").status_code == 302
    assert "/login" in client.get("/").headers["Location"]
    assert client.get("/servers/new").status_code == 302


def test_codigo_certo_completa_o_login(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    _password(client, post)
    response = post(client, "/login/2fa", {"codigo": _code(secret, clock_at)})
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_codigo_errado_nao_entra(admin, post, clock_at, client):
    _with_2fa(admin, post, clock_at)
    _password(client, post)
    response = post(client, "/login/2fa", {"codigo": "123456"})
    assert response.status_code == 401
    assert client.get("/").status_code == 302


def test_codigo_usado_nao_serve_de_novo(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    _password(client, post)
    code = _code(secret, clock_at)
    assert post(client, "/login/2fa", {"codigo": code}).status_code == 302
    other = panel.app.test_client()
    _password(other, post)
    assert post(other, "/login/2fa", {"codigo": code}).status_code == 401, "repeticao"
    clock_at.advance(30)
    assert post(other, "/login/2fa", {"codigo": _code(secret, clock_at)}).status_code == 302


def test_codigo_da_ativacao_tambem_nao_serve_no_primeiro_login(admin, post, clock_at, client):
    """O codigo que ligou o 2FA foi visto na tela de ativacao: nao pode abrir a porta depois."""
    secret, _ = _enable_2fa(admin, post, clock_at)
    _password(client, post)
    assert post(client, "/login/2fa", {"codigo": _code(secret, clock_at)}).status_code == 401


def test_o_destino_pedido_antes_do_login_sobrevive_ao_segundo_passo(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    _password(client, post, proximo="/history")
    response = post(client, "/login/2fa", {"codigo": _code(secret, clock_at)})
    assert response.headers["Location"].endswith("/history")


def test_destino_de_fora_do_painel_continua_recusado_no_segundo_passo(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    _password(client, post, proximo="//evil.com")
    response = post(client, "/login/2fa", {"codigo": _code(secret, clock_at)})
    assert "evil.com" not in response.headers["Location"]


def test_tela_do_codigo_sem_passar_pela_senha_volta_para_o_login(client):
    response = client.get("/login/2fa")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_a_verificacao_expira(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    _password(client, post)
    clock_at.advance(panel.PRE_2FA_SECONDS + 1)
    response = post(client, "/login/2fa", {"codigo": _code(secret, clock_at)})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert client.get("/").status_code == 302


def test_trava_por_usuario_bloqueia_ate_o_codigo_certo(admin, post, clock_at, client):
    secret, _ = _with_2fa(admin, post, clock_at)
    for _ in range(panel.LOCKOUT_2FA_TRIES):
        _password(client, post)
        assert post(client, "/login/2fa", {"codigo": "000000"}).status_code == 401
    _password(client, post)
    blocked = post(client, "/login/2fa", {"codigo": _code(secret, clock_at)})
    assert blocked.status_code == 429, "com a trava ligada nem o codigo certo passa"
    assert client.get("/").status_code == 302
    clock_at.advance(panel.LOCKOUT_2FA_WINDOW + 1)
    _password(client, post)
    assert post(client, "/login/2fa", {"codigo": _code(secret, clock_at)}).status_code == 302


def test_a_trava_e_do_usuario_e_nao_do_ip(admin, post, clock_at):
    """Trocar de IP nao devolve as tentativas: a chave e o nome do usuario."""
    _with_2fa(admin, post, clock_at)
    for _ in range(panel.LOCKOUT_2FA_TRIES):
        other = panel.app.test_client()
        _password(other, post)
        post(other, "/login/2fa", {"codigo": "000000"})
    fresh = panel.app.test_client()
    _password(fresh, post)
    assert post(fresh, "/login/2fa", {"codigo": "000000"}).status_code == 429


# --- recuperacao --------------------------------------------------------------------------------------

def test_codigo_de_recuperacao_entra_uma_vez_so(admin, post, clock_at, client):
    _, codes = _with_2fa(admin, post, clock_at)
    _password(client, post)
    assert post(client, "/login/2fa", {"codigo": codes[0]}).status_code == 302
    assert client.get("/").status_code == 200
    other = panel.app.test_client()
    _password(other, post)
    assert post(other, "/login/2fa", {"codigo": codes[0]}).status_code == 401
    assert post(other, "/login/2fa", {"codigo": codes[1].upper().replace("-", " ")}).status_code == 302


# --- desativar e trocar codigos ---------------------------------------------------------------------

def test_desativar_pede_senha_e_codigo(admin, post, clock_at):
    secret, _ = _with_2fa(admin, post, clock_at)
    post(admin, "/account/2fa/off", {"senha": "errada", "codigo": _code(secret, clock_at)})
    post(admin, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": "000000"})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 1
    post(admin, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": _code(secret, clock_at)})
    line = panel._connect().execute("SELECT * FROM users WHERE username = 'chefe'").fetchone()
    assert (line["totp_enabled"], line["totp_secret"], line["totp_recovery"]) == (0, "", "")


def test_desativar_aceita_um_codigo_de_recuperacao(admin, post, clock_at):
    _, codes = _with_2fa(admin, post, clock_at)
    post(admin, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": codes[0]})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_codigos_novos_invalidam_os_antigos(admin, post, clock_at, client):
    secret, old_ones = _with_2fa(admin, post, clock_at)
    response = post(admin, "/account/2fa/codes", {"senha": "senha-do-chefe", "codigo": _code(secret, clock_at)})
    fresh_ones = RE_CODIGO.findall(response.get_data(as_text=True))
    assert len(fresh_ones) == totp.RECOVERY_CODES
    assert not set(fresh_ones) & set(old_ones)
    _password(client, post)
    assert post(client, "/login/2fa", {"codigo": old_ones[0]}).status_code == 401
    assert post(client, "/login/2fa", {"codigo": fresh_ones[0]}).status_code == 302


def test_codigos_novos_pedem_senha(admin, post, clock_at):
    secret, old_ones = _with_2fa(admin, post, clock_at)
    post(admin, "/account/2fa/codes", {"senha": "errada", "codigo": _code(secret, clock_at)})
    line = panel._connect().execute("SELECT totp_recovery FROM users").fetchone()
    assert len(json.loads(line[0])) == totp.RECOVERY_CODES
    assert totp.hash_recovery_code(old_ones[0]) in json.loads(line[0])


# --- admin e linha de comando -------------------------------------------------------------------------

def _two_users(post, clock_at):
    """Admin logado e uma operadora `ana` com 2FA ativo. Devolve (admin, id da ana)."""
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    panel.ensure_admin_user("ana", "senha-da-ana", panel.ROLE_OPERATOR)
    ana = panel.app.test_client()
    _password(ana, post, "ana", "senha-da-ana")
    _enable_2fa(ana, post, clock_at)
    admin = panel.app.test_client()
    _password(admin, post)
    uid = panel._connect().execute("SELECT id FROM users WHERE username = 'ana'").fetchone()[0]
    return admin, uid


def test_admin_desliga_o_2fa_de_outra_pessoa(client, post, clock_at):
    admin, uid = _two_users(post, clock_at)
    assert "2FA" in admin.get("/users").get_data(as_text=True)
    assert post(admin, f"/users/{uid}/2fa/off").status_code == 302
    line = panel._connect().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    assert (line["totp_enabled"], line["totp_secret"]) == (0, "")


def test_operador_nao_desliga_o_2fa_de_ninguem(client, post, clock_at):
    admin, uid = _two_users(post, clock_at)
    panel.ensure_admin_user("beto", "senha-do-beto", panel.ROLE_OPERATOR)
    beto = panel.app.test_client()
    _password(beto, post, "beto", "senha-do-beto")
    assert post(beto, f"/users/{uid}/2fa/off").status_code == 403
    assert panel._connect().execute("SELECT totp_enabled FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1


def test_admin_nao_desliga_o_proprio_2fa_por_la(admin, post, clock_at):
    _with_2fa(admin, post, clock_at)
    uid = panel._connect().execute("SELECT id FROM users WHERE username = 'chefe'").fetchone()[0]
    post(admin, f"/users/{uid}/2fa/off")
    assert panel._connect().execute("SELECT totp_enabled FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1


def test_linha_de_comando_desliga_o_2fa(admin, post, clock_at):
    _with_2fa(admin, post, clock_at)
    output = subprocess.run([sys.executable, "-m", "gamepanel.app", "--reset-2fa", "chefe"],
                           env=ENV_COM_SRC, capture_output=True, text=True, cwd=ADMIN, timeout=60)
    assert output.returncode == 0, output.stderr
    assert "desligado" in output.stdout
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_linha_de_comando_recusa_usuario_que_nao_existe(database):
    output = subprocess.run([sys.executable, "-m", "gamepanel.app", "--reset-2fa", "ninguem"],
                           env=ENV_COM_SRC, capture_output=True, text=True, cwd=ADMIN, timeout=60)
    assert output.returncode != 0
    assert "nao existe" in output.stderr


# --- exigir para todos ---------------------------------------------------------------------------------

def test_com_2fa_obrigatorio_quem_nao_ativou_so_alcanca_a_ativacao(admin, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    response = admin.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account/2fa")
    assert admin.get("/account/2fa").status_code == 200
    assert admin.get("/servers/new").status_code == 302
    assert admin.get("/health").status_code == 200


def test_com_2fa_obrigatorio_a_api_responde_403_em_json(admin, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    response = admin.get("/api/v1/status")
    assert response.status_code == 403
    assert "duas etapas" in response.get_json()["error"]


def test_com_2fa_obrigatorio_ativar_libera_o_painel(admin, post, clock_at, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    _enable_2fa(admin, post, clock_at)
    assert admin.get("/").status_code == 200


def test_com_2fa_obrigatorio_nao_da_para_desativar(admin, post, clock_at, monkeypatch):
    secret, _ = _with_2fa(admin, post, clock_at)
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    post(admin, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": _code(secret, clock_at)})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 1
    assert "exige" in admin.get("/account").get_data(as_text=True)


def test_sem_a_exigencia_o_painel_segue_como_antes(admin):
    assert admin.get("/").status_code == 200


def test_login_de_quem_nao_ativou_continua_direto(admin, post, client):
    response = _password(client, post)
    assert response.status_code == 302
    assert not response.headers["Location"].endswith("/login/2fa")
    assert client.get("/").status_code == 200


def test_migracao_criou_as_colunas(database):
    columns = {r["name"] for r in panel._connect().execute("PRAGMA table_info(users)")}
    assert {"totp_secret", "totp_enabled", "totp_last_step", "totp_recovery"} <= columns


def test_conta_avisa_admin_quando_o_broker_esta_ligado(admin, monkeypatch):
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    assert "broker" in admin.get("/account").get_data(as_text=True)
