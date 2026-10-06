"""The Updates screen: which version runs, what GitHub has, and the automatic update mode - for the
panel and, when the broker is on, for the broker too.

The panel never installs anything itself (see `updater.py`): these routes only write the mode and
leave a request for the root updater, which the path unit wakes within a second. Admin only: an
update restarts the panel for everyone.

Each status card refreshes itself: the buttons post in the background (`update.js`) and the card
polls its `api_*` route, which renders the SAME partial the page includes, until the updater has
written something new. Without JavaScript the buttons are plain forms that come back here.
"""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel import updater, version

bp = Blueprint("updates", __name__)

INDEX = "updates.index"

# What tells "the updater has answered" apart from "still the old status": any of these changes.
_STAMP_FIELDS = ("checked_at", "result", "current", "latest", "installed_at", "message")


def stamp(status: dict | None, running: str) -> str:
    """A fingerprint of a status card. The running version is in it because an install that
    worked shows up first as the new version answering, and only then in status.json."""
    status = status or {}
    return "|".join([running, *(str(status.get(field, "")) for field in _STAMP_FIELDS)])


def wants_json() -> bool:
    """The card's JavaScript asks for JSON; a plain form (no JavaScript) asks for a page."""
    return request.accept_mimetypes.best == "application/json"


def broker_view() -> dict:
    """What the broker card shows.

    The broker is only asked when the person has 2FA, the same rule `broker_required` applies to
    every broker route: without it the request never reaches `broker_client`, here either.
    """
    if not panel.ALLOW_BROKER:
        return {"enabled": False}
    user = panel.logged_user()
    if not user or not user["totp_enabled"]:
        return {"enabled": True, "needs_2fa": True}
    try:
        return {"enabled": True, "info": panel.broker_client.update_info()}
    except panel.broker_client.BrokerError as failure:
        return {"enabled": True, "error": panel.translate("flash.broker_error", reason=failure.message)}


def broker_stamp(broker: dict) -> str:
    if broker.get("info") is not None:
        return stamp(broker["info"].get("status"), str(broker["info"].get("version", "")))
    return f"error|{broker.get('error', '')}" if broker.get("error") else "2fa"


@bp.get("/updates")
@panel.admin_required
def index():
    update = panel.update_state()
    broker = broker_view()
    return render_template("updates.html", update=update, modes=updater.MODES,
                           panel_stamp=stamp(update["status"], version.BUILD.version),
                           broker=broker, broker_stamp=broker_stamp(broker))


@bp.get("/api/v1/updates/panel")
@panel.admin_required
def api_panel():
    update = panel.update_state()
    return jsonify({"html": render_template("partials/update_panel.html", update=update),
                    "stamp": stamp(update["status"], version.BUILD.version)})


@bp.get("/api/v1/updates/broker")
@panel.admin_required
@panel.broker_required
def api_broker():
    broker = broker_view()
    return jsonify({"html": render_template("partials/update_broker.html", broker=broker),
                    "stamp": broker_stamp(broker)})


@bp.post("/updates/mode")
@panel.admin_required
def mode():
    chosen = request.form.get("mode", "")
    if chosen not in updater.MODES:
        flash(panel.translate("updates.bad_mode"), "error")
        return redirect(url_for(INDEX))
    try:
        updater.save_mode(panel.UPDATE_DIR, chosen)
    except OSError:
        panel.app.logger.exception("nao consegui gravar o modo de atualizacao")
        flash(panel.translate("updates.write_failed"), "error")
        return redirect(url_for(INDEX))
    flash(panel.translate("updates.mode_saved"), "ok")
    return redirect(url_for(INDEX))


def answer(ok: bool, text: str):
    """The end of a check/install request (the panel's or the broker's): the sentence for the
    card's JavaScript, or a flash and this page back for a plain form."""
    if wants_json():
        return (jsonify({"message": text}), 200) if ok else (jsonify({"error": text}), 503)
    flash(text, "ok" if ok else "error")
    return redirect(url_for(INDEX))


def _request(what: str, done_key: str):
    try:
        updater.leave_request(panel.UPDATE_DIR, what)
    except OSError:
        panel.app.logger.exception("nao consegui deixar o pedido de atualizacao")
        return answer(False, panel.translate("updates.write_failed"))
    return answer(True, panel.translate(done_key))


@bp.post("/updates/check")
@panel.admin_required
def check():
    return _request("check", "updates.check_requested")


@bp.post("/updates/install")
@panel.admin_required
def install():
    return _request("install", "updates.install_requested")
