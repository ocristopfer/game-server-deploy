"""Quem entra no painel e com que papel."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("users", __name__)


@bp.get("/users")
@panel.admin_required
def index():
    rows = panel.db().execute(
        "SELECT id, username, role, created_at, totp_enabled FROM users ORDER BY role, username"
    ).fetchall()
    return render_template(
        "users.html", users=rows, roles=panel.ROLES, role_labels=panel.labels_of(panel.ROLE_LABELS),
        meu_id=session.get("uid"), min_len=panel.PASSWORD_MIN,
    )


@bp.post("/users")
@panel.admin_required
def new():
    username = request.form.get("username", "").strip().lower()
    role = request.form.get("role", panel.ROLE_OPERADOR)
    senha = request.form.get("new", "")
    if not panel.USER_RE.match(username):
        erro = ("Nome de usuario invalido: use de 1 a 32 caracteres entre letras"
                " minusculas, numeros, '-' e '_', comecando por letra ou '_'.")
    elif role not in panel.ROLES:
        erro = "Papel invalido."
    else:
        erro = panel.validate_password(senha, request.form.get("confirm", ""))
    if erro:
        flash(panel.translate(erro), "error")
        return redirect(url_for("users.index"))

    conn = panel.db()
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at)"
                " VALUES (?,?,?,?)",
                (username, panel.hash_password(senha), role, panel.now_iso()),
            )
    except sqlite3.IntegrityError:
        # username e UNIQUE: e o unico jeito de dois admins criarem o mesmo nome ao
        # mesmo tempo sem um sobrescrever o outro.
        flash(panel.translate("flash.user_exists", user=username), "error")
        return redirect(url_for("users.index"))
    flash(panel.translate("flash.user_created", user=username,
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/role")
@panel.admin_required
def role(uid: int):
    alvo = panel._user_or_404(uid)
    role = request.form.get("role", "")
    if role not in panel.ROLES:
        abort(400, "Papel invalido.")
    if uid == session.get("uid"):
        # Rebaixar a si mesmo tranca a pessoa fora desta tela no mesmo clique.
        flash(panel.translate("flash.cannot_change_own_role"), "error")
    elif role == alvo["role"]:
        flash(panel.translate("flash.user_already_is", user=alvo["username"],
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    elif alvo["role"] == panel.ROLE_ADMIN and panel.count_admins(excluindo=uid) == 0:
        flash(panel.translate("flash.only_admin_demote"), "error")
    else:
        conn = panel.db()
        with conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))
        flash(panel.translate("flash.user_now_is", user=alvo["username"],
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/password")
@panel.admin_required
def password(uid: int):
    """Reset feito pelo admin — sem a senha atual, que e justamente a esquecida."""
    alvo = panel._user_or_404(uid)
    erro = panel.validate_password(request.form.get("new", ""), request.form.get("confirm", ""))
    if erro:
        flash(panel.translate(erro), "error")
        return redirect(url_for("users.index"))
    conn = panel.db()
    with conn:
        conn.execute(panel.SQL_SET_PASSWORD, (panel.hash_password(request.form.get("new", "")), uid))
    flash(panel.translate("flash.password_reset", user=alvo["username"]), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/2fa/off")
@panel.admin_required
def two_factor_off(uid: int):
    """Celular perdido e codigos de recuperacao perdidos: o admin desliga o 2FA da pessoa, que
    entra so com a senha e ativa de novo. Nao vale para si mesmo (use a tela Conta)."""
    alvo = panel._user_or_404(uid)
    if uid == session.get("uid"):
        flash(panel.translate("flash.own_two_factor_in_account"), "error")
    else:
        panel._apaga_o_segundo_fator(uid)
        flash(panel.translate("flash.user_two_factor_off", user=alvo["username"]), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/delete")
@panel.admin_required
def delete(uid: int):
    alvo = panel._user_or_404(uid)
    if uid == session.get("uid"):
        flash(panel.translate("flash.cannot_remove_self"), "error")
    elif alvo["role"] == panel.ROLE_ADMIN and panel.count_admins(excluindo=uid) == 0:
        flash(panel.translate("flash.cannot_remove_only_admin"), "error")
    else:
        conn = panel.db()
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        # A sessao dele morre no proximo clique: o login_required confere o banco.
        flash(panel.translate("flash.user_removed", user=alvo["username"]), "ok")
    return redirect(url_for("users.index"))
