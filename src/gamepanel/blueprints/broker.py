"""Catalogo de jogos e instancias criadas pelo broker."""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel.games.catalog import search as catalog_search
from gamepanel.games.catalog.templates import TEMPLATES as GAME_TEMPLATES
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("broker", __name__)


@bp.route("/catalog", methods=["GET"])
@panel.admin_required
@panel.broker_required
def catalog():
    try:
        games = panel.broker_client.catalog()
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        games = []
    return render_template("catalog.html", games=games, recipes=panel.BROKER_RECIPES, form={},
                           checked_recipes=[], editing=False, game_templates=GAME_TEMPLATES)


@bp.get("/api/v1/catalog/suggestions")
@panel.admin_required
@panel.broker_required
def api_suggestions():
    """Busca por nome ou App ID numa lista FIXA (gerada do LinuxGSM, no repositorio): nada aqui
    vai a internet, e a consulta so seleciona entre entradas conhecidas."""
    found = catalog_search.search(request.args.get("q", ""))
    return jsonify({"resultados": [catalog_search.result(s) for s in found],
                    "fonte": catalog_search.SOURCE})


@bp.post("/catalog/new")
@panel.admin_required
@panel.broker_required
def catalog_new():
    data, failures = panel._game_from_form(request.form)
    if not failures:
        try:
            panel.broker_client.add_game(data, panel._actor())
        except panel.broker_client.BrokerError as exc:
            failures.append(f"Broker: {exc.message}")
    if failures:
        for failure in failures:
            flash(panel.translate(failure), "error")
        try:
            games = panel.broker_client.catalog()
        except panel.broker_client.BrokerError:
            games = []
        return render_template("catalog.html", games=games, recipes=panel.BROKER_RECIPES,
                               form=request.form, checked_recipes=request.form.getlist("recipes"),
                               editing=False, game_templates=GAME_TEMPLATES), 400
    # "key"/"name", e nao "chave"/"nome": o formulario ja manda os nomes em ingles, e com os
    # antigos o historico gravava a acao sem dizer qual jogo e o aviso saia sem o nome.
    panel._log_broker_action("broker-jogo", panel._actor(), data.get("key", ""), "Jogo adicionado ao catalogo.")
    flash(panel.translate("flash.game_added", name=data.get("name", data.get("key", ""))), "ok")
    return redirect(url_for("broker.catalog"))


def _form_of(game: dict) -> dict:
    """O jogo como o broker o guarda, no formato dos campos do formulario (texto)."""
    form = {k: "" if v is None else str(v) for k, v in game.items()
            if not isinstance(v, list | bool)}
    form["ports"] = " ".join(game.get("ports") or [])
    form["config_files"] = "\n".join(game.get("config_files") or [])
    form["backup_paths"] = "\n".join(game.get("backup_paths") or [])
    form["shiftable"] = "1" if game.get("shiftable") else ""
    # Porta 0 e "nao tem": no formulario ela e o campo vazio, que e como foi cadastrada.
    for field in ("query_port", "extra_port"):
        if form.get(field) == "0":
            form[field] = ""
    return form


def _render_edit(key: str, form, checked_recipes: list, source: str, status: int = 200):
    return render_template("catalog_edit.html", key=key, form=form, checked_recipes=checked_recipes,
                           source=source, recipes=panel.BROKER_RECIPES, editing=True), status


@bp.get("/catalog/<key>/edit")
@panel.admin_required
@panel.broker_required
def catalog_edit(key: str):
    try:
        game = panel.broker_client.game(key)
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        return redirect(url_for("broker.catalog"))
    return _render_edit(key, _form_of(game), list(game.get("recipes") or []), str(game.get("source", "")))


@bp.post("/catalog/<key>/edit")
@panel.admin_required
@panel.broker_required
def catalog_update(key: str):
    data, failures = panel._game_from_form(request.form)
    # A chave vem da URL, e nao do campo: ela e o que se esta editando, e o campo so leitura
    # ainda pode ser adulterado no envio.
    data["key"] = key
    if not failures:
        try:
            panel.broker_client.update_game(key, data, panel._actor())
        except panel.broker_client.BrokerError as exc:
            failures.append(f"Broker: {exc.message}")
    if failures:
        for failure in failures:
            flash(panel.translate(failure), "error")
        return _render_edit(key, request.form, request.form.getlist("recipes"),
                            request.form.get("source", ""), 400)
    panel._log_broker_action("broker-jogo-editar", panel._actor(), key, "Jogo do catalogo editado.")
    flash(panel.translate("flash.game_updated", name=data.get("name", key)), "ok")
    return redirect(url_for("broker.catalog"))


@bp.post("/catalog/<key>/delete")
@panel.admin_required
@panel.broker_required
def catalog_remove(key: str):
    try:
        restored = panel.broker_client.remove_game(key, panel._actor())
    except panel.broker_client.BrokerError as failure:
        panel._log_broker_action("broker-jogo-apagar", panel._actor(), key, failure.message, "error")
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        return redirect(url_for("broker.catalog"))
    if restored:
        panel._log_broker_action("broker-jogo-apagar", panel._actor(), key,
                                 "Edicao desfeita: vale de novo o arquivo do repositorio.")
        flash(panel.translate("flash.game_restored", name=restored.get("name", key)), "ok")
    else:
        panel._log_broker_action("broker-jogo-apagar", panel._actor(), key, "Jogo apagado do catalogo.")
        flash(panel.translate("flash.game_removed", name=key), "ok")
    return redirect(url_for("broker.catalog"))


@bp.get("/instances")
@panel.admin_required
@panel.broker_required
def instances():
    try:
        instances = panel.broker_client.instances()
        games = [j for j in panel.broker_client.catalog() if j.get("creatable")]
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        instances, games = [], []
    bound = {
        r["broker_id"]: r
        for r in servers_repo.from_broker(panel.db())
    }
    return render_template("instances.html", instances=instances, games=games, servers=bound)


@bp.post("/instances/new")
@panel.admin_required
@panel.broker_required
def instance_new():
    game = (request.form.get("game") or "").strip()
    name = (request.form.get("name") or "").strip()
    try:
        response = panel.broker_client.create(game, name, panel._actor())
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        return redirect(url_for("broker.instances"))
    op_id = str(response.get("operation_id", ""))
    if not op_id:
        flash(panel.translate("flash.broker_no_operation_id"), "error")
        return redirect(url_for("broker.instances"))
    job_id = panel.start_broker_job("broker-criar", panel._actor(), op_id, f"{game}: {name}")
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/instances/<int:iid>/deactivate")
@panel.admin_required
@panel.broker_required
def instance_deactivate(iid: int):
    try:
        panel.broker_client.deactivate(iid, panel._actor())
    except panel.broker_client.BrokerError as failure:
        panel._log_broker_action("broker-desativar", panel._actor(), f"instancia {iid}", failure.message, "error")
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
    else:
        panel._log_broker_action("broker-desativar", panel._actor(), f"instancia {iid}",
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
        panel.broker_client.remove(iid, confirm, panel._actor(), db_only)
    except panel.broker_client.BrokerError as failure:
        panel._log_broker_action("broker-remover", panel._actor(), f"instancia {iid}", failure.message, "error")
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        return redirect(url_for("broker.instances"))
    conn = panel.db()
    with conn:
        # O servidor do painel aponta para um container que deixou de existir.
        servers_repo.delete_by_broker_id(conn, iid)
    panel._log_broker_action(
        "broker-remover", panel._actor(), f"instancia {iid}",
        "So o registro foi esquecido." if db_only else "Container destruido e servidor removido do painel.")
    flash(panel.translate("flash.instance_removed"), "ok")
    return redirect(url_for("broker.instances"))
