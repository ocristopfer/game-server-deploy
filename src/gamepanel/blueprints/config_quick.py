"""A tela Config: o arquivo do jogo como formulario, um campo por chave."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel import i18n

bp = Blueprint("config_quick", __name__)


@bp.get("/servers/<int:sid>/config")
@panel.login_required
def index(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    file_names = panel.config_paths(server)
    errors: list[str] = []
    target = panel._target_config(file_names, errors)

    doc = info = None
    if target:
        try:
            doc, info = panel.load_config_doc(server, target)
            # Aqui o formulario deixa de ser "chave = texto" e passa a saber o que cada
            # campo significa: booleano vira caixa, enum vira lista, duracao aparece em
            # minutos em vez de nanossegundos.
            panel.enrich_settings(doc, info["name"])
        except (panel.RemoteError, panel.gameconf.ConfigError) as exc:
            errors.append(f"{target}: {exc}")

    suggestions = panel._suggestion_config(server, file_names, target, errors)

    return render_template(
        "config.html", server=server, files=file_names, target=target, doc=doc, info=info,
        suggestions=suggestions, errors=errors, registered=target in file_names,
        max_files=panel.CONFIG_FILES_MAX,
    )


@bp.post("/servers/<int:sid>/config/files")
@panel.admin_required
def register_file(sid: int):
    """Registra (ou tira) um arquivo da tela rapida, com um clique."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("config_quick.index", sid=sid))

    paths = panel.config_paths(server)
    if request.form.get("acao") == "remover":
        paths = [p for p in paths if p != path]
        panel._save_config_files(sid, paths)
        flash(panel.translate("flash.left_config_screen", path=path), "ok")
        return redirect(url_for("config_quick.index", sid=sid))

    if path in paths:
        return redirect(url_for("config_quick.index", sid=sid, file=path))
    if len(paths) >= panel.CONFIG_FILES_MAX:
        flash(panel.translate("flash.config_files_limit", n=panel.CONFIG_FILES_MAX), "error")
        return redirect(url_for("config_quick.index", sid=sid))
    paths.append(path)
    panel._save_config_files(sid, paths)
    flash(panel.translate("flash.now_opens_in_config", path=path), "ok")
    return redirect(url_for("config_quick.index", sid=sid, file=path))


@bp.post("/servers/<int:sid>/config/save")
@panel.login_required
def save(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("config_quick.index", sid=sid))
    # Mesma trava do config_quick, agora na escrita: o caminho chega pelo formulario.
    if path not in panel.config_paths(server) and not panel.is_admin():
        abort(403, i18n.Message("error.operator_saves_registered_only"))

    go_back = url_for("config_quick.index", sid=sid, file=path)
    try:
        # O nome do arquivo escolhe o catalogo: e ele que diz o que validar e em que
        # unidade o valor foi digitado.
        edits, validation_failures = panel._edits_from_form(request.form, path.rsplit("/", 1)[-1])
    except panel.gameconf.ConfigError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(go_back)
    if validation_failures:
        # Nada e gravado quando ha erro: salvar metade das alteracoes deixaria o arquivo
        # num estado que a pessoa nao pediu e nao sabe qual e.
        flash(panel.translate("flash.value_out_of_range",
                       errors="; ".join(validation_failures[:3])), "error")
        return redirect(go_back)
    if not edits:
        flash(panel.translate("flash.no_field_changed"), "ok")
        return redirect(go_back)

    # O arquivo e relido AGORA: o jogo pode te-lo reescrito desde que a tela abriu, e as
    # alteracoes sao aplicadas por chave — nao por numero de linha.
    try:
        doc, info = panel.load_config_doc(server, path)
        text = doc.apply(edits)
    except (panel.RemoteError, panel.gameconf.ConfigError) as exc:
        flash(panel.translate("flash.could_not_save", reason=exc), "error")
        return redirect(go_back)

    if info["crlf"]:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if len(data) > panel.FILE_MAX_BYTES:
        flash(panel.translate("flash.file_too_big", kb=panel.FILE_MAX_BYTES // 1024), "error")
        return redirect(go_back)

    touched = ", ".join(dict.fromkeys(e.key for e in edits))
    try:
        output = panel.write_file(server, path, data)
    except panel.RemoteError as exc:
        panel.log_job("edit-config", server, session.get("username", "?"),
                command=f"{path}: {touched}", output=str(exc), status="error")
        flash(panel.translate("flash.could_not_save", reason=exc), "error")
        return redirect(go_back)

    panel.log_job("edit-config", server, session.get("username", "?"),
            command=f"{path}: {touched}", output=f"{output}\nalterado: {touched}")
    flash(panel.translate("flash.settings_saved", n=len(edits), path=path,
                       keys=touched), "ok")

    # Quase todo jogo so le a configuracao no start — por isso o reiniciar mora aqui.
    if request.form.get("restart") == "1":
        job_id = panel.start_job("restart", server, session.get("username", "?"))
        panel.invalidate_status(sid)
        return redirect(url_for("jobs.detail", jid=job_id))
    return redirect(go_back)
