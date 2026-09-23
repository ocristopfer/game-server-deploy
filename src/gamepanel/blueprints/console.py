"""Comando unico dentro do container, e o historico do que ja rodou."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import servers as servers_repo

# Quantas sessoes de comando avulso a tela mostra.
CONSOLE_HISTORY = 20

bp = Blueprint("console", __name__)


@bp.route("/servers/<int:sid>/console", methods=["GET", "POST"])
@panel.admin_required
def index(sid: int):
    if not panel.ALLOW_SHELL:
        abort(403, i18n.Message("error.console_disabled"))
    conn = panel.db()
    server = servers_repo.by_id(conn, sid)
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
        job = jobs_repo.by_id_and_server(conn, int(job_arg), sid)
    history = jobs_repo.shell_history(conn, sid, CONSOLE_HISTORY)
    return render_template(
        "console.html", server=server, job=job, history=history,
        shell_timeout=panel.SHELL_TIMEOUT,
    )
