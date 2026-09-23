"""Os destinos de webhook, os limites de recurso e o diario de alertas."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel

bp = Blueprint("alerts", __name__)


@bp.get("/alerts")
@panel.admin_required
def index():
    conn = panel.db()
    return render_template(
        "alerts.html", cfg=panel.webhook_config(conn), eventos=panel.labels_of(panel.ALERT_EVENTS),
        padrao=panel.clean_events(panel.ALERT_DEFAULT), do_env=bool(panel.WEBHOOK_URL_PADRAO),
        monitor=int(panel.MONITOR_EVERY), disco_a_cada=int(panel.DISK_CHECK_EVERY / 60),
        # O piso do relogio conta: o alerta nao pode chegar mais rapido que a volta dele.
        jogadores_a_cada=int(max(panel.PLAYER_CHECK_EVERY, panel.SCHEDULE_TICK)),
        quieto=int(panel.ALERT_QUIET), limite_hooks=panel.WEBHOOK_MAX,
        mudo_voltas=panel.MUTE_ROUNDS, log_a_cada=int(panel.LOG_CHECK_EVERY),
        pendencias=panel.alerts_without_baseline(conn), diario=panel.recent_alerts(conn),
        streams=panel.live_streams(),
    )


@bp.post("/alerts")
@panel.admin_required
def save():
    """So o que vale para todos os destinos: hoje, os limites de disco, memoria e CPU."""
    conn = panel.db()
    novos = []
    for campo, key, name in panel.LIMITES_ALERTA:
        # Campo que nem veio no formulario fica como esta. Tratar ausencia como erro
        # faria um formulario sem o campo derrubar um limite que ja estava certo.
        if campo not in request.form:
            continue
        value = (request.form.get(campo, "") or "").strip()
        if not value.isdigit() or not 50 <= int(value) <= 100:
            flash(panel.translate("flash.threshold_range", name=name), "error")
            return redirect(url_for("alerts.index"))
        novos.append((key, value))
    # So grava depois de validar todos: meio salvo e pior que nada salvo, porque a tela
    # volta dizendo "recusado" enquanto um dos limites ja mudou por baixo.
    for key, value in novos:
        panel.config_set(conn, key, value)
    panel._reset_baseline()
    flash(panel.translate("flash.preferences_saved"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets")
@panel.admin_required
def hook_new():
    conn = panel.db()
    quantos = conn.execute("SELECT COUNT(*) AS n FROM webhooks").fetchone()["n"]
    if quantos >= panel.WEBHOOK_MAX:
        flash(panel.translate("flash.destination_limit", n=panel.WEBHOOK_MAX), "error")
        return redirect(url_for("alerts.index"))
    data, erro = panel._le_form_webhook()
    if erro or not data["url"]:
        flash(panel.translate(erro) if erro else panel.translate("flash.need_webhook_url"), "error")
        return redirect(url_for("alerts.index"))
    with conn:
        conn.execute(
            "INSERT INTO webhooks (name, url, events, enabled, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (data["name"] or "Destino", data["url"], data["events"],
             data["enabled"], panel.now_iso()),
        )
    panel._reset_baseline()
    flash(panel.translate("flash.destination_added"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>")
@panel.admin_required
def hook_save(hid: int):
    conn = panel.db()
    atual = conn.execute("SELECT url FROM webhooks WHERE id = ?", (hid,)).fetchone()
    if not atual:
        flash(panel.translate("flash.destination_not_found"), "error")
        return redirect(url_for("alerts.index"))
    data, erro = panel._le_form_webhook()
    if erro:
        flash(panel.translate(erro), "error")
        return redirect(url_for("alerts.index"))
    # Campo de URL em branco quer dizer "mantem a que ja esta la". A tela mostra a URL
    # mascarada, entao nao ha o que reenviar: so quem digitar uma nova a troca.
    url = data["url"] or atual["url"]
    with conn:
        conn.execute(
            "UPDATE webhooks SET name = ?, url = ?, events = ?, enabled = ? WHERE id = ?",
            (data["name"] or "Destino", url, data["events"], data["enabled"], hid),
        )
    panel._reset_baseline()
    flash(panel.translate("flash.destination_saved"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>/delete")
@panel.admin_required
def hook_delete(hid: int):
    conn = panel.db()
    with conn:
        conn.execute("DELETE FROM webhooks WHERE id = ?", (hid,))
    flash(panel.translate("flash.destination_removed"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>/test")
@panel.admin_required
def hook_test(hid: int):
    """Manda uma mensagem agora para UM destino, para conferir se a URL esta certa."""
    conn = panel.db()
    row = conn.execute(
        "SELECT name, url FROM webhooks WHERE id = ?", (hid,)
    ).fetchone()
    if not row or not row["url"]:
        flash(panel.translate("flash.destination_not_found"), "error")
        return redirect(url_for("alerts.index"))
    # Se ha uma URL digitada no formulario, testa ELA: o ponto do botao e conferir a URL
    # nova antes de gravar, e nao repetir o teste da que ja estava salva.
    digitada = (request.form.get("url", "") or "").strip()[:400]
    if digitada and not panel.URL_RE.match(digitada):
        flash(panel.translate("flash.bad_url"), "error")
        return redirect(url_for("alerts.index"))
    erro = panel.send_webhook(
        digitada or row["url"],
        f"**Teste do painel de jogos**\nSe voce esta lendo isto, os alertas funcionam."
        f" ({session.get('username', '?')})",
    )
    name = row["name"] or "destino"
    flash(
        panel.translate("flash.destination_test_failed", name=name, reason=erro) if erro
        else panel.translate("flash.destination_test_sent", name=name),
        "error" if erro else "ok",
    )
    return redirect(url_for("alerts.index"))
