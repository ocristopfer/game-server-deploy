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

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


@pytest.fixture
def hora(monkeypatch):
    """Relogio controlado: o TOTP depende do instante, e o teste precisa andar de 30 em 30 s."""
    relogio = Clock()
    monkeypatch.setattr(panel.time, "time", lambda: relogio.agora)
    return relogio


def _codigo(segredo: str, relogio: Clock) -> str:
    return totp.code(segredo, totp.step_of(relogio.agora))


def _ativar(cli, postar, relogio: Clock) -> tuple[str, list[str]]:
    """Ativa o 2FA da conta logada em `cli`. Devolve (segredo, codigos de recuperacao)."""
    assert cli.get("/account/2fa").status_code == 200
    with cli.session_transaction() as sess:
        segredo = sess["totp_pendente"]
    resposta = postar(cli, "/account/2fa", {"codigo": _codigo(segredo, relogio)})
    assert resposta.status_code == 200, resposta.get_data(as_text=True)[:300]
    return segredo, RE_CODIGO.findall(resposta.get_data(as_text=True))


def _senha(cli, postar, user="chefe", senha="senha-do-chefe", proximo=""):
    cli.get("/login")
    url = "/login" + (f"?next={proximo}" if proximo else "")
    return postar(cli, url, {"username": user, "password": senha})


def _com_2fa(chefe, postar, hora):
    """Chefe logado ativa o 2FA; devolve (segredo, codigos)."""
    segredo, codigos = _ativar(chefe, postar, hora)
    hora.avancar(31)     # o codigo da ativacao ja foi gasto: o proximo login usa outro passo
    return segredo, codigos


# --- ativar ----------------------------------------------------------------------------------------

def test_tela_de_ativacao_mostra_a_chave_e_o_endereco_para_o_aplicativo(chefe, hora):
    html = chefe.get("/account/2fa").get_data(as_text=True)
    with chefe.session_transaction() as sess:
        segredo = sess["totp_pendente"]
    assert totp.group(segredo) in html
    assert "otpauth://totp/" in html
    assert "secret=" + segredo in html


def test_tela_de_ativacao_tem_o_qr_code_do_mesmo_endereco_mostrado(chefe, hora):
    """Nao testa a matematica do QR (isso e `test_qr.py` + `tools/verify-qr.py`, contra um
    leitor de verdade): so que a ROTA liga o SVG ao mesmo `otpauth://` que a chave e o link
    representam - um bug aqui deixaria a camera cadastrar uma conta diferente da que a
    pessoa confirma logo abaixo."""
    html = chefe.get("/account/2fa").get_data(as_text=True)
    with chefe.session_transaction() as sess:
        segredo = sess["totp_pendente"]
    endereco = totp.uri(segredo, "chefe", "Painel de Jogos")
    assert qr.svg(endereco, label="QR code da verificacao em duas etapas") in html


def test_usuario_no_limite_de_32_caracteres_nao_quebra_a_tela(postar, hora):
    panel.ensure_admin_user("a" * 32, "senha-bem-grande-123")
    cli = panel.app.test_client()
    _senha(cli, postar, "a" * 32, "senha-bem-grande-123")
    resposta = cli.get("/account/2fa")
    assert resposta.status_code == 200
    assert "<svg" in resposta.get_data(as_text=True)


def test_recarregar_a_tela_de_ativacao_mostra_a_mesma_chave(chefe, hora):
    chefe.get("/account/2fa")
    with chefe.session_transaction() as sess:
        primeira = sess["totp_pendente"]
    chefe.get("/account/2fa")
    with chefe.session_transaction() as sess:
        assert sess["totp_pendente"] == primeira


def test_codigo_errado_nao_liga_o_2fa(chefe, postar, hora):
    chefe.get("/account/2fa")
    resposta = postar(chefe, "/account/2fa", {"codigo": "000000"})
    assert resposta.status_code == 200
    assert "Codigo incorreto" in resposta.get_data(as_text=True)
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_codigo_certo_liga_e_mostra_os_codigos_de_recuperacao_uma_vez(chefe, postar, hora):
    segredo, codigos = _ativar(chefe, postar, hora)
    assert len(codigos) == totp.RECOVERY_CODES
    line = panel._connect().execute("SELECT * FROM users WHERE username = 'chefe'").fetchone()
    assert line["totp_enabled"] == 1
    assert line["totp_secret"] == segredo
    with chefe.session_transaction() as sess:
        assert "totp_pendente" not in sess
    # Nada em texto no banco: so os hashes.
    assert not any(c.replace("-", "") in line["totp_recovery"] for c in codigos)
    assert len(json.loads(line["totp_recovery"])) == totp.RECOVERY_CODES
    # E a tela de conta nunca mais mostra a chave nem os codigos.
    conta = chefe.get("/account").get_data(as_text=True)
    assert segredo not in conta
    assert not RE_CODIGO.search(conta)
    assert "ativada" in conta


def test_ja_ativado_a_tela_de_ativacao_volta_para_a_conta(chefe, postar, hora):
    _ativar(chefe, postar, hora)
    assert chefe.get("/account/2fa").headers["Location"].endswith("/account")


# --- entrar ------------------------------------------------------------------------------------------

def test_senha_certa_com_2fa_nao_abre_a_sessao(chefe, postar, hora, cliente):
    _com_2fa(chefe, postar, hora)
    resposta = _senha(cliente, postar)
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login/2fa")
    with cliente.session_transaction() as sess:
        assert "uid" not in sess, "so a senha nao pode virar sessao"
    assert cliente.get("/").status_code == 302
    assert "/login" in cliente.get("/").headers["Location"]
    assert cliente.get("/servers/new").status_code == 302


def test_codigo_certo_completa_o_login(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar)
    resposta = postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)})
    assert resposta.status_code == 302
    assert cliente.get("/").status_code == 200


def test_codigo_errado_nao_entra(chefe, postar, hora, cliente):
    _com_2fa(chefe, postar, hora)
    _senha(cliente, postar)
    resposta = postar(cliente, "/login/2fa", {"codigo": "123456"})
    assert resposta.status_code == 401
    assert cliente.get("/").status_code == 302


def test_codigo_usado_nao_serve_de_novo(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar)
    codigo = _codigo(segredo, hora)
    assert postar(cliente, "/login/2fa", {"codigo": codigo}).status_code == 302
    outro = panel.app.test_client()
    _senha(outro, postar)
    assert postar(outro, "/login/2fa", {"codigo": codigo}).status_code == 401, "repeticao"
    hora.avancar(30)
    assert postar(outro, "/login/2fa", {"codigo": _codigo(segredo, hora)}).status_code == 302


def test_codigo_da_ativacao_tambem_nao_serve_no_primeiro_login(chefe, postar, hora, cliente):
    """O codigo que ligou o 2FA foi visto na tela de ativacao: nao pode abrir a porta depois."""
    segredo, _ = _ativar(chefe, postar, hora)
    _senha(cliente, postar)
    assert postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)}).status_code == 401


def test_o_destino_pedido_antes_do_login_sobrevive_ao_segundo_passo(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar, proximo="/history")
    resposta = postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)})
    assert resposta.headers["Location"].endswith("/history")


def test_destino_de_fora_do_painel_continua_recusado_no_segundo_passo(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar, proximo="//evil.com")
    resposta = postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)})
    assert "evil.com" not in resposta.headers["Location"]


def test_tela_do_codigo_sem_passar_pela_senha_volta_para_o_login(cliente):
    resposta = cliente.get("/login/2fa")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login")


def test_a_verificacao_expira(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar)
    hora.avancar(panel.PRE_2FA_SEGUNDOS + 1)
    resposta = postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)})
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login")
    assert cliente.get("/").status_code == 302


def test_trava_por_usuario_bloqueia_ate_o_codigo_certo(chefe, postar, hora, cliente):
    segredo, _ = _com_2fa(chefe, postar, hora)
    for _ in range(panel.LOCKOUT_2FA_TENTATIVAS):
        _senha(cliente, postar)
        assert postar(cliente, "/login/2fa", {"codigo": "000000"}).status_code == 401
    _senha(cliente, postar)
    bloqueado = postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)})
    assert bloqueado.status_code == 429, "com a trava ligada nem o codigo certo passa"
    assert cliente.get("/").status_code == 302
    hora.avancar(panel.LOCKOUT_2FA_JANELA + 1)
    _senha(cliente, postar)
    assert postar(cliente, "/login/2fa", {"codigo": _codigo(segredo, hora)}).status_code == 302


def test_a_trava_e_do_usuario_e_nao_do_ip(chefe, postar, hora):
    """Trocar de IP nao devolve as tentativas: a chave e o nome do usuario."""
    _com_2fa(chefe, postar, hora)
    for _ in range(panel.LOCKOUT_2FA_TENTATIVAS):
        outro = panel.app.test_client()
        _senha(outro, postar)
        postar(outro, "/login/2fa", {"codigo": "000000"})
    novo = panel.app.test_client()
    _senha(novo, postar)
    assert postar(novo, "/login/2fa", {"codigo": "000000"}).status_code == 429


# --- recuperacao --------------------------------------------------------------------------------------

def test_codigo_de_recuperacao_entra_uma_vez_so(chefe, postar, hora, cliente):
    _, codigos = _com_2fa(chefe, postar, hora)
    _senha(cliente, postar)
    assert postar(cliente, "/login/2fa", {"codigo": codigos[0]}).status_code == 302
    assert cliente.get("/").status_code == 200
    outro = panel.app.test_client()
    _senha(outro, postar)
    assert postar(outro, "/login/2fa", {"codigo": codigos[0]}).status_code == 401
    assert postar(outro, "/login/2fa", {"codigo": codigos[1].upper().replace("-", " ")}).status_code == 302


# --- desativar e trocar codigos ---------------------------------------------------------------------

def test_desativar_pede_senha_e_codigo(chefe, postar, hora):
    segredo, _ = _com_2fa(chefe, postar, hora)
    postar(chefe, "/account/2fa/off", {"senha": "errada", "codigo": _codigo(segredo, hora)})
    postar(chefe, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": "000000"})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 1
    postar(chefe, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": _codigo(segredo, hora)})
    line = panel._connect().execute("SELECT * FROM users WHERE username = 'chefe'").fetchone()
    assert (line["totp_enabled"], line["totp_secret"], line["totp_recovery"]) == (0, "", "")


def test_desativar_aceita_um_codigo_de_recuperacao(chefe, postar, hora):
    _, codigos = _com_2fa(chefe, postar, hora)
    postar(chefe, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": codigos[0]})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_codigos_novos_invalidam_os_antigos(chefe, postar, hora, cliente):
    segredo, antigos = _com_2fa(chefe, postar, hora)
    resposta = postar(chefe, "/account/2fa/codes", {"senha": "senha-do-chefe", "codigo": _codigo(segredo, hora)})
    novos = RE_CODIGO.findall(resposta.get_data(as_text=True))
    assert len(novos) == totp.RECOVERY_CODES
    assert not set(novos) & set(antigos)
    _senha(cliente, postar)
    assert postar(cliente, "/login/2fa", {"codigo": antigos[0]}).status_code == 401
    assert postar(cliente, "/login/2fa", {"codigo": novos[0]}).status_code == 302


def test_codigos_novos_pedem_senha(chefe, postar, hora):
    segredo, antigos = _com_2fa(chefe, postar, hora)
    postar(chefe, "/account/2fa/codes", {"senha": "errada", "codigo": _codigo(segredo, hora)})
    line = panel._connect().execute("SELECT totp_recovery FROM users").fetchone()
    assert len(json.loads(line[0])) == totp.RECOVERY_CODES
    assert totp.hash_recovery_code(antigos[0]) in json.loads(line[0])


# --- admin e linha de comando -------------------------------------------------------------------------

def _dois_usuarios(postar, hora):
    """Admin logado e uma operadora `ana` com 2FA ativo. Devolve (admin, id da ana)."""
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    panel.ensure_admin_user("ana", "senha-da-ana", panel.ROLE_OPERADOR)
    ana = panel.app.test_client()
    _senha(ana, postar, "ana", "senha-da-ana")
    _ativar(ana, postar, hora)
    admin = panel.app.test_client()
    _senha(admin, postar)
    uid = panel._connect().execute("SELECT id FROM users WHERE username = 'ana'").fetchone()[0]
    return admin, uid


def test_admin_desliga_o_2fa_de_outra_pessoa(cliente, postar, hora):
    admin, uid = _dois_usuarios(postar, hora)
    assert "2FA" in admin.get("/users").get_data(as_text=True)
    assert postar(admin, f"/users/{uid}/2fa/off").status_code == 302
    line = panel._connect().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    assert (line["totp_enabled"], line["totp_secret"]) == (0, "")


def test_operador_nao_desliga_o_2fa_de_ninguem(cliente, postar, hora):
    admin, uid = _dois_usuarios(postar, hora)
    panel.ensure_admin_user("beto", "senha-do-beto", panel.ROLE_OPERADOR)
    beto = panel.app.test_client()
    _senha(beto, postar, "beto", "senha-do-beto")
    assert postar(beto, f"/users/{uid}/2fa/off").status_code == 403
    assert panel._connect().execute("SELECT totp_enabled FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1


def test_admin_nao_desliga_o_proprio_2fa_por_la(chefe, postar, hora):
    _com_2fa(chefe, postar, hora)
    uid = panel._connect().execute("SELECT id FROM users WHERE username = 'chefe'").fetchone()[0]
    postar(chefe, f"/users/{uid}/2fa/off")
    assert panel._connect().execute("SELECT totp_enabled FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1


def test_linha_de_comando_desliga_o_2fa(chefe, postar, hora):
    _com_2fa(chefe, postar, hora)
    output = subprocess.run([sys.executable, "-m", "gamepanel.app", "--reset-2fa", "chefe"],
                           env=ENV_COM_SRC, capture_output=True, text=True, cwd=ADMIN, timeout=60)
    assert output.returncode == 0, output.stderr
    assert "desligado" in output.stdout
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 0


def test_linha_de_comando_recusa_usuario_que_nao_existe(banco):
    output = subprocess.run([sys.executable, "-m", "gamepanel.app", "--reset-2fa", "ninguem"],
                           env=ENV_COM_SRC, capture_output=True, text=True, cwd=ADMIN, timeout=60)
    assert output.returncode != 0
    assert "nao existe" in output.stderr


# --- exigir para todos ---------------------------------------------------------------------------------

def test_com_2fa_obrigatorio_quem_nao_ativou_so_alcanca_a_ativacao(chefe, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    resposta = chefe.get("/")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/account/2fa")
    assert chefe.get("/account/2fa").status_code == 200
    assert chefe.get("/servers/new").status_code == 302
    assert chefe.get("/health").status_code == 200


def test_com_2fa_obrigatorio_a_api_responde_403_em_json(chefe, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    resposta = chefe.get("/api/v1/status")
    assert resposta.status_code == 403
    assert "duas etapas" in resposta.get_json()["error"]


def test_com_2fa_obrigatorio_ativar_libera_o_painel(chefe, postar, hora, monkeypatch):
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    _ativar(chefe, postar, hora)
    assert chefe.get("/").status_code == 200


def test_com_2fa_obrigatorio_nao_da_para_desativar(chefe, postar, hora, monkeypatch):
    segredo, _ = _com_2fa(chefe, postar, hora)
    monkeypatch.setattr(panel, "REQUIRE_2FA", True)
    postar(chefe, "/account/2fa/off", {"senha": "senha-do-chefe", "codigo": _codigo(segredo, hora)})
    assert panel._connect().execute("SELECT totp_enabled FROM users").fetchone()[0] == 1
    assert "exige" in chefe.get("/account").get_data(as_text=True)


def test_sem_a_exigencia_o_painel_segue_como_antes(chefe):
    assert chefe.get("/").status_code == 200


def test_login_de_quem_nao_ativou_continua_direto(chefe, postar, cliente):
    resposta = _senha(cliente, postar)
    assert resposta.status_code == 302
    assert not resposta.headers["Location"].endswith("/login/2fa")
    assert cliente.get("/").status_code == 200


def test_migracao_criou_as_colunas(banco):
    colunas = {r["name"] for r in panel._connect().execute("PRAGMA table_info(users)")}
    assert {"totp_secret", "totp_enabled", "totp_last_step", "totp_recovery"} <= colunas


def test_conta_avisa_admin_quando_o_broker_esta_ligado(chefe, monkeypatch):
    monkeypatch.setattr(panel, "ALLOW_BROKER", True)
    assert "broker" in chefe.get("/account").get_data(as_text=True)
