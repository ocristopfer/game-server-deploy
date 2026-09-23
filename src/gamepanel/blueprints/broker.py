"""Catalogo de jogos e instancias criadas pelo broker."""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel.games.catalog import search as catalog_search
from gamepanel.games.catalog.templates import TEMPLATES as GAME_TEMPLATES

bp = Blueprint("broker", __name__)


@bp.route("/catalog", methods=["GET"])
@panel.admin_required
@panel.broker_required
def catalog():
    try:
        jogos = panel.broker_client.catalog()
    except panel.broker_client.BrokerError as erro:
        flash(panel.translate("flash.broker_error", reason=erro.message), "error")
        jogos = []
    return render_template("catalogo.html", jogos=jogos, receitas=panel.BROKER_RECIPES, form={},
                           modelos=GAME_TEMPLATES)


@bp.get("/api/v1/catalog/suggestions")
@panel.admin_required
@panel.broker_required
def api_suggestions():
    """Busca por nome ou App ID numa lista FIXA (gerada do LinuxGSM, no repositorio): nada aqui
    vai a internet, e a consulta so seleciona entre entradas conhecidas."""
    achados = catalog_search.search(request.args.get("q", ""))
    return jsonify({"resultados": [catalog_search.result(s) for s in achados],
                    "fonte": catalog_search.SOURCE})


@bp.post("/catalog/new")
@panel.admin_required
@panel.broker_required
def catalog_new():
    data, erros = panel._game_from_form(request.form)
    if not erros:
        try:
            panel.broker_client.add_game(data, panel._ator())
        except panel.broker_client.BrokerError as exc:
            erros.append(f"Broker: {exc.message}")
    if erros:
        for erro in erros:
            flash(panel.translate(erro), "error")
        try:
            jogos = panel.broker_client.catalog()
        except panel.broker_client.BrokerError:
            jogos = []
        return render_template("catalogo.html", jogos=jogos, receitas=panel.BROKER_RECIPES,
                               form=request.form, modelos=GAME_TEMPLATES), 400
    panel._log_broker_action("broker-jogo", panel._ator(), data.get("chave", ""), "Jogo adicionado ao catalogo.")
    flash(panel.translate("flash.game_added",
                       name=data.get("nome", data.get("chave", ""))), "ok")
    return redirect(url_for("broker.catalog"))


@bp.get("/instances")
@panel.admin_required
@panel.broker_required
def instances():
    try:
        instances = panel.broker_client.instances()
        jogos = [j for j in panel.broker_client.catalog() if j.get("creatable")]
    except panel.broker_client.BrokerError as erro:
        flash(panel.translate("flash.broker_error", reason=erro.message), "error")
        instances, jogos = [], []
    ligados = {
        r["broker_id"]: r
        for r in panel.db().execute("SELECT id, name, broker_id FROM servers WHERE broker_id > 0")
    }
    return render_template("instancias.html", instancias=instances, jogos=jogos, servidores=ligados)


@bp.post("/instances/new")
@panel.admin_required
@panel.broker_required
def instance_new():
    game = (request.form.get("game") or "").strip()
    name = (request.form.get("name") or "").strip()
    try:
        resposta = panel.broker_client.create(game, name, panel._ator())
    except panel.broker_client.BrokerError as erro:
        flash(panel.translate("flash.broker_error", reason=erro.message), "error")
        return redirect(url_for("broker.instances"))
    op_id = str(resposta.get("operation_id", ""))
    if not op_id:
        flash(panel.translate("flash.broker_no_operation_id"), "error")
        return redirect(url_for("broker.instances"))
    job_id = panel.start_broker_job("broker-criar", panel._ator(), op_id, f"{game}: {name}")
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/instances/<int:iid>/deactivate")
@panel.admin_required
@panel.broker_required
def instance_deactivate(iid: int):
    try:
        panel.broker_client.deactivate(iid, panel._ator())
    except panel.broker_client.BrokerError as erro:
        panel._log_broker_action("broker-desativar", panel._ator(), f"instancia {iid}", erro.message, "error")
        flash(panel.translate("flash.broker_error", reason=erro.message), "error")
    else:
        panel._log_broker_action("broker-desativar", panel._ator(), f"instancia {iid}",
                                 "Portas fechadas no firewall e container parado.")
        flash(panel.translate("flash.instance_deactivated"), "ok")
    return redirect(url_for("broker.instances"))


@bp.post("/instances/<int:iid>/delete")
@panel.admin_required
@panel.broker_required
def instance_remove(iid: int):
    confirm = (request.form.get("confirmation") or "").strip()
    db_only = request.form.get("db_only") == "1"
    try:
        panel.broker_client.remove(iid, confirm, panel._ator(), db_only)
    except panel.broker_client.BrokerError as erro:
        panel._log_broker_action("broker-remover", panel._ator(), f"instancia {iid}", erro.message, "error")
        flash(panel.translate("flash.broker_error", reason=erro.message), "error")
        return redirect(url_for("broker.instances"))
    conn = panel.db()
    with conn:
        # O servidor do painel aponta para um container que deixou de existir.
        conn.execute("DELETE FROM servers WHERE broker_id = ?", (iid,))
    panel._log_broker_action(
        "broker-remover", panel._ator(), f"instancia {iid}",
        "So o registro foi esquecido." if db_only else "Container destruido e servidor removido do painel.")
    flash(panel.translate("flash.instance_removed"), "ok")
    return redirect(url_for("broker.instances"))
