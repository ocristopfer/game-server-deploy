"""Quem esta jogando: o assistente de contagem, a escolha da fonte e a moderacao."""
from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("players", __name__)


@bp.get("/api/v1/servers/<int:sid>/players")
@panel.login_required
def api_list(sid: int):
    server = panel.db().execute(panel.SQL_SERVER_BY_ID, (sid,)).fetchone()
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
    origem = request.form if request.method == "POST" else request.args
    aba = origem.get("aba", "porta")
    testar = bool(origem.get("testar"))

    http = {campo: origem.get(campo, server[campo]) for campo in panel.HTTP_FIELDS}
    join_re = origem.get("join_re", server["join_re"])
    leave_re = origem.get("leave_re", server["leave_re"])
    log_path = origem.get("log_path", server["log_path"])

    data = {"portas": [], "aviso": "", "achados": [], "mudas": [], "amostras": [],
             "tem_api": False, "udp_do_jogo": 0, "udp_mudas": False,
             "teste": None, "teste_http": None, "erro_log": "", "erro_http": ""}
    if aba == "http":
        data.update(panel._aba_http(server, http, testar))
    elif aba == "log":
        data.update(panel._aba_log(server, join_re, leave_re, log_path, testar))
    else:
        data.update(panel._port_tab(server))

    return render_template(
        "players_setup.html", server=server, aba=aba,
        http=http, join_re=join_re, leave_re=leave_re, log_path=log_path, **data,
    )


@bp.post("/servers/<int:sid>/players/use")
@panel.admin_required
def use(sid: int):
    """Grava a forma de contagem escolhida no assistente."""
    panel._server_or_404(sid)  # so pelo 404: daqui para baixo os UPDATE usam o proprio sid
    liga = panel.FONTES_DE_CONTAGEM.get(request.form.get("player_source", ""))
    if liga is None:
        flash(panel.translate("flash.bad_choice"), "error")
        return redirect(url_for("players.setup", sid=sid))

    recusa = liga(panel.db(), sid)
    if recusa is not None:
        return recusa

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
    quem = name or player or "todos"
    registro = f"{panel.label_for_db(panel.PLAYER_ACTION_LABELS.get(action, action))}: {quem}"
    if message:
        registro += f" ({message})"
    voltar = url_for("servers.detail", sid=sid)

    try:
        label = panel.translate(panel.run_player_action(server, action, player, message))
    except (panel.QueryError, panel.RemoteError) as exc:
        panel.log_job("player-action", server, session.get("username", "?"),
                command=registro, output=str(exc), status="error")
        flash(panel.translate("flash.could_not", reason=exc), "error")
        return redirect(voltar)

    panel.log_job("player-action", server, session.get("username", "?"),
            command=registro, output="a API aceitou o pedido")
    # A contagem fica alguns segundos em cache e ainda tem quem acabou de sair.
    panel.invalidate_players(sid)
    flash(panel.translate("flash.player_action_done", label=label, who=quem)
          if action != "announce"
          else panel.translate("flash.notice_sent", message=message), "ok")
    return redirect(voltar)
