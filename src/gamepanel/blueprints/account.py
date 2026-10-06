"""The signed-in person's account: password, language, second factor, push devices and the SSH key."""
from __future__ import annotations

import json
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import passkeys as passkeys_repo
from gamepanel.persistence.repositories import push as push_repo
from gamepanel.persistence.repositories import users as users_repo
from gamepanel.security import qr, webauthn

bp = Blueprint("account", __name__)


@bp.get("/ssh-key")
@panel.login_required
def ssh_key():
    return render_template("ssh_key.html", pubkey=panel.public_key())


@bp.post("/account/language")
@panel.login_required
def language():
    """Store the screen language for THIS person.

    Per user, not per session: someone who works in English does not want to pick it again
    at every login, and two people on the same panel may prefer different languages.
    """
    chosen_one = panel.i18n.valid_language(request.form.get("lang"))
    with panel.db() as conn:
        users_repo.set_language(conn, session["uid"], chosen_one)
    # This request's `g` already stored the old language, and the flash below is read on
    # the NEXT one (after the redirect), so it already comes out in the new language.
    g._language = chosen_one
    flash(panel.translate("account.language.changed"), "ok")
    return redirect(url_for("account.index"))


@bp.route("/account", methods=["GET", "POST"])
@panel.login_required
def index():
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        row = users_repo.by_id(panel.db(), session["uid"])
        failure = panel.validate_password(new, confirm)
        if not row or not panel.verify_password(current, row["password_hash"]):
            flash(panel.translate("flash.wrong_current_password"), "error")
        elif failure:
            flash(panel.translate(failure), "error")
        else:
            conn = panel.db()
            with conn:
                users_repo.set_password(conn, session["uid"], panel.hash_password(new))
            flash(panel.translate("flash.password_changed"), "ok")
            return redirect(url_for("dashboard.index"))
    return render_template("account.html", two_factor=panel._two_factor_state(),
                           requires_2fa=panel.REQUIRE_2FA, broker_enabled=panel.ALLOW_BROKER,
                           passkeys=passkeys_repo.for_user(panel.db(), session["uid"]),
                           push_devices=_push_devices(), push_key=webauthn.b64url(panel.push_keys(panel.db()).public),
                           push_limit=panel.PUSH_MAX_PER_USER, events=panel.labels_of(panel.ALERT_EVENTS))


def _push_devices() -> list[dict]:
    """This person's devices, with the events already as a set (the checkboxes test membership)."""
    return [{**dict(row), "events": panel.clean_events(row["events"])}
            for row in push_repo.for_user(panel.db(), session["uid"])]


@bp.route("/account/2fa", methods=["GET", "POST"])
@panel.login_required
def two_factor():
    """Enable the second factor: show the secret, check ONE code from the app and only then turn it on."""
    if panel._two_factor_state()["ativo"]:
        return redirect(url_for("account.index"))
    if request.method == "POST":
        secret = session.get("totp_pendente", "")
        step = panel.totp.verify(secret, request.form.get("code", ""), time.time()) if secret else None
        if step is None:
            flash(panel.translate("flash.wrong_code"), "error")
        else:
            codes = panel._store_second_factor(session["uid"], secret, step)
            session.pop("totp_pendente", None)
            flash(panel.translate("flash.two_factor_on"), "ok")
            return render_template("account_2fa_codes.html", codes=codes)
    # The secret stays in the SESSION (signed cookie) until confirmed; reloading the page shows
    # the same one, and leaving the screen does not leave anything half-enabled in the database.
    secret = session.get("totp_pendente") or panel.totp.new_secret()
    session["totp_pendente"] = secret
    address = panel.totp.uri(secret, session.get("username", ""), "Painel de Jogos")
    return render_template(
        "account_2fa.html", secret=panel.totp.group(secret), address=address,
        qr_svg=qr.svg(address, label=panel.translate("account_2fa.qr_label")))


@bp.post("/account/2fa/off")
@panel.login_required
def two_factor_off():
    if panel.REQUIRE_2FA:
        flash(panel.translate("account.two_factor_required"), "error")
        return redirect(url_for("account.index"))
    row, failure = panel._password_and_code_ok(session["uid"])
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("account.index"))
    panel._delete_second_factor(row["id"])
    flash(panel.translate("flash.two_factor_off"), "ok")
    return redirect(url_for("account.index"))


@bp.post("/account/2fa/codes")
@panel.login_required
def two_factor_codes():
    """New recovery codes: the old ones stop working."""
    row, failure = panel._password_and_code_ok(session["uid"])
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("account.index"))
    codes = panel.totp.new_recovery_codes()
    conn = panel.db()
    with conn:
        users_repo.set_recovery(
            conn, row["id"],
            json.dumps([panel.totp.hash_recovery_code(c) for c in codes]))
    flash(panel.translate("flash.new_codes"), "ok")
    return render_template("account_2fa_codes.html", codes=codes)
