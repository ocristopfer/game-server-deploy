"""Copias do save: tirar, listar, restaurar e apagar — no container e no painel.

Cada backup existe em dois lugares: no container do jogo e no disco do painel (ver
`runtime.backup_archive`). A copia do painel e a que sobrevive a remover a instancia, e
e por ela que um servidor recriado recupera o save do anterior.
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
    """Dispara o backup. E operacao, nao administracao: o operador pode tirar copia."""
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
    """Volta o servidor para uma copia. Para o jogo, extrai e religa."""
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
    """Copia de seguranca, (a copia do painel volta ao container,) extrai, e guarda a de
    seguranca no painel tambem.

    A copia de seguranca vem ANTES de extrair: restaurar e a operacao mais destrutiva do
    painel, e sem ela quem escolhe o backup errado nao tem para onde voltar. Os passos
    param no primeiro que falha — sem a copia de seguranca, nada e extraido.
    """
    steps: list = []
    if paths:
        steps.append(panel.backup_command(server, paths, "-antes-de-restaurar"))
    if from_panel:
        steps.append(panel.push_panel_backup_step(name))
    steps.append(panel.q("bash", "-lc", panel.RESTORE_SCRIPT, "gp", panel.BACKUP_DIR, name, server["service"]))
    if paths:
        steps.append(panel.pull_new_backup_step)
    return steps


@bp.post("/servers/<int:sid>/backups/send-to-panel")
@panel.admin_required
def send_to_panel(sid: int):
    """Guarda no painel uma copia que so existia no container (as de antes desta funcao)."""
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
    """Restaura a partir da copia do PAINEL: o caso do servidor removido e criado de novo,
    em que o container novo nao tem copia nenhuma."""
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
    """Tira a copia do container. Mesmo streaming do download de arquivo."""
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


# ------------------------------------------------ todas as copias do painel
#
# A aba Backups de um servidor so mostra o jogo DELE. Esta tela mostra tudo o que o painel
# guardou, inclusive o jogo cujo servidor ja foi removido — que e justo o caso em que a
# copia do painel mais importa.

def _archive_target(prefix: str) -> dict:
    """O "servidor" do historico para a copia de um jogo que talvez ja nao tenha servidor:
    sem id, e o alvo diz que a acao foi no painel (`painel@valheim`)."""
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
            # Onde da para restaurar: o servidor do MESMO jogo. O tar guarda caminho
            # absoluto, entao o save de um jogo extraido no container de outro so espalharia
            # arquivo onde ninguem le.
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
