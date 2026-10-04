"""Entrar com a biometria do aparelho: as rotas de `blueprints/passkeys.py`, de ponta a ponta.

O aparelho e o `fake_passkey` (mesma matematica do celular); o painel e o de verdade, com
banco, sessao, CSRF e trava de tentativas.
"""
from __future__ import annotations

import hashlib

import fake_passkey as device
import pytest

from gamepanel import app as panel
from gamepanel.persistence.repositories import passkeys as passkeys_repo
from gamepanel.security import webauthn as wa

ORIGIN = "https://painel.exemplo.com"
RP_ID = "painel.exemplo.com"


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(panel, "WEBAUTHN_ORIGIN", ORIGIN)


def _csrf(cli) -> str:
    cli.get("/login")
    with cli.session_transaction() as sess:
        return sess.get("csrf", "")


def _uid(cli) -> int:
    # O id nao e sempre 1: a limpeza entre testes apaga as linhas, mas nao zera a sequencia.
    with cli.session_transaction() as sess:
        return sess["uid"]


def _post_json(cli, url, body):
    return cli.post(url, json=body, headers={"X-CSRF-Token": _csrf(cli)})


def _register(cli, post, password="senha-do-chefe", cred_id=device.CRED_ID, origin=ORIGIN):
    options = post(cli, "/account/passkey/options", {"password": password, "label": "meu celular"})
    assert options.status_code == 200, options.get_data(as_text=True)
    challenge = options.get_json()["publicKey"]["challenge"]
    client = device.client_data("webauthn.create", challenge, origin)
    return _post_json(cli, "/account/passkey", {
        "id": wa.b64url(cred_id), "clientDataJSON": wa.b64url(client),
        "attestationObject": wa.b64url(device.attestation(RP_ID, cred_id=cred_id))})


def _assertion(cli, count=1, handle=None):
    options = _post_json(cli, "/login/passkey/options", {})
    challenge = options.get_json()["publicKey"]["challenge"]
    client = device.client_data("webauthn.get", challenge, ORIGIN)
    data = device.auth_data(RP_ID, count=count)
    body = {"id": wa.b64url(device.CRED_ID), "clientDataJSON": wa.b64url(client),
            "authenticatorData": wa.b64url(data),
            "signature": wa.b64url(device.sign_es256(data + hashlib.sha256(client).digest())),
            "userHandle": handle or "", "next": "/history"}
    return body


def test_desligado_as_rotas_nao_existem_e_o_botao_nao_aparece(client):
    assert _post_json(client, "/login/passkey/options", {}).status_code == 404
    assert b"data-passkey-login" not in client.get("/login").data


def test_ligado_o_login_mostra_o_botao_escondido(client, enabled):
    page = client.get("/login").get_data(as_text=True)
    assert "data-passkey-login" in page
    assert 'hidden data-passkey-login' in page


def test_opcoes_de_login_nao_dizem_quem_existe(client, enabled):
    key = _post_json(client, "/login/passkey/options", {}).get_json()["publicKey"]
    assert key["rpId"] == RP_ID
    assert key["allowCredentials"] == []
    assert key["userVerification"] == "required"


def test_cadastrar_e_entrar(admin, client, enabled, post, database):
    response = _register(admin, post)
    assert response.status_code == 200, response.get_data(as_text=True)
    rows = passkeys_repo.for_user(database, _uid(admin))
    assert [r["label"] for r in rows] == ["meu celular"]
    assert "meu celular" in admin.get("/account").get_data(as_text=True)

    handle = database.execute("SELECT user_handle FROM passkeys").fetchone()["user_handle"]
    answer = _post_json(client, "/login/passkey", _assertion(client, handle=handle))
    assert answer.status_code == 200, answer.get_data(as_text=True)
    assert answer.get_json()["redirect"].endswith("/history")
    assert _uid(client) == _uid(admin)
    assert database.execute("SELECT sign_count FROM passkeys").fetchone()["sign_count"] == 1


def test_a_mesma_resposta_nao_entra_duas_vezes(admin, client, enabled, post):
    _register(admin, post)
    body = _assertion(client)
    assert _post_json(client, "/login/passkey", body).status_code == 200
    other = panel.app.test_client()
    assert _post_json(other, "/login/passkey", body).status_code == 401


def test_contador_que_nao_sobe_e_recusado(admin, client, enabled, post):
    _register(admin, post)
    assert _post_json(client, "/login/passkey", _assertion(client, count=5)).status_code == 200
    again = panel.app.test_client()
    assert _post_json(again, "/login/passkey", _assertion(again, count=5)).status_code == 401


def test_user_handle_de_outra_conta_e_recusado(admin, client, enabled, post):
    _register(admin, post)
    response = _post_json(client, "/login/passkey", _assertion(client, handle="outra-pessoa"))
    assert response.status_code == 401
    with client.session_transaction() as sess:
        assert "uid" not in sess


def test_passkey_desconhecida_conta_como_tentativa(client, enabled):
    for _ in range(panel.LOCKOUT_TRIES):
        assert _post_json(client, "/login/passkey", _assertion(client)).status_code == 401
    assert _post_json(client, "/login/passkey", _assertion(client)).status_code == 429


def test_cadastro_exige_a_senha(admin, enabled, post, database):
    response = post(admin, "/account/passkey/options", {"password": "errada"})
    assert response.status_code == 403
    assert "error" in response.get_json()
    assert passkeys_repo.for_user(database, _uid(admin)) == []


def test_cadastro_com_2fa_exige_o_codigo(admin_2fa, enabled, post):
    response = post(admin_2fa, "/account/passkey/options", {"password": "senha-do-chefe", "code": "000000"})
    assert response.status_code == 403


def test_cadastro_de_outra_origem_e_recusado(admin, enabled, post, database):
    response = _register(admin, post, origin="https://falso.exemplo.com")
    assert response.status_code == 400
    assert passkeys_repo.for_user(database, _uid(admin)) == []


def test_desafio_de_cadastro_de_outra_pessoa_nao_serve(admin, operator, enabled, post, database):
    options = post(admin, "/account/passkey/options", {"password": "senha-do-chefe"})
    challenge = options.get_json()["publicKey"]["challenge"]
    client = device.client_data("webauthn.create", challenge, ORIGIN)
    response = _post_json(operator, "/account/passkey", {
        "id": wa.b64url(device.CRED_ID), "clientDataJSON": wa.b64url(client),
        "attestationObject": wa.b64url(device.attestation(RP_ID))})
    assert response.status_code == 400
    assert database.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] == 0


def test_o_mesmo_aparelho_nao_entra_duas_vezes(admin, enabled, post):
    assert _register(admin, post).status_code == 200
    assert _register(admin, post).status_code == 409


def test_remover_so_o_proprio_aparelho(admin, operator, enabled, post, database):
    _register(admin, post)
    cred = wa.b64url(device.CRED_ID)
    post(operator, "/account/passkey/delete", {"id": cred})
    assert len(passkeys_repo.for_user(database, _uid(admin))) == 1
    assert post(admin, "/account/passkey/delete", {"id": cred}).status_code == 302
    assert passkeys_repo.for_user(database, _uid(admin)) == []


def test_apagar_o_usuario_leva_as_passkeys(admin, enabled, post, database):
    _register(admin, post)
    with database:
        database.execute("DELETE FROM users WHERE id = ?", (_uid(admin),))
    assert database.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0] == 0
