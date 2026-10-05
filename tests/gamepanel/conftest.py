"""Scenario shared by the panel suites.

Two things happen here that could not be done inside a test file:

1. **The database is chosen before any import.** `app.py` reads `GAMEPANEL_DB` and
   calls `init_db()` at import time. Since pytest loads this file before collecting
   the tests, this is the place - the only place - to point the panel at a throwaway
   database. Getting it wrong means running the tests against the real
   `/var/lib/gamepanel/panel.db`.

2. **Every module starts with a clean database.** Before the move to pytest each suite
   was a process with its own temporary database; now they all share one process. The
   `banco` fixture restores the same isolation by emptying the tables.
"""
from __future__ import annotations

import os
import sys
import tempfile

# Direct assignment, NEVER setdefault - and always before `import app`. See item 1 of
# the docstring.
#
# The panel container (docker/panel/Dockerfile) pins `ENV GAMEPANEL_DB=/var/lib/
# gamepanel/panel.db`: that variable is ALREADY set when this process starts, and
# `setdefault` would have been a no-op there. That is exactly what happened in an
# earlier version of this file: the tests ran against the dev container's real
# database, deleting the 'admin' user and filling the servers screen with "alvo",
# "outro" and "Sem consulta". Direct assignment guarantees a throwaway database in ANY
# environment, container or local machine, whatever came in the environment.
os.environ["GAMEPANEL_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")
# Alerts never go out to the network from here: a test that wants to exercise sending
# swaps `panel.envia_webhook` for a capturer (see the `webhooks` fixture).
os.environ["GAMEPANEL_WEBHOOK_URL"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time

import pytest

from gamepanel import app as panel
from gamepanel.security import totp

# Every table in SCHEMA. Emptying beats recreating: `init_db()` also runs the
# migrations, and repeating them on every test would measure their time, not the test's.
TABLES = ("alert_log", "jobs", "samples", "schedules", "servers", "settings",
           "users", "webhooks")


@pytest.fixture
def database():
    """Own connection to the empty database. Closes by itself at the end of the test."""
    conn = panel._connect()
    with conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
    _reset_module_state()
    try:
        yield conn
    finally:
        conn.close()


def _reset_module_state() -> None:
    """Clears the caches and clocks that `app.py` keeps in module variables.

    Without this a test inherits the previous one's reading: the monitor thinks it has
    already seen that server (and does not alert), the status cache returns another
    scenario's state, and the clock tick thinks it is not time yet. That was why each
    suite used to be a separate process; now it is a function.
    """
    panel._monitor_state.clear()
    panel._status_cache.clear()
    panel._metrics_cache.clear()
    panel._players_cache.clear()
    panel.login_lockout.reset()
    panel.totp_lockout.reset()
    panel.passkey_challenges.reset()
    for tick in (panel.monitor_tick, panel.state_tick, panel.resource_tick,
                 panel.log_tick, panel.sample_tick, panel.cleanup_tick):
        tick.reset()


@pytest.fixture
def webhooks(database, monkeypatch):
    """Captures what the panel WOULD send, without touching the network.

    Returns the list of `(url, text)`. What the alert suites test is WHEN the panel
    decides to notify - one alert too many becomes noise and the channel stops being
    read; one too few is a server down at 3 a.m. that nobody finds out about.
    """
    sent_ones: list[tuple[str, str]] = []

    def capture(url, text):
        sent_ones.append((url, text))
        return ""      # empty string = sent successfully

    monkeypatch.setattr(panel, "send_webhook", capture)
    return sent_ones


@pytest.fixture
def client(database):
    """Flask HTTP client, with nobody logged in."""
    panel.app.config["TESTING"] = True
    return panel.app.test_client()


def _login(cli, username: str, password: str):
    """Logs `username` into the test client `cli`. Returns the same `cli`, logged in.

    Failing loudly (not a 302) is always a FIXTURE error, not one of the test using it -
    hence the `assert` here, and not a `check()` that would just record one more failure.
    """
    cli.get("/login")
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    resp = cli.post("/login", data={"username": username, "password": password, "csrf": token},
                    follow_redirects=False)
    assert resp.status_code == 302, f"login de {username} falhou ({resp.status_code})"
    return cli


def _post(cli, url, data=None):
    """POST with the session's CSRF already filled in - what every panel POST requires."""
    data = dict(data or {})
    with cli.session_transaction() as sess:
        data["csrf"] = sess.get("csrf", "")
    return cli.post(url, data=data, follow_redirects=False)


@pytest.fixture
def post():
    """`postar(cli, url, dados)`: POST with CSRF, without following redirects."""
    return _post


@pytest.fixture
def login(database):
    """`entrar(username, senha)`: returns a NEW client, already logged in.

    Each call creates its own `test_client()` - two logins in the same suite (boss and
    worker, for example) must not share a session.
    """
    def _do(username: str, password: str):
        return _login(panel.app.test_client(), username, password)
    return _do


@pytest.fixture
def admin(login):
    """A registered, logged-in administrator - the most common case in the web suites."""
    panel.ensure_admin_user("chefe", "senha-do-chefe")
    return login("chefe", "senha-do-chefe")


@pytest.fixture
def operator(login):
    """A registered, logged-in operator, for the permission tests."""
    panel.ensure_admin_user("peao", "senha-do-peao", panel.ROLE_OPERATOR)
    return login("peao", "senha-do-peao")


@pytest.fixture
def admin_2fa(admin):
    """The same `chefe`, with the second factor ACTIVE.

    `broker_required` always requires the PERSON's 2FA, not only when
    `GAMEPANEL_REQUIRE_2FA` is on - without this fixture, every broker route test would
    land on the activation screen instead of what it wants to exercise. Enabling 2FA in
    an already logged-in session does not drop it (`_store_second_factor` does not touch
    the session), so the same client keeps working afterwards.
    """
    admin.get("/account/2fa")
    with admin.session_transaction() as sess:
        secret = sess["totp_pendente"]
    response = _post(admin, "/account/2fa", {"code": totp.code(secret, totp.step_of(time.time()))})
    assert response.status_code == 200, "nao consegui ativar o 2FA de 'chefe' para o teste"
    return admin
