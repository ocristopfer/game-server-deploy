"""Sign in with the device biometrics (passkey / WebAuthn) and register devices.

The verification lives in `security/webauthn.py`; here only the HTTP. Both ceremonies have two
steps each: the browser asks for the OPTIONS (with a fresh challenge), the device signs, and the
response comes back to be checked. Everything is JSON because the browser's `navigator.credentials`
is what talks to the device - without JavaScript there is no passkey, and the screens hide the button
in that case.

**The passkey replaces the password AND the second factor.** It is only accepted with UV (the device
biometrics or PIN verified the person), so it already is two factors: the device one holds and the
finger or face. That is why registering requires the password, and also the code when 2FA is on: a
session left open must not gain a way to sign in without either of them.
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

# How long a challenge is valid (server) and how long the browser waits for the device (ms). The
# server one is longer: the person still needs to find the right finger after the device prompt opens.
CHALLENGE_SECONDS = 180
CEREMONY_MS = 120_000
KIND_LOGIN = "login"
KIND_REGISTER = "register"
LABEL_MAX = 60


def _rp_id() -> str:
    """The domain the device key is bound to: the host of the configured address."""
    return urlsplit(panel.WEBAUTHN_ORIGIN).hostname or ""


def _enabled() -> None:
    # 404, not 403: without the configured address the route simply does not exist for anyone.
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
    # EMPTY credential list on purpose: the device offers the passkeys it has for
    # this domain, and the panel does not need to (and must not) tell whoever asks which users exist.
    challenge = panel.passkey_challenges.issue(KIND_LOGIN, CHALLENGE_SECONDS)
    return jsonify({"publicKey": {
        "challenge": challenge, "rpId": _rp_id(), "timeout": CEREMONY_MS,
        "userVerification": "required", "allowCredentials": [],
    }})


def _verified_login(body: dict):
    """The row of the user who owns the passkey, or WebAuthnError with the reason (goes only to the log)."""
    client = _field(body, "clientDataJSON")
    if panel.passkey_challenges.take(KIND_LOGIN, webauthn.client_challenge(client)) is None:
        raise webauthn.WebAuthnError("desafio desconhecido, vencido ou ja usado")
    conn = panel.db()
    stored = passkeys_repo.by_id(conn, str(body.get("id", "")))
    if stored is None:
        raise webauthn.WebAuthnError("passkey nao cadastrada")
    handle = body.get("userHandle")
    # The device returns the user handle it received at registration; any other value is another account.
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
    # By IP: the request does not say the user before the signature is checked.
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


# ------------------------------------------------------------------ registration


def _password_and_code_error(row) -> str:
    """Error key, or '' when the password (and the code, if 2FA is on) checks out."""
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
    # One user handle per PERSON, random and never the id: the device stores it next to the key, and
    # a sequential number would reveal how many accounts the panel has.
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
        # `platform`: the biometrics of the device ITSELF, which is what is asked for. Resident key: the login
        # does not ask for the user first, so the device has to remember whose key it is.
        "authenticatorSelection": {"authenticatorAttachment": "platform", "residentKey": "required",
                                   "requireResidentKey": True, "userVerification": "required"},
        "attestation": "none",
        # The same device twice would only create one more row to delete later.
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
        # The challenge stores WHO asked for it: the response has to come back in the same person's session.
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
    # No `_enabled()`: deleting still works with the feature off, which is exactly when
    # devices from an old address are left over to clean up.
    conn = panel.db()
    with conn:
        removed = passkeys_repo.delete(conn, session["uid"], request.form.get("id", ""))
    flash(panel.translate("passkey.removed" if removed else "passkey.not_found"),
          "ok" if removed else "error")
    return redirect(url_for("account.index"))
