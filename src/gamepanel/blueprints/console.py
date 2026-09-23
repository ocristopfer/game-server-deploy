"""Comando unico dentro do container, e o historico do que ja rodou."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("console", __name__)


@bp.route("/servers/<int:sid>/console", methods=["GET", "POST"])
@panel.admin_required
def index(sid: int):
    if not panel.ALLOW_SHELL:
        abort(403, "O console esta desabilitado (GAMEPANEL_ALLOW_SHELL=0).")
    conn = panel.db()
    server = conn.execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)

    if request.method == "POST":
        command = request.form.get("command", "").strip()
        if not command:
            flash(panel.translate("flash.type_a_command"), "error")
        elif len(command) > panel.SHELL_MAX_LEN:
            flash(panel.translate("flash.command_too_long", n=panel.SHELL_MAX_LEN), "error")
        else:
            # O comando inteiro vira UM argumento de 'bash -lc' no destino — o shell
            # local do ssh nunca o interpreta, entao pipes e aspas chegam intactos.
            job_id = panel.start_job(
                "shell",
                server,
                session.get("username", "?"),
                remote_cmd=panel.q("bash", "-lc", command),
                command=command,
                timeout=panel.SHELL_TIMEOUT,
            )
            return redirect(url_for("console.index", sid=sid, job=job_id))

    job = None
    job_arg = request.args.get("job", "")
    if job_arg.isdigit():
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND server_id = ?", (int(job_arg), sid)
        ).fetchone()
    history = conn.execute(
        "SELECT * FROM jobs WHERE server_id = ? AND action = 'shell'"
        " ORDER BY id DESC LIMIT 20",
        (sid,),
    ).fetchall()
    return render_template(
        "console.html", server=server, job=job, history=history,
        shell_timeout=panel.SHELL_TIMEOUT,
    )
