"""Game catalog and the instances created by the broker."""
from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.games.catalog import search as catalog_search
from gamepanel.games.catalog import templates as game_templates
from gamepanel.persistence.repositories import jobs as jobs_repo
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
    return _catalog_page(games, form={}, checked_recipes=[])


def _catalog_page(games: list, form, checked_recipes: list, status: int = 200):
    """The catalog screen, the same on GET and when coming back from a rejected submission."""
    # What the search needs to say "already in the catalog" without asking the server: it is
    # what was missing for V Rising (curated) not to show up as "nothing found".
    index = [{"key": g.get("key", ""), "name": g.get("name", ""), "app_id": g.get("app_id") or 0,
              "creatable": bool(g.get("creatable"))} for g in games]
    return render_template("catalog.html", games=games, recipes=panel.BROKER_RECIPES, form=form,
                           checked_recipes=checked_recipes, editing=False,
                           game_templates=game_templates.TEMPLATES, catalog_index=index,
                           # The placeholder names each template asks to replace, mentioned in the
                           # description: the sentence comes from the i18n catalog, the name from here.
                           template_project=game_templates.PROJECT,
                           template_executable=game_templates.EXECUTABLE,
                           template_mod=game_templates.MOD), status


@bp.get("/api/v1/catalog/suggestions")
@panel.admin_required
@panel.broker_required
def api_suggestions():
    """Search by name or App ID in FIXED lists from the repository (LinuxGSM, Pterodactyl, curation):
    nothing here goes to the internet, and the query only selects among known entries."""
    found = catalog_search.search(request.args.get("q", ""))
    # Warnings and source of the hand-written list are catalog keys: translated here, in the
    # language of whoever is searching (the search module itself has no request).
    return jsonify({"resultados": [catalog_search.result(s, panel.translate) for s in found],
                    "fonte": catalog_search.source_text(panel.translate)})


@bp.post("/catalog/new")
@panel.admin_required
@panel.broker_required
def catalog_new():
    data, failures = panel._game_from_form(request.form)
    if not failures:
        try:
            panel.broker_client.add_game(data, panel._actor())
        except panel.broker_client.BrokerError as exc:
            # A `Message`, not an f-string: `translate` below then puts the reason in the viewer's
            # language too (the broker's own sentence passes as is).
            failures.append(i18n.Message("flash.broker_error", reason=exc.message))
    if failures:
        for failure in failures:
            flash(panel.translate(failure), "error")
        try:
            games = panel.broker_client.catalog()
        except panel.broker_client.BrokerError:
            games = []
        return _catalog_page(games, form=request.form,
                             checked_recipes=request.form.getlist("recipes"), status=400)
    # "key"/"name", not "chave"/"nome": the form already sends the names in English, and with the
    # old ones the history recorded the action without saying which game and the notice came out without the name.
    panel._log_broker_action("broker-jogo", panel._actor(), data.get("key", ""), "Jogo adicionado ao catalogo.")
    flash(panel.translate("flash.game_added", name=data.get("name", data.get("key", ""))), "ok")
    return redirect(url_for("broker.catalog"))


def _form_of(game: dict) -> dict:
    """The game as the broker stores it, in the format of the form fields (text)."""
    form = {k: "" if v is None else str(v) for k, v in game.items()
            if not isinstance(v, list | bool)}
    form["ports"] = " ".join(game.get("ports") or [])
    form["config_files"] = "\n".join(game.get("config_files") or [])
    form["backup_paths"] = "\n".join(game.get("backup_paths") or [])
    form["shiftable"] = "1" if game.get("shiftable") else ""
    # Port 0 means "none": in the form it is the empty field, which is how it was registered.
    for field in ("query_port", "extra_port", "client_app_id"):
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
    # The key comes from the URL, not from the field: it is what is being edited, and the read-only
    # field can still be tampered with on submit.
    data["key"] = key
    if not failures:
        try:
            panel.broker_client.update_game(key, data, panel._actor())
        except panel.broker_client.BrokerError as exc:
            # A `Message`, not an f-string: `translate` below then puts the reason in the viewer's
            # language too (the broker's own sentence passes as is).
            failures.append(i18n.Message("flash.broker_error", reason=exc.message))
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
    # ?game= comes from the catalog's "Create instance" shortcut: the game arrives already chosen.
    return render_template("instances.html", instances=instances, games=games, servers=bound,
                           selected_game=request.args.get("game", ""),
                           panel_copies=_panel_copies(instances, bound),
                           installing=jobs_repo.running_creations(panel.db()))


def _panel_copies(instances: list, bound: dict) -> dict:
    """How many save copies the PANEL has of each instance, and the newest one.

    It is what the screen shows at removal time: removing deletes the container and the copies
    inside it, and only what is on the panel survives. An instance without a server on the panel
    falls back to the game name, which is the service the broker gives it.
    """
    summary = {}
    for inst in instances:
        server = bound.get(inst.get("id")) or {"service": f"{inst.get('game', '')}.service"}
        try:
            copies = panel.list_panel_backups(server)
        except ValueError:
            copies = []
        summary[inst.get("id")] = {"count": len(copies), "latest": copies[0]["mtime"] if copies else ""}
    return summary


@bp.post("/instances/new")
@panel.admin_required
@panel.broker_required
def instance_new():
    """Two steps: first show the CT, IP and ports the instance will get, and only create
    when the person confirms. No JavaScript: the confirmation is a screen, not an alert."""
    game = (request.form.get("game") or "").strip()
    name = (request.form.get("name") or "").strip()
    if request.form.get("confirmed") != "1":
        return _confirm_instance(game, name)
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


def _confirm_instance(game: str, name: str):
    try:
        preview = panel.broker_client.preview(game)
        info = panel.broker_client.game(game)
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        return redirect(url_for("broker.instances"))
    return render_template("instance_confirm.html", game=game, game_name=info.get("name", game),
                           name=name, preview=preview)


@bp.post("/instances/jobs/<int:jid>/cancel")
@panel.admin_required
@panel.broker_required
def instance_cancel(jid: int):
    """Cancel the creation this job follows. The broker is what stops and undoes it: the created CT is
    deleted, and the job finishes on its own when its operation finishes."""
    job = jobs_repo.by_id(panel.db(), jid)
    if job is None or job["action"] != "broker-criar" or not job["broker_op"]:
        abort(404)
    if job["status"] != "running":
        flash(panel.translate("flash.install_already_finished"), "error")
        return redirect(url_for("jobs.detail", jid=jid))
    try:
        panel.broker_client.cancel(job["broker_op"], panel._actor())
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
    else:
        flash(panel.translate("flash.install_cancelling"), "ok")
    return redirect(url_for("jobs.detail", jid=jid))


@bp.post("/instances/<int:iid>/deactivate")
@panel.admin_required
@panel.broker_required
def instance_deactivate(iid: int):
    """Backup on the panel, and ONLY THEN deactivate.

    Deactivating is the step before removing, and removing deletes the CT with its disks. Once
    deactivated the container is stopped and there is no SSH to take any copy: this is the
    last moment when the save can still be stored. If the backup fails, the instance
    stays active; whoever wants to go ahead anyway uses "without backup".
    """
    server = servers_repo.by_broker_id(panel.db(), iid)
    paths = panel.backup_paths(server) if server else []
    if server is None or request.form.get("skip_backup") == "1" or not paths:
        if not paths:
            flash(panel.translate("flash.deactivate_without_backup"), "error")
        return _deactivate_now(iid)
    actor = panel._actor()
    job_id = panel.start_job(
        "broker-desativar", server, actor,
        steps=[*panel.backup_steps(server, paths), _deactivate_step(iid, actor)],
        command=f"instancia {iid}: backup e desativacao",
        timeout=panel.BACKUP_TIMEOUT,
    )
    return redirect(url_for("jobs.detail", jid=job_id))


def _deactivate_step(iid: int, actor: str):
    def step(_target: dict, _output: str) -> str:
        try:
            panel.broker_client.deactivate(iid, actor)
        except panel.broker_client.BrokerError as failure:
            raise panel.RemoteError(
                f"o backup foi guardado, mas o broker recusou a desativacao: {failure.message}") from failure
        return "Portas fechadas no firewall e container parado.\n"
    return step


def _deactivate_now(iid: int):
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
        # The panel's server points at a container that no longer exists.
        servers_repo.delete_by_broker_id(conn, iid)
    panel._log_broker_action(
        "broker-remover", panel._actor(), f"instancia {iid}",
        "So o registro foi esquecido." if db_only else "Container destruido e servidor removido do painel.")
    flash(panel.translate("flash.instance_removed"), "ok")
    return redirect(url_for("broker.instances"))


# ------------------------------------------------------------------ the broker's own updates

@bp.get("/broker/update")
@panel.admin_required
@panel.broker_required
def update():
    """The broker's version and its root updater's last status, read through the broker API."""
    try:
        info = panel.broker_client.update_info()
    except panel.broker_client.BrokerError as failure:
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
        info = None
    return render_template("broker_update.html", info=info)


def _update_request(action: str, done_key: str):
    try:
        panel.broker_client.request_update(action, panel._actor())
    except panel.broker_client.BrokerError as failure:
        panel._log_broker_action("broker-atualizar", panel._actor(), action, str(failure.message), "error")
        flash(panel.translate("flash.broker_error", reason=failure.message), "error")
    else:
        # An install restarts the broker: the history says who asked for it, and when.
        panel._log_broker_action("broker-atualizar", panel._actor(), action, "Pedido enviado ao atualizador do broker.")
        flash(panel.translate(done_key), "ok")
    return redirect(url_for("broker.update"))


@bp.post("/broker/update/check")
@panel.admin_required
@panel.broker_required
def update_check():
    return _update_request("check", "broker_update.check_requested")


@bp.post("/broker/update/install")
@panel.admin_required
@panel.broker_required
def update_install():
    return _update_request("install", "broker_update.install_requested")
