"""Screen preferences that apply BEFORE login: theme (light/dark) and language.

A cookie, not the session or the database, because the login screen also honors them and there
is no user there yet. For someone signed in the language ALSO goes to the database (`users.lang`): that
is what follows the person to another device, and the cookie only covers the way up to the login.
"""
from __future__ import annotations

from flask import Blueprint, g, redirect, request, session, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import users as users_repo

bp = Blueprint("preferences", __name__)

THEMES = ("light", "dark")
THEME_COOKIE = "theme"
LANG_COOKIE = "lang"
# One year: it is a device choice, not a session one. Expiring early would send the screen back to the
# system default in the middle of normal use.
COOKIE_AGE = 365 * 24 * 3600


def _back() -> str:
    """Where to go back after switching: the page it came from, if it is on THIS panel.

    `next` comes from the form; accepting anything there would let an outside link take
    someone from the panel to another site (open redirect). The rule is the same as the login's.
    """
    return panel.safe_target((request.form.get("next") or "").rstrip("?")) or url_for("dashboard.index")


def _remember(response, name: str, value: str):
    # httponly: the JavaScript reads the theme from the `data-theme` of <html>, never from the cookie.
    response.set_cookie(name, value, max_age=COOKIE_AGE, samesite="Lax",
                        secure=request.is_secure, httponly=True)
    return response


@bp.post("/preferences/theme")
def theme():
    chosen = request.form.get("theme", "")
    response = redirect(_back())
    if chosen not in THEMES:
        # A malformed value does not become a cookie: the theme would follow the system's, as before.
        return response
    return _remember(response, THEME_COOKIE, chosen)


@bp.post("/preferences/language")
def language():
    chosen = panel.i18n.valid_language(request.form.get("lang"))
    if panel.logged_user() is not None:
        with panel.db() as conn:
            users_repo.set_language(conn, session["uid"], chosen)
    # This request's `g` may already have stored the old language.
    g._language = chosen
    return _remember(redirect(_back()), LANG_COOKIE, chosen)
