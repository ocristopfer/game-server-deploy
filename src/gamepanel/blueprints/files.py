"""Browse, edit, upload and download the container's files."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, stream_with_context, url_for

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.runtime import remote_cmd

bp = Blueprint("files", __name__)


@bp.get("/servers/<int:sid>/files")
@panel.admin_required
def index(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    default_dir = server["config_path"] or panel.FILE_DEFAULT_PATH

    entries: list[dict] = []
    truncated = False
    errors: list[str] = []
    opened = None

    file_arg = request.args.get("file", "").strip()
    dir_arg = request.args.get("path", "").strip()

    try:
        current = panel.clean_path(file_arg or dir_arg or default_dir)
    except ValueError as exc:
        errors.append(panel.translate(panel.error_text(exc)))
        current = "/"
    if file_arg and current != "/":
        try:
            opened = panel.read_file(server, current)
        except panel.RemoteError as exc:
            errors.append(panel.translate(panel.error_text(exc)))
        current = panel.parent_of(current)

    try:
        entries, truncated = panel.list_dir(server, current)
    except panel.RemoteError as exc:
        errors.append(panel.translate(panel.error_text(exc)))

    # Breadcrumbs: /opt/game/Pal -> [/, /opt, /opt/game, /opt/game/Pal]
    crumbs, walked = [{"name": "/", "path": "/"}], ""
    for seg in current.strip("/").split("/"):
        if not seg:
            continue
        walked += "/" + seg
        crumbs.append({"name": seg, "path": walked})

    return render_template(
        "files.html", server=server, entries=entries, truncated=truncated,
        current=current, crumbs=crumbs, opened=opened, errors=errors,
        max_kb=panel.FILE_MAX_BYTES // 1024, preview_kb=panel.FILE_PREVIEW_BYTES // 1024,
    )


@bp.post("/servers/<int:sid>/files/save")
@panel.admin_required
def save(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    raw_path = request.form.get("path", "")
    content = request.form.get("content", "")
    keep_crlf = request.form.get("crlf") == "1"

    try:
        path = panel.clean_path(raw_path)
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("files.index", sid=sid))

    # The browser sends \r\n; we only give it back that way if the original file already used CRLF.
    text = content.replace("\r\n", "\n")
    if keep_crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if len(data) > panel.FILE_MAX_BYTES:
        flash(panel.translate("flash.file_too_big", kb=panel.FILE_MAX_BYTES // 1024), "error")
        return redirect(url_for("files.index", sid=sid, file=path))

    # The file may have grown since the screen opened (log, game save). Writing
    # what is in the textarea now would erase everything that did not fit in it.
    try:
        current_one = panel.stat_file(server, path)
        if current_one["size"] > panel.FILE_MAX_BYTES:
            flash(panel.translate("flash.file_over_edit_limit", path=path,
                              size=current_one["size"] // 1024, kb=panel.FILE_MAX_BYTES // 1024), "error")
            return redirect(url_for("files.index", sid=sid, file=path))
    except panel.RemoteError:
        pass  # new file, or stat failed: the write itself reports the error

    try:
        output = panel.write_file(server, path, data)
        panel.log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=output,
        )
        flash(panel.translate("flash.file_saved", path=path, bytes=len(data)), "ok")
    except panel.RemoteError as exc:
        panel.log_job(
            "edit-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(panel.translate("flash.could_not_save", reason=panel.error_text(exc)), "error")

    return redirect(url_for("files.index", sid=sid, file=path))


@bp.post("/servers/<int:sid>/files/delete")
@panel.admin_required
def delete(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)

    try:
        path = panel.clean_path(request.form.get("path", ""))
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(url_for("files.index", sid=sid))

    # An allowed root is never deleted: without this a wrong click could take the whole of
    # /opt/game (the folder only goes when empty, but not even that case is worth allowing).
    roots = {"/"} | {r.rstrip("/") or "/" for r in panel.FILE_ROOTS}
    if path in roots:
        flash(panel.translate("flash.is_a_root_folder", path=path), "error")
        return redirect(url_for("files.index", sid=sid, path=path))

    round_trip = panel.parent_of(path)
    try:
        output = panel.delete_file(server, path)
        panel.log_job("delete-file", server, session.get("username", "?"), command=path, output=output)
        flash(panel.translate("flash.deleted_no_bak", output=output), "ok")
        # A file pinned on the Config screen that no longer exists: removing it from the registry keeps
        # the screen from always opening on a read error.
        registered = panel.config_paths(server)
        if path in registered:
            panel._save_config_files(sid, [p for p in registered if p != path])
            flash(panel.translate("flash.also_left_config", path=path), "ok")
    except panel.RemoteError as exc:
        panel.log_job(
            "delete-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(panel.translate("flash.could_not_delete", reason=panel.error_text(exc)), "error")

    return redirect(url_for("files.index", sid=sid, path=round_trip))


@bp.get("/servers/<int:sid>/files/download")
@panel.admin_required
def download(sid: int):
    """Download any file from the container, including binary ones or ones too big for the editor."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.args.get("path", ""))
        info = panel.stat_file(server, path)
    except (ValueError, panel.RemoteError) as exc:
        abort(400, panel.error_text(exc))

    if panel.FILE_DOWNLOAD_MAX and info["size"] > panel.FILE_DOWNLOAD_MAX:
        abort(400, i18n.Message("error.download_too_large", size=info["size"],
                                limit=panel.FILE_DOWNLOAD_MAX))

    panel.log_job(
        "download-file", server, session.get("username", "?"),
        command=path, output=f"{info['size']} bytes",
    )
    return panel.app.response_class(
        stream_with_context(panel.stream_remote_file(server, path)),
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": panel._attachment_header(info["name"]),
            "Content-Length": str(info["size"]),
            "X-Content-Type-Options": "nosniff",
        },
    )


@bp.post("/servers/<int:sid>/files/upload")
@panel.admin_required
def upload(sid: int):
    """Send a file from the computer into the container (mod, save, config)."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    # This request's cap was already raised in _body_cap (BIG_BODY_ENDPOINTS).
    target_dir = request.form.get("path", "") or panel.FILE_DEFAULT_PATH
    go_back = url_for("files.index", sid=sid, path=target_dir)
    sent_value = request.files.get("file")
    if not sent_value or not sent_value.filename:
        flash(panel.translate("flash.pick_a_file"), "error")
        return redirect(go_back)

    # The browser sends the name as the source disk had it: only the last part is kept,
    # so "../../etc/passwd" does not become a path.
    name = sent_value.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in (".", ".."):
        flash(panel.translate("flash.bad_file_name"), "error")
        return redirect(go_back)

    try:
        folder = panel.clean_path(target_dir)
        target = panel.clean_path(f"{folder.rstrip('/')}/{name}")
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(go_back)

    try:
        output = panel.ssh_stream_in(
            server, remote_cmd.as_steam(server, "bash", "-lc", panel.UPLOAD_SCRIPT, "gp", target),
            sent_value.stream, timeout=panel.JOB_TIMEOUT,
        )
    except panel.RemoteError as exc:
        panel.log_job("upload-file", server, session.get("username", "?"),
                command=target, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_upload", reason=panel.error_text(exc)), "error")
        return redirect(go_back)

    panel.log_job("upload-file", server, session.get("username", "?"), command=target, output=output)
    flash(panel.translate("flash.uploaded", output=output), "ok")
    return redirect(url_for("files.index", sid=sid, path=folder))
