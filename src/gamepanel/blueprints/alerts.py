"""Webhook destinations, resource limits and the alert log."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import alerts as alerts_repo

bp = Blueprint("alerts", __name__)


@bp.get("/alerts")
@panel.admin_required
def index():
    conn = panel.db()
    return render_template(
        "alerts.html", cfg=panel.webhook_config(conn), events=panel.labels_of(panel.ALERT_EVENTS),
        defaults=panel.clean_events(panel.ALERT_DEFAULT), from_env=bool(panel.DEFAULT_WEBHOOK_URL),
        monitor=int(panel.MONITOR_EVERY), disk_every=int(panel.DISK_CHECK_EVERY / 60),
        # The clock floor matters: the alert cannot arrive faster than its own loop.
        players_every=int(max(panel.PLAYER_CHECK_EVERY, panel.SCHEDULE_TICK)),
        quiet=int(panel.ALERT_QUIET), hook_limit=panel.WEBHOOK_MAX,
        silent_rounds=panel.MUTE_ROUNDS, log_every=int(panel.LOG_CHECK_EVERY),
        pending=panel.alerts_without_baseline(conn), journal=panel.recent_alerts(conn),
        streams=panel.live_streams(),
    )


@bp.post("/alerts")
@panel.admin_required
def save():
    """Only what applies to every destination: today, the disk, memory and CPU limits."""
    conn = panel.db()
    fresh_ones = []
    for field, key, name in panel.ALERT_LIMITS:
        # A field that did not even come in the form stays as it is. Treating absence as an error
        # would make a form without the field knock down a limit that was already right.
        if field not in request.form:
            continue
        value = (request.form.get(field, "") or "").strip()
        if not value.isdigit() or not 50 <= int(value) <= 100:
            flash(panel.translate("flash.threshold_range", name=name), "error")
            return redirect(url_for("alerts.index"))
        fresh_ones.append((key, value))
    # Only save after validating all of them: half saved is worse than nothing saved, because the
    # screen comes back saying "rejected" while one of the limits has already changed underneath.
    for key, value in fresh_ones:
        panel.config_set(conn, key, value)
    panel._reset_baseline()
    flash(panel.translate("flash.preferences_saved"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets")
@panel.admin_required
def hook_new():
    conn = panel.db()
    how_many = alerts_repo.count_webhooks(conn)
    if how_many >= panel.WEBHOOK_MAX:
        flash(panel.translate("flash.destination_limit", n=panel.WEBHOOK_MAX), "error")
        return redirect(url_for("alerts.index"))
    data, failure = panel._read_webhook_form()
    if failure or not data["url"]:
        flash(panel.translate(failure) if failure else panel.translate("flash.need_webhook_url"), "error")
        return redirect(url_for("alerts.index"))
    with conn:
        alerts_repo.insert_webhook(conn, data, panel.now_iso())
    panel._reset_baseline()
    flash(panel.translate("flash.destination_added"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>")
@panel.admin_required
def hook_save(hid: int):
    conn = panel.db()
    current_one = alerts_repo.webhook_by_id(conn, hid)
    if not current_one:
        flash(panel.translate("flash.destination_not_found"), "error")
        return redirect(url_for("alerts.index"))
    data, failure = panel._read_webhook_form()
    if failure:
        flash(panel.translate(failure), "error")
        return redirect(url_for("alerts.index"))
    # A blank URL field means "keep the one already there". The screen shows the URL
    # masked, so there is nothing to resend: only someone who types a new one replaces it.
    url = data["url"] or current_one["url"]
    with conn:
        alerts_repo.update_webhook(conn, hid, data["name"], url, data["events"],
                                   data["enabled"])
    panel._reset_baseline()
    flash(panel.translate("flash.destination_saved"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>/delete")
@panel.admin_required
def hook_delete(hid: int):
    conn = panel.db()
    with conn:
        alerts_repo.delete_webhook(conn, hid)
    flash(panel.translate("flash.destination_removed"), "ok")
    return redirect(url_for("alerts.index"))


@bp.post("/alerts/targets/<int:hid>/test")
@panel.admin_required
def hook_test(hid: int):
    """Send a message now to ONE destination, to check that the URL is right."""
    conn = panel.db()
    row = alerts_repo.webhook_by_id(conn, hid)
    if not row or not row["url"]:
        flash(panel.translate("flash.destination_not_found"), "error")
        return redirect(url_for("alerts.index"))
    # If a URL was typed in the form, test IT: the point of the button is to check the new URL
    # before saving, not to repeat the test of the one already saved.
    typed = (request.form.get("url", "") or "").strip()[:400]
    if typed and not panel.URL_RE.match(typed):
        flash(panel.translate("flash.bad_url"), "error")
        return redirect(url_for("alerts.index"))
    failure = panel.send_webhook(
        typed or row["url"],
        f"**Teste do painel de jogos**\nSe voce esta lendo isto, os alertas funcionam."
        f" ({session.get('username', '?')})",
    )
    name = row["name"] or "destino"
    flash(
        panel.translate("flash.destination_test_failed", name=name, reason=failure) if failure
        else panel.translate("flash.destination_test_sent", name=name),
        "error" if failure else "ok",
    )
    return redirect(url_for("alerts.index"))
