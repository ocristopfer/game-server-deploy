"""Alert delivery via webhook (Discord, Slack, or anything that accepts JSON).

Only the sending: what to alert about, and to whom, is decided by
`services.alert_service`. There is no database or rule here - just a POST and the failure
reason (an `i18n.Message`, so the screen can show it in the viewer's language).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from gamepanel.i18n import Message
from gamepanel.runtime.http_probe import URL_RE

# How much of the error response body is worth reading: the destination says what it
# disliked in the first lines, and keeping more than that only fills the alert screen.
ERROR_MAX = 300
RESPONSE_MAX = 2048
# Path shaped .../<id>/<token>: with both, the id can be shown and only the token hidden.
# With fewer than that there is nothing to split, and everything becomes asterisks.
PARTS_WITH_ID_AND_TOKEN = 2


def mask_url(url: str) -> str:
    """Keep only enough to recognize the destination, without exposing the token.

    A webhook URL is a credential: whoever reads the screen over someone's shoulder (or in a
    screenshot pasted into a chat) should not walk away able to post to the channel.
    """
    if not url:
        return ""
    cut = url.split("://", 1)[-1]
    host, _, rest = cut.partition("/")
    if not rest:
        return host
    parts = [p for p in rest.split("/") if p]
    if len(parts) >= PARTS_WITH_ID_AND_TOKEN:
        # Discord: .../webhooks/<id>/<token>. The id identifies, the token is the secret.
        return f"{host}/.../{parts[-2]}/{'*' * 8}"
    return f"{host}/.../{'*' * 8}"


def send(url: str, text: str, timeout: float, user_agent: str) -> str:
    """Do the POST. Returns "" on success, or the failure reason.

    The body carries 'content' AND 'text': the first is Discord's field, the second
    Slack's. Each reads its own and ignores the other, so the same call serves both (and
    anything else that accepts JSON).
    """
    if not URL_RE.match(url or ""):
        return Message("webhook.bad_url")
    body = json.dumps({"content": text, "text": text}).encode("utf-8")
    request_body = urllib.request.Request(  # noqa: S310  # NOSONAR - URL_RE already rejected anything not http(s)
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
    )
    try:
        with urllib.request.urlopen(request_body, timeout=timeout) as resp:  # noqa: S310  # NOSONAR
            resp.read(RESPONSE_MAX)
        return ""
    except urllib.error.HTTPError as exc:
        # The response body is where the destination says what it disliked (Discord sends
        # a JSON with 'message'). Without it, a 400 for a malformed payload and a 403 from a
        # Cloudflare block look the same on the screen.
        try:
            reason = exc.read(ERROR_MAX).decode("utf-8", "replace").strip().replace("\n", " ")
        # Response already consumed/closed.
        except Exception:  # noqa: BLE001
            reason = ""
        if reason:
            return Message("webhook.http_status_reason", status=exc.code, reason=reason)
        return Message("webhook.http_status", status=exc.code)
    # Network: DNS, TLS, timeout, refused...
    except Exception as exc:  # noqa: BLE001
        return Message("webhook.call_failed", reason=exc)
