"""Single command inside the container, and the history of what already ran."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import remote_cmd

# How many one-off command sessions the screen shows.
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
            # The whole command becomes ONE argument of 'bash -lc' at the destination: the local
            # ssh shell never interprets it, so pipes and quotes arrive intact. In helper mode it
            # runs as steam, like the terminal: root is not a console away any more.
            job_id = panel.start_job(
                "shell",
                server,
                session.get("username", "?"),
                remote_cmd=remote_cmd.as_steam(server, "bash", "-lc", command),
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
