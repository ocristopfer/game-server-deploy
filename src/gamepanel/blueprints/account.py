"""A conta de quem esta logado: senha, idioma, segundo fator e a chave SSH."""
from __future__ import annotations

import json
import time

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.security import qr

bp = Blueprint("account", __name__)


@bp.get("/ssh-key")
@panel.login_required
def ssh_key():
    return render_template("ssh_key.html", pubkey=panel.public_key())


@bp.post("/account/language")
@panel.login_required
def language():
    """Guarda o idioma da tela para ESTA pessoa.

    Por usuario, e nao por sessao: quem trabalha em ingles nao quer reescolher a cada
    login, e duas pessoas no mesmo painel podem preferir idiomas diferentes.
    """
    chosen_one = panel.i18n.valid_language(request.form.get("lang"))
    with panel.db() as conn:
        conn.execute("UPDATE users SET lang = ? WHERE id = ?", (chosen_one, session["uid"]))
    # O `g` desta requisicao ja guardou o idioma antigo, e o flash abaixo e lido na
    # PROXIMA (depois do redirect) — entao ele ja sai no idioma novo.
    g._idioma = chosen_one
    flash(panel.translate("account.language.changed"), "ok")
    return redirect(url_for("account.index"))


@bp.route("/account", methods=["GET", "POST"])
@panel.login_required
def index():
    if request.method == "POST":
        current = request.form.get("current", "")
        new = request.form.get("new", "")
        confirm = request.form.get("confirm", "")
        row = panel.db().execute(
            "SELECT * FROM users WHERE id = ?", (session["uid"],)
        ).fetchone()
        failure = panel.validate_password(new, confirm)
        if not row or not panel.verify_password(current, row["password_hash"]):
            flash(panel.translate("flash.wrong_current_password"), "error")
        elif failure:
            flash(panel.translate(failure), "error")
        else:
            conn = panel.db()
            with conn:
                conn.execute(panel.SQL_SET_PASSWORD, (panel.hash_password(new), session["uid"]))
            flash(panel.translate("flash.password_changed"), "ok")
            return redirect(url_for("dashboard.index"))
    return render_template("account.html", segundo_fator=panel._two_factor_state(),
                           exige_2fa=panel.REQUIRE_2FA, broker_ligado=panel.ALLOW_BROKER)


@bp.route("/account/2fa", methods=["GET", "POST"])
@panel.login_required
def two_factor():
    """Ativar o segundo fator: mostra o segredo, confere UM codigo do aplicativo e so entao liga."""
    if panel._two_factor_state()["ativo"]:
        return redirect(url_for("account.index"))
    if request.method == "POST":
        secret = session.get("totp_pendente", "")
        step = panel.totp.verify(secret, request.form.get("codigo", ""), time.time()) if secret else None
        if step is None:
            flash(panel.translate("flash.wrong_code"), "error")
        else:
            codes = panel._guarda_o_segundo_fator(session["uid"], secret, step)
            session.pop("totp_pendente", None)
            flash(panel.translate("flash.two_factor_on"), "ok")
            return render_template("account_2fa_codigos.html", codigos=codes)
    # O segredo fica na SESSAO (cookie assinado) ate ser confirmado; recarregar a pagina mostra
    # o mesmo, e abandonar a tela nao deixa nada meio ligado no banco.
    secret = session.get("totp_pendente") or panel.totp.new_secret()
    session["totp_pendente"] = secret
    address = panel.totp.uri(secret, session.get("username", ""), "Painel de Jogos")
    return render_template(
        "account_2fa.html", segredo=panel.totp.group(secret), endereco=address,
        qr_svg=qr.svg(address, label="QR code da verificacao em duas etapas"))


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
    panel._apaga_o_segundo_fator(row["id"])
    flash(panel.translate("flash.two_factor_off"), "ok")
    return redirect(url_for("account.index"))


@bp.post("/account/2fa/codes")
@panel.login_required
def two_factor_codes():
    """Codigos de recuperacao novos: os antigos deixam de valer."""
    row, failure = panel._password_and_code_ok(session["uid"])
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("account.index"))
    codes = panel.totp.new_recovery_codes()
    conn = panel.db()
    with conn:
        conn.execute("UPDATE users SET totp_recovery = ? WHERE id = ?",
                     (json.dumps([panel.totp.hash_recovery_code(c) for c in codes]), row["id"]))
    flash(panel.translate("flash.new_codes"), "ok")
    return render_template("account_2fa_codigos.html", codigos=codes)
