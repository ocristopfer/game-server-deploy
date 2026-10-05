"""What makes the panel installable on a phone: manifest, service worker and the offline screen."""
from __future__ import annotations

from flask import Blueprint, render_template

from gamepanel import app as panel

bp = Blueprint("pwa", __name__)


@bp.get("/manifest.webmanifest")
def manifest():
    """App sheet: name, icons, color and start screen.

    It comes from a template (not a static file) so the icon paths
    come from Flask itself, including the version mark of `static_url`.
    """
    resp = panel.app.response_class(
        render_template("manifest.webmanifest.jinja"),
        mimetype="application/manifest+json",
    )
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/sw.js")
def service_worker():
    """The service worker, served from the ROOT on purpose.

    A service worker's scope is the folder it lives in: at /static/sw.js it would only
    see /static/ and would not see the panel's navigation. That is why it is not a
    static file: it is a route.
    """
    precache, version_mark = panel._shell_files()
    resp = panel.app.response_class(
        render_template("sw.js.jinja", version=version_mark, precache=precache),
        mimetype="text/javascript",
    )
    # Without this the worker file itself would be cached and the panel would never
    # find out that a new version of it exists.
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.get("/offline")
def offline():
    """The "no connection" screen, stored on the device along with the shell.

    It does not require login: it is served from the cache, without going through the server, and shows
    no data at all; it only explains what happened and offers "try again".
    """
    return render_template("offline.html")
