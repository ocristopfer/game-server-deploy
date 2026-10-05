"""Health probe, no session: it is what a load balancer or the deploy asks."""
from __future__ import annotations

from flask import Blueprint, jsonify

from gamepanel import version

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Beyond "up", WHICH code is up.

    The deploy publishes a release and asks here whether the version that came back is the one
    it just sent. Without this, "the service started" is compatible with "systemd restarted
    the old version because the new one did not even import", and both cases show the same
    green screen. There is no session on this route, so what goes out is only code identity:
    no path, no address, no user name.
    """
    return jsonify({"status": "ok", **version.BUILD.as_public()})
