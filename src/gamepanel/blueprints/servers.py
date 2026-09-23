"""Cadastro e operacao de um servidor: criar, editar, remover e agir sobre ele."""
from __future__ import annotations

import sqlite3

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("servers", __name__)


@bp.route("/servers/new", methods=["GET", "POST"])
@panel.admin_required
def new():
    data: dict = dict.fromkeys(panel.SERVER_FIELDS, "")
    data.update({"ssh_user": "root", "ssh_port": 22, "query_port": 0})
    if request.method == "POST":
        data, errors = panel._form_server(request.form)
        if not errors:
            try:
                conn = panel.db()
                with conn:
                    conn.execute(
                        panel.SQL_INSERT_SERVER,
                        (*[data[c] for c in panel.SERVER_FIELDS], panel.now_iso()),
                    )
                flash(panel.translate("flash.server_added", name=data["name"]), "ok")
                return redirect(url_for("dashboard.index"))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(panel.translate(err), "error")
    return render_template("server_form.html", data=data, mode="new")


@bp.route("/servers/<int:sid>/edit", methods=["GET", "POST"])
@panel.admin_required
def edit(sid: int):
    server = panel.db().execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    data = dict(server)
    if request.method == "POST":
        data, errors = panel._form_server(request.form)
        if not errors:
            try:
                conn = panel.db()
                with conn:
                    conn.execute(
                        panel.SQL_UPDATE_SERVER, (*[data[c] for c in panel.SERVER_FIELDS], sid)
                    )
                panel.invalidate_status(sid)
                # A contagem fica em cache por alguns segundos: trocar a fonte pelo
                # formulario tem que valer na hora, como vale pelo assistente.
                panel.invalidate_players(sid)
                flash(panel.translate("flash.server_updated"), "ok")
                return redirect(url_for("servers.detail", sid=sid))
            except sqlite3.IntegrityError:
                errors.append(f"Ja existe um servidor cadastrado em {data['host']}.")
        for err in errors:
            flash(panel.translate(err), "error")
    # `server` (a linha do banco, nao o formulario) vai junto: e dele que a barra de
    # navegacao do servidor tira o id e o nome. Sem isso esta tela seria a unica do
    # servidor sem a barra — e era exatamente assim que a navegacao ia divergindo.
    return render_template("server_form.html", data=data, mode="edit", sid=sid,
                           server=server)


@bp.post("/servers/<int:sid>/delete")
@panel.admin_required
def delete(sid: int):
    conn = panel.db()
    with conn:
        conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
    panel.invalidate_status(sid)
    flash(panel.translate("flash.server_removed"), "ok")
    return redirect(url_for("dashboard.index"))


@bp.get("/servers/<int:sid>")
@panel.login_required
def detail(sid: int):
    conn = panel.db()
    server = conn.execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    jobs = panel.server_jobs(conn, sid, 15)
    lines = panel._log_lines_arg(request.args.get("lines"))

    # Status, medidores, jogadores e log sao quatro idas de SSH independentes. Em serie a
    # tela custava a soma das quatro — e com o container fora do ar, a soma dos quatro
    # timeouts antes de mostrar "inacessivel".
    read_value = panel.em_paralelo({
        "status": lambda: panel.server_status(server),
        "metrics": lambda: panel.server_metrics(server),
        "players": lambda: panel.server_players(server),
        "logs": lambda: panel.read_logs(server, lines),
    })
    # read_logs devolve (texto, cursor) — o par inteiro vem no lugar do "valor".
    log_pair, log_error = read_value["logs"]
    logs, log_cursor = log_pair if log_pair else ("", "")

    return render_template(
        "server_detail.html",
        server=server,
        status=read_value["status"][0] or {"reachable": False, "service": "desconhecido",
                                     "error": read_value["status"][1]},
        metrics=read_value["metrics"][0] or {"error": read_value["metrics"][1]},
        # Mesma forma que o server_players devolve, para a tela nao precisar saber que
        # houve erro na leitura em vez de erro na contagem.
        players=read_value["players"][0] or {"configured": True, "error": read_value["players"][1],
                                       "players": None, "list": [], "source": ""},
        jobs=jobs,
        logs=logs,
        log_cursor=log_cursor,
        log_error=log_error,
        lines=lines,
        actions=panel.ACTIONS,
    )


@bp.get("/api/v1/servers/<int:sid>/resources")
@panel.login_required
def api_metrics(sid: int):
    server = panel.db().execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    data = panel.server_metrics(server)
    return jsonify(data), (502 if data.get("error") else 200)


@bp.get("/api/v1/servers/<int:sid>/logs")
@panel.login_required
def api_logs(sid: int):
    """Alimenta o "seguir log" da tela de detalhe."""
    server = panel.db().execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    # Cursor recusado (adulterado, ou de um journalctl que nao os emite) vira leitura
    # completa: sem isso o cliente anexaria o log inteiro por cima do que ja esta na tela.
    cursor = request.args.get("cursor", "")
    if not panel.CURSOR_RE.match(cursor or ""):
        cursor = ""
    try:
        text, new_cursor = panel.read_logs(server, panel._log_lines_arg(request.args.get("lines")), cursor)
    except panel.RemoteError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({
        "text": text,
        "cursor": new_cursor,
        # Sem cursor (primeira volta, ou journalctl antigo) o cliente troca o bloco
        # inteiro; com cursor ele so anexa as linhas novas.
        "append": bool(cursor and new_cursor),
    })


@bp.post("/servers/<int:sid>/action/<action>")
@panel.login_required
def action(sid: int, action: str):
    if action not in panel.ACTIONS:
        abort(404)
    server = panel.db().execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
    if not server:
        abort(404)
    job_id = panel.start_job(action, server, session.get("username", "?"))
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))
