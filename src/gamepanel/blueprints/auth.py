"""Entrar, sair e o segundo fator na hora do login."""
from __future__ import annotations

import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("uid"):
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = f"{request.remote_addr}|{username.lower()}"
        remaining = panel._lockout_remaining(key)
        if remaining:
            flash(panel.translate("flash.too_many_tries", n=remaining), "error")
            return render_template(panel.TPL_LOGIN), 429
        row = panel.db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and panel.verify_password(password, row["password_hash"]):
            panel._clear_fails(key)
            next_one = panel.safe_target(request.args.get("next", ""))
            if row["totp_enabled"]:
                # Senha certa NAO abre a sessao: so guarda "esta pessoa passou da senha, falta o
                # codigo". Sem `uid` na sessao, nenhuma rota do painel a reconhece como logada.
                session.clear()
                session["pre2fa"] = {"uid": row["id"], "ate": time.time() + panel.PRE_2FA_SEGUNDOS,
                                     "proximo": next_one}
                panel.csrf_token()
                return redirect(url_for("auth.login_2fa"))
            return panel._abre_sessao(row, next_one)
        panel._record_fail(key)
        flash(panel.translate("flash.bad_credentials"), "error")
        return render_template(panel.TPL_LOGIN), 401
    return render_template(panel.TPL_LOGIN)


@bp.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    if session.get("uid"):
        return redirect(url_for("dashboard.index"))
    pending_one = session.get("pre2fa") or {}
    row = None
    if pending_one and pending_one.get("ate", 0) > time.time():
        row = panel.db().execute("SELECT * FROM users WHERE id = ?", (pending_one.get("uid"),)).fetchone()
    if row is None or not row["totp_enabled"]:
        session.clear()
        flash(panel.translate("flash.verification_expired"), "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        key = f"2fa|{row['username'].lower()}"
        remaining = panel._lockout_remaining(key, panel.LOCKOUT_2FA_TENTATIVAS, panel.LOCKOUT_2FA_JANELA)
        if remaining:
            flash(panel.translate("flash.too_many_tries", n=remaining), "error")
            return render_template("login_2fa.html"), 429
        if panel._confere_segundo_fator(row, request.form.get("codigo", "")):
            panel._clear_fails(key)
            return panel._abre_sessao(row, pending_one.get("proximo", ""))
        panel._record_fail(key)
        flash(panel.translate("flash.code_invalid_or_used"), "error")
        return render_template("login_2fa.html"), 401
    return render_template("login_2fa.html")


@bp.post("/logout")
@panel.login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
