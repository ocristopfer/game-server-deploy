"""Push notifications: subscribe this device, choose its events, test and remove it.

The encryption lives in `security/webpush.py` and the sending in `app.notify`; here only the HTTP.
Subscribing is JSON because it is the browser's `PushManager` that creates the subscription -
without JavaScript there is nothing to subscribe, and the screen hides the button in that case.
Everything else (events, test, remove) is a plain form, like the rest of the Account screen.

Every route works on the signed-in person's OWN devices: the repository filters by `user_id`, so
a guessed id from someone else's device answers "not found".
"""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for

from gamepanel import app as panel
from gamepanel.integrations import push_client
from gamepanel.persistence.repositories import push as push_repo
from gamepanel.security import webauthn, webpush

bp = Blueprint("push", __name__)

ENDPOINT_MAX = 1000


def _error(key: str, status: int, **fields):
    return jsonify({"error": panel.translate(key, **fields)}), status


def _payload() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _valid_keys(p256dh: str, auth: str) -> bool:
    """The same checks the encryption makes, done NOW: a bad key found at the first alert would
    only show up as a device that never rings."""
    try:
        point = webauthn.unb64url(p256dh)
        secret = webauthn.unb64url(auth)
        webpush.encrypt(b"", point, secret)
    except (webauthn.WebAuthnError, webpush.PushError):
        return False
    return True


@bp.post("/account/push")
@panel.login_required
def subscribe():
    body = _payload()
    endpoint = str(body.get("endpoint", ""))[:ENDPOINT_MAX + 1]
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    p256dh, auth = str(keys.get("p256dh", "")), str(keys.get("auth", ""))
    if (len(endpoint) > ENDPOINT_MAX or not push_client.allowed_endpoint(endpoint)
            or not _valid_keys(p256dh, auth)):
        return _error("push.bad_subscription", 400)
    conn = panel.db()
    uid = session["uid"]
    known = push_repo.by_endpoint(conn, endpoint)
    if known is None and push_repo.count_for_user(conn, uid) >= panel.PUSH_MAX_PER_USER:
        return _error("push.limit", 409, n=panel.PUSH_MAX_PER_USER)
    label = str(body.get("label", "")).strip() or panel.translate("push.default_label")
    with conn:
        push_repo.upsert(conn, uid, endpoint, p256dh, auth, panel.ALERT_DEFAULT, label, panel.now_iso())
    # The monitor's memory was built for the old destinations; a new device starts from the current
    # state instead of receiving, right away, an alert about something that was already so.
    panel._reset_baseline()
    flash(panel.translate("push.subscribed"), "ok")
    return jsonify({"redirect": url_for("account.index")})


@bp.post("/account/push/unsubscribe")
@panel.login_required
def unsubscribe():
    """This browser turned notifications off: forget its endpoint (only if it is the person's)."""
    endpoint = str(_payload().get("endpoint", ""))
    conn = panel.db()
    with conn:
        push_repo.delete_endpoint(conn, session["uid"], endpoint)
    flash(panel.translate("push.unsubscribed"), "ok")
    return jsonify({"redirect": url_for("account.index")})


@bp.post("/account/push/<int:sid>")
@panel.login_required
def save(sid: int):
    events = [e for e in request.form.getlist("events") if e in panel.ALERT_EVENTS]
    label = (request.form.get("label", "") or "").strip() or panel.translate("push.default_label")
    conn = panel.db()
    with conn:
        saved = push_repo.set_events(conn, session["uid"], sid, ",".join(events), label)
    panel._reset_baseline()
    flash(panel.translate("push.saved" if saved else "push.not_found"), "ok" if saved else "error")
    return redirect(url_for("account.index"))


@bp.post("/account/push/<int:sid>/delete")
@panel.login_required
def delete(sid: int):
    conn = panel.db()
    with conn:
        removed = push_repo.delete(conn, session["uid"], sid)
    flash(panel.translate("push.removed" if removed else "push.not_found"),
          "ok" if removed else "error")
    return redirect(url_for("account.index"))


@bp.post("/account/push/<int:sid>/test")
@panel.login_required
def test(sid: int):
    """Send one notification now, to check the whole path: key, push service and the phone."""
    conn = panel.db()
    row = push_repo.by_id(conn, session["uid"], sid)
    if row is None:
        flash(panel.translate("push.not_found"), "error")
        return redirect(url_for("account.index"))
    language = panel.current_language()
    payload = panel.push_payload(panel.i18n.Message("push.test_title"),
                                 panel.i18n.Message("push.test_body"), "teste", language)
    result = panel.send_push(row, payload, panel.push_keys(conn))
    with conn:
        if result.gone:
            push_repo.forget(conn, sid)
        else:
            push_repo.mark_result(conn, sid, panel.now_iso(), result.error)
    if result.error:
        flash(panel.translate("push.test_failed", name=row["label"], reason=panel.translate(result.error)),
              "error")
    else:
        flash(panel.translate("push.test_sent", name=row["label"]), "ok")
    return redirect(url_for("account.index"))
