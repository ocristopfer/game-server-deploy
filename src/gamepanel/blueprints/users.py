"""Who gets into the panel and with which role."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel import i18n
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
        failure = i18n.Message("flash.username_invalid")
    elif role not in panel.ROLES:
        failure = i18n.Message("flash.role_invalid")
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
        # username is UNIQUE: it is the only way for two admins creating the same name at the
        # same time not to overwrite each other.
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
        abort(400, i18n.Message("flash.role_invalid"))
    if uid == session.get("uid"):
        # Demoting yourself locks you out of this screen in the same click.
        flash(panel.translate("flash.cannot_change_own_role"), "error")
    elif role == target["role"]:
        flash(panel.translate("flash.user_already_is", user=target["username"],
                       role=panel.translate(panel.ROLE_LABELS[role]).lower()), "ok")
    elif target["role"] == panel.ROLE_ADMIN and panel.count_admins(excluding=uid) == 0:
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
    """Reset done by the admin, without the current password, which is exactly the forgotten one."""
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
    """Lost phone and lost recovery codes: the admin turns off the person's 2FA, who then
    signs in with just the password and enables it again. Not for yourself (use the Account screen)."""
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
    elif target["role"] == panel.ROLE_ADMIN and panel.count_admins(excluding=uid) == 0:
        flash(panel.translate("flash.cannot_remove_only_admin"), "error")
    else:
        conn = panel.db()
        with conn:
            users_repo.delete(conn, uid)
        # Their session dies on the next click: login_required checks the database.
        flash(panel.translate("flash.user_removed", user=target["username"]), "ok")
    return redirect(url_for("users.index"))
