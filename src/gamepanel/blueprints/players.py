"""Quem esta jogando: o assistente de contagem, a escolha da fonte e a moderacao."""
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
    """Assistente: acha a porta/API que responde e ajuda a achar o padrao no log."""
    server = panel._server_or_404(sid)
    # Os campos das tres abas precisam sobreviver ao botao "Testar", e entre eles esta a
    # senha de admin do jogo (http_auth, http_login_body). Por isso o formulario e POST:
    # na URL a senha ficaria no historico do navegador, no cabecalho Referer e no log de
    # qualquer proxy na frente do painel. O GET continua servindo a navegacao entre abas,
    # que so carrega o nome da aba.
    source_dir = request.form if request.method == "POST" else request.args
    tab = source_dir.get("aba", "porta")
    should_test = bool(source_dir.get("testar"))

    http = {field: source_dir.get(field, server[field]) for field in panel.HTTP_FIELDS}
    join_re = source_dir.get("join_re", server["join_re"])
    leave_re = source_dir.get("leave_re", server["leave_re"])
    log_path = source_dir.get("log_path", server["log_path"])

    data = {"portas": [], "aviso": "", "achados": [], "mudas": [], "amostras": [],
             "tem_api": False, "udp_do_jogo": 0, "udp_mudas": False,
             "teste": None, "teste_http": None, "erro_log": "", "erro_http": ""}
    if tab == "http":
        data.update(panel._aba_http(server, http, should_test))
    elif tab == "log":
        data.update(panel._aba_log(server, join_re, leave_re, log_path, should_test))
    else:
        data.update(panel._port_tab(server))

    return render_template(
        "players_setup.html", server=server, tab=tab,
        http=http, join_re=join_re, leave_re=leave_re, log_path=log_path, **data,
    )


@bp.post("/servers/<int:sid>/players/use")
@panel.admin_required
def use(sid: int):
    """Grava a forma de contagem escolhida no assistente."""
    panel._server_or_404(sid)  # so pelo 404: daqui para baixo os UPDATE usam o proprio sid
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
    """Expulsa, bane ou avisa, pela API do proprio jogo.

    E operacao, nao administracao: moderar quem esta jogando nao da acesso ao container,
    entao o operador pode — do mesmo jeito que ele ja reinicia o servidor.
    """
    server = panel._server_or_404(sid)
    action = (request.form.get("acao", "") or "").strip()
    player = (request.form.get("jogador", "") or "").strip()[:200]
    name = (request.form.get("nome", "") or "").strip()[:100]
    message = (request.form.get("mensagem", "") or "").strip()[:panel.PLAYER_MSG_MAX]
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
    # A contagem fica alguns segundos em cache e ainda tem quem acabou de sair.
    panel.invalidate_players(sid)
    flash(panel.translate("flash.player_action_done", label=label, who=who)
          if action != "announce"
          else panel.translate("flash.notice_sent", message=message), "ok")
    return redirect(go_back)
