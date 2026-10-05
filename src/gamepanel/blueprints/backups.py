"""Save copies: take, list, restore and delete, in the container and on the panel.

Each backup exists in two places: in the game container and on the panel's disk (see
`runtime.backup_archive`). The panel copy is the one that survives removing the instance, and
it is how a recreated server recovers the previous one's save.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    stream_with_context,
    url_for,
)

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("backups", __name__)


@bp.get("/servers/<int:sid>/backups")
@panel.login_required
def index(sid: int):
    server = panel._server_or_404(sid)
    paths = panel.backup_paths(server)
    copies, failure = [], ""
    try:
        copies = panel.list_backups(server)
    except panel.RemoteError as exc:
        failure = str(exc)
    return render_template(
        "backups.html", server=server, copies=copies, error=failure, paths=paths,
        backup_dir=panel.BACKUP_DIR, keep=panel.BACKUP_KEEP,
        panel_copies=panel.list_panel_backups(server), panel_keep=panel.PANEL_BACKUP_KEEP,
    )


@bp.post("/servers/<int:sid>/backups/create")
@panel.login_required
def create(sid: int):
    """Trigger the backup. It is an operation, not administration: the operator may take a copy."""
    server = panel._server_or_404(sid)
    paths = panel.backup_paths(server)
    if not paths:
        flash(panel.translate("flash.nothing_to_back_up"), "error")
        return redirect(url_for("backups.index", sid=sid))
    job_id = panel.start_job(
        "backup", server, session.get("username", "?"),
        steps=panel.backup_steps(server, paths),
        command=", ".join(paths),
        timeout=panel.BACKUP_TIMEOUT,
    )
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/backups/restore")
@panel.admin_required
def restore(sid: int):
    """Roll the server back to a copy. Stops the game, extracts and starts it again."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("name", ""))
    paths = panel.backup_paths(server)

    job_id = panel.start_job(
        "restore-backup", server, session.get("username", "?"),
        steps=_restore_steps(server, paths, name),
        command=name,
        timeout=panel.BACKUP_TIMEOUT,
    )
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


def _restore_steps(server, paths: list[str], name: str, from_panel: bool = False) -> list:
    """Safety copy, (the panel copy goes back to the container,) extract, and store the
    safety copy on the panel too.

    The safety copy comes BEFORE extracting: restoring is the most destructive operation in
    the panel, and without it whoever picks the wrong backup has nowhere to go back to. The steps
    stop at the first one that fails: without the safety copy, nothing is extracted.
    """
    steps: list = []
    if paths:
        steps.append(panel.backup_command(server, paths, "-antes-de-restaurar"))
    if from_panel:
        steps.append(panel.push_panel_backup_step(name))
    # The backup paths travel along: the restore only extracts what is under them, and refuses
    # the whole archive if a member points anywhere else.
    steps.append(panel.restore_command(server, paths, name))
    if paths:
        steps.append(panel.pull_new_backup_step)
    return steps


@bp.post("/servers/<int:sid>/backups/send-to-panel")
@panel.admin_required
def send_to_panel(sid: int):
    """Store on the panel a copy that only existed in the container (the ones from before this function)."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("name", ""))
    job_id = panel.start_job(
        "backup-to-panel", server, session.get("username", "?"),
        steps=[panel.pull_existing_backup_step(name)],
        command=name,
        timeout=panel.BACKUP_TIMEOUT,
    )
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/backups/panel/restore")
@panel.admin_required
def panel_restore(sid: int):
    """Restore from the PANEL copy: the case of a server removed and created again,
    where the new container has no copy at all."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("name", ""))
    try:
        panel.panel_backup_path(server, name)
    except FileNotFoundError:
        abort(404)
    job_id = panel.start_job(
        "restore-backup", server, session.get("username", "?"),
        steps=_restore_steps(server, panel.backup_paths(server), name, from_panel=True),
        command=f"painel: {name}",
        timeout=panel.BACKUP_TIMEOUT,
    )
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/backups/panel/delete")
@panel.admin_required
def panel_delete(sid: int):
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("name", ""))
    try:
        size = panel.delete_panel_backup(server, name)
    except FileNotFoundError:
        abort(404)
    panel.log_job("delete-backup", server, session.get("username", "?"),
                  command=f"painel: {name}", output=f"copia do painel apagada: {name} ({size} bytes)")
    flash(panel.translate("flash.panel_backup_deleted", file=name), "ok")
    return redirect(url_for("backups.index", sid=sid))


@bp.get("/servers/<int:sid>/backups/panel/download")
@panel.admin_required
def panel_download(sid: int):
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.args.get("name", ""))
    try:
        path = panel.panel_backup_path(server, name)
    except FileNotFoundError:
        abort(404)
    panel.log_job("download-file", server, session.get("username", "?"), command=f"painel: {name}")
    return send_file(path, mimetype="application/gzip", as_attachment=True, download_name=name)


@bp.post("/servers/<int:sid>/backups/delete")
@panel.admin_required
def delete(sid: int):
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("name", ""))
    try:
        output = panel.delete_backup(server, name)
    except panel.RemoteError as exc:
        panel.log_job("delete-backup", server, session.get("username", "?"),
                command=name, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_delete", reason=exc), "error")
        return redirect(url_for("backups.index", sid=sid))
    panel.log_job("delete-backup", server, session.get("username", "?"), command=name, output=output)
    flash(output, "ok")
    return redirect(url_for("backups.index", sid=sid))


@bp.get("/servers/<int:sid>/backups/download")
@panel.admin_required
def download(sid: int):
    """Fetch the copy from the container. Same streaming as the file download."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.args.get("name", ""))
    path = f"{panel.BACKUP_DIR.rstrip('/')}/{name}"
    try:
        info = panel.stat_file(server, path)
    except panel.RemoteError as exc:
        abort(400, str(exc))

    panel.log_job("download-file", server, session.get("username", "?"),
            command=path, output=f"{info['size']} bytes")
    return panel.app.response_class(
        stream_with_context(panel.stream_remote_file(server, path)),
        mimetype="application/gzip",
        headers={
            "Content-Disposition": panel._attachment_header(info["name"]),
            "Content-Length": str(info["size"]),
            "X-Content-Type-Options": "nosniff",
        },
    )


# ------------------------------------------------ every copy on the panel
#
# A server's Backups tab only shows ITS game. This screen shows everything the panel
# stored, including the game whose server has already been removed, which is exactly the case
# where the panel copy matters most.

def _archive_target(prefix: str) -> dict:
    """The history "server" for the copy of a game that may no longer have a server:
    no id, and the target says the action was on the panel (`painel@valheim`)."""
    return {"id": None, "ssh_user": "painel", "host": prefix}


def _archive_path_or_404(prefix: str, name: str) -> str:
    try:
        return panel.backup_archive.path_of(panel.PANEL_BACKUP_DIR, prefix, name)
    except (FileNotFoundError, ValueError):
        abort(404)


@bp.get("/backups")
@panel.admin_required
def archive():
    servers = [dict(s) for s in servers_repo.all_ordered(panel.db())]
    games = []
    for prefix in panel.backup_archive.list_games(panel.PANEL_BACKUP_DIR):
        games.append({
            "prefix": prefix,
            "copies": panel.backup_archive.list_copies(panel.PANEL_BACKUP_DIR, prefix),
            # Where it can be restored: the server of the SAME game. The tar stores absolute
            # paths, so one game's save extracted into another's container would only scatter
            # files where nobody reads them.
            "servers": [s for s in servers if panel.backup_prefix(s) == prefix],
        })
    return render_template("backup_archive.html", games=games, keep=panel.PANEL_BACKUP_KEEP,
                           archive_dir=panel.PANEL_BACKUP_DIR)


@bp.get("/backups/<prefix>/download")
@panel.admin_required
def archive_download(prefix: str):
    name = panel._backup_or_400(request.args.get("name", ""))
    path = _archive_path_or_404(prefix, name)
    panel.log_job("download-file", _archive_target(prefix), session.get("username", "?"),
                  command=f"painel: {name}")
    return send_file(path, mimetype="application/gzip", as_attachment=True, download_name=name)


@bp.post("/backups/<prefix>/delete")
@panel.admin_required
def archive_delete(prefix: str):
    name = panel._backup_or_400(request.form.get("name", ""))
    _archive_path_or_404(prefix, name)
    size = panel.backup_archive.delete(panel.PANEL_BACKUP_DIR, prefix, name)
    panel.log_job("delete-backup", _archive_target(prefix), session.get("username", "?"),
                  command=f"painel: {name}", output=f"copia do painel apagada: {name} ({size} bytes)")
    flash(panel.translate("flash.panel_backup_deleted", file=name), "ok")
    return redirect(url_for("backups.archive"))
