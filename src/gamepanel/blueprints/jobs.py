"""Uma acao do painel em detalhe, e o que o JavaScript le enquanto ela roda."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template

from gamepanel import app as panel
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("jobs", __name__)


@bp.get("/jobs/<int:jid>")
@panel.login_required
def detail(jid: int):
    conn = panel.db()
    job = jobs_repo.by_id(conn, jid)
    if not job:
        abort(404)
    panel.job_or_403(job)
    server = None
    if job["server_id"]:
        server = servers_repo.by_id(conn, job["server_id"])
    return render_template("job.html", job=job, server=server)


@bp.get("/api/v1/jobs/<int:jid>")
@panel.login_required
def api_detail(jid: int):
    job = jobs_repo.by_id(panel.db(), jid)
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
