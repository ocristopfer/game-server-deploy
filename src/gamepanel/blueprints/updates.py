"""The Updates screen: which version runs, what GitHub has, and the automatic update mode.

The panel never installs anything itself (see `updater.py`): these routes only write the mode and
leave a request for the root updater, which the path unit wakes within a second. Admin only: an
update restarts the panel for everyone.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel import updater

bp = Blueprint("updates", __name__)


@bp.get("/updates")
@panel.admin_required
def index():
    return render_template("updates.html", update=panel.update_state(), modes=updater.MODES)


@bp.post("/updates/mode")
@panel.admin_required
def mode():
    chosen = request.form.get("mode", "")
    if chosen not in updater.MODES:
        flash(panel.translate("updates.bad_mode"), "error")
        return redirect(url_for("updates.index"))
    try:
        updater.save_mode(panel.UPDATE_DIR, chosen)
    except OSError:
        panel.app.logger.exception("nao consegui gravar o modo de atualizacao")
        flash(panel.translate("updates.write_failed"), "error")
        return redirect(url_for("updates.index"))
    flash(panel.translate("updates.mode_saved"), "ok")
    return redirect(url_for("updates.index"))


def _request(what: str, done_key: str):
    try:
        updater.leave_request(panel.UPDATE_DIR, what)
    except OSError:
        panel.app.logger.exception("nao consegui deixar o pedido de atualizacao")
        flash(panel.translate("updates.write_failed"), "error")
        return redirect(url_for("updates.index"))
    flash(panel.translate(done_key), "ok")
    return redirect(url_for("updates.index"))


@bp.post("/updates/check")
@panel.admin_required
def check():
    return _request("check", "updates.check_requested")


@bp.post("/updates/install")
@panel.admin_required
def install():
    return _request("install", "updates.install_requested")
