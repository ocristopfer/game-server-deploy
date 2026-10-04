"""Entrar com a biometria do aparelho (passkey / WebAuthn) e cadastrar os aparelhos.

A verificacao mora em `security/webauthn.py`; aqui so o HTTP. As duas cerimonias tem dois
passos cada: o navegador pede as OPCOES (com um desafio novo), o aparelho assina, e a resposta
volta para ser conferida. Tudo e JSON porque e o `navigator.credentials` do navegador quem fala
com o aparelho - sem JavaScript nao ha passkey, e as telas escondem o botao nesse caso.

**A passkey substitui a senha E o segundo fator.** Ela so e aceita com UV (a biometria ou o PIN
do aparelho conferiu a pessoa), entao ja sao dois fatores: o aparelho que se tem e o dedo ou o
rosto. Por isso cadastrar exige a senha, e tambem o codigo quando o 2FA esta ligado: uma sessao
esquecida aberta nao pode ganhar um jeito de entrar sem nenhum dos dois.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, jsonify, redirect, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import passkeys as passkeys_repo
from gamepanel.persistence.repositories import users as users_repo
from gamepanel.security import webauthn

bp = Blueprint("passkeys", __name__)

# Quanto tempo um desafio vale (servidor) e quanto o navegador espera o aparelho (ms). O do
# servidor e maior: a pessoa ainda precisa achar o dedo certo depois de o aparelho abrir.
CHALLENGE_SECONDS = 180
CEREMONY_MS = 120_000
KIND_LOGIN = "login"
KIND_REGISTER = "register"
LABEL_MAX = 60


def _rp_id() -> str:
    """O dominio a que a chave do aparelho fica presa: o host do endereco configurado."""
    return urlsplit(panel.WEBAUTHN_ORIGIN).hostname or ""


def _enabled() -> None:
    # 404 e nao 403: sem o endereco configurado a rota simplesmente nao existe para ninguem.
    if not panel.WEBAUTHN_ORIGIN:
        abort(404)


def _error(key: str, status: int, **fields):
    return jsonify({"error": panel.translate(key, **fields)}), status


def _payload() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _field(body: dict, name: str) -> bytes:
    value = body.get(name)
    if not isinstance(value, str):
        raise webauthn.WebAuthnError(f"campo ausente: {name}")
    return webauthn.unb64url(value)


# ------------------------------------------------------------------ login


@bp.post("/login/passkey/options")
def login_options():
    _enabled()
    # Lista de credenciais VAZIA de proposito: o aparelho oferece as passkeys que ele tem para
    # este dominio, e o painel nao precisa (nem deve) dizer a quem pergunta quais usuarios existem.
    challenge = panel.passkey_challenges.issue(KIND_LOGIN, CHALLENGE_SECONDS)
    return jsonify({"publicKey": {
        "challenge": challenge, "rpId": _rp_id(), "timeout": CEREMONY_MS,
        "userVerification": "required", "allowCredentials": [],
    }})


def _verified_login(body: dict):
    """A linha do usuario dono da passkey, ou WebAuthnError com o motivo (vai so para o log)."""
    client = _field(body, "clientDataJSON")
    if panel.passkey_challenges.take(KIND_LOGIN, webauthn.client_challenge(client)) is None:
        raise webauthn.WebAuthnError("desafio desconhecido, vencido ou ja usado")
    conn = panel.db()
    stored = passkeys_repo.by_id(conn, str(body.get("id", "")))
    if stored is None:
        raise webauthn.WebAuthnError("passkey nao cadastrada")
    handle = body.get("userHandle")
    # O aparelho devolve o user handle que recebeu no cadastro; outro valor e outra conta.
    if handle and handle != stored["user_handle"]:
        raise webauthn.WebAuthnError("user handle nao confere")
    count = webauthn.verify_assertion(
        challenge=webauthn.client_challenge(client), origin=panel.WEBAUTHN_ORIGIN, rp_id=_rp_id(),
        public_key=stored["public_key"], stored_count=stored["sign_count"], client_data_json=client,
        authenticator_data=_field(body, "authenticatorData"), signature=_field(body, "signature"))
    row = users_repo.by_id(conn, stored["user_id"])
    if row is None:
        raise webauthn.WebAuthnError("usuario da passkey nao existe mais")
    with conn:
        passkeys_repo.mark_used(conn, stored["id"], count, panel.now_iso())
    return row


@bp.post("/login/passkey")
def login():
    _enabled()
    # Por IP: o pedido nao diz o usuario antes de a assinatura ser conferida.
    key = f"passkey|{request.remote_addr}"
    remaining = panel.login_lockout.remaining(key)
    if remaining:
        return _error("flash.too_many_tries", 429, n=remaining)
    body = _payload()
    try:
        row = _verified_login(body)
    except webauthn.WebAuthnError as exc:
        panel.login_lockout.record_failure(key)
        panel.app.logger.warning("passkey recusada (%s): %s", request.remote_addr, exc)
        return _error("passkey.login_failed", 401)
    panel.login_lockout.clear(key)
    response = panel._open_session(row, panel.safe_target(str(body.get("next", ""))))
    return jsonify({"redirect": response.location})


# ------------------------------------------------------------------ cadastro


def _password_and_code_error(row) -> str:
    """Chave do erro, ou '' quando a senha (e o codigo, se o 2FA estiver ligado) confere."""
    key = f"2fa|{row['username'].lower()}"
    if panel.totp_lockout.remaining(key):
        return "flash.too_many_tries"
    if not panel.verify_password(request.form.get("password", ""), row["password_hash"]):
        panel.totp_lockout.record_failure(key)
        return "flash.wrong_current_password"
    if row["totp_enabled"] and not panel._check_second_factor(row, request.form.get("code", "")):
        panel.totp_lockout.record_failure(key)
        return "flash.code_invalid_or_used"
    panel.totp_lockout.clear(key)
    return ""


@bp.post("/account/passkey/options")
@panel.login_required
def register_options():
    _enabled()
    conn = panel.db()
    row = users_repo.by_id(conn, session["uid"])
    if row is None:
        abort(403)
    failure = _password_and_code_error(row)
    if failure:
        return _error(failure, 403, n=panel.totp_lockout.remaining(f"2fa|{row['username'].lower()}"))
    # Um user handle por PESSOA, aleatorio e nunca o id: o aparelho o guarda junto da chave, e
    # um numero sequencial diria quantas contas o painel tem.
    handle = passkeys_repo.handle_for_user(conn, row["id"]) or webauthn.b64url(secrets.token_bytes(16))
    label = request.form.get("label", "").strip()[:LABEL_MAX]
    challenge = panel.passkey_challenges.issue(
        KIND_REGISTER, CHALLENGE_SECONDS, {"uid": row["id"], "handle": handle, "label": label})
    return jsonify({"publicKey": {
        "challenge": challenge,
        "rp": {"id": _rp_id(), "name": panel.translate("app.name")},
        "user": {"id": handle, "name": row["username"], "displayName": row["username"]},
        "pubKeyCredParams": [{"type": "public-key", "alg": webauthn.ALG_ES256},
                             {"type": "public-key", "alg": webauthn.ALG_RS256}],
        "timeout": CEREMONY_MS,
        # `platform`: a biometria do PROPRIO aparelho, que e o pedido. Chave residente: o login
        # nao pergunta o usuario antes, entao o aparelho tem de lembrar de quem e a chave.
        "authenticatorSelection": {"authenticatorAttachment": "platform", "residentKey": "required",
                                   "requireResidentKey": True, "userVerification": "required"},
        "attestation": "none",
        # O mesmo aparelho duas vezes so criaria uma linha a mais para apagar depois.
        "excludeCredentials": [{"type": "public-key", "id": cid}
                               for cid in passkeys_repo.ids_for_user(conn, row["id"])],
    }})


@bp.post("/account/passkey")
@panel.login_required
def register():
    _enabled()
    body = _payload()
    try:
        client = _field(body, "clientDataJSON")
        challenge = webauthn.client_challenge(client)
        pending = panel.passkey_challenges.take(KIND_REGISTER, challenge)
        # O desafio guarda QUEM o pediu: a resposta tem de voltar na sessao da mesma pessoa.
        if pending is None or pending.get("uid") != session["uid"]:
            raise webauthn.WebAuthnError("desafio desconhecido, vencido ou de outra sessao")
        credential = webauthn.verify_registration(
            challenge=challenge, origin=panel.WEBAUTHN_ORIGIN, rp_id=_rp_id(), client_data_json=client,
            attestation_object=_field(body, "attestationObject"))
    except webauthn.WebAuthnError as exc:
        panel.app.logger.warning("cadastro de passkey recusado (uid %s): %s", session["uid"], exc)
        return _error("passkey.register_failed", 400)
    conn = panel.db()
    if passkeys_repo.by_id(conn, credential.credential_id) is not None:
        return _error("passkey.already_registered", 409)
    with conn:
        passkeys_repo.insert(conn, credential.credential_id, session["uid"], pending["handle"],
                             credential.public_key, credential.sign_count,
                             pending["label"] or panel.translate("passkey.default_label"), panel.now_iso())
    flash(panel.translate("passkey.registered"), "ok")
    return jsonify({"redirect": url_for("account.index")})


@bp.post("/account/passkey/delete")
@panel.login_required
def delete():
    # Sem `_enabled()`: apagar continua valendo com o recurso desligado, que e justo quando
    # sobram aparelhos de um endereco antigo para limpar.
    conn = panel.db()
    with conn:
        removed = passkeys_repo.delete(conn, session["uid"], request.form.get("id", ""))
    flash(panel.translate("passkey.removed" if removed else "passkey.not_found"),
          "ok" if removed else "error")
    return redirect(url_for("account.index"))
