"""The server list and the gauges it fetches from time to time."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@panel.login_required
def index():
    servers = servers_repo.all_ordered(panel.db())
    return render_template(
        "dashboard.html", servers=servers, status=panel.all_status(servers)
    )


@bp.get("/api/v1/status")
@panel.login_required
def api_status():
    servers = servers_repo.all_ordered(panel.db())
    return jsonify({str(sid): state for sid, state in panel.all_status(servers).items()})


@bp.get("/api/v1/resources")
@panel.login_required
def api_metrics():
    """Gauges for every server: feeds the panel's mini charts.

    The path is "/api/resources", not "/api/metrics", on purpose: "/api/metrics" is
    a common rule in tracker filter lists (uBlock Origin, AdGuard,
    filtered DNS). With one of them on, the browser does not even send the request: it
    returns a transparent pixel with status 499, and the panel stayed forever on
    "measuring resources...", with no visible error anywhere. A Portuguese name was also
    what the rest of the panel's routes used (/historico, /alertas, /graficos)."""
    servers = servers_repo.all_ordered(panel.db())
    return jsonify({str(sid): data for sid, data in panel.all_metrics(servers).items()})


@bp.get("/api/v1/players")
@panel.login_required
def api_players():
    servers = servers_repo.all_ordered(panel.db())
    return jsonify({str(sid): data for sid, data in panel.all_players(servers).items()})
