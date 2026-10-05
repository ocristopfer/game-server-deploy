"""The Config screen: the game's file as a form, one field per key."""
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
            # Here the form stops being "key = text" and starts knowing what each
            # field means: a boolean becomes a checkbox, an enum becomes a list, a duration shows in
            # minutes instead of nanoseconds.
            panel.enrich_settings(doc, info["name"])
        except (panel.RemoteError, panel.gameconf.ConfigError) as exc:
            # `error_text` keeps the KEY of a `Message` (ConfigError), so the reason comes out in
            # the language of whoever is looking and not in the deploy language.
            errors.append(f"{target}: {panel.translate(panel.error_text(exc))}")

    suggestions = panel._suggestion_config(server, file_names, target, errors)

    return render_template(
        "config.html", server=server, files=file_names, target=target, doc=doc, info=info,
        suggestions=suggestions, errors=errors, registered=target in file_names,
        max_files=panel.CONFIG_FILES_MAX,
    )


@bp.post("/servers/<int:sid>/config/files")
@panel.admin_required
def register_file(sid: int):
    """Register (or remove) a file from the quick screen, with one click."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("config_quick.index", sid=sid))

    paths = panel.config_paths(server)
    if request.form.get("action") == "remover":
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
def save(sid: int):  # noqa: PLR0911 - each validation error leaves through its own return
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("config_quick.index", sid=sid))
    # Same guard as config_quick, now on write: the path arrives through the form.
    if path not in panel.config_paths(server) and not panel.is_admin():
        abort(403, i18n.Message("error.operator_saves_registered_only"))

    go_back = url_for("config_quick.index", sid=sid, file=path)
    try:
        # The file name picks the catalog: it is what says what to validate and in which
        # unit the value was typed.
        edits, validation_failures = panel._edits_from_form(request.form, path.rsplit("/", 1)[-1])
    except panel.gameconf.ConfigError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(go_back)
    if validation_failures:
        # Nothing is saved when there is an error: saving half the changes would leave the file
        # in a state the person did not ask for and does not know.
        flash(panel.translate("flash.value_out_of_range",
                       errors="; ".join(validation_failures[:3])), "error")
        return redirect(go_back)
    if not edits:
        flash(panel.translate("flash.no_field_changed"), "ok")
        return redirect(go_back)

    # The file is reread NOW: the game may have rewritten it since the screen opened, and the
    # changes are applied by key, not by line number.
    try:
        doc, info = panel.load_config_doc(server, path)
        text = doc.apply(edits)
    except (panel.RemoteError, panel.gameconf.ConfigError) as exc:
        flash(panel.translate("flash.could_not_save", reason=panel.error_text(exc)), "error")
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
        flash(panel.translate("flash.could_not_save", reason=panel.error_text(exc)), "error")
        return redirect(go_back)

    panel.log_job("edit-config", server, session.get("username", "?"),
            command=f"{path}: {touched}", output=f"{output}\nalterado: {touched}")
    flash(panel.translate("flash.settings_saved", n=len(edits), path=path,
                       keys=touched), "ok")

    # Almost every game only reads its configuration at start, which is why restart lives here.
    if request.form.get("restart") == "1":
        job_id = panel.start_job("restart", server, session.get("username", "?"))
        panel.invalidate_status(sid)
        return redirect(url_for("jobs.detail", jid=job_id))
    return redirect(go_back)
