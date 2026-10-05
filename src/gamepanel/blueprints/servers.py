"""Registering and operating a server: create, edit, remove and act on it."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import remote_cmd

bp = Blueprint("servers", __name__)


@bp.route("/servers/new", methods=["GET", "POST"])
@panel.admin_required
def new():
    data: dict = dict.fromkeys(panel.SERVER_FIELDS, "")
    # New servers log in unprivileged: containers created from now on have the `gamepanel` user
    # (docs/security-hardening-contract.md). The field stays editable for a legacy container.
    data.update({"ssh_user": remote_cmd.HELPER_USER, "ssh_port": 22, "query_port": 0})
    if request.method == "POST":
        data, errors = panel._form_server(request.form)
        if not errors:
            try:
                conn = panel.db()
                with conn:
                    servers_repo.insert(conn, data, panel.now_iso())
                flash(panel.translate("flash.server_added", name=data["name"]), "ok")
                return redirect(url_for("dashboard.index"))
            except sqlite3.IntegrityError:
                errors.append(i18n.Message("flash.server_duplicate", host=data["host"]))
        for err in errors:
            flash(panel.translate(err), "error")
    return render_template("server_form.html", data=data, mode="new")


@bp.route("/servers/<int:sid>/edit", methods=["GET", "POST"])
@panel.admin_required
def edit(sid: int):
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    data = dict(server)
    if request.method == "POST":
        data, errors = panel._form_server(request.form)
        if not errors:
            try:
                conn = panel.db()
                with conn:
                    servers_repo.update(conn, data, sid)
                panel.invalidate_status(sid)
                # The count is cached for a few seconds: changing the source through the
                # form has to take effect immediately, as it does through the wizard.
                panel.invalidate_players(sid)
                flash(panel.translate("flash.server_updated"), "ok")
                return redirect(url_for("servers.detail", sid=sid))
            except sqlite3.IntegrityError:
                errors.append(i18n.Message("flash.server_duplicate", host=data["host"]))
        for err in errors:
            flash(panel.translate(err), "error")
    # `server` (the database row, not the form) goes along: the server's navigation bar
    # takes the id and name from it. Without it this screen would be the only server screen
    # without the bar, and that was exactly how the navigation kept drifting apart.
    return render_template("server_form.html", data=data, mode="edit", sid=sid,
                           server=server)


@bp.post("/servers/<int:sid>/delete")
@panel.admin_required
def delete(sid: int):
    conn = panel.db()
    with conn:
        servers_repo.delete(conn, sid)
    panel.invalidate_status(sid)
    flash(panel.translate("flash.server_removed"), "ok")
    return redirect(url_for("dashboard.index"))


@bp.get("/servers/<int:sid>")
@panel.login_required
def detail(sid: int):
    conn = panel.db()
    server = servers_repo.by_id(conn, sid)
    if not server:
        abort(404)
    jobs = panel.server_jobs(conn, sid, 15)
    lines = panel._log_lines_arg(request.args.get("lines"))

    # Status, gauges, players and log are four independent SSH round trips. In series the
    # screen cost the sum of the four, and with the container down, the sum of the four
    # timeouts before showing "unreachable".
    read_value = panel.in_parallel({
        "status": lambda: panel.server_status(server),
        "metrics": lambda: panel.server_metrics(server),
        "players": lambda: panel.server_players(server),
        "logs": lambda: panel.read_logs(server, lines),
    })
    # read_logs returns (text, cursor): the whole pair comes in place of the "value".
    log_pair, log_error = read_value["logs"]
    logs, log_cursor = log_pair if log_pair else ("", "")

    return render_template(
        "server_detail.html",
        server=server,
        status=read_value["status"][0] or {"reachable": False, "service": "desconhecido",
                                     "error": read_value["status"][1]},
        metrics=read_value["metrics"][0] or {"error": read_value["metrics"][1]},
        # Same shape that server_players returns, so the screen does not need to know that
        # the error was in reading rather than in counting.
        players=read_value["players"][0] or {"configured": True, "error": read_value["players"][1],
                                       "players": None, "list": [], "source": ""},
        jobs=jobs,
        logs=logs,
        log_cursor=log_cursor,
        log_error=log_error,
        lines=lines,
        actions=panel.ACTIONS,
    )


@bp.get("/api/v1/servers/<int:sid>/resources")
@panel.login_required
def api_metrics(sid: int):
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    data = panel.server_metrics(server)
    return jsonify(data), (502 if data.get("error") else 200)


@bp.get("/api/v1/servers/<int:sid>/logs")
@panel.login_required
def api_logs(sid: int):
    """Feed the detail screen's "follow log"."""
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    # A rejected cursor (tampered with, or from a journalctl that does not emit them) becomes a full
    # read: without this the client would append the whole log on top of what is already on screen.
    cursor = request.args.get("cursor", "")
    if not panel.CURSOR_RE.match(cursor or ""):
        cursor = ""
    try:
        text, new_cursor = panel.read_logs(server, panel._log_lines_arg(request.args.get("lines")), cursor)
    except panel.RemoteError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({
        "text": text,
        "cursor": new_cursor,
        # Without a cursor (first round, or an old journalctl) the client replaces the whole
        # block; with a cursor it only appends the new lines.
        "append": bool(cursor and new_cursor),
    })


@bp.post("/servers/<int:sid>/action/<action>")
@panel.login_required
def action(sid: int, action: str):
    if action not in panel.ACTIONS:
        abort(404)
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    job_id = panel.start_job(action, server, session.get("username", "?"))
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))
