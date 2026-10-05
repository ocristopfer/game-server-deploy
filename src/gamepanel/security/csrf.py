"""The panel's own CSRF protection - not Flask-WTF.

Production only has the stdlib plus apt's `python3-flask` (see CLAUDE.md), so there is no
`CSRFProtect` to install. The protection is the pair: `token()` generates the value and keeps
it in the session, and `check()` rejects every POST that does not send the same value back.

Static analyzers tend to flag `Flask(__name__)` in `app.py` as "CSRF disabled" because they
do not see a `CSRFProtect(app)`. That is a false positive, and there is a `# NOSONAR` there
with the reason. **Do not remove `check()` from `before_request`.**
"""
from __future__ import annotations

import hmac
import secrets
from collections.abc import Mapping, MutableMapping

TOKEN_BYTES = 32
SESSION_KEY = "csrf"
FORM_FIELD = "csrf"
# The terminal and the editor post JSON (no form), so they send the same value in a header.
# Without this they would need a path of their own, with no protection.
HEADER = "X-CSRF-Token"


def token(session: MutableMapping[str, object]) -> str:
    """This session's token, created the first time someone asks for it."""
    current = session.get(SESSION_KEY)
    if not current:
        current = secrets.token_urlsafe(TOKEN_BYTES)
        session[SESSION_KEY] = current
    return str(current)


def matches(session: Mapping[str, object], form: Mapping[str, str],
            headers: Mapping[str, str]) -> bool:
    """Does what came back match what is in the session?

    `compare_digest` and not `==`: the response time of a plain comparison reveals how many
    leading bytes match, and that is enough to discover the token byte by byte.
    """
    sent = form.get(FORM_FIELD, "") or headers.get(HEADER, "")
    expected = str(session.get(SESSION_KEY, ""))
    return bool(sent) and hmac.compare_digest(sent, expected)
