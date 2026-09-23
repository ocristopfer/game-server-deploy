"""Navegar, editar, enviar e baixar os arquivos do container."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, stream_with_context, url_for

from gamepanel import app as panel

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
        errors.append(str(exc))
        current = "/"
    if file_arg and current != "/":
        try:
            opened = panel.read_file(server, current)
        except panel.RemoteError as exc:
            errors.append(str(exc))
        current = panel.parent_of(current)

    try:
        entries, truncated = panel.list_dir(server, current)
    except panel.RemoteError as exc:
        errors.append(str(exc))

    # Migalhas de pao: /opt/game/Pal -> [/, /opt, /opt/game, /opt/game/Pal]
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


@bp.get("/servers/<int:sid>/files/search")
@panel.admin_required
def search(sid: int):
    """Procurar arquivos de configuracao — agora numa tela so.

    Isto era uma SEGUNDA implementacao da mesma coisa: `find_config_files` numa lista
    dentro de Arquivos, e a mesma `find_config_files` na mesma lista dentro de
    Configuracao. Duas telas, dois botoes chamados "Procurar", um resultado que so
    valia num dos dois lugares (so a tela de Configuracao sabe fixar o arquivo
    encontrado).

    A busca ficou onde ela serve para alguma coisa. Esta rota continua existindo para
    nao quebrar link antigo nem historico de navegador.
    """
    panel._server_or_404(sid)
    # `pasta` so entra na URL quando existe: `pasta=` vazio faria a busca procurar na
    # raiz do container em vez da pasta de config do cadastro.
    extras: dict[str, panel.Any] = {"pasta": request.args["path"]} if request.args.get("path") else {}
    return redirect(url_for("config_quick.index", sid=sid, descobrir=1, **extras))


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

    # O navegador manda \r\n; so devolvemos assim se o arquivo original ja usava CRLF.
    text = content.replace("\r\n", "\n")
    if keep_crlf:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if len(data) > panel.FILE_MAX_BYTES:
        flash(panel.translate("flash.file_too_big", kb=panel.FILE_MAX_BYTES // 1024), "error")
        return redirect(url_for("files.index", sid=sid, file=path))

    # O arquivo pode ter crescido desde que a tela abriu (log, save do jogo). Gravar o
    # que esta no textarea agora apagaria tudo o que nao coube nele.
    try:
        atual = panel.stat_file(server, path)
        if atual["size"] > panel.FILE_MAX_BYTES:
            flash(panel.translate("flash.file_over_edit_limit", path=path,
                              size=atual["size"] // 1024, kb=panel.FILE_MAX_BYTES // 1024), "error")
            return redirect(url_for("files.index", sid=sid, file=path))
    except panel.RemoteError:
        pass  # arquivo novo, ou stat falhou: o proprio gravar reporta o erro

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
        flash(panel.translate("flash.could_not_save", reason=exc), "error")

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

    # Raiz permitida nao se apaga: sem isso um clique errado poderia levar /opt/game
    # inteiro (a pasta so cai vazia, mas nem esse caso vale a pena permitir).
    raizes = {"/"} | {r.rstrip("/") or "/" for r in panel.FILE_ROOTS}
    if path in raizes:
        flash(panel.translate("flash.is_a_root_folder", path=path), "error")
        return redirect(url_for("files.index", sid=sid, path=path))

    volta = panel.parent_of(path)
    try:
        output = panel.delete_file(server, path)
        panel.log_job("delete-file", server, session.get("username", "?"), command=path, output=output)
        flash(panel.translate("flash.deleted_no_bak", output=output), "ok")
        # Arquivo fixado na tela Config que deixou de existir: tirar do cadastro evita
        # que a tela abra sempre num erro de leitura.
        registrados = panel.config_paths(server)
        if path in registrados:
            panel._save_config_files(sid, [p for p in registrados if p != path])
            flash(panel.translate("flash.also_left_config", path=path), "ok")
    except panel.RemoteError as exc:
        panel.log_job(
            "delete-file", server, session.get("username", "?"),
            command=path, output=str(exc), status="error",
        )
        flash(panel.translate("flash.could_not_delete", reason=exc), "error")

    return redirect(url_for("files.index", sid=sid, path=volta))


@bp.get("/servers/<int:sid>/files/download")
@panel.admin_required
def download(sid: int):
    """Baixa qualquer arquivo do container — inclusive binario ou grande demais para o editor."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    try:
        path = panel.clean_path(request.args.get("path", ""))
        info = panel.stat_file(server, path)
    except (ValueError, panel.RemoteError) as exc:
        abort(400, str(exc))

    if panel.FILE_DOWNLOAD_MAX and info["size"] > panel.FILE_DOWNLOAD_MAX:
        abort(400, f"arquivo de {info['size']} bytes acima do limite de download"
                   f" ({panel.FILE_DOWNLOAD_MAX} bytes) — use scp para este")

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
    """Manda um arquivo do computador para dentro do container (mod, save, config)."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    # O teto deste request ja foi levantado no _teto_do_corpo (BIG_BODY_ENDPOINTS).
    destino_dir = request.form.get("path", "") or panel.FILE_DEFAULT_PATH
    voltar = url_for("files.index", sid=sid, path=destino_dir)
    enviado = request.files.get("arquivo")
    if not enviado or not enviado.filename:
        flash(panel.translate("flash.pick_a_file"), "error")
        return redirect(voltar)

    # O navegador manda o nome como o disco de origem o tinha: fica so a ultima parte,
    # para "../../etc/passwd" nao virar caminho.
    name = enviado.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in (".", ".."):
        flash(panel.translate("flash.bad_file_name"), "error")
        return redirect(voltar)

    try:
        pasta = panel.clean_path(destino_dir)
        alvo = panel.clean_path(f"{pasta.rstrip('/')}/{name}")
    except ValueError as exc:
        flash(panel.translate(panel.error_text(exc)), "error")
        return redirect(voltar)

    try:
        output = panel.ssh_stream_in(
            server, panel.q("bash", "-lc", panel.UPLOAD_SCRIPT, "gp", alvo),
            enviado.stream, timeout=panel.JOB_TIMEOUT,
        )
    except panel.RemoteError as exc:
        panel.log_job("upload-file", server, session.get("username", "?"),
                command=alvo, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_upload", reason=exc), "error")
        return redirect(voltar)

    panel.log_job("upload-file", server, session.get("username", "?"), command=alvo, output=output)
    flash(panel.translate("flash.uploaded", output=output), "ok")
    return redirect(url_for("files.index", sid=sid, path=pasta))
