"""A lista de servidores e os medidores que ela busca de tempos em tempos."""
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
    """Medidores de todos os servidores — alimenta os mini-graficos do painel.

    O caminho e "/api/resources", e nao "/api/metrics", de proposito: "/api/metrics" e
    uma regra corriqueira das listas de filtro de rastreadores (uBlock Origin, AdGuard,
    DNS filtrado). Com uma delas ligada, o navegador nem chega a mandar o pedido — ele
    devolve um pixel transparente com status 499 — e o painel ficava eternamente em
    "medindo recursos...", sem erro visivel em lugar nenhum. Nome em portugues tambem
    e o que o resto das rotas do painel usa (/historico, /alertas, /graficos)."""
    servers = servers_repo.all_ordered(panel.db())
    return jsonify({str(sid): data for sid, data in panel.all_metrics(servers).items()})


@bp.get("/api/v1/players")
@panel.login_required
def api_players():
    servers = servers_repo.all_ordered(panel.db())
    return jsonify({str(sid): data for sid, data in panel.all_players(servers).items()})
