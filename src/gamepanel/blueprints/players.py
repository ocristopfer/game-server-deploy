"""Who is playing: the counting wizard, the choice of source and moderation."""
from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("players", __name__)


@bp.get("/api/v1/servers/<int:sid>/players")
@panel.login_required
def api_list(sid: int):
    server = servers_repo.by_id(panel.db(), sid)
    if not server:
        abort(404)
    return jsonify(panel.server_players(server))


@bp.route("/servers/<int:sid>/players/discover", methods=["GET", "POST"])
@panel.admin_required
def setup(sid: int):
    """Wizard: find the port/API that answers and help find the pattern in the log."""
    server = panel._server_or_404(sid)
    # The fields of the three tabs need to survive the "Test" button, and among them is the
    # game's admin password (http_auth, http_login_body). That is why the form is POST:
    # in the URL the password would end up in the browser history, in the Referer header and in the log of
    # any proxy in front of the panel. GET still serves navigation between tabs,
    # which only carries the tab name.
    source_dir = request.form if request.method == "POST" else request.args
    tab = source_dir.get("tab", "port")
    should_test = bool(source_dir.get("test"))

    http = {field: source_dir.get(field, server[field]) for field in panel.HTTP_FIELDS}
    join_re = source_dir.get("join_re", server["join_re"])
    leave_re = source_dir.get("leave_re", server["leave_re"])
    log_path = source_dir.get("log_path", server["log_path"])

    data = {"portas": [], "aviso": "", "achados": [], "mudas": [], "amostras": [],
             "tem_api": False, "udp_do_jogo": 0, "udp_mudas": False,
             "teste": None, "teste_http": None, "erro_log": "", "erro_http": "",
             "presenca": None}
    if tab == "http":
        data.update(panel._http_tab(server, http, should_test))
    elif tab == "log":
        data.update(panel._log_tab(server, join_re, leave_re, log_path, should_test))
    else:
        data.update(panel._port_tab(server))

    return render_template(
        "players_setup.html", server=server, tab=tab,
        http=http, join_re=join_re, leave_re=leave_re, log_path=log_path, **data,
    )


@bp.post("/servers/<int:sid>/players/use")
@panel.admin_required
def use(sid: int):
    """Save the counting method chosen in the wizard."""
    panel._server_or_404(sid)  # only for the 404: from here on the UPDATEs use the sid itself
    links_to = panel.COUNT_SOURCES.get(request.form.get("player_source", ""))
    if links_to is None:
        flash(panel.translate("flash.bad_choice"), "error")
        return redirect(url_for("players.setup", sid=sid))

    refusal = links_to(panel.db(), sid)
    if refusal is not None:
        return refusal

    panel.invalidate_players(sid)
    return redirect(url_for("servers.detail", sid=sid))


@bp.post("/servers/<int:sid>/players/action")
@panel.login_required
def action(sid: int):
    """Kick, ban or warn, through the game's own API.

    It is an operation, not administration: moderating who is playing gives no access to the container,
    so the operator may do it, the same way they already restart the server.
    """
    server = panel._server_or_404(sid)
    action = (request.form.get("action", "") or "").strip()
    player = (request.form.get("player", "") or "").strip()[:200]
    name = (request.form.get("name", "") or "").strip()[:100]
    message = (request.form.get("message", "") or "").strip()[:panel.PLAYER_MSG_MAX]
    who = name or player or "todos"
    record = f"{panel.label_for_db(panel.PLAYER_ACTION_LABELS.get(action, action))}: {who}"
    if message:
        record += f" ({message})"
    go_back = url_for("servers.detail", sid=sid)

    try:
        label = panel.translate(panel.run_player_action(server, action, player, message))
    except (panel.QueryError, panel.RemoteError) as exc:
        panel.log_job("player-action", server, session.get("username", "?"),
                command=record, output=str(exc), status="error")
        flash(panel.translate("flash.could_not", reason=exc), "error")
        return redirect(go_back)

    panel.log_job("player-action", server, session.get("username", "?"),
            command=record, output="a API aceitou o pedido")
    # The count stays cached for a few seconds and still includes whoever just left.
    panel.invalidate_players(sid)
    flash(panel.translate("flash.player_action_done", label=label, who=who)
          if action != "announce"
          else panel.translate("flash.notice_sent", message=message), "ok")
    return redirect(go_back)
