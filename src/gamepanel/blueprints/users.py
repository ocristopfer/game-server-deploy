"""Quem entra no painel e com que papel."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import users as users_repo

bp = Blueprint("users", __name__)


@bp.get("/users")
@panel.admin_required
def index():
    rows = users_repo.all_ordered(panel.db())
    return render_template(
        "users.html", users=rows, roles=panel.ROLES, role_labels=panel.labels_of(panel.ROLE_LABELS),
        my_id=session.get("uid"), min_len=panel.PASSWORD_MIN,
    )


@bp.post("/users")
@panel.admin_required
def new():
    username = request.form.get("username", "").strip().lower()
    role = request.form.get("role", panel.ROLE_OPERATOR)
    new_password = request.form.get("new", "")
    if not panel.USER_RE.match(username):
        failure = ("Nome de usuario invalido: use de 1 a 32 caracteres entre letras"
                " minusculas, numeros, '-' e '_', comecando por letra ou '_'.")
    elif role not in panel.ROLES:
        failure = "Papel invalido."
    else:
        failure = panel.validate_password(new_password, request.form.get("confirm", ""))
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("users.index"))

    conn = panel.db()
    try:
        with conn:
            users_repo.insert(conn, username, panel.hash_password(new_password),
                              role, panel.now_iso())
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
    target = panel._user_or_404(uid)
    role = request.form.get("role", "")
    if role not in panel.ROLES:
        abort(400, "Papel invalido.")
    if uid == session.get("uid"):
        # Rebaixar a si mesmo tranca a pessoa fora desta tela no mesmo clique.
        flash(panel.translate("flash.cannot_change_own_role"), "error")
    elif role == target["role"]:
        flash(panel.translate("flash.user_already_is", user=target["username"],
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    elif target["role"] == panel.ROLE_ADMIN and panel.count_admins(excluindo=uid) == 0:
        flash(panel.translate("flash.only_admin_demote"), "error")
    else:
        conn = panel.db()
        with conn:
            users_repo.set_role(conn, uid, role)
        flash(panel.translate("flash.user_now_is", user=target["username"],
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/password")
@panel.admin_required
def password(uid: int):
    """Reset feito pelo admin — sem a senha atual, que e justamente a esquecida."""
    target = panel._user_or_404(uid)
    failure = panel.validate_password(request.form.get("new", ""), request.form.get("confirm", ""))
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("users.index"))
    conn = panel.db()
    with conn:
        users_repo.set_password(conn, uid, panel.hash_password(request.form.get("new", "")))
    flash(panel.translate("flash.password_reset", user=target["username"]), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/2fa/off")
@panel.admin_required
def two_factor_off(uid: int):
    """Celular perdido e codigos de recuperacao perdidos: o admin desliga o 2FA da pessoa, que
    entra so com a senha e ativa de novo. Nao vale para si mesmo (use a tela Conta)."""
    target = panel._user_or_404(uid)
    if uid == session.get("uid"):
        flash(panel.translate("flash.own_two_factor_in_account"), "error")
    else:
        panel._delete_second_factor(uid)
        flash(panel.translate("flash.user_two_factor_off", user=target["username"]), "ok")
    return redirect(url_for("users.index"))


@bp.post("/users/<int:uid>/delete")
@panel.admin_required
def delete(uid: int):
    target = panel._user_or_404(uid)
    if uid == session.get("uid"):
        flash(panel.translate("flash.cannot_remove_self"), "error")
    elif target["role"] == panel.ROLE_ADMIN and panel.count_admins(excluindo=uid) == 0:
        flash(panel.translate("flash.cannot_remove_only_admin"), "error")
    else:
        conn = panel.db()
        with conn:
            users_repo.delete(conn, uid)
        # A sessao dele morre no proximo clique: o login_required confere o banco.
        flash(panel.translate("flash.user_removed", user=target["username"]), "ok")
    return redirect(url_for("users.index"))
