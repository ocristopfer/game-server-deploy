"""Alert delivery as a push notification (the installed app on the phone, a desktop browser).

Only the sending, like `webhook_client`: what to alert about and to whom is decided in
`app.notify`. The encryption and the VAPID signature live in `security/webpush.py`.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

from gamepanel.i18n import Message
from gamepanel.security import webauthn, webpush

# The push services the browsers use. The endpoint comes from the BROWSER, through a route any
# signed-in person can call, and the panel then POSTs to it from inside the network: without
# this list, an operator could point it at any internal https address. These four cover Chrome
# (and every Chromium, Samsung Internet included: FCM), Firefox, Safari/iPhone and Edge.
PUSH_HOST_SUFFIXES = (
    ".googleapis.com",
    ".mozilla.com",
    ".push.apple.com",
    ".notify.windows.com",
)
# The VAPID JWT may live 24 h at most; 12 h leaves room for a clock that is a bit off.
JWT_SECONDS = 12 * 3600
# How long the push service keeps a message for a phone that is off. An alert about a server
# that went down an hour ago is still worth reading; one from yesterday is noise.
TTL_SECONDS = 3600
ERROR_MAX = 300
# The push service answers these when the subscription no longer exists (the app was
# uninstalled, the person revoked the permission): the row has to go, or every alert would
# keep failing on it forever.
GONE = (404, 410)


class Result(NamedTuple):
    error: str      # "" on success, else an i18n.Message with the reason
    gone: bool      # the subscription is dead and should be deleted


class Device(NamedTuple):
    """What the browser's `PushSubscription.toJSON()` gives: where, and the keys to encrypt to."""
    endpoint: str
    p256dh: str
    auth: str


class Sender(NamedTuple):
    """The panel's side: its VAPID key, the contact in the JWT, and the HTTP settings."""
    vapid: webpush.KeyPair
    subject: str
    timeout: float
    user_agent: str


def allowed_endpoint(endpoint: str) -> bool:
    parts = urlsplit(endpoint or "")
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and not parts.username and not parts.password
            and any(host.endswith(suffix) for suffix in PUSH_HOST_SUFFIXES))


def send(device: Device, payload: bytes, sender: Sender, urgency: str = "high") -> Result:
    """Encrypt `payload` to this device and hand it to its push service."""
    endpoint = device.endpoint
    if not allowed_endpoint(endpoint):
        return Result(Message("push.bad_endpoint"), gone=True)
    try:
        body = webpush.encrypt(payload, webauthn.unb64url(device.p256dh),
                               webauthn.unb64url(device.auth))
    except (webpush.PushError, webauthn.WebAuthnError):
        # A key the panel cannot encrypt to will never start working: drop the row.
        return Result(Message("push.bad_keys"), gone=True)
    parts = urlsplit(endpoint)
    audience = f"{parts.scheme}://{parts.netloc}"
    request_body = urllib.request.Request(  # noqa: S310  # NOSONAR - allowed_endpoint() only lets https push services through
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": webpush.vapid_header(sender.vapid, audience, sender.subject,
                                                  int(time.time()) + JWT_SECONDS),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SECONDS),
            # "high" wakes a phone in battery saving; that is the point of an alert.
            "Urgency": urgency,
            "User-Agent": sender.user_agent,
        },
    )
    try:
        with urllib.request.urlopen(request_body, timeout=sender.timeout) as resp:  # noqa: S310  # NOSONAR
            resp.read(ERROR_MAX)
        return Result("", gone=False)
    except urllib.error.HTTPError as exc:
        try:
            reason = exc.read(ERROR_MAX).decode("utf-8", "replace").strip().replace("\n", " ")
        # Response already consumed/closed.
        except Exception:  # noqa: BLE001
            reason = ""
        message = (Message("push.http_status_reason", status=exc.code, reason=reason) if reason
                   else Message("push.http_status", status=exc.code))
        return Result(message, gone=exc.code in GONE)
    # Network: DNS, TLS, timeout, refused... The subscription may be fine: keep it.
    except Exception as exc:  # noqa: BLE001
        return Result(Message("push.call_failed", reason=exc), gone=False)
