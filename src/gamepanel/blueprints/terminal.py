"""Terminal interativo por SSH, e as rotas que o JavaScript usa para toca-lo."""
from __future__ import annotations

import base64

from flask import Blueprint, abort, jsonify, render_template, request, session

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("terminal", __name__)


@bp.get("/servers/<int:sid>/terminal")
@panel.admin_required
def index(sid: int):
    panel._terminal_guard()
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    return render_template(
        "terminal.html", server=server, idle_timeout=panel.TERM_IDLE_TIMEOUT
    )


@bp.post("/api/v1/term/<int:sid>/open")
@panel.admin_required
def api_open(sid: int):
    panel._terminal_guard()
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    body = request.get_json(silent=True) or {}
    cols = max(20, min(400, int(body.get("cols") or 80)))
    rows = max(5, min(150, int(body.get("rows") or 24)))

    with panel._terms_lock:
        # Uma aba esquecida nao pode impedir a proxima de abrir: derruba as mortas.
        for dead in [t for t in panel._terms.values() if not t.alive]:
            panel._terms.pop(dead.id, None)
        if len(panel._terms) >= panel.TERM_MAX_SESSIONS:
            return jsonify({
                "error": f"limite de {panel.TERM_MAX_SESSIONS} terminais simultaneos atingido"
            }), 429

    try:
        term = panel._open_term(dict(server), session["uid"], session.get("username", "?"), cols, rows)
    except panel.RemoteError as exc:
        return jsonify({"error": str(exc)}), 502

    with panel._terms_lock:
        panel._terms[term.id] = term
        panel._ensure_reaper()

    panel.log_job(
        "terminal", server, session.get("username", "?"),
        command=f"terminal interativo aberto ({cols}x{rows})",
        output=f"sessao {term.id[:8]} em {server['ssh_user']}@{server['host']}",
    )
    return jsonify({"id": term.id, "offset": 0, "cols": cols, "rows": rows})


@bp.get("/api/v1/term/<tid>/read")
@panel.admin_required
def api_read(tid: str):
    panel._terminal_guard()
    term = panel._term_of_user(tid)
    try:
        offset = max(0, int(request.args.get("offset", "0")))
    except ValueError:
        offset = 0
    data, new_offset, lost = term.read(offset, panel.TERM_POLL_WAIT)
    return jsonify({
        "data": base64.b64encode(data).decode("ascii"),
        "offset": new_offset,
        "lost": lost,
        "alive": term.alive,
        "exit_code": term.exit_code,
    })


@bp.post("/api/v1/term/<tid>/keys")
@panel.admin_required
def api_keys(tid: str):
    panel._terminal_guard()
    term = panel._term_of_user(tid)
    body = request.get_json(silent=True) or {}
    data = body.get("data", "")
    if not isinstance(data, str) or len(data) > 64 * 1024:
        abort(400, "entrada invalida")
    try:
        term.write(data.encode("utf-8"))
    except panel.RemoteError as exc:
        return jsonify({"error": str(exc), "alive": False}), 409
    return jsonify({"ok": True, "alive": term.alive})


@bp.post("/api/v1/term/<tid>/resize")
@panel.admin_required
def api_resize(tid: str):
    panel._terminal_guard()
    term = panel._term_of_user(tid)
    body = request.get_json(silent=True) or {}
    try:
        cols = max(20, min(400, int(body.get("cols", 80))))
        rows = max(5, min(150, int(body.get("rows", 24))))
    except (TypeError, ValueError):
        abort(400, "tamanho invalido")
    term.resize(cols, rows)
    return jsonify({"ok": True})


@bp.post("/api/v1/term/<tid>/close")
@panel.admin_required
def api_close(tid: str):
    panel._terminal_guard()
    term = panel._term_of_user(tid)
    term.close()
    with panel._terms_lock:
        panel._terms.pop(term.id, None)
    return jsonify({"ok": True})
