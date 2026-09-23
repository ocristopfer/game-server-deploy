"""Uma acao do painel em detalhe, e o que o JavaScript le enquanto ela roda."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template

from gamepanel import app as panel

bp = Blueprint("jobs", __name__)


@bp.get("/jobs/<int:jid>")
@panel.login_required
def detail(jid: int):
    conn = panel.db()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    if not job:
        abort(404)
    panel.job_or_403(job)
    server = None
    if job["server_id"]:
        server = conn.execute(
            panel.SQL_SERVER_BY_ID, (job["server_id"],)
        ).fetchone()
    return render_template("job.html", job=job, server=server)


@bp.get("/api/v1/jobs/<int:jid>")
@panel.login_required
def api_detail(jid: int):
    job = panel.db().execute("SELECT * FROM jobs WHERE id = ?", (jid,)).fetchone()
    if not job:
        abort(404)
    panel.job_or_403(job)
    return jsonify(
        {
            "status": job["status"],
            "exit_code": job["exit_code"],
            "output": job["output"],
            "finished_at": job["finished_at"],
        }
    )
