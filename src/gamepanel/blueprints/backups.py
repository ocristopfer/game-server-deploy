"""Copias do save: tirar, listar, restaurar e apagar."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, stream_with_context, url_for

from gamepanel import app as panel

bp = Blueprint("backups", __name__)


@bp.get("/servers/<int:sid>/backups")
@panel.login_required
def index(sid: int):
    server = panel._server_or_404(sid)
    caminhos = panel.backup_paths(server)
    copias, erro = [], ""
    try:
        copias = panel.list_backups(server)
    except panel.RemoteError as exc:
        erro = str(exc)
    return render_template(
        "backups.html", server=server, copias=copias, erro=erro, caminhos=caminhos,
        backup_dir=panel.BACKUP_DIR, manter=panel.BACKUP_KEEP,
    )


@bp.post("/servers/<int:sid>/backups/create")
@panel.login_required
def create(sid: int):
    """Dispara o backup. E operacao, nao administracao: o operador pode tirar copia."""
    server = panel._server_or_404(sid)
    caminhos = panel.backup_paths(server)
    if not caminhos:
        flash(panel.translate("flash.nothing_to_back_up"), "error")
        return redirect(url_for("backups.index", sid=sid))
    job_id = panel.start_job(
        "backup", server, session.get("username", "?"),
        remote_cmd=panel.backup_command(server, caminhos),
        command=", ".join(caminhos),
        timeout=panel.BACKUP_TIMEOUT,
    )
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/backups/restore")
@panel.admin_required
def restore(sid: int):
    """Volta o servidor para uma copia. Para o jogo, extrai e religa."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("nome", ""))
    caminhos = panel.backup_paths(server)

    # Copia de seguranca ANTES de extrair: restaurar e a operacao mais destrutiva do
    # painel, e sem isto quem escolhe o backup errado nao tem para onde voltar. Os dois
    # comandos vao num job so — se o backup falhar, o '&&' impede a restauracao.
    passos = []
    if caminhos:
        passos.append(panel.backup_command(server, caminhos, "-antes-de-restaurar"))
    passos.append(panel.q("bash", "-lc", panel.RESTORE_SCRIPT, "gp", panel.BACKUP_DIR, name, server["service"]))

    job_id = panel.start_job(
        "restore-backup", server, session.get("username", "?"),
        remote_cmd=" && ".join(passos),
        command=name,
        timeout=panel.BACKUP_TIMEOUT,
    )
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/backups/delete")
@panel.admin_required
def delete(sid: int):
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.form.get("nome", ""))
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
    """Tira a copia do container. Mesmo streaming do download de arquivo."""
    server = panel._server_or_404(sid)
    name = panel._backup_or_400(request.args.get("nome", ""))
    caminho = f"{panel.BACKUP_DIR.rstrip('/')}/{name}"
    try:
        info = panel.stat_file(server, caminho)
    except panel.RemoteError as exc:
        abort(400, str(exc))

    panel.log_job("download-file", server, session.get("username", "?"),
            command=caminho, output=f"{info['size']} bytes")
    return panel.app.response_class(
        stream_with_context(panel.stream_remote_file(server, caminho)),
        mimetype="application/gzip",
        headers={
            "Content-Disposition": panel._attachment_header(info["name"]),
            "Content-Length": str(info["size"]),
            "X-Content-Type-Options": "nosniff",
        },
    )
