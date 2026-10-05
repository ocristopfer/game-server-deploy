#!/usr/bin/env python3
"""Admin panel for the game servers.

Runs in its own container and talks SSH *directly* to each game container: the Proxmox
host is not in the path, the panel has no access to it and does not know about `pct`.

Each registered server is an SSH destination (host/port/user). For the panel to reach
a container, that container needs sshd and the panel's public key authorized
(see the panel's "SSH access" page).

Dependencies: python3-flask (apt). Password hashing and sessions use only the stdlib.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any, NamedTuple

# Running as a SCRIPT (`python3 /opt/gamepanel/gamepanel/app.py --reset-2fa ...`), what
# goes into sys.path is the package's own folder, and `import gamepanel` does not resolve. This
# puts its parent in front. It is not a detail: the second-factor emergency exit and the
# server registration of deploy-game.ps1 call the file by path, and since the
# code moved to src/ both broke with ModuleNotFoundError - the deploy one
# silently, because it only warns "panel not found" and moves on.
if __package__ in (None, ""):  # pragma: no cover - only applies outside a normal import
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Running as a SCRIPT (`python -m gamepanel.app` or by the file path), this module
# is called `__main__`, and `gamepanel.app` is not in `sys.modules`. When a blueprint
# does `from gamepanel import app as panel`, Python imports the file AGAIN, from scratch;
# that second copy reaches the bottom, registers the blueprints again and finds the
# first of them still half built ("partially initialized module ... has no attribute
# 'bp'"). Registering the module under its import name makes the blueprint find this copy, which is
# the one with the real `app`.
if __name__ == "__main__":  # pragma: no cover - only applies outside a normal import
    sys.modules.setdefault("gamepanel.app", sys.modules[__name__])

# markupsafe comes with Jinja, which comes with the apt python3-flask: it is not a
# new dependency. It is the same escaping the template autoescape uses.
from markupsafe import Markup, escape

from gamepanel import cli, config, i18n, version
from gamepanel import navigation as ui
from gamepanel.blueprints import register_all
from gamepanel.games import config_format as gameconf
from gamepanel.games import registry as game_fields
from gamepanel.integrations import broker_client, webhook_client
from gamepanel.persistence import schema
from gamepanel.persistence.repositories import alerts as alerts_repo
from gamepanel.persistence.repositories import jobs as jobs_repo
from gamepanel.persistence.repositories import samples as samples_repo
from gamepanel.persistence.repositories import schedules as schedules_repo
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.persistence.repositories import settings as settings_repo
from gamepanel.persistence.repositories import users as users_repo

# Alias: there is a `terminal()` route in this same module (the /servers/<id>/terminal screen),
# and the name `terminal` without an alias would end up REBOUND by it: the import would only hold
# until the route definition, silently (mypy caught this: "Name already defined").
# Aliases for the same reason: there are `files()` (`/servers/<id>/files`) and
# `backups()` (`/servers/<id>/backups`) routes in this module.
from gamepanel.runtime import (
    a2s,
    backup_archive,
    http_probe,
    log_probe,
    port_probe,
    presence_probe,
    remote_cmd,
)
from gamepanel.runtime import backups as backups_rt
from gamepanel.runtime import files as files_rt
from gamepanel.runtime import ssh as ssh_transport
from gamepanel.runtime import terminal as term_runtime
from gamepanel.security import csrf, passwords, totp, webauthn
from gamepanel.services import (
    alert_service,
    auth_service,
    broker_service,
    chart_service,
    job_service,
    metrics_service,
    parallel,
    player_service,
    schedule_service,
    server_service,
    status_service,
)
from gamepanel.tasks import broker_jobs, log_stream, scheduler, ticker

# The interactive terminal depends on a PTY (only exists on POSIX). On other systems the
# rest of the panel keeps working and the terminal screen answers 503.
HAVE_PTY = term_runtime.HAVE_PTY
# The flask import comes AFTER on purpose: the line above reads from `term_runtime`, which was just
# imported, and the comment explaining it needs to stay next to it.
from flask import (  # noqa: E402
    Flask,
    abort,
    flash,
    g,
    has_app_context,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# A registered server, as the rest of the panel sees it.
#
# Either the SQLite row, or a dict COPY of it - and the copy is not an implementation
# detail: a `sqlite3.Row` belongs to the connection that produced it, and a SQLite
# connection does not cross threads. Every long task (a game update takes almost an hour)
# runs with `dict(server)` instead of the Row; see `start_job`. Both forms answer
# `server["host"]`, which is all these functions need.
ServerRow = sqlite3.Row | Mapping[str, Any]


# ---------------------------------------------------------------- configuration

# A single read, at import, with ALL problems listed at once (see
# `config.py`). The module names below still exist because the tests
# swap `panel.X` for fakes: reading `settings.x` directly in them would make the swap
# silently stop taking effect.
settings = config.load()

DB_PATH = settings.db_path
SECRET_FILE = settings.secret_file
SSH_KEY = settings.ssh_key
# Writable: the containers' host keys are learned on first access (accept-new).
KNOWN_HOSTS = settings.known_hosts
# Where the SSH connection-reuse sockets live. Next to known_hosts, not in
# /tmp: the socket gives access to an already authenticated session on the game containers, and /tmp is
# shared space; the panel's own folder, with 0700, closes that door.
SSH_CONTROL_DIR = settings.ssh_control_dir
# How long the master connection stays up after its command ends. It is what lets the
# monitor's next round piggyback instead of paying for another handshake; 60s comfortably covers
# the monitor's pace (15s to 60s) without leaving an idle connection hanging for hours.
SSH_CONTROL_PERSIST = settings.ssh_control_persist

# Quick commands (status, logs) vs long commands (update downloads the whole game).
QUICK_TIMEOUT = 20
JOB_TIMEOUT = settings.job_timeout
STATUS_TTL = 8.0
# CPU/memory/disk/network gauges: each reading costs an SSH round trip of ~1s.
METRICS_TTL = settings.metrics_ttl

# Web console: runs commands as root INSIDE the chosen game container.
# It is the most powerful feature of the panel; turn it off with GAMEPANEL_ALLOW_SHELL=0.
ALLOW_SHELL = settings.allow_shell
SHELL_TIMEOUT = settings.shell_timeout
SHELL_MAX_LEN = 4000
# 16 bits: the largest port that exists in TCP/UDP.
MAX_PORT = 65535

# Interactive terminal: live SSH session with a PTY, keyboard wired to the container shell.
# Inherits ALLOW_SHELL (it is the same power as the console, only interactive).
TERM_MAX_SESSIONS = settings.term_max_sessions
TERM_IDLE_TIMEOUT = settings.term_idle_timeout
TERM_BUFFER_BYTES = 512 * 1024
TERM_POLL_WAIT = 20.0  # long-poll: holds the response until new output arrives

# Provisioning broker: creates game instances and opens ports on the firewall. The panel
# does not keep Proxmox/OPNsense credentials, only the broker token. OFF by default: whoever
# turns it on (GAMEPANEL_ALLOW_BROKER=1) needs to set the URL, the token file and, on https, the
# certificate's SHA-256 fingerprint. Without that the feature does not appear anywhere.
BROKER_URL = settings.broker_url
BROKER_TOKEN_FILE = settings.broker_token_file
BROKER_CERT_SHA256 = settings.broker_cert_sha256
BROKER_POLL = settings.broker_poll
# Consecutive rounds without a broker response before giving the job up as lost.
BROKER_FAILURES_MAX = 15
# MODULE names, not `settings.x` directly inside `_configure_broker`: the tests
# swap `panel.X` for fakes to exercise each bad configuration, and reading
# `settings` in there would ignore the swap.
BROKER_REQUESTED = settings.allow_broker
DEV = settings.dev


def _configure_broker() -> bool:
    """Set up the broker client. Any bad configuration TURNS OFF the feature (and logs the
    reason) instead of taking the panel down: the rest of it does not depend on this."""
    if not BROKER_REQUESTED:
        return False
    try:
        with open(BROKER_TOKEN_FILE, encoding="utf-8") as file_path:
            token = file_path.read().strip()
        broker_client.configure(BROKER_URL, token, BROKER_CERT_SHA256,
                                 allow_http=DEV)
    except (OSError, ValueError) as failure:
        print(f"[painel] broker DESLIGADO: {failure}", file=sys.stderr)
        return False
    return True


ALLOW_BROKER = _configure_broker()

# File editor: reads/writes the game's configuration files over the same SSH.
ALLOW_FILES = settings.allow_files
# 1 = whoever has not enabled the second factor only reaches the enable screen. Off by default: turning it on
# BEFORE every admin has the app on their phone locks everyone out of the panel.
REQUIRE_2FA = settings.require_2fa
# https address (with a DOMAIN) through which people open the panel; empty = no biometric
# sign-in. The browser only allows WebAuthn in a secure context, and the device key is
# bound to the domain: changing the address later invalidates every registered passkey.
WEBAUTHN_ORIGIN = settings.webauthn_origin
# Limit for EDITING (the whole file goes into a textarea and comes back in a POST).
FILE_MAX_BYTES = settings.file_max_bytes
# Above the edit limit the panel still shows the end of the file, read-only.
FILE_PREVIEW_BYTES = settings.file_preview_bytes
# Download does not go through memory (it streams), so the cap is much larger.
# 0 = no limit.
FILE_DOWNLOAD_MAX = settings.file_download_max
DOWNLOAD_CHUNK = 256 * 1024
# Request body cap: the edited file is uploaded percent-encoded (up to 3x) + slack.
REQUEST_LIMIT = max(4 * 1024 * 1024, FILE_MAX_BYTES * 4 + 65536)
# Roots the file browser may enter. "/" = no restriction.
FILE_ROOTS = settings.file_roots
FILE_DEFAULT_PATH = settings.file_default_path
FILE_LIST_MAX = 800
# Upload: the file comes up as multipart and goes down over SSH as a stream, without passing whole
# through the panel's memory; that is why the cap here is much larger than the editor's, which loads
# everything into a textarea. 0 = no limit.
#
# Careful when raising it: Werkzeug stores the multipart body in a temporary file of the
# PANEL CONTAINER before the view sees a single byte. Uploading 2 GB needs 2 GB free there, and the
# panel CT is usually small. 512 MB covers mods and saves without that risk.
FILE_UPLOAD_MAX = settings.file_upload_max
UPLOAD_CHUNK = 256 * 1024

# Backup: tar.gz of the folders worth keeping (the save), created INSIDE the
# container and stored there, and right after pulled to the panel (see
# `runtime.backup_archive`). Both copies exist because the container one dies with it:
# removing the instance through the broker deletes the CT along with its disks.
BACKUP_DIR = settings.backup_dir
# How many copies to keep per server, in the container; the oldest ones go away on their own.
BACKUP_KEEP = settings.backup_keep
BACKUP_TIMEOUT = settings.backup_timeout
BACKUP_PATHS_MAX = 8
BACKUP_LIST_MAX = 100
# The panel copy: by PREFIX (the game service), not by server, to survive
# removing and registering again. Its own retention, 0 = never delete.
PANEL_BACKUP_DIR = settings.panel_backup_dir
PANEL_BACKUP_KEEP = settings.panel_backup_keep

# Scheduling: tasks the panel fires on its own (restart at dawn, daily
# backup). The clock is the PANEL CONTAINER's: if the times do not match yours,
# what is wrong is its TZ.
# This is the floor for ALL panel notifications: nothing can arrive faster than the clock's
# round. The clock itself costs almost nothing (the four tasks each have their own
# pace inside it and return right away when it is not their turn), so 15s gives room for the
# player alert without multiplying anyone's SSH.
SCHEDULE_TICK = settings.schedule_tick
# A task that is too late does not fire. If the panel was down overnight, nobody wants
# the "restart at 5am" landing at 2pm, in the middle of a match: it waits for the next occurrence.
SCHEDULE_GRACE = settings.schedule_grace
# Name shown in the history in place of the user, when the clock is what triggered it.
SCHEDULE_USER = "agendador"

# History retention: each job stores up to 200 KB of output, and a daily backup alone
# already puts 365 rows a year in the database. 0 turns cleanup off.
JOBS_KEEP_DAYS = settings.jobs_keep_days
JOBS_PURGE_EVERY = 3600.0
HISTORY_PAGE = 60

# Samples for the usage charts. Each one costs a gauge reading (the most expensive call
# in the panel: the remote script sleeps 0.5s to take two CPU samples),
# so the interval is generous: 5 min gives 288 points a day, plenty for the chart.
SAMPLE_EVERY = settings.sample_every
SAMPLES_KEEP_DAYS = settings.samples_keep_days

# Alerts: the panel notifies by webhook (Discord, Slack, anything that accepts a JSON POST)
# when a server goes down, drops off SSH, fills its disk or when a scheduled task fails.
# The URL lives in the database ("Alerts" screen); this variable only serves as the initial value, so the
# deploy can leave everything ready.
DEFAULT_WEBHOOK_URL = settings.webhook_url
WEBHOOK_TIMEOUT = settings.webhook_timeout
# The Cloudflare in front of Discord returns 403 (error 1010) for urllib's default
# User-Agent ("Python-urllib/3.x"), before the request even reaches the webhook. Sending our own
# User-Agent fixes it, and no other destination minds it.
WEBHOOK_UA = settings.webhook_ua
# Cap on destinations. Each alert becomes one POST per destination, in series, inside the
# monitor round: an endless list would make the round wait for all of them.
WEBHOOK_MAX = settings.webhook_max
# How often the panel checks the state of each server. Each round costs
# one SSH round trip per server: going too low does not help.
MONITOR_EVERY = settings.monitor_every
# A player joining is the only thing someone expects to see "now": whoever gets the notice
# usually wants to join too, and a minute later is already too late. That is why it has its own
# clock, shorter than the state one.
PLAYER_CHECK_EVERY = settings.player_check_every
# ...but it only applies to sources that answer for free. A2S and HTTP come from inside the container with
# nothing extra; counting by LOG is another story: each query is an SSH round trip that
# drags up to LOG_SCAN_MAX lines to the panel to apply the regex. At this short pace that would
# be megabytes per minute per server, to find two new lines. Whoever counts by
# log stays on the state clock until there is incremental reading or log streaming.
PLAYER_FAST_SOURCES = {"a2s", "http"}
# Whoever counts by log gets real time another way: a long SSH connection running
# `journalctl -f`. Instead of asking "is there anyone new?" every minute, the panel
# keeps listening and reacts to the line the instant it comes out.
LOG_STREAM = settings.log_stream
# A join and a leave in the same second (someone switching servers, a group
# joining together) must not each turn into a log reread. The first line triggers,
# the following ones in that window piggyback on the same check.
LOG_STREAM_DEBOUNCE = settings.log_stream_debounce
# After the connection drops, how long to wait before trying again. A server that is off
# must not turn into an SSH loop every second.
LOG_STREAM_RETRY = settings.log_stream_retry
# Disk comes from the gauges, which cost a lot more (the remote script sleeps 0.5s to
# take two samples). It does not fill up in a minute, so the check is spaced out.
DISK_CHECK_EVERY = settings.disk_check_every
# A panel action (stop, restart, update) takes the server down on purpose. In this
# window after it, a drop does not become an alert; otherwise every restart from the button would be a scare.
ALERT_QUIET = settings.alert_quiet

# Patterns used by the "find config files" button.
CONFIG_GLOBS = ("*.ini", "*.cfg", "*.conf", "*.json", "*.yaml", "*.yml", "*.properties", "*.txt")
# How many configuration files a server may have registered for the "Config" screen.
CONFIG_FILES_MAX = 8
# Cap on fields in the "Config" screen form: above this the file is almost certainly
# not configuration (a log matches "key=value" on many lines).
CONFIG_SETTINGS_MAX = 600

# The panel's short date format ("17/09 05:00"). It was handwritten on three
# screens; one of them with an extra space was enough to make the list look misaligned.
SHORT_DATE_FORMAT = "%d/%m %H:%M"

TPL_ERROR = "error.html"
TPL_LOGIN = "login.html"
MSG_TIMEOUT = "tempo esgotado"

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Panel roles. The split follows what gives root power on the container: shell, file
# editor and server registration are admin; operating what is already registered
# (start/stop/update, game configuration, log, players) is operator.
ROLE_ADMIN = "admin"
# The VALUE is the `role` column in the database: changing "operador" to "operator" would demote every
# operator already registered to "unknown role". Only the constant name is translated.
ROLE_OPERATOR = "operador"
ROLES = (ROLE_ADMIN, ROLE_OPERATOR)
# Catalog key, not the text: whoever reads the screen picks the language (`i18n`).
ROLE_LABELS = {
    ROLE_ADMIN: "role.admin",
    ROLE_OPERATOR: "role.operator",
}
PASSWORD_MIN = passwords.MIN_LENGTH

# CSRF: the panel has its own protection, not Flask-WTF.
#
# Static analyzers often flag this `Flask(__name__)` as "CSRF disabled"
# because they do not see a `CSRFProtect(app)`. Here the protection is the pair `csrf_token()` (the
# generator the templates call) and `_check_csrf` (a `before_request` that blocks
# any state-changing method without the session token) - look for both in this
# file. The choice is the same as the rest of the panel: dependencies are only the stdlib plus the
# apt `python3-flask`, because the panel container does not download packages from
# anywhere. Do not remove `_check_csrf` thinking Flask covers this on its own: it does not
# cover it.
#
# The suppression marker on the line below is the analyzer's own "reviewed hotspot"
# (rule python:S4502). Without it the warning comes back on every analysis and ends up as noise that
# one learns to ignore - which is how a real CSRF warning would slip by one day.
#
# It sits alone on the line, with no text after it: the marker has its own syntax, and an explanation
# glued to it is a malformed suppression (that is what happened here the first time). The
# why stays in this block, which is where one looks for it.
app = Flask(__name__)  # NOSONAR


def _load_secret_key() -> bytes:
    """Read the cookie signing key; generate it on the first run."""
    try:
        with open(SECRET_FILE, "rb") as fh:
            data = fh.read().strip()
        if data:
            return data
    except FileNotFoundError:
        pass
    data = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return data


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # The panel itself speaks http (TLS lives in a proxy in front). Whoever declared an https
    # address for the passkey already said the panel is accessed over https: then the session
    # cookie only travels encrypted, and a forgotten http link does not hand it over in clear text.
    SESSION_COOKIE_SECURE=WEBAUTHN_ORIGIN.startswith("https://"),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    # The editor posts the file as a form: in the worst case each byte becomes %XX (3x),
    # so the request limit has to be much larger than the file's own.
    MAX_CONTENT_LENGTH=REQUEST_LIMIT,
    # Werkzeug 3.1 started cutting form fields at 500 KB by default. Without
    # raising this too, saving a large file dies with 413 before reaching the view.
    MAX_FORM_MEMORY_SIZE=REQUEST_LIMIT,
)

# Development mode (docker compose): reloads templates without restarting.
if DEV:
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True

# ------------------------------------------------------------------- database

SCHEMA = schema.SCHEMA
MIGRATIONS = schema.MIGRATIONS


def db() -> sqlite3.Connection:
    """Connection per request. WAL so the background job does not block the screen's reads."""
    conn = getattr(g, "_db", None)
    if conn is None:
        conn = _connect()
        g._db = conn
    return conn


def _connect() -> sqlite3.Connection:
    return schema.connect(DB_PATH)


@app.teardown_appcontext
def _close_db(_exc) -> None:
    conn = getattr(g, "_db", None)
    if conn is not None:
        conn.close()


# Columns added after the first version: CREATE TABLE IF NOT EXISTS does not
# alter tables that already exist, so each one needs its own ALTER here.
# The third item is a SQL command or a tuple of them (the ALTER plus the fix for the
# old rows, when the column's default value does not suit the ones that already existed).
def init_db() -> None:
    schema.init_db(DB_PATH, DEFAULT_WEBHOOK_URL, ALERT_DEFAULT, now_iso)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- passwords


# Aliases: the algorithm lives in `security/passwords.py`, but the tests swap
# `panel.X` for fakes and the templates call `csrf_token()` by name; keeping both
# here is what keeps both of those working.
hash_password = passwords.hash_password
verify_password = passwords.verify_password


# ------------------------------------------------------- auth / csrf / brute force

LOCKOUT_TRIES = 5
LOCKOUT_WINDOW = 300.0
# A 6-digit guess has 3 valid numbers in 10^6: that is why the code lock is per
# USER (not per IP, which an attacker can change) and longer than the password one.
LOCKOUT_2FA_TRIES = 5
LOCKOUT_2FA_WINDOW = 900.0

# The password lock key is `ip|user` and the code one is `2fa|user`: separate
# instances because the limits differ, not because the keys would collide.
login_lockout = auth_service.Lockout(LOCKOUT_TRIES, LOCKOUT_WINDOW)
totp_lockout = auth_service.Lockout(LOCKOUT_2FA_TRIES, LOCKOUT_2FA_WINDOW)
# Passkey challenges issued and not yet answered (single use, in the worker's memory).
passkey_challenges = webauthn.Challenges()


def logged_user() -> sqlite3.Row | None:
    """The session user's row, read from the database once per request.

    The role does NOT live in the cookie: removing someone's admin has to take effect on the next click,
    not only when their session expires. A lookup by id in local SQLite costs
    less than anything this panel does next.
    """
    # `in`, not `getattr(..., sentinel)`: the cache stores None on purpose (nobody
    # signed in), so "has the key" and "has a value" are different questions here.
    if "_user" in g:
        return g._user
    uid = session.get("uid")
    row = None
    if uid:
        row = users_repo.for_session(db(), uid)
    g._user = row
    return row


def is_admin() -> bool:
    row = logged_user()
    return row is not None and row["role"] == ROLE_ADMIN


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if logged_user() is None:
            # Account deleted with the session still open: the cookie is still signed and
            # valid, so without checking the database it would keep working until it expired.
            session.clear()
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    """Routes that give root power on the container or change who has access."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            abort(403, i18n.Message("error.admin_only"))
        return view(*args, **kwargs)

    return login_required(wrapper)


def csrf_token() -> str:
    return csrf.token(session)


# Routes that receive a large body. The general cap (MAX_CONTENT_LENGTH) is tight because the
# editor sends the file percent-encoded inside a form; the upload needs a lot
# more than that.
#
# This hook has to come BEFORE _check_csrf in the file: registration order is execution
# order, and _check_csrf is what touches request.form first. The cap is checked at the
# moment the body is read, so adjusting it only inside the view would be too late (413).
# The mod upload too: a .pak or a map package easily exceeds the normal cap.
BIG_BODY_ENDPOINTS = {"files.upload", "mods.upload"}


@app.before_request
def _body_cap():
    if request.endpoint in BIG_BODY_ENDPOINTS:
        request.max_content_length = (FILE_UPLOAD_MAX + UPLOAD_CHUNK) if FILE_UPLOAD_MAX else None


@app.before_request
def _check_csrf():
    if request.method != "POST":
        return None
    if not csrf.matches(session, request.form, request.headers):
        abort(400, i18n.Message("error.csrf_invalid"))
    return None


# With GAMEPANEL_REQUIRE_2FA=1 whoever has not enabled the second factor only reaches this.
ENDPOINTS_WITHOUT_2FA = frozenset({
    "auth.login", "auth.login_2fa", "auth.logout", "account.two_factor",
    "passkeys.login_options", "passkeys.login",
    "health.health", "static",
    "pwa.manifest", "pwa.service_worker", "pwa.offline",
    "preferences.theme", "preferences.language",
})


@app.before_request
def _requires_second_factor():
    if not REQUIRE_2FA or request.endpoint in ENDPOINTS_WITHOUT_2FA or request.endpoint is None:
        return None
    user = logged_user()
    if user is None or user["totp_enabled"]:
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "ative a verificacao em duas etapas em Conta"}), 403
    flash(translate("flash.two_factor_required_here"), "error")
    return redirect(url_for("account.two_factor"))


def static_url(name: str) -> str:
    """URL of a static file with the mtime mark.

    Without this, a deploy that changes css/components.css or js/terminal.js keeps
    serving what the browser cached, and the report arrives as "the screen broke after
    the update".

    Accepts a path with a subfolder ("css/tokens.css"): the static tree is organized
    into css/, js/ and icons/.
    """
    try:
        mark = int(os.path.getmtime(os.path.join(app.static_folder or "", name)))
    except OSError:
        mark = 0
    return url_for("static", filename=name, v=mark)


DEFAULT_LANG = i18n.valid_language(settings.lang)


def current_language() -> str:
    """The language of THIS request, decided once and stored in `g`.

    The order is by preference: what the person chose in Account beats everything; with no choice
    (or nobody signed in, as on the login screen) the header language button
    (cookie) applies, then what the browser asks for; and the last resort is the deploy default.

    OUTSIDE a request there is no person or browser, and `g` does not even exist: the monitor and the
    scheduler run in their own thread, and the alert that comes out of there is written for the
    team channel, not for whoever has the screen open. There the deploy default applies. Without this
    gate, translating an alert message would take down the whole monitor round with
    "Working outside of application context", and an alert that breaks is a server down that
    nobody hears about.
    """
    if not has_app_context():
        return DEFAULT_LANG
    chosen_one = getattr(g, "_language", None)
    if chosen_one is not None:
        return chosen_one
    user = logged_user()
    from_user = _stored_value(user, "lang") if user else ""
    if from_user:
        chosen_one = i18n.valid_language(from_user)
    elif request and request.cookies.get("lang"):
        chosen_one = i18n.valid_language(request.cookies.get("lang"))
    elif request:
        chosen_one = i18n.from_header(request.headers.get("Accept-Language"))
    else:
        chosen_one = DEFAULT_LANG
    g._language = chosen_one
    return chosen_one


def translate(key: str, **fields: object) -> str:
    """The `_()` of screens and messages: the sentence for that key, in the language
    of this request."""
    return i18n.translate(key, current_language(), **fields)


def error_text(exc: BaseException) -> str:
    """What the exception has to say, preserving the KEY when it came from one.

    `str(exc)` would collapse an `i18n.Message` into loose text, and with it the chance to
    show the sentence in the language of whoever is looking. An `except` catches any exception,
    including those born outside here (`OSError`, `json`), and those go through `str`.
    """
    if exc.args and isinstance(exc.args[0], i18n.Message):
        return exc.args[0]
    return str(exc)

def label_for_db(key: str) -> str:
    """The sentence for that key in the DEPLOY language, not in that of whoever has the screen open.

    For text that is going to be STORED (the `command` column of a job, for example). The
    history is read later, by someone else, maybe in another language: if each record
    came out in the language of whoever clicked, the same action would appear written three ways in the
    same list, and filtering by it would stop working.
    """
    return i18n.translate(key, DEFAULT_LANG)


def translate_html(key: str, **fields: object) -> Markup:
    """The screens' `_h()`: a sentence that CARRIES markup (`<strong>`, `<code>`).

    It exists because a help paragraph is not split: breaking the text at each `<strong>`
    would leave half the paragraph in Portuguese on the English screen. The sentence comes from the catalog,
    which is code from this repository, so it may contain markup; what comes from outside
    are the FIELDS, and each one is escaped before going in.

    `escape`, not `escape(str(...))`, on purpose: that way a field that ALREADY is markup
    (the `_h` of another sentence, nested in this one) passes whole instead of showing up on screen
    with its angle brackets exposed.
    """
    # The sentence comes from `i18n`, which is code from this repository, and every field went through
    # `escape` on the line below: there is no user input arriving raw here.
    return Markup(i18n.translate(  # noqa: S704
        key, current_language(), **{name: escape(value) for name, value in fields.items()}
    ))


def labels_of(labels: dict[str, str]) -> dict[str, str]:
    """Translate a table of labels at once, so the screen receives ready text.

    The tables (`ALERT_EVENTS`, `JOB_LABELS`, `ROLE_LABELS`, ...) store the catalog KEY
    and not the sentence: the key is what goes to the database and to `<option value=>`,
    and it cannot change just because someone fixed a comma in the text.
    """
    return {key: translate(label) for key, label in labels.items()}

def _chosen_theme() -> str:
    raw = request.cookies.get("theme", "") if has_request_context() else ""
    return raw if raw in ("light", "dark") else ""


@app.context_processor
def _inject():
    user = logged_user()
    return {
        "csrf_token": csrf_token,
        # `_` is the usual name for translating on a screen; `_h` is its sibling for a sentence
        # that carries markup (see `translate_html`).
        "_": translate,
        "_h": translate_html,
        "current_language": current_language(),
        "html_lang": i18n.html_lang(current_language()),
        "languages": i18n.LANGUAGES,
        # The language the header button offers: the other of the two.
        "other_language": next(code for code, _name in i18n.LANGUAGES if code != current_language()),
        # Empty = follow the system (prefers-color-scheme); only the button stores light/dark.
        "current_theme": _chosen_theme(),
        "static_url": static_url,
        "current_user": user["username"] if user else None,
        # The screens hide what the operator cannot open. The @admin_required on the route
        # is what rules; this is only so as not to show a button that leads to 403.
        "is_admin": bool(user) and user["role"] == ROLE_ADMIN,
        # The biometrics button only appears with the address configured (without it there is no RP ID).
        "passkeys_enabled": bool(WEBAUTHN_ORIGIN),
        "role_label": translate(ROLE_LABELS[user["role"]]) if user else "",
        "job_label": job_label,
        # Which code is serving this screen. It goes in the footer, and not only in /health, because
        # whoever opens a ticket ("the screen did not update") is looking at the SCREEN, and the
        # answer fits in a line they can read out loud.
        "app_version": version.BUILD.version,
        "allow_shell": ALLOW_SHELL,
        "allow_term": ALLOW_SHELL and HAVE_PTY,
        "allow_files": ALLOW_FILES,
        "allow_broker": ALLOW_BROKER,
        # The screen needs to know whether counting is on, and it may come from the query
        # port OR from the log: looking only at query_port is not enough.
        "player_source": player_source,
        # Which actions that server's API accepts (empty for most games).
        "player_actions": player_actions,
        "action_label": labels_of(PLAYER_ACTION_LABELS),
        # Legacy (root) or helper (gamepanel) access: the server screen says which, so whoever
        # looks after the servers sees at a glance which ones still have to be migrated.
        "privileged_access": remote_cmd.privileged,
        "content_user": remote_cmd.content_user,
        **_navigation_context(),
    }


def _navigation_context() -> dict:
    """The interface map, already filtered for whoever is signed in and for this deploy.

    The templates no longer decide what exists in the menu: they draw whatever comes
    from here. Before, a server's list of screens was handwritten in six
    different templates, each with its own subset, and that was why
    "Charts" existed on one screen and not on the other.
    """
    admin = is_admin()
    sections = ui.visible_sections(admin=admin, arquivos=ALLOW_FILES, shell=ALLOW_SHELL)
    has_pty = ALLOW_SHELL and HAVE_PTY
    slash, account = ui.nav_desktop(admin=admin, broker=ALLOW_BROKER)
    return {
        "nav_main": ui.visible_items(ui.NAV_MAIN, admin=admin, broker=ALLOW_BROKER),
        "nav_secondary": ui.visible_items(ui.NAV_SECONDARY, admin=admin, broker=ALLOW_BROKER),
        "nav_active": ui.active_nav_for(request.endpoint),
        "nav_desktop_bar": slash,
        "nav_desktop_account": account,
        "nav_active_desktop": ui.active_desktop_nav_for(request.endpoint),
        "server_sections": sections,
        "section_endpoint": lambda section: ui.section_endpoint(section, tem_pty=has_pty),
        "power_actions": ui.actions_in_group(ui.GROUP_POWER),
        "maintenance_actions": ui.actions_in_group(ui.GROUP_MAINTENANCE),
        "card_power": ui.card_power,
        "remaining_power": ui.remaining_power,
    }


# ------------------------------------------------------------------- ssh
#
# Real implementation in gamepanel.runtime.ssh (extracted in Phase 4 - only the transport
# layer, tested indirectly by the dozens of tests that already exercise
# server_status/server_players/etc.). The names below still exist in this module
# on purpose: it is what `monkeypatch.setattr(panel, "ssh_run", ...)` and direct calls
# like `panel.ssh_argv(...)` (see test_players.py) expect to find.

def _ssh_config() -> ssh_transport.SshConfig:
    # A function, not a value: monkeypatch.setattr(panel, "SSH_KEY", ...) (and the other
    # variables below) only take effect if this rereads the module globals on every call.
    return ssh_transport.SshConfig(
        key=SSH_KEY, known_hosts=KNOWN_HOSTS, control_dir=SSH_CONTROL_DIR,
        control_persist=SSH_CONTROL_PERSIST, quick_timeout=QUICK_TIMEOUT,
    )


_ssh = ssh_transport.SshClient(_ssh_config)
RemoteError = ssh_transport.RemoteError
ssh_argv = _ssh.argv
ssh_run = _ssh.run
ssh_output = _ssh.output
public_key = _ssh.public_key
forget_host_key = _ssh.forget_host
q = ssh_transport.quote_command


def in_parallel(tasks: dict, timeout: float = 40.0) -> dict:
    """Run several remote reads at the same time; return {name: (value, error)}.

    Each one costs its own SSH round trip, and they do not depend on each other: in series the
    screen pays the sum, and with a server down it pays the sum of the timeouts.

    Nothing here may touch Flask's `g` (the per-request connection does not cross threads).
    The functions used on the detail screen either do not talk to the database, or open their
    own connection: the `http_login` of API counting is that case, and it already does so.
    """
    output: dict = {}
    lock = threading.Lock()

    def work(name, call):
        try:
            value, failure = call(), ""
        except (RemoteError, QueryError) as exc:
            value, failure = None, str(exc)
        with lock:
            output[name] = (value, failure)

    threads = [threading.Thread(target=work, args=(n, f), daemon=True)
               for n, f in tasks.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    for name in tasks:
        output.setdefault(name, (None, MSG_TIMEOUT))
    return output


# --------------------------------------------------------- players via the A2S protocol
#
# Real implementation in gamepanel.runtime.a2s (extracted in Phase 4). The names below
# still exist in this module on purpose - QueryError in particular is used by
# `raise`/`except` all over the rest of app.py (HTTP, log, player actions), and
# `pytest.raises(panel.QueryError)` in test_players.py needs to keep finding the
# SAME class.
QUERY_TIMEOUT = settings.query_timeout
PLAYERS_TTL = settings.players_ttl

PLAYER_SOURCES = player_service.PLAYER_SOURCES

QueryError = a2s.QueryError
AuthError = a2s.AuthError


def query_players(host: str, port: int) -> dict:
    # Reads QUERY_TIMEOUT at call time (not a value frozen at import): same
    # reason as SshClient in runtime/ssh.py.
    return a2s.query_players(host, port, timeout=QUERY_TIMEOUT)


# ------------------------------------------- players (the game's own HTTP API)
#
# The pure part (building the HTTP request, interpreting the response, finding the list/count in the
# JSON) lives in gamepanel.runtime.http_probe; the part that depends on the database (storing the renewed
# token) lives in gamepanel.services.player_service. The names below stay here
# because the rest of app.py, and the tests, call them.
HTTP_TIMEOUT = settings.http_timeout
HTTP_BODY_MAX = 2000
HTTP_PATH_MAX = 120
HTTP_FIELDS = player_service.HTTP_FIELDS

auth_header = http_probe.auth_header
read_players_json = http_probe.read_players_json
URL_RE = http_probe.URL_RE
HTTP_URL_MAX = http_probe.HTTP_URL_MAX
_split_status = http_probe._split_status
_json_walk = http_probe._json_walk
_id_do_item = http_probe._id_of
_has_login = player_service._has_login


def http_json(server: ServerRow, url: str, auth: str, body: str, exigir_json: bool = True):
    # HTTP_TIMEOUT read at call time, not frozen - same care as SshClient
    # (runtime/ssh.py) and query_players (runtime/a2s.py).
    return http_probe.http_json(ssh_output, server, url, auth, body, HTTP_TIMEOUT, exigir_json)


def _stored_value(server: ServerRow, coluna: str) -> str:
    try:
        return (server[coluna] or "").strip()
    except (IndexError, KeyError):
        return ""


def _player_deps() -> player_service.PlayerDeps:
    """The pieces that counting needs, assembled at call time.

    At call time, not at import: `http_json`, `read_log_lines` and `query_players` are names
    in this module that a test may swap for fakes, and a bundle frozen at import
    would bypass the swap without anyone noticing.
    """
    return player_service.PlayerDeps(
        http_json=http_json, connect=_connect, read_log_lines=read_log_lines,
        query_players=query_players, players_ttl=PLAYERS_TTL,
        presence_players=presence_players,
    )


def presence_players(server: ServerRow) -> dict:
    return presence_probe.players_from_presence(ssh_output, server)


def http_login(server: ServerRow) -> str:
    return player_service.http_login(_player_deps(), server)


def call_game_api(server: ServerRow, url: str, body: str = "",
                      exigir_json: bool = True):
    return player_service.call_game_api(_player_deps(), server, url, body, exigir_json)


def players_from_http(server: ServerRow) -> dict:
    return player_service.players_from_http(_player_deps(), server)


# ------------------------------------------- actions on who is playing
#
# Catalog and rules in gamepanel.services.player_service; here only the names that the
# screen, the routes and the tests already use.

PLAYER_MSG_MAX = player_service.PLAYER_MSG_MAX
PLAYER_ACTION_LABELS = player_service.PLAYER_ACTION_LABELS
BASE_MARK = player_service.BASE_MARK
PLAYER_MARK = player_service.PLAYER_MARK
MESSAGE_MARK = player_service.MESSAGE_MARK
API_ACTIONS = player_service.API_ACTIONS
actions_api = player_service.actions_api
player_actions = player_service.player_actions
_fill = player_service._fill


def run_player_action(server: ServerRow, action: str, player: str, message: str) -> str:
    return player_service.player_action(_player_deps(), server, action, player, message)


# ------------------------------------------------------ players (from the log)
#
# Real implementation in gamepanel.runtime.log_probe (Phase 4). Names kept here
# for the same two usual reasons: direct tests by name (`panel.compile_pattern`,
# `panel._apply_log_events`) and use by the rest of app.py not yet extracted (LOG_FOLLOW_SCRIPT
# feeds the real-time log streaming, further down in the file).
LOG_SCAN_MAX = log_probe.LOG_SCAN_MAX
RE_MAX_LEN = log_probe.RE_MAX_LEN
LOG_HINT_WORDS = log_probe.LOG_HINT_WORDS
LOG_LINE_MAX = log_probe.LOG_LINE_MAX
LOG_FOLLOW_SCRIPT = log_probe.LOG_FOLLOW_SCRIPT
LOG_PATH_RE = log_probe.LOG_PATH_RE
compile_pattern = log_probe.compile_pattern
_apply_log_events = log_probe.apply_log_events
valid_log_path = log_probe.valid_log_path


# ------------------------------------------- discovering how to count players
#
# Real implementation in gamepanel.runtime.port_probe (Phase 4). Names kept here
# for the same two usual reasons: direct tests by name (`panel._ports_from_text`,
# `panel._without_repeats`, `panel._with_owner`, `panel._summarize_generic`) and use by routes
# that have not been extracted yet.
QUERY_PORT_GUESSES = port_probe.QUERY_PORT_GUESSES
API_PORT_GUESSES = port_probe.API_PORT_GUESSES
HTTP_PROBE_TIMEOUT = settings.http_probe_timeout
HTTP_PROBE_PORTS_MAX = port_probe.HTTP_PROBE_PORTS_MAX
_ports_from_text = port_probe._ports_from_text
_without_repeats = port_probe._without_repeats
_with_owner = port_probe._with_owner
_summarize_generic = port_probe._summarize_generic


def candidate_ports(server: ServerRow) -> tuple[list[int], list[int], dict, str]:
    return port_probe.candidate_ports(ssh_output, server, server["game_port"])


def probe_http_ports(server: ServerRow, ports: list[int]) -> tuple[list[dict], list[int], str]:
    return port_probe.probe_http_ports(ssh_output, server, ports, HTTP_PROBE_TIMEOUT)


def probe_ports(host: str, ports: list[int]) -> list[dict]:
    return port_probe.probe_ports(host, ports, QUERY_TIMEOUT)


def read_log_lines(server: ServerRow, limit: int = LOG_SCAN_MAX) -> list[str]:
    return log_probe.read_log_lines(
        ssh_output, server, server["service"], _stored_value(server, "log_path"), limit,
    )


def players_from_log(server: ServerRow) -> dict:
    return player_service.players_from_log(_player_deps(), server)


# The SAME object as the service's (not a copy): the tests' `database` fixture clears the
# stored count by this name, and a different dictionary here would leave the real cache
# intact between cases.
_players_cache = player_service._players_cache
invalidate_players = player_service.invalidate
player_source = player_service.player_source


def server_players(server: ServerRow, force: bool = False) -> dict:
    return player_service.server_players(_player_deps(), server, force)


def all_players(servers) -> dict[int, dict]:
    # `server_players` goes inside a lambda, not directly: that way the name is
    # resolved in this module on every call, and swapping it for a fake (monkeypatch in the
    # alert and chart tests) keeps taking effect inside the parallel run.
    return player_service.all_players(
        lambda srv: server_players(srv), servers, QUERY_TIMEOUT * 3 + 2, MSG_TIMEOUT,
    )


# ------------------------------------------------------------------ resources
#
# Script and number parsing in gamepanel.runtime.metrics_probe; cache and decision in
# gamepanel.services.metrics_service. `server_metrics` stays here because the rest of
# app.py, and the monkeypatch of the alert and chart tests, call it.
#
# The SAME dictionary as the service's: the `database` fixture clears the cache by this name.
_metrics_cache = metrics_service._metrics_cache


def server_metrics(server: ServerRow, force: bool = False) -> dict:
    return metrics_service.server_metrics(
        ssh_output, server, FILE_DEFAULT_PATH, METRICS_TTL, force)


def all_metrics(servers) -> dict[int, dict]:
    # `server_metrics` goes in through a lambda so the name is resolved in this module on every
    # call: that is what keeps the swap for a fake taking effect inside the parallel run.
    return parallel.per_server(
        lambda srv: server_metrics(srv), servers, 35, {"error": MSG_TIMEOUT})


# --------------------------------------------------------------- status cache

_status_cache = status_service._status_cache
invalidate_status = status_service.invalidate


def server_status(server: ServerRow, force: bool = False) -> dict:
    return status_service.server_status(ssh_output, server, STATUS_TTL, force)


def all_status(servers) -> dict[int, dict]:
    return parallel.per_server(
        lambda srv: server_status(srv), servers, QUICK_TIMEOUT + 5,
        {"reachable": False, "service": "desconhecido", "error": MSG_TIMEOUT},
    )


# ------------------------------------------------------------------- jobs

# What each action RUNS in the container. How it is presented (label, icon, group,
# visual weight) is another responsibility, and lives in `navigation.py`; here there are only the
# commands, which is what this module has to say about them.
#
# Each one is a ROOT action: `remote_cmd` turns it into `systemctl`/the update script for a
# legacy (root) server and into the fixed `sudo -n` helper line for a `gamepanel` one.
COMMANDS = {
    key: (lambda s, key=key: remote_cmd.as_root_action(s, key))
    for key in ("start", "restart", "stop", "update", "check-update")
}

# The two lists must not diverge silently: an action with a button and no command gives a
# 500 on click, and one with a command and no button is dead code nobody notices.
#
# `raise`, not `assert`: with `python -O` the assert is DISCARDED, and I measured that the divergence
# goes unnoticed in that mode, exactly what this line exists to prevent.
# Production does not run with -O today, but an invariant that depends on that is not an invariant.
# At import, failing the START is the right behavior: better not to start than to start with
# a button that gives a 500 on the first click.
if set(COMMANDS) != set(ui.BY_KEY):
    difference = set(COMMANDS) ^ set(ui.BY_KEY)
    raise RuntimeError(f"ui.ACTIONS e app.COMMANDS fora de sincronia: {sorted(difference)}")

# Old shape, built from the two: key -> (label, command, confirm).
# Still what `start_job` and the history consume.
ACTIONS = {
    key: (ui.BY_KEY[key].label, command, ui.BY_KEY[key].confirm)
    for key, command in COMMANDS.items()
}

# The labels of button actions come from `ui`; those of actions born on other screens
# (console, editor, broker) come from `job_service`, along with the list of who may read them.
JOB_LABELS = job_service.labels(
    {key: label for key, (label, _cmd, _c) in ACTIONS.items()})
JOB_ACTIONS_ADMIN = job_service.ADMIN_ONLY_ACTIONS


def job_label(action: str) -> str:
    """The action name on screen. `JOB_LABELS` stores a KEY, never ready text:
    the history is a screen like the others and follows the language of whoever opened it.
    """
    return translate(JOB_LABELS.get(action, action))


def job_or_403(job: sqlite3.Row) -> None:
    """Block the operator from the output of a job they would not be allowed to trigger."""
    if job_service.is_restricted(job["action"]) and not is_admin():
        abort(403, i18n.Message("error.job_admin_only"))


def role_filter() -> tuple[str, tuple]:
    """WHERE fragment that hides the restricted actions' jobs from the operator."""
    return job_service.hidden_filter(is_admin())


def server_jobs(conn: sqlite3.Connection, sid: int, limit: int) -> list:
    """Server history already filtered by the role of whoever is looking."""
    cut, values = role_filter()
    return jobs_repo.of_server(conn, sid, limit, cut, values)


def _inserted_id(cur: sqlite3.Cursor) -> int:
    """The id of the row just inserted.

    `lastrowid` is Optional in the type because a cursor may not have inserted anything; after
    an INSERT that succeeded, never. Failing loudly here is better than spreading an
    `or 0` that would become "job number zero" in the history.
    """
    if cur.lastrowid is None:
        raise RuntimeError("INSERT nao devolveu id da linha")
    return cur.lastrowid


def log_job(
    action: str,
    server: ServerRow | dict,
    username: str,
    command: str = "",
    output: str = "",
    status: str = "ok",
) -> int:
    """Record in the history something that already happened (file edit, terminal
    session). Unlike start_job, it triggers nothing: it only leaves the trail."""
    conn = db()
    with conn:
        return jobs_repo.record(conn, server, action, status, output, command,
                                username, now_iso())


# A job step: a remote command (text, goes over SSH) or a Python function that receives the
# server and the output so far and returns its own text. A function is what SSH alone does not
# do: pull the backup to the panel's disk, send the copy back, call the broker.
JobStep = str | Callable[[dict, str], str]


def _join_output(before: str, text: str) -> str:
    if before and text and not before.endswith("\n"):
        before += "\n"
    return before + text


def _run_steps(target: dict, steps: list[JobStep], timeout: int) -> tuple[str, str, int | None]:
    """Run the steps in order and stop at the first that fails: (output, status, code).

    Stopping is the point: the restore only extracts if the safety copy came out, and deactivating the
    instance only happens if the save is already on the panel.
    """
    output = ""
    for step in steps:
        try:
            if callable(step):
                text, code = step(target, output), 0
            else:
                # Its own connection: an update takes almost an hour, and the shared master
                # would be stuck with it, with the whole monitor depending on a command that
                # may drop halfway.
                proc = ssh_run(target, step, timeout=timeout, multiplex=False)
                text, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
        except RemoteError as exc:
            return _join_output(output, str(exc)), "error", None
        output = _join_output(output, text)
        if code != 0:
            return output, "error", code
    return output, "ok", 0


def start_job(
    action: str,
    server: ServerRow,
    username: str,
    remote_cmd: str | None = None,
    command: str = "",
    timeout: int = JOB_TIMEOUT,
    steps: list[JobStep] | None = None,
) -> int:
    # Resolved HERE, not inside `run()` down below: what the thread executes must not
    # depend on an optional parameter someone changes along the way.
    if steps is None:
        steps = [remote_cmd if remote_cmd is not None else ACTIONS[action][1](server)]
    job_steps = list(steps)
    conn = db()
    with conn:
        job_id = jobs_repo.start(conn, server, action, command, username, now_iso())
    server_id = int(server["id"])
    # The thread cannot use the Row tied to the request connection: copy what it needs.
    target = dict(server)

    def run():
        output, status, code = _run_steps(target, job_steps, timeout)
        # Its own connection: this thread lives outside the request context.
        conn2 = _connect()
        with conn2:
            jobs_repo.finish(conn2, job_id, status, code, output, now_iso())
        # Failure of a SCHEDULED task becomes an alert: it is the only one nobody is watching. Whoever
        # clicked the button already has the result on screen.
        if status == "error" and username == SCHEDULE_USER:
            try:
                notify(conn2, "job-falhou",
                         f"{target.get('name', '?')}: {job_label(action)} falhou",
                         (output or "").strip()[-500:])
            # An alert never takes down the job.
            except Exception:
                app.logger.exception("falha ao avisar sobre o job %s", job_id)
        conn2.close()
        invalidate_status(server_id)

    threading.Thread(target=run, daemon=True).start()
    return job_id


# ----------------------------------------------------------------- alerts
#
# The panel already knows the state of each server (and the dashboard screen asks for it all
# the time). What was missing was TELLING someone without anybody watching: a
# JSON POST to the URL that Discord or Slack give for free.

# The VALUE is a catalog key; the KEY is what goes to the database and to the webhook.
# Changing an event's text must not touch what is already stored in `alert_log`.
ALERT_EVENTS = {
    "caiu": "event.server_stopped",
    "voltou": "event.server_back",
    "quebrou": "event.game_failed",
    "reiniciando": "event.restart_loop",
    "travou": "event.game_mute",
    "respondeu": "event.game_answering",
    "jogador-entrou": "event.player_joined",
    "jogador-saiu": "event.player_left",
    "erro-no-log": "event.log_error",
    "inacessivel": "event.lost_contact",
    "acessivel": "event.contact_back",
    "job-falhou": "event.scheduled_task_failed",
    "disco-cheio": "event.disk_almost_full",
    "memoria-alta": "event.memory_almost_full",
    "cpu-alta": "event.cpu_high",
}
# They need configuration in the server registration to do anything. The screen warns
# about whoever is checked without having anywhere to look; otherwise the alert stays on and silent, and the person
# concludes the game never fails.
ALERT_PRECISA_CONFIG = {
    "travou": "contagem de jogadores por consulta (A2S) ou API HTTP",
    "respondeu": "contagem de jogadores por consulta (A2S) ou API HTTP",
    "jogador-entrou": "contagem de jogadores (A2S, API HTTP ou log)",
    "jogador-saiu": "contagem de jogadores (A2S, API HTTP ou log)",
    "erro-no-log": "uma expressao de erro no cadastro do servidor",
}
# What comes on by default: the bad news that works without configuring anything. 'voltou',
# 'acessivel' and 'respondeu' are relief, not urgency; whoever wants the full pair turns it on in the
# screen. 'erro-no-log' stays out because it costs one more SSH round trip per server and does
# nothing without a registered expression.
ALERT_DEFAULT = "caiu,quebrou,reiniciando,travou,inacessivel,job-falhou,disco-cheio"
DISK_PCT_DEFAULT = 90
MEM_PCT_DEFAULT = 90
CPU_PCT_DEFAULT = 90
# The three come from the SAME gauge reading: with the server_metrics cache in between, looking at
# all three costs a single SSH round trip, so they move together on the same clock.
RESOURCE_EVENTS = {"disco-cheio", "memoria-alta", "cpu-alta"}
# How many lines of the alert log are kept.
ALERT_LOG_KEEP = settings.alert_log_keep

# How many consecutive rounds the game needs to stay silent before the alert. An A2S query is
# UDP: a lost packet is routine, and alerting on the first silence would fill the channel with
# false scares.
MUTE_ROUNDS = settings.mute_rounds
# The log is the only one of these that costs its own SSH round trip, so it has its own interval.
LOG_CHECK_EVERY = settings.log_check_every
# How many lines from the end of the log to look at on each pass.
LOG_ERR_LINES = 200
# Cap of one log alert per server in this window. The expression comes from the screen and a careless '.'
# matches everything: without this lock, a typo becomes a flood.
LOG_ERR_COOLDOWN = settings.log_err_cooldown


def config_get(conn: sqlite3.Connection, key: str, padrao: str = "") -> str:
    return settings_repo.get(conn, key, padrao)


def config_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        settings_repo.set_value(conn, key, value)


def clean_events(raw: str) -> set:
    """Filter by the known list: an event that left the code does not come back through the database."""
    return {e for e in (raw or "").split(",") if e in ALERT_EVENTS}


def webhook_list(conn: sqlite3.Connection) -> list:
    """All destinations, in registration order, with the events already as a set."""
    lines_of = alerts_repo.all_webhooks(conn)
    return [
        {
            "id": r["id"],
            "name": r["name"] or "Sem nome",
            "url": r["url"],
            "url_curta": mask_url(r["url"]),
            "events": clean_events(r["events"]),
            "enabled": bool(r["enabled"]),
        }
        for r in lines_of
    ]


def webhook_config(conn: sqlite3.Connection) -> dict:
    """Alert state: the destinations, what their union covers, and the disk limit.

    'events' is the UNION of the enabled destinations: it is what the monitor uses to decide whether it is
    worth looking at anything. Who receives what is resolved later, destination by destination.
    """
    try:
        disk = int(config_get(conn, "webhook_disk_pct", str(DISK_PCT_DEFAULT)))
    except ValueError:
        disk = DISK_PCT_DEFAULT
    try:
        memory = int(config_get(conn, "webhook_mem_pct", str(MEM_PCT_DEFAULT)))
    except ValueError:
        memory = MEM_PCT_DEFAULT
    try:
        cpu = int(config_get(conn, "webhook_cpu_pct", str(CPU_PCT_DEFAULT)))
    except ValueError:
        cpu = CPU_PCT_DEFAULT
    targets = webhook_list(conn)
    covered = set()
    for d in targets:
        if d["enabled"] and d["url"]:
            covered |= d["events"]
    return {
        "targets": targets,
        "active": [d for d in targets if d["enabled"] and d["url"]],
        "events": covered,
        "disk": min(100, max(50, disk)),
        "memory": min(100, max(50, memory)),
        "cpu": min(100, max(50, cpu)),
    }


mask_url = webhook_client.mask_url


def send_webhook(url: str, text: str) -> str:
    # Its own name (and not `webhook_client.send` directly in the calls) because the conftest's
    # `webhooks` fixture swaps THIS name for a capturer: every alert test
    # depends on it to see what would go out over HTTP without anything actually going out.
    return webhook_client.send(url, text, WEBHOOK_TIMEOUT, WEBHOOK_UA)


def notify(conn: sqlite3.Connection, event: str, title: str, detail: str = "") -> bool:
    """Send the alert to each destination that asked for this event.

    Return whether it went out to ANYONE. A destination that is down (Discord up, Slack down) does not
    silence the others: each one is tried and each failure goes to the log with the destination name,
    so one can tell which of them is broken without guessing.
    """
    targets = [d for d in webhook_list(conn)
             if d["enabled"] and d["url"] and event in d["events"]]
    if not targets:
        # Recorded on purpose: "the alert fired and nobody asked for it" is the
        # most common cause of a silent channel, and it is indistinguishable from "nothing happened" for whoever
        # only looks at Discord. In the log the two become different things.
        _record_alert(conn, event, title, detail, "", "sem-destino")
        return False
    text = f"**{title}**"
    if detail:
        text += f"\n{detail}"
    left = False
    for target in targets:
        failure = send_webhook(target["url"], text)
        if failure:
            app.logger.warning(
                "alerta '%s' nao saiu para '%s': %s", event, target["name"], failure
            )
            _record_alert(conn, event, title, detail, target["name"],
                             "falhou", failure)
        else:
            left = True
            _record_alert(conn, event, title, detail, target["name"], "enviado")
    return left


def _record_alert(conn: sqlite3.Connection, event: str, title: str, detail: str,
                     target: str, status: str, error: str = "") -> None:
    """Write one line to the alert log.

    Swallows its own error on purpose: the log exists to explain the alert, and it would be
    absurd for it to stop the alert from going out. At worst there is no record, never no delivery.
    """
    try:
        with conn:
            alerts_repo.log(conn, now_iso(), event, title, detail, target, status, error)
    except sqlite3.Error:
        app.logger.exception("nao consegui gravar no diario de alertas")


def recent_alerts(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    """The last lines of the alert log, newest to oldest."""
    return [dict(row) for row in alerts_repo.recent(conn, limit)]


def _recent_job(conn: sqlite3.Connection, sid: int) -> bool:
    """Was there a panel action on this server a short while ago?

    Restarting from the button takes the service down for a few seconds, and that is NOT a crash.
    Without this window, every restart and every update would become an alert.
    """
    cut = (datetime.now(UTC) - timedelta(seconds=ALERT_QUIET)).isoformat()
    return jobs_repo.acted_since(conn, sid, cut)


# server_id -> last state seen. It stays only in memory on purpose: restarting the panel
# rebuilds the baseline, and nobody gets an alert about something that was already like that.
_monitor_state: dict[int, dict] = {}
# One clock per pace (see `tasks/ticker.py`). An instance and not a loose variable because
# `conftest.py` needs to reset all of them between one test and the next, and one more `global` is
# one more name for it to get wrong silently.
monitor_tick = ticker.Ticker()
state_tick = ticker.Ticker()
resource_tick = ticker.Ticker()
log_tick = ticker.Ticker()


def _alert_deps() -> alert_service.AlertDeps:
    """The pieces the alert rules need, assembled at call time.

    At call time, not at import: `server_players`, `server_metrics` and `notify` are names
    in this module, and the alert tests swap the first two for fakes in each case;
    a bundle frozen at import would bypass the swap silently.
    """
    return alert_service.AlertDeps(
        notify=notify, recent_job=_recent_job, player_source=player_source,
        server_players=server_players, server_metrics=server_metrics,
        read_log_lines=read_log_lines, stored_value=_stored_value,
        human_size=_human_size, monitor_state=_monitor_state,
        logger=app.logger, mute_rounds=MUTE_ROUNDS, log_err_lines=LOG_ERR_LINES,
        log_err_cooldown=LOG_ERR_COOLDOWN,
    )


def _state_alert(conn, server, state, anterior) -> None:
    alert_service.state_alert(_alert_deps(), conn, server, state, anterior)


def _restart_alert(conn, server, state, anterior) -> None:
    alert_service.restart_alert(_alert_deps(), conn, server, state, anterior)


def _mute_alert(conn, server, state, anterior) -> None:
    alert_service.mute_alert(_alert_deps(), conn, server, state, anterior)


def _log_alert(conn, server, anterior) -> None:
    alert_service.log_alert(_alert_deps(), conn, server, anterior)


def _disk_alert(conn, server, cfg) -> None:
    alert_service.disk_alert(_alert_deps(), conn, server, cfg)


def _memory_alert(conn, server, cfg) -> None:
    alert_service.memory_alert(_alert_deps(), conn, server, cfg)


def _cpu_alert(conn, server, cfg) -> None:
    alert_service.cpu_alert(_alert_deps(), conn, server, cfg)


# Resource event -> who checks it. The three read the SAME gauge and move on the same
# clock; as a table, enabling a fourth (network, for example) is adding a line,
# not one more `if` inside the monitor loop.
#
# Points to the functions of THIS module, not the service's: the table captures the
# object at import, and it is by these names that the tests call.
RESOURCE_ALERTS = {
    "disco-cheio": _disk_alert,
    "memoria-alta": _memory_alert,
    "cpu-alta": _cpu_alert,
}


def _players_alert(conn, server, service, anterior, cfg) -> None:
    alert_service.players_alert(_alert_deps(), conn, server, service, anterior, cfg)


_players_reading = alert_service.players_reading
_online_text = alert_service.online_text


# ------------------------------------------------- real-time log
#
# Counting by log was the only case with no way to become fast: each check is an
# SSH round trip that drags the whole log, so asking every 15 seconds would cost megabytes
# per minute to find two lines. The way out is to stop asking: a long SSH connection
# with `journalctl -f` leaves the panel LISTENING, and the line arrives the second it comes out.
#
# The point of the design: the stream is a TRIGGER, not a second count. It only says "something
# happened" and asks for the count to be redone the usual way. Reproducing the log's state
# machine here would be a second place to get it wrong, and worse, one that would silently diverge
# from the number the screen shows.

# One player alert per server at a time: the stream and the monitor round touch the
# SAME _monitor_state[sid], and without this the two could announce the same join.
_players_locks: dict[int, threading.Lock] = {}
_players_locks_lock = threading.Lock()


def players_lock(sid: int) -> threading.Lock:
    with _players_locks_lock:
        return _players_locks.setdefault(sid, threading.Lock())


def _log_stream_deps() -> log_stream.LogStreamDeps:
    return log_stream.LogStreamDeps(
        ssh_argv=ssh_argv, monitor_state=_monitor_state,
        invalidate_players=invalidate_players, connect=_connect,
        webhook_config=webhook_config, players_lock=players_lock,
        players_alert=_players_alert, logger=app.logger,
        debounce=LOG_STREAM_DEBOUNCE, retry=LOG_STREAM_RETRY,
    )


class _LogStream(log_stream.LogStream):
    """The log connection with the panel pieces already wired.

    A subclass (and not `functools.partial`) so it remains a two-argument
    CLASS: the supervisor swaps it for a test double in the tests, and there is a test that builds it
    directly to check that a malformed regex makes the thread give up.
    """

    def __init__(self, server, signature):
        super().__init__(_log_stream_deps(), server, signature)


def _player_line(line: str, entrar, sair) -> bool:
    return log_stream.player_line(line, entrar, sair)


def _stream_signature(server) -> tuple:
    return log_stream.stream_signature(server, _stored_value)


def wanted_streams(servers, cfg) -> dict[int, tuple]:
    return log_stream.wanted_streams(
        servers, cfg, LOG_STREAM, player_source, _stored_value)


# `_LogStream` goes through a lambda: the name is resolved in this module on each open, which is
# what lets the supervisor test swap it for a double without SSH.
_supervisor = log_stream.Supervisor(lambda server, signature: _LogStream(server, signature))
# The SAME dictionary as the supervisor's: the test fixture clears it by this name.
_streams = _supervisor.open_ones


def live_streams() -> int:
    return _supervisor.alive_ids()


def supervise_streams() -> int:
    """Start, stop and revive the log connections. Return how many are registered."""
    conn = db()
    servers = servers_repo.all_ordered(conn)
    return _supervisor.sync(servers, wanted_streams(servers, webhook_config(conn)))


class _Rhythm(NamedTuple):
    """What THIS monitor round is going to check.

    Not everything moves at the same pace, and the reason is cost: player counting asks
    the game directly (cheap), state/silence/restart cost one SSH per server, disk,
    memory and CPU come from an expensive gauge worth reading together, and the log costs an
    SSH round trip of its own. Separating this decision from the loop is what made the monitoring function fit
    in one's head: here it is "what is due now", there it is "what to do with each server".
    """

    see_state: bool
    wants_players: bool
    resources: set
    see_log: bool


def _monitor_rhythm(cfg: dict, now: float, force: bool) -> _Rhythm | None:
    """Decide what is due this round and advance the clocks. None = not time yet."""
    # The monitor's pace is that of the most hurried alert that is ON. With players
    # on, the round is short; without them nothing changes compared with before.
    wants_players = bool(cfg["events"] & {"jogador-entrou", "jogador-saiu"})
    step = min(MONITOR_EVERY, PLAYER_CHECK_EVERY) if wants_players else MONITOR_EVERY
    if not monitor_tick.due(now, step, force):
        return None
    monitor_tick.mark(now)

    # ...but only player counting moves at this short pace. Service state, silence
    # and restart stay at the old pace: each of them costs SSH per server, and
    # speeding everything up together would multiply that bill by four for no need.
    see_state = state_tick.due(now, MONITOR_EVERY, force)
    if see_state:
        state_tick.mark(now)

    # One clock for disk, memory and CPU only: the three read the same gauge, and giving each
    # its own pace would multiply the SSH round trips without seeing anything new.
    resource_wins = resource_tick.due(now, DISK_CHECK_EVERY, force)
    resources = cfg["events"] & RESOURCE_EVENTS if resource_wins else set()
    # Mark only when SOMETHING was read: with no resource alert on, letting the window run
    # would make the next round with one of them on wait the whole interval again.
    if resources:
        resource_tick.mark(now)

    # The log is the only one that costs an SSH round trip of its own, so it moves at its own pace.
    see_log = "erro-no-log" in cfg["events"] and log_tick.due(now, LOG_CHECK_EVERY, force)
    if see_log:
        log_tick.mark(now)

    return _Rhythm(see_state, wants_players, resources, see_log)


def _short_round(conn, server, anterior, cfg, rhythm: _Rhythm) -> None:
    """The 15s round: players only, and without touching SSH.

    The service that matters here is "was up at the last real look", and that is
    already stored. If it went down since then, the query to the game itself fails
    and `_players_alert` returns without announcing anything: the delay of a stale state does not
    invent an alert.

    Counting by log stays out: it costs SSH, and paying that every 15s just to reread
    the same whole log does not hold up. Those servers keep notifying at the pace
    of the full round.
    """
    if not rhythm.wants_players or anterior is None:
        return
    if player_source(server) not in PLAYER_FAST_SOURCES:
        return
    with players_lock(int(server["id"])):
        _players_alert(conn, server, anterior.get("service", ""), anterior, cfg)


def _server_alerts(conn, server, state, anterior, cfg, rhythm: _Rhythm) -> None:
    """The alerts that only make sense with the container REACHABLE."""
    if "reiniciando" in cfg["events"]:
        _restart_alert(conn, server, state, anterior)
    else:
        # With the event off the counter still needs to keep up, otherwise turning the alert on
        # in the middle of the day would yield a false "loop" with everything that piled up while
        # it was off.
        anterior["restarts"] = int(state.get("restarts") or 0)

    # This one costs a probe of the game (UDP or HTTP): not worth paying for it with
    # the event off.
    if cfg["events"] & {"travou", "respondeu"}:
        _mute_alert(conn, server, state, anterior)

    if rhythm.wants_players:
        # With the log stream on, this call becomes a safety net: if the stream has
        # dropped, nobody is left without notice, only slower. The lock is what keeps the two
        # from announcing the same join.
        with players_lock(int(server["id"])):
            _players_alert(conn, server, state["service"], anterior, cfg)

    if rhythm.see_log:
        _log_alert(conn, server, anterior)

    for event, check_it in RESOURCE_ALERTS.items():
        if event in rhythm.resources:
            check_it(conn, server, cfg)


def monitor_servers(force: bool = False) -> int:
    """Check everyone's state and fire whatever changed. Return how many were checked."""
    conn = db()
    cfg = webhook_config(conn)
    # With no enabled destination asking for any event, the whole round would be SSH spent
    # producing an alert that nobody would receive.
    if not cfg["events"]:
        return 0

    rhythm = _monitor_rhythm(cfg, time.monotonic(), force)
    if rhythm is None:
        return 0

    servers = servers_repo.all_ordered(conn)
    for server in servers:
        sid = int(server["id"])
        previous = _monitor_state.get(sid)

        if not rhythm.see_state:
            _short_round(conn, server, previous, cfg, rhythm)
            continue

        state = server_status(server)
        if previous is None:
            # First look: only record. Alerting here would fill the channel with "is stopped"
            # every time the panel restarted. The same goes for the restart counter:
            # what matters is how much it goes up FROM HERE on.
            _monitor_state[sid] = {"reachable": state["reachable"],
                                    "service": state["service"],
                                    "restarts": int(state.get("restarts") or 0)}
            continue

        _state_alert(conn, server, state, previous)
        if state["reachable"]:
            _server_alerts(conn, server, state, previous, cfg, rhythm)
        # After the alerts: they need to compare against the PREVIOUS state, and updating
        # before would make every change vanish halfway.
        previous.update(reachable=state["reachable"], service=state["service"])

    _forget_removed_servers(servers)
    return len(servers)


def _forget_removed_servers(servers) -> None:
    """A server removed from the panel must not keep state forever."""
    alive_ids = {int(s["id"]) for s in servers}
    for dead_one in [k for k in _monitor_state if k not in alive_ids]:
        _monitor_state.pop(dead_one, None)


# -------------------------------------------------------- usage samples

sample_tick = ticker.Ticker()


def collect_samples(force: bool = False) -> int:
    """Store one CPU/memory/players row per server. Return how many were written."""
    now_ts = time.monotonic()
    if not sample_tick.due(now_ts, SAMPLE_EVERY, force):
        return 0
    sample_tick.mark(now_ts)

    conn = db()
    stamp = now_iso()
    lines_of = []
    for server in servers_repo.all_ordered(conn):
        data = server_metrics(server)
        if data.get("error"):
            # A container that is down does not become a row: a gap in the chart is the right
            # information, and zero would be a lie (it was not "used 0% CPU").
            continue
        count = None
        if player_source(server):
            try:
                playing = server_players(server)
                count = None if playing.get("error") else playing.get("players")
            except (QueryError, RemoteError):
                count = None
        lines_of.append((
            int(server["id"]), stamp, data.get("cpu_pct"),
            (data.get("mem") or {}).get("pct"), count,
        ))

    if lines_of:
        with conn:
            samples_repo.insert_many(conn, lines_of)
    return len(lines_of)


# ------------------------------------------------------------- scheduling
#
# A single thread, waking every SCHEDULE_TICK, looks at what is due and fires it through the SAME
# start_job as the screens: a scheduled task shows up in the history like any other, with
# 'agendador' in place of the user.
#
# This depends on the panel running with ONE worker (which is how gunicorn is configured here,
# see provision-admin-lxc.sh): with two processes, each would have its own thread and the
# same task would fire twice.

# Clock math in gamepanel.services.schedule_service; the names stay here because
# the scheduling routes, the templates and the tests call them.
SCHEDULE_KINDS = schedule_service.SCHEDULE_KINDS
SCHEDULE_ACTIONS = schedule_service.SCHEDULE_ACTIONS
WEEKDAYS = schedule_service.WEEKDAYS
EVERY_HOURS_MAX = schedule_service.EVERY_HOURS_MAX
local_now = schedule_service.local_now
schedule_label = schedule_service.schedule_label
previous_occurrence = schedule_service.previous_occurrence
# Also used by the scheduling routes and by the chart, outside this section.
_parse_dt = schedule_service._parse_dt


def is_due(sched, now: datetime) -> bool:
    return schedule_service.is_due(sched, now, SCHEDULE_GRACE)


def fire_schedule(conn: sqlite3.Connection, sched) -> int:
    """Queue the task to run. Return the job id (0 when it could not be triggered)."""
    server = servers_repo.by_id(conn, sched["server_id"])
    if not server:
        return 0
    steps: list[JobStep]
    if sched["action"] == "backup":
        paths = backup_paths(server)
        if not paths:
            return 0  # nothing to store: no point waking the container
        steps, limit = backup_steps(server, paths), BACKUP_TIMEOUT
    else:
        steps, limit = [ACTIONS[sched["action"]][1](server)], JOB_TIMEOUT
    job_id = start_job(
        sched["action"], server, SCHEDULE_USER, steps=steps,
        command=f"agendado: {schedule_label(sched)}", timeout=limit,
    )
    invalidate_status(int(server["id"]))
    return job_id


def run_schedules() -> int:
    """One pass of the clock. Return how many tasks it fired."""
    now_ts = local_now()
    conn = db()
    fired = 0
    for sched in schedules_repo.enabled(conn):
        if sched["action"] not in SCHEDULE_ACTIONS or not is_due(sched, now_ts):
            continue
        # Mark BEFORE firing: if the job takes long (an update takes almost an hour), the
        # next clock round must not think the task is still due.
        with conn:
            schedules_repo.mark_run(conn, sched["id"], now_ts.isoformat())
        if fire_schedule(conn, sched):
            fired += 1
    return fired


cleanup_tick = ticker.Ticker()


def clean_history(force: bool = False) -> int:
    """Delete what has aged: jobs and samples. Return how many JOBS went away.

    The two cleanups go together because they have the same reason to exist (the panel database
    cannot grow forever) and the same hourly clock; only the deadlines change,
    because a sample is tiny next to a job's output.
    """
    now_ts = time.monotonic()
    if not cleanup_tick.due(now_ts, JOBS_PURGE_EVERY, force):
        return 0
    cleanup_tick.mark(now_ts)
    conn = db()

    if SAMPLES_KEEP_DAYS:
        old_ones = (datetime.now(UTC)
                  - timedelta(days=SAMPLES_KEEP_DAYS)).isoformat()
        with conn:
            samples_repo.delete_older_than(conn, old_ones)

    # The alert log is measured in lines, not days: what one wants from it is "the last N", and a
    # deadline in days would leave the screen empty precisely on a quiet panel, which is when the doubt
    # "is this still working?" shows up.
    with conn:
        alerts_repo.trim_log(conn, ALERT_LOG_KEEP)

    if not JOBS_KEEP_DAYS:
        return 0
    cut = (datetime.now(UTC) - timedelta(days=JOBS_KEEP_DAYS)).isoformat()
    with conn:
        return jobs_repo.delete_older_than(conn, cut)


def _clock_failure(name: str) -> None:
    """Note it in the process log AND in the alert log.

    The alert log is what the person can see: the traceback in gunicorn's stderr only shows up
    for whoever knows where to look, and the complaint that brings someone here is always the same:
    "nothing arrives on Discord".
    """
    app.logger.exception("falha na tarefa '%s' do relogio", name)
    try:  # noqa: SIM105 - see the except
        _record_alert(db(), "", f"a tarefa '{name}' do relogio falhou",
                         traceback.format_exc(limit=4)[-500:], "", "erro-interno")
    # Recording the failure must not become another failure: this block is ALREADY handling an error,
    # and logging from inside it would be circular. A silent `pass` is deliberate: the
    # `logger.exception` on the line above already recorded what matters.
    except Exception:  # noqa: BLE001, S110
        pass


def _scheduler_tick() -> None:
    """One round of the clock. Needs an application context because of db().

    The list is built on every round, not stored: each name is resolved in this module
    at that moment, which is what lets the test swap a task for one that blows up.
    """
    scheduler.tick(
        (("agendamentos", run_schedules),
         ("monitor", monitor_servers),
         ("log-em-tempo-real", supervise_streams),
         ("amostras", collect_samples),
         ("limpeza", clean_history)),
        _clock_failure,
    )


def _with_context() -> None:
    # Application context: it is what makes this thread's db() work like the routes' one
    # (its own connection, closed at the end by the teardown).
    with app.app_context():
        _scheduler_tick()


_clock = scheduler.Clock(SCHEDULE_TICK, _with_context, app.logger)


def start_scheduler() -> None:
    _clock.start()


# ------------------------------------------------------------------- routes


def safe_target(raw: str) -> str:
    r"""Where to go back to after login. Empty when the destination is not on the panel.

    Starting with "/" is not enough: for the browser "//evil.com" and "/\evil.com" are ABSOLUTE
    addresses, and would send whoever just typed the password out of the panel.
    """
    target = (raw or "").strip()
    if not target.startswith("/") or target[:2] in ("//", "/\\"):
        return ""
    if any(c in target for c in "\r\n\t"):
        return ""
    return target


# Time to type the code after getting the password right.
PRE_2FA_SECONDS = 300


def _open_session(row: sqlite3.Row, next_one: str = ""):
    session.clear()
    session["uid"] = row["id"]
    session["username"] = row["username"]
    session.permanent = True
    csrf_token()
    return redirect(next_one or url_for("dashboard.index"))


def _check_second_factor(row: sqlite3.Row, typed: str) -> bool:
    """App code OR a recovery code (which gets used up). Valid only once."""
    conn = db()
    step = totp.verify(row["totp_secret"], typed, time.time(), row["totp_last_step"])
    if step is not None:
        with conn:
            # The `WHERE` makes the UPDATE the gate: two requests with the same code at the same time
            # do not both pass (the second does not find the row with a smaller step).
            return users_repo.spend_step(conn, row["id"], step)
    try:
        stored = json.loads(row["totp_recovery"] or "[]")
    except ValueError:
        stored = []
    leftover = totp.consume(typed, stored)
    if leftover is None:
        return False
    with conn:
        return users_repo.spend_recovery(
            conn, row["id"], json.dumps(leftover), row["totp_recovery"])


def _port_tab(server: ServerRow) -> dict:
    """Tab 1: fire A2S at each UDP port the container is listening on."""
    candidates, _tcp, owners, warning_text = candidate_ports(server)
    ports = _with_owner(probe_ports(server["host"], candidates[:12]), owners, "udp")
    # A port opened by the game process that did not answer A2S is a conclusion, not an
    # error: the game simply does not publish a query. Without this count the screen would only say
    # "no answer" and leave the doubt between "wrong port" and "no query exists".
    from_game = [p for p in ports if p["origem"] == "detectada" and not p["infra"]]
    # The active conversations on the game port apply to every CT with the current firewall, even
    # when no port answers A2S - that is the case of Dragonwilds (EOS, no query).
    try:
        presence: dict[str, Any] = {"players": presence_players(server)["players"], "error": ""}
    except QueryError as exc:
        presence = {"players": None, "error": str(exc)}
    return {
        "presenca": presence,
        "portas": ports,
        "aviso": warning_text,
        "udp_do_jogo": len(from_game),
        "udp_mudas": bool(from_game) and not any(p["ok"] for p in from_game),
    }


def _http_tab(server: ServerRow, http: dict, should_test: bool) -> dict:
    """Tab 2: which TCP ports speak HTTP, and the test of the chosen URL."""
    _udp, candidates, owners, warning_text = candidate_ports(server)
    found, silent_ones, probe_failure = probe_http_ports(server, candidates)
    _with_owner(found, owners, "tcp")
    # A NEW NAME, not the same one reused: the value changes meaning (from a list of
    # port numbers to a list of dicts with an owner), and reusing the name hid that from
    # the reader; it was the type checker that pointed it out, rejecting the re-annotation.
    silent_with_owner: list[dict] = _with_owner(
        [{"port": p} for p in silent_ones], owners, "tcp")
    output = {"achados": found, "mudas": silent_with_owner, "aviso": warning_text or probe_failure,
             # A finding worth a click: a port that answered on a known route. With
             # none, the screen explains that the API usually comes disabled out of the box.
             "tem_api": any(not a.get("generico") for a in found),
             "teste_http": None, "erro_http": ""}
    if not should_test:
        return output
    try:
        # The test uses the FORM values, not the database ones: it is the only way to
        # check the login before saving. That is why a temporary row is built.
        temporary_path = dict(server)
        temporary_path.update(http)
        if (http.get("http_login_url") or "").strip() and (http.get("http_token_path") or "").strip():
            token = http_login(temporary_path)
            auth = f"bearer:{token}"
        else:
            auth = http["http_auth"]
        data = http_json(server, http["http_url"], auth, http["http_body"])
        test_value = read_players_json(data, http["http_list_path"], http["http_count_path"])
        # The raw response helps fill in the paths when the automatic search gets it wrong.
        test_value["amostra"] = json.dumps(data, indent=2, ensure_ascii=False)[:4000]
        output["teste_http"] = test_value
    except QueryError as exc:
        output["erro_http"] = str(exc)
    return output


def _log_tab(server: ServerRow, join_re: str, leave_re: str, log_path: str,
             should_test: bool) -> dict:
    """Tab 3: log lines that look like join/leave and the test of the patterns."""
    output: dict[str, Any] = {"amostras": [], "teste": None, "erro_log": ""}
    try:
        # The path comes from the FORM, not the database: it is the only way to check a
        # new file (DayZ's .ADM, for example) before saving.
        temporary_path = dict(server)
        temporary_path["log_path"] = log_path
        lines_of = read_log_lines(temporary_path)
        keys = re.compile("|".join(LOG_HINT_WORDS), re.I)
        samples = [ln for ln in lines_of if keys.search(ln)][-120:]
        output["amostras"] = samples
        if not should_test:
            return output
        join_pattern = compile_pattern(join_re, "pattern.join")
        if not join_pattern:
            raise QueryError("informe o padrao da linha de entrada")
        leave_pattern = compile_pattern(leave_re, "pattern.leave")
        test_value = _apply_log_events(lines_of, join_pattern, leave_pattern)
        test_value["casaram"] = [
            ln for ln in samples
            if join_pattern.search(ln[:LOG_LINE_MAX]) or (leave_pattern and leave_pattern.search(ln[:LOG_LINE_MAX]))
        ][-20:]
        output["teste"] = test_value
    except (RemoteError, QueryError) as exc:
        output["erro_log"] = str(exc)
    return output


def _enable_a2s_count(conn, sid: int):
    """Direct UDP query (A2S). Return a redirect when the form is wrong."""
    port = request.form.get("query_port", "0")
    if not port.isdigit() or not 1 <= int(port) <= MAX_PORT:
        flash(translate("flash.bad_port"), "error")
        return redirect(url_for("players.setup", sid=sid))
    with conn:
        servers_repo.use_query_port(conn, sid, int(port))
    flash(translate("flash.count_on_by_query", port=port), "ok")
    return None


def _enable_net_count(conn, sid: int):
    """Active conversations on the game port, through the CT firewall. No field: only the choice."""
    with conn:
        servers_repo.use_presence(conn, sid)
    flash(translate("flash.count_on_by_net"), "ok")


def _enable_http_count(conn, sid: int):
    """The game's own HTTP API."""
    errors: list[str] = []
    fields = _http_fields(request.form, errors)
    if errors or not fields["http_url"]:
        flash(translate(errors[0]) if errors else translate("flash.need_api_url"), "error")
        return redirect(url_for("players.setup", sid=sid, tab="http"))
    with conn:
        servers_repo.use_http(conn, sid, fields)
    if fields["http_login_url"]:
        flash(translate("flash.count_on_by_api_login"), "ok")
    else:
        flash(translate("flash.count_on_by_api"), "ok")
    return None


def _enable_log_count(conn, sid: int):
    """Last resort: the join and leave lines in the server log."""
    errors: list[str] = []
    entry = _pattern(request.form.get("join_re"), "entrada", errors)
    output = _pattern(request.form.get("leave_re"), "saida", errors)
    path = _log_path(request.form.get("log_path"), errors)
    if errors or not entry:
        flash(translate(errors[0]) if errors else translate("flash.need_join_pattern"), "error")
        return redirect(url_for("players.setup", sid=sid, tab="log"))
    with conn:
        servers_repo.use_log(conn, sid, entry, output, path)
    flash(translate("flash.count_on_by_log"), "ok")
    return None


# Counting source -> who stores the choice. A new source (RCON, for example) is one
# function and one line here; the route below does not change.
COUNT_SOURCES = {
    "a2s": _enable_a2s_count,
    "http": _enable_http_count,
    "net": _enable_net_count,
    "log": _enable_log_count,
}


# Form validation in gamepanel.services.server_service. The limits stay here
# (they are panel configuration) and travel in a bundle; `clean_path` goes along because it already
# carries the allowed roots (GAMEPANEL_FILE_ROOTS).
UNIT_RE = server_service.UNIT_RE
HOST_RE = server_service.HOST_RE
USER_RE = server_service.USER_RE
JSON_PATH_RE = server_service.JSON_PATH_RE


def _form_limits() -> server_service.FormLimits:
    return server_service.FormLimits(
        config_files_max=CONFIG_FILES_MAX, backup_paths_max=BACKUP_PATHS_MAX,
        http_url_max=HTTP_URL_MAX, http_body_max=HTTP_BODY_MAX,
        http_path_max=HTTP_PATH_MAX, re_max_len=RE_MAX_LEN,
        player_sources=PLAYER_SOURCES,
    )


def _form_server(form) -> tuple[dict, list[str]]:
    return server_service.form_server(form, clean_path, _form_limits())


# The three are also used by the counting wizard (HTTP and log tabs), outside the
# registration form.
_log_path = server_service._log_path


def _pattern(value: str | None, label: str, errors: list[str]) -> str:
    return server_service._pattern(value, label, RE_MAX_LEN, errors)


def _http_fields(form, errors: list[str]) -> dict:
    return server_service._http_fields(form, _form_limits(), errors)


# Columns the form fills, in the same order as the INSERT/UPDATE below. Keeping the
# list in a single place avoids the classic "I added the column and forgot one of the SQLs".
# The column names live in the repository; here there is only the alias the blueprints
# already used (swapping through `panel.X` is what makes the tests' `monkeypatch` work).
SERVER_FIELDS = servers_repo.EDITABLE_FIELDS


# The cursor is an opaque journald key ("s=...;i=...;b=..."): validated here because it
# comes back from the browser and goes into a remote command.
CURSOR_RE = re.compile(r"^[A-Za-z0-9=;:._-]{1,400}$")
LOG_FOLLOW_MAX = 500


def _log_lines_arg(raw: str | None, default: int = 80) -> int:
    try:
        return max(10, min(500, int(raw or "")))
    except (TypeError, ValueError):
        return default


def read_logs(server: ServerRow, lines: int, cursor: str = "") -> tuple[str, str]:
    """Read the service log. With a cursor, bring only what came in after it.

    Return (text, new_cursor). The cursor comes empty when the container's journalctl
    cannot emit it; in that case the screen reloads the whole block on every round.
    """
    if cursor and CURSOR_RE.match(cursor):
        cmd = remote_cmd.unprivileged(
            "journalctl", "-u", server["service"], "--no-pager", "--show-cursor",
            "--after-cursor", cursor, "-n", str(LOG_FOLLOW_MAX),
        )
    else:
        # journalctl reads through the systemd-journal group: the same command in both modes.
        cmd = remote_cmd.unprivileged(
            "journalctl", "-u", server["service"], "--no-pager", "--show-cursor",
            "-n", str(lines),
        )
    raw = ssh_output(server, cmd, timeout=30)

    out = raw.splitlines()
    new_cursor = ""
    if out and out[-1].startswith("-- cursor:"):
        new_cursor = out.pop().split(":", 1)[1].strip()
    body = "\n".join(ln for ln in out if ln.strip() != "-- No entries --")
    return body, new_cursor


# ------------------------------------------------------------------ console


# ------------------------------------------------------- interactive terminal

TERM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

TermSession = term_runtime.TermSession


def _open_term(server: dict, uid: int, username: str, cols: int, rows: int) -> TermSession:
    return term_runtime.TermSession(
        ssh_argv, server, uid, username, cols, rows,
        known_hosts=KNOWN_HOSTS, buffer_bytes=TERM_BUFFER_BYTES,
    )


_terms: dict[str, TermSession] = {}
_terms_lock = threading.Lock()
_reaper_started = False


def _reap_terms() -> None:
    """Kill idle sessions: each one holds an ssh process and a PTY."""
    while True:
        time.sleep(30)
        now = time.time()
        # Copy under the lock: the loop removes sessions from the dictionary, and a tab opening
        # another session at the same time would change the dictionary mid-iteration.
        with _terms_lock:
            open_ones = tuple(_terms.values())
        for term in open_ones:
            idle = now - term.last_seen
            # A finished session stays up for a while so the browser can read the final output.
            if idle > TERM_IDLE_TIMEOUT or (not term.alive and idle > 60):
                term.close()
                with _terms_lock:
                    _terms.pop(term.id, None)


def _ensure_reaper() -> None:
    """Start the idle session reaper the first time someone opens a terminal.

    The "only once" lock lives here, not in the blueprint, because `_reaper_started` and
    `_terms_lock` are the same state: a `global` on the other side of the package would read the copy
    in the blueprint module and start a new thread for every tab opened. The caller already
    holds `_terms_lock`.
    """
    global _reaper_started
    if not _reaper_started:
        threading.Thread(target=_reap_terms, daemon=True).start()
        _reaper_started = True


def _term_of_user(tid: str) -> TermSession:
    if not TERM_ID_RE.match(tid or ""):
        abort(404)
    with _terms_lock:
        term = _terms.get(tid)
    # Another user's session is treated as nonexistent.
    if not term or term.uid != session.get("uid"):
        abort(404, i18n.Message("error.terminal_session_gone"))
    term.last_seen = time.time()
    return term


def _terminal_guard():
    if not ALLOW_SHELL:
        abort(403, i18n.Message("error.terminal_disabled"))
    if not HAVE_PTY:
        abort(503, i18n.Message("error.terminal_no_pty"))


# ------------------------------------------------- configuration editor


def clean_path(raw: str) -> str:
    return files_rt.clean_path(raw, FILE_ROOTS)


def parent_of(path: str) -> str:
    return files_rt.parent_of(path)


# When the gauge bar changes color. The SAME numbers are in `barLevel` in
# `static/js/core/format.js`: the screen draws the bar on the server and the JS updates it live,
# so diverging here would make the color change on reload and not on the moving gauge,
# with no error anywhere. There is no build step to share the constant, which is why
# there is a test comparing the two files (`test_frontend_contract.py`).
GAUGE_HOT = 92
GAUGE_WARN = 80


@app.template_filter("level")
def _bar_level(pct: float | None) -> str:
    """Bar class: near the ceiling it changes color (same rule as format.js)."""
    if pct is None:
        return ""
    if pct >= GAUGE_HOT:
        return " hot"
    if pct >= GAUGE_WARN:
        return " warn"
    return ""


@app.template_filter("duration")
def _human_uptime(seconds: float | None) -> str:
    total = int(seconds or 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}min"
    if minutes:
        return f"{minutes}min"
    # A player who just joined: "0min" says nothing.
    return f"{total}s"


@app.template_filter("filesize")
def _human_size(num: int | None) -> str:
    """1536 -> '1.5 KB'. A game save in raw bytes says nothing to anyone."""
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _files_guard():
    if not ALLOW_FILES:
        abort(403, i18n.Message("error.files_disabled"))


def _server_or_404(sid: int) -> sqlite3.Row:
    server = servers_repo.by_id(db(), sid)
    if not server:
        abort(404)
    return server


def list_dir(server: ServerRow, path: str) -> tuple[list[dict], bool]:
    return files_rt.list_dir(ssh_run, server, path, FILE_LIST_MAX)


def stat_file(server: ServerRow, path: str) -> dict:
    return files_rt.stat_file(ssh_run, server, path)


def read_file(server: ServerRow, path: str) -> dict:
    return files_rt.read_file(ssh_run, server, path, FILE_MAX_BYTES, FILE_PREVIEW_BYTES)


RESTORE_SCRIPT = backups_rt.RESTORE_SCRIPT

# $1 = final destination. The content comes RAW through standard input (no base64: the file may
# be gigabytes, and encoding would inflate it 33% for nothing).
UPLOAD_SCRIPT = files_rt.UPLOAD_SCRIPT


def ssh_stream_in(server, remote_cmd: str, source, timeout: int) -> str:
    return files_rt.ssh_stream_in(ssh_argv, server, remote_cmd, source, timeout, UPLOAD_CHUNK)


def find_config_files(server: ServerRow, root: str) -> list[dict]:
    return files_rt.find_config_files(ssh_run, server, root, CONFIG_GLOBS)


def write_file(server: ServerRow, path: str, data: bytes) -> str:
    return files_rt.write_file(ssh_run, server, path, data)


def delete_file(server: ServerRow, path: str) -> str:
    return files_rt.delete_file(ssh_run, server, path)


def _attachment_header(name: str) -> str:
    """Content-Disposition that copes with accents and quotes in the file name."""
    ascii_name = re.sub(r'[^A-Za-z0-9._-]', "_", name) or "arquivo"
    quoted = urllib.parse.quote(name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def stream_remote_file(server: ServerRow, path: str):
    return files_rt.stream_remote_file(ssh_argv, server, path, DOWNLOAD_CHUNK)


# ------------------------------------------------------------------ upload


# ------------------------------------------------------------------ backup
#
# The backup is born INSIDE the game container (a tar.gz of the save folders) and is pulled
# to the panel in the same job. The panel triggers, lists, downloads and restores, and the restore
# stops the server, extracts and starts it again, because a game with the world swapped underneath it writes
# over what was just brought back.


def backup_paths(server: ServerRow) -> list[str]:
    return backups_rt.backup_paths(server, BACKUP_PATHS_MAX)


def backup_prefix(server: ServerRow) -> str:
    return backups_rt.backup_prefix(server)


def _backup_or_400(name: str) -> str:
    """Check the name that came back from the screen before it goes into a remote command."""
    try:
        return backups_rt.validate_backup_name(name)
    except ValueError as exc:
        abort(400, str(exc))


def list_backups(server: ServerRow) -> list[dict]:
    return backups_rt.list_backups(ssh_run, server, BACKUP_DIR, BACKUP_LIST_MAX)


def backup_command(server: ServerRow | dict, paths: list[str], suffix: str = "") -> str:
    # The restore's safety copy (the only one with a suffix) does NOT apply retention: with the
    # copies at the limit, it would delete the oldest one, which may be exactly the one the person
    # chose to restore. The next regular backup cleans up the excess.
    keep = 0 if suffix else BACKUP_KEEP
    return backups_rt.backup_command(server, BACKUP_DIR, keep, paths, suffix)


def restore_command(server: ServerRow | dict, paths: list[str], name: str) -> str:
    return backups_rt.restore_command(server, BACKUP_DIR, name, paths)


def delete_backup(server: ServerRow, name: str) -> str:
    return backups_rt.delete_backup(ssh_run, server, BACKUP_DIR, name)


def list_panel_backups(server: ServerRow | dict) -> list[dict]:
    return backup_archive.list_copies(PANEL_BACKUP_DIR, backup_prefix(server))


def panel_backup_path(server: ServerRow | dict, name: str) -> str:
    return backup_archive.path_of(PANEL_BACKUP_DIR, backup_prefix(server), name)


def delete_panel_backup(server: ServerRow | dict, name: str) -> int:
    return backup_archive.delete(PANEL_BACKUP_DIR, backup_prefix(server), name)


def _pull_to_panel(target: dict, remote_path: str, size: int | None) -> str:
    """Bring a backup from the container to the panel's disk. Text goes to the job output."""
    name = backups_rt.validate_backup_name(remote_path.rsplit("/", 1)[-1])
    try:
        written, removed = backup_archive.store(
            PANEL_BACKUP_DIR, backup_prefix(target), name,
            stream_remote_file(target, remote_path), size, PANEL_BACKUP_KEEP)
    except OSError as exc:
        # The container backup is still there; what failed was only the second copy. It is an error
        # anyway: whoever counts on the panel to survive the CT removal needs to
        # know now, not on the day the container no longer exists.
        raise RemoteError(f"a copia no container saiu, mas a do painel falhou: {exc}") from exc
    lines = [f"copia guardada no painel: {name} ({written} bytes)"]
    lines += [f"retencao no painel: apagado {old}" for old in removed]
    return "\n".join(lines) + "\n"


def pull_new_backup_step(target: dict, output: str) -> str:
    """Job step: pull to the panel the backup the previous step just created."""
    try:
        found = backup_archive.created_file(output, BACKUP_DIR)
    except ValueError as exc:
        raise RemoteError(str(exc)) from exc
    if not found:
        raise RemoteError("o backup nao disse qual arquivo criou; nada foi copiado para o painel")
    return _pull_to_panel(target, *found)


def pull_existing_backup_step(name: str) -> JobStep:
    """Job step: pull to the panel a backup that was already in the container."""
    def step(target: dict, _output: str) -> str:
        path = f"{BACKUP_DIR.rstrip('/')}/{name}"
        return _pull_to_panel(target, path, int(stat_file(target, path)["size"]))
    return step


def push_panel_backup_step(name: str) -> JobStep:
    """Job step: return to the container a copy stored on the panel."""
    def step(target: dict, _output: str) -> str:
        try:
            path = panel_backup_path(target, name)
        except FileNotFoundError as exc:
            raise RemoteError(f"a copia {name} nao esta mais no painel") from exc
        with open(path, "rb") as source:
            remote = backups_rt.receive_command(target, BACKUP_DIR, name)
            return ssh_stream_in(target, remote, source, BACKUP_TIMEOUT) + "\n"
    return step


def backup_steps(server: ServerRow | dict, paths: list[str], suffix: str = "") -> list[JobStep]:
    """Full backup: create it in the container and store the second copy on the panel."""
    return [backup_command(server, paths, suffix), pull_new_backup_step]


# ------------------------------------------------- quick config editing
#
# Same read/write engine as the "Files" screen, except the file reaches the screen
# as a form: one field per key. Whoever knows what they want to change (server name,
# admin password, number of players) does not need to find the file or count commas.


def config_paths(server: ServerRow) -> list[str]:
    """Configuration files registered in the server's record."""
    return [line.strip() for line in (server["config_files"] or "").splitlines() if line.strip()]


def load_config_doc(server: ServerRow, path: str) -> tuple[gameconf.ConfigFile, dict]:
    """Read the file in the container and interpret it field by field."""
    info = read_file(server, path)
    if info["binary"]:
        raise gameconf.ConfigError(
            "este arquivo e binario — a edicao campo a campo nao se aplica a ele"
        )
    if info["truncated"]:
        raise gameconf.ConfigError(
            f"o arquivo tem {info['size'] // 1024} KB e passa do limite de edicao"
            f" ({FILE_MAX_BYTES // 1024} KB) — arquivo de configuracao nao costuma"
            " chegar a esse tamanho, confira se e o arquivo certo"
        )
    # The parser works with \n only; if the file used CRLF it goes back that way on write.
    doc = gameconf.load(info["name"], info["text"].replace("\r\n", "\n"))
    if len(doc.settings) > CONFIG_SETTINGS_MAX:
        raise gameconf.ConfigError(
            f"o arquivo tem {len(doc.settings)} chaves (o formulario para em"
            f" {CONFIG_SETTINGS_MAX}) — pelo jeito nao e um arquivo de configuracao"
        )
    return doc, info


def _save_config_files(sid: int, paths: list[str]) -> None:
    conn = db()
    with conn:
        servers_repo.set_config_files(conn, sid, paths)


def _target_config(arquivos: list[str], errors: list[str]) -> str:
    """Which file the Config screen opens: the one requested in the URL, or the first registered."""
    request_body = (request.args.get("file") or "").strip()
    if not request_body:
        return arquivos[0] if arquivos else ""
    try:
        target = clean_path(request_body)
    except ValueError as exc:
        errors.append(str(exc))
        return arquivos[0] if arquivos else ""
    # The path comes from the URL: without this guard the Config screen would be a reader of any
    # file in the container (as root), exactly what the operator is not allowed to
    # open. For them only the files an admin already registered on the server count.
    if target not in arquivos and not is_admin():
        abort(403, i18n.Message("error.operator_reads_registered_only"))
    return target


def _suggestion_config(server: ServerRow, arquivos: list[str], alvo: str,
                      errors: list[str]) -> list | None:
    """Configuration file candidates in the container; None = not even worth searching.

    With no file registered the screen already arrives with the list ready: it is the way of
    "telling which file it is" without browsing through folders. Searching lists folders
    of the container, so only an admin does it.
    """
    if not is_admin():
        return None
    if request.args.get("discover") != "1" and (arquivos or alvo):
        return None
    # `folder` allows searching somewhere other than the registered config folder. It is
    # what the Files screen offered with a button of its own; now it is a parameter
    # of this search, which is the only one that exists.
    fallback = server["config_path"] or FILE_DEFAULT_PATH
    try:
        root = clean_path(request.args.get("folder", "") or fallback)
    except ValueError as exc:
        errors.append(str(exc))
        root = fallback
    try:
        return find_config_files(server, root)
    except RemoteError as exc:
        errors.append(str(exc))
        return []


@app.template_filter("ident")
def _ident(value: str) -> str:
    """Section/key identifier inside the form.

    gameconf ids use \\x1f to separate levels; percent-encoded they go through
    the HTML without becoming a loose control character in the middle of an attribute.
    """
    return urllib.parse.quote(value or "", safe="")


def enrich_settings(doc: gameconf.ConfigFile, file_name: str) -> None:
    """Attach the catalog description to each field read from the file.

    A field with no catalog entry stays exactly as before (free text): the goal
    is to improve what can be improved, never to hide a key the game started using.
    """
    for section in doc.sections:
        for s in section.settings:
            spec = game_fields.describe(file_name, s.key)
            s.spec = spec
            s.display_value = spec.to_display(s.value) if spec else s.value


def _edits_from_form(form, file_name: str = "") -> tuple[list[gameconf.Edit], list[str]]:
    """Build the list of changes: only what the user actually touched.

    Also return the validation errors. The value arrives in the SCREEN unit (minutes,
    multiplier) and is converted to the FILE unit (nanoseconds) here - that is
    why the check happens before the conversion, so the message speaks the language of
    whoever typed it.
    """
    total = form.get("n", "0")
    total = int(total) if total.isdigit() else 0
    edits: list[gameconf.Edit] = []
    failures: list[str] = []
    for i in range(min(total, 4000)):
        edit = _edit_from_row(form, i, file_name, failures)
        if edit is not None:
            edits.append(edit)
    return edits, failures


def _edit_from_row(form, i: int, file_name: str, errors: list[str]) -> gameconf.Edit | None:
    """One form row becomes a change, or nothing.

    Nothing happens in three cases: an "add configuration" row left blank,
    a field nobody touched (compared with the hidden `orig.N`) and a value the catalog
    rejected. The three are together here because they are the same question: "does this row have anything
    to write?".
    """
    key = (form.get(f"key.{i}", "") or "").strip()
    if not key:
        return None

    value = (form.get(f"val.{i}", "") or "").replace("\r", "")
    ident = urllib.parse.unquote((form.get(f"id.{i}", "") or "").strip())
    if ident and value == (form.get(f"orig.{i}", "") or "").replace("\r", ""):
        return None  # untouched field: does not rewrite the line

    spec = game_fields.describe(file_name, key) if file_name else None
    if spec:
        problem = spec.validate(value)
        if problem:
            errors.append(f"{spec.label or key}: {problem}")
            return None
        value = spec.from_display(value)

    return gameconf.Edit(
        id=ident,
        section=urllib.parse.unquote(form.get(f"sec.{i}", "") or ""),
        key=key,
        value=value,
    )


# --------------------------------------------------------------------- jobs


# ------------------------------------------------------------------- broker
#
# Create a game instance and open a port on the firewall. The broker is what holds the Proxmox and
# OPNsense credentials (gamebroker/); here the panel only ASKS, follows and registers the result.

# New-game form in gamepanel.services.broker_service; following the
# operation in gamepanel.tasks.broker_jobs.
BROKER_RECIPES = broker_service.BROKER_RECIPES


def broker_required(view):
    """Route that only exists when the deploy turned the broker on. Stacks AFTER
    `admin_required`: the operator gets the administrator 403, and only the admin finds out the
    feature is off.

    It also requires the PERSON's second factor, always, regardless of `GAMEPANEL_REQUIRE_2FA`
    (which is about the whole panel). The broker creates and deletes containers on Proxmox and opens ports
    on OPNsense; if an admin's session is stolen (XSS, malicious proxy, unlocked
    phone), 2FA is the only thing that still separates "seeing the screen" from "destroying
    infrastructure". Without it the request never even reaches `broker_client`."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not ALLOW_BROKER:
            abort(403, i18n.Message("error.broker_disabled"))
        user = logged_user()
        if not user or not user["totp_enabled"]:
            if request.path.startswith("/api/"):
                return jsonify({"error": "ative a verificacao em duas etapas em Conta para "
                                         "usar o broker"}), 403
            flash(translate("flash.broker_needs_two_factor"), "error")
            return redirect(url_for("account.two_factor"))
        return view(*args, **kwargs)

    return wrapper


def _fire(task) -> None:
    """Run `task` in a thread. Exists so the tests can swap it for a direct execution."""
    threading.Thread(target=task, daemon=True).start()


def _update_job(job_id: int, **fields) -> None:
    # Its own connection: the caller lives in a thread outside the request context. The
    # column NAMES come from the callers (fixed); only the values travel as parameters.
    conn = _connect()
    try:
        with conn:
            jobs_repo.set_fields(conn, job_id, fields)
    finally:
        conn.close()


def _finish_job(job_id: int, status: str, output: str, exit_code: int | None = None,
               server_id: int | None = None) -> None:
    fields: dict = {"status": status, "exit_code": exit_code, "output": output.strip()[-200000:],
                    "finished_at": now_iso()}
    if server_id is not None:
        fields["server_id"] = server_id
    _update_job(job_id, **fields)


def _broker_job_deps() -> broker_jobs.BrokerJobDeps:
    """Built at call time: `BROKER_POLL` and `BROKER_FAILURES_MAX` are swapped by the tests
    before following the operation, and a bundle frozen at import would not see the swap."""
    return broker_jobs.BrokerJobDeps(
        update_job=_update_job, close_job=_finish_job, ensure_server=ensure_server,
        deploy_server=DeployServer, connect=_connect, forget_host_key=forget_host_key,
        poll=BROKER_POLL,
        max_failures=BROKER_FAILURES_MAX, timeout=JOB_TIMEOUT,
    )


def _register_broker_server(r: dict) -> int:
    return broker_jobs.register_server(_broker_job_deps(), r)


def follow_operation(job_id: int, op_id: str, sleep=time.sleep) -> None:
    broker_jobs.follow_operation(_broker_job_deps(), job_id, op_id, sleep)


def start_broker_job(action: str, username: str, op_id: str, command: str) -> int:
    conn = db()
    with conn:
        job_id = jobs_repo.start_broker(conn, action, command, username, now_iso(), op_id)
    _fire(lambda: follow_operation(job_id, op_id))
    return job_id


def resume_broker_jobs() -> int:
    """After a panel restart, resume following the operations that were still
    running on the broker. Without this the job would stay 'running' forever, and the newly
    created server would never be registered."""
    if not ALLOW_BROKER:
        return 0
    conn = _connect()
    try:
        pending_ones = jobs_repo.running_broker_ops(conn)
    finally:
        conn.close()
    for job in pending_ones:
        _fire(lambda jid=job["id"], op=job["broker_op"]: follow_operation(jid, op))
    return len(pending_ones)


def _log_broker_action(action: str, username: str, command: str, output: str,
                             status: str = "ok") -> int:
    """Leave a short broker action in the history (deactivate, remove, new game)."""
    conn = db()
    with conn:
        return jobs_repo.record_broker(
            conn, action, status, output, command, username, now_iso())


def _actor() -> str:
    return session.get("username", "")


_game_from_form = broker_service.game_from_form


# ------------------------------------------------------------- schedules


def _bounded_int(value, minimum: int, maximum: int, default: int) -> int:
    raw = (value or "").strip()
    if raw.lstrip("-").isdigit() and minimum <= int(raw) <= maximum:
        return int(raw)
    return default


def _schedule_form(form, errors: list[str]) -> dict:
    action = (form.get("action", "") or "").strip()
    if action not in SCHEDULE_ACTIONS:
        errors.append(i18n.Message("flash.schedule_pick_action"))
        action = "restart"
    kind = (form.get("kind", "") or "").strip()
    if kind not in SCHEDULE_KINDS:
        errors.append(i18n.Message("flash.schedule_pick_kind"))
        kind = "diario"

    hour = _bounded_int(form.get("hour"), 0, 23, -1)
    minute = _bounded_int(form.get("minute"), 0, 59, -1)
    if kind != "intervalo" and (hour < 0 or minute < 0):
        errors.append(i18n.Message("flash.schedule_bad_time"))
    hours = _bounded_int(form.get("every_hours"), 1, EVERY_HOURS_MAX, -1)
    if kind == "intervalo" and hours < 0:
        errors.append(i18n.Message("flash.schedule_bad_interval", max=EVERY_HOURS_MAX))

    return {
        "action": action,
        "kind": kind,
        "hour": max(0, hour),
        "minute": max(0, minute),
        "weekday": _bounded_int(form.get("weekday"), 0, 6, 0),
        "every_hours": max(1, hours),
    }


def _schedule_or_404(aid: int) -> sqlite3.Row:
    sched = schedules_repo.by_id(db(), aid)
    if not sched:
        abort(404)
    return sched


def _next_occurrence(sched, now: datetime) -> datetime:
    """When this task runs next.

    'intervalo' counts from the last run; daily and weekly add one step to the
    previous occurrence. `previous_occurrence` only returns None for 'intervalo', which
    never reaches the second half - but the check stays explicit, because the alternative
    is a `TypeError` on a screen that only breaks for whoever has a schedule registered.
    """
    if sched["kind"] == "intervalo":
        last_one = _parse_dt(sched["last_run"]) or now
        return last_one + timedelta(hours=int(sched["every_hours"]))

    previous = previous_occurrence(sched, now) or now
    return previous + timedelta(days=7 if sched["kind"] == "semanal" else 1)


# ---------------------------------------------------------- usage charts
#
# The samples become COORDINATES here, on the server: the screen receives a ready SVG and
# stays readable without JavaScript. The JS on top only adds the crosshair and the tooltip;
# no value depends on it (the end of each line has a label, and there is the table below).

# Two samples further apart than this become a GAP in the line, not a straight stroke
# across: a server that was down for two hours did not "move in a straight line".
# Chart drawing in gamepanel.services.chart_service; the names stay here because
# the route, the template and the tests call them.
CHART_TICKS = chart_service.CHART_TICKS
CHART_RANGES = chart_service.CHART_RANGES
CHART_CPU = chart_service.CHART_CPU
CHART_MEM = chart_service.CHART_MEM
_clean_ceiling = chart_service.clean_ceiling


def build_chart(amostras, series, teto: float, start, fim, time_format: str) -> dict:
    # `SAMPLE_EVERY` comes in here because it is panel configuration: it is what says from
    # which gap between two samples the chart line should be cut.
    return chart_service.build_chart(
        amostras, series, teto, start, fim, time_format, SAMPLE_EVERY)


# --------------------------------------------------------------- history


# ------------------------------------------------------------- access / account


def _two_factor_state() -> dict:
    row = users_repo.two_factor_state(db(), session["uid"])
    # Session of a user who was DELETED while it was open. Saying "off"
    # is right: there is nothing to turn off, and `login_required` sends the person to the login
    # on the next round. Before this the line blew up with TypeError.
    if row is None:
        return {"ativo": False, "codigos_restantes": 0}
    try:
        remaining_ones = len(json.loads(row["totp_recovery"] or "[]"))
    except ValueError:
        remaining_ones = 0
    return {"ativo": bool(row["totp_enabled"]), "codigos_restantes": remaining_ones}


def _store_second_factor(uid: int, secret: str, step: int) -> list[str]:
    """Enable 2FA and return the recovery codes IN PLAIN TEXT, the only time they exist."""
    codes = totp.new_recovery_codes()
    conn = db()
    with conn:
        users_repo.enable_two_factor(
            conn, uid, secret, step,
            json.dumps([totp.hash_recovery_code(c) for c in codes]))
    return codes


def _password_and_code_ok(uid: int) -> tuple[sqlite3.Row | None, str]:
    """To turn 2FA off or ask for new codes: the password AND a code. Whoever is signed in already
    proved both at login, but a session left open must not be able to turn off the protection."""
    row = users_repo.by_id(db(), uid)
    if row is None:
        # Same orphan session as in `_two_factor_state`: without a user there is no password to check.
        return None, "Senha incorreta."
    key = f"2fa|{row['username'].lower()}"
    if totp_lockout.remaining(key):
        return None, "Muitas tentativas. Espere alguns minutos."
    if not verify_password(request.form.get("password", ""), row["password_hash"]):
        totp_lockout.record_failure(key)
        return None, "Senha incorreta."
    if not _check_second_factor(row, request.form.get("code", "")):
        totp_lockout.record_failure(key)
        return None, "Codigo invalido ou ja usado."
    totp_lockout.clear(key)
    return row, ""


def _delete_second_factor(uid: int) -> None:
    conn = db()
    with conn:
        users_repo.disable_two_factor(conn, uid)


# ------------------------------------------------------------------ alerts


def alerts_without_baseline(conn: sqlite3.Connection) -> dict:
    """Enabled events that have no servers to look at.

    An alert that is on and silent is worse than an alert that is off: the person checks 'game not
    answering', no server has a query configured, and the channel's silence comes to
    be read as "everything is fine".
    """
    bound = webhook_config(conn)["events"]
    if not bound & set(ALERT_PRECISA_CONFIG):
        return {}
    servers = servers_repo.all_ordered(conn)
    with_query = sum(1 for s in servers if player_source(s) in ("a2s", "http"))
    with_players = sum(1 for s in servers if player_source(s))
    with_regex = sum(1 for s in servers if _stored_value(s, "error_re"))
    missing_ones = {}
    if ("travou" in bound or "respondeu" in bound) and not with_query:
        missing_ones["travou"] = ALERT_PRECISA_CONFIG["travou"]
    if ("jogador-entrou" in bound or "jogador-saiu" in bound) and not with_players:
        missing_ones["jogador-entrou"] = ALERT_PRECISA_CONFIG["jogador-entrou"]
    if "erro-no-log" in bound and not with_regex:
        missing_ones["erro-no-log"] = ALERT_PRECISA_CONFIG["erro-no-log"]
    return missing_ones


# The percentage limits of the Alerts screen: form field, database key and
# how the rejection notice names the thing.
ALERT_LIMITS = (
    ("disk_pct", "webhook_disk_pct", "disco cheio"),
    ("mem_pct", "webhook_mem_pct", "memoria cheia"),
    ("cpu_pct", "webhook_cpu_pct", "CPU alta"),
)


def _reset_baseline() -> None:
    """The monitor's memory goes stale when the configuration changes.

    Resetting it, the next round only RECORDS the current state instead of firing an alert about
    what was already like that before the change.
    """
    _monitor_state.clear()


def _read_webhook_form() -> tuple:
    """Validate a destination's form. Return (data, error)."""
    name = (request.form.get("name", "") or "").strip()[:60]
    url = (request.form.get("url", "") or "").strip()[:400]
    events = [e for e in request.form.getlist("events") if e in ALERT_EVENTS]
    enabled = 1 if request.form.get("enabled") else 0
    if url and not URL_RE.match(url):
        return None, "URL invalida (comece com http:// ou https://)."
    return {"name": name, "url": url, "events": ",".join(events), "enabled": enabled}, ""


# ------------------------------------------------------------------ users


validate_password = passwords.validate_password


def count_admins(excluding: int = 0) -> int:
    """How many administrators would remain without the user `excluding`."""
    return users_repo.count_admins_besides(db(), ROLE_ADMIN, excluding)


def _user_or_404(uid: int) -> sqlite3.Row:
    row = users_repo.identity(db(), uid)
    if not row:
        abort(404)
    return row


@app.after_request
def _security_headers(resp):
    """The panel gives root power on the containers: it must not be embedded in another page.

    Without X-Frame-Options any site can put the panel in an invisible iframe and capture the
    clicks of whoever is signed in (clickjacking), and the buttons here stop servers.
    Referrer-Policy keeps the address of a panel screen from leaking along with a
    click to the outside.
    """
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


# ------------------------------------------------- installable app (PWA)

# Folders whose content the panel can serve offline after being installed.
SHELL_FOLDERS = ("css", "js", "icons")


def _shell_files() -> tuple[list[str], str]:
    """URLs of the app shell and its version mark.

    It is what makes a deploy reach the phone: new mark -> different service worker
    file -> the browser installs it and discards the old cache. Without this, whoever installed
    the panel would keep seeing last week's screen.

    In a packaged release the mark is the VERSION: it answers "which code is this phone
    serving?", which the mtime does not. Running from the repository there is no version to
    mark, so the most recent mtime of the static files applies: it is the only signal that changes
    when one saves a CSS file without packaging anything.
    """
    urls: list[str] = []
    newest = 0
    for folder in SHELL_FOLDERS:
        root = os.path.join(app.static_folder or "", folder)
        for base, _dirs, files in os.walk(root):
            for name in sorted(files):
                path = os.path.join(base, name)
                relative = os.path.relpath(path, app.static_folder).replace(os.sep, "/")
                urls.append(static_url(relative))
                newest = max(newest, int(os.path.getmtime(path)))
    mark = str(newest) if version.BUILD.is_dev else version.BUILD.version
    return urls, mark


def _error_page(exc, code: int):
    """The description of the `abort(...)` in the language of whoever is looking.

    `exc.description`, not `str(exc)`: the latter prepends "403 Forbidden: " (the
    template already shows the code above) and collapses the `i18n.Message` into a plain `str`,
    which is the DEPLOY language: the English screen showed Portuguese.
    """
    return render_template(TPL_ERROR, code=code, message=translate(exc.description)), code


@app.errorhandler(400)
def _bad_request(exc):
    return _error_page(exc, 400)


@app.errorhandler(403)
def _forbidden(exc):
    return _error_page(exc, 403)


@app.errorhandler(404)
def _not_found(_exc):
    return render_template(
        TPL_ERROR, code=404, message=translate("error.not_found")), 404


@app.errorhandler(413)
def _too_large(_exc):
    # The two caps are very different, and landing on a 413 without knowing which of them does not help
    # anyone: the editor loads the whole file into a textarea, the upload does not.
    if request.endpoint in BIG_BODY_ENDPOINTS:
        message = translate("error.upload_too_large", limit=_human_size(FILE_UPLOAD_MAX))
    else:
        message = translate("error.content_too_large", kb=FILE_MAX_BYTES // 1024)
    return render_template(TPL_ERROR, code=413, message=message), 413


@app.errorhandler(503)
def _unavailable(exc):
    return _error_page(exc, 503)


# --------------------------------------------------------------- bootstrap CLI


def ensure_admin_user(username: str, password: str, role: str = "") -> None:
    """Create the initial user, or reset the password if it already exists.

    It is still the emergency exit when nobody can get in: this is how
    the admin role is given back to someone without going through the screen (`--role admin`).
    Without `--role`, a user that already exists keeps the role it had.
    """
    if role and role not in ROLES:
        raise SystemExit(f"papel invalido: {role} (use {' ou '.join(ROLES)})")
    init_db()
    conn = _connect()
    with conn:
        row = users_repo.id_by_username(conn, username)
        if row and role:
            users_repo.set_password_and_role(conn, row["id"], hash_password(password), role)
            print(f"Senha do usuario '{username}' redefinida; papel: {role}.")
        elif row:
            users_repo.set_password(conn, row["id"], hash_password(password))
            print(f"Senha do usuario '{username}' redefinida.")
        else:
            # A user created from the command line is admin by default: it is the deploy one,
            # which needs to register servers and create the others on the screen.
            papel = role or ROLE_ADMIN
            users_repo.insert(conn, username, hash_password(password), papel, now_iso())
            print(f"Usuario '{username}' criado ({papel}).")
    conn.close()


class DeployServer(NamedTuple):
    """A server's data coming from the deploy, in a single object.

    It used to be fifteen loose parameters. Fifteen positions is the kind of signature where a
    `join_re` ends up in place of the `leave_re` and nobody notices until the player
    count starts lying. As a named tuple, the field has a name at the call
    site and the object travels whole between the functions below.
    """

    name: str
    host: str
    service: str
    ssh_port: int = 22
    # Empty = the deploy did not say. A NEW server is then registered with the unprivileged
    # login user (`remote_cmd.HELPER_USER`); an EXISTING one keeps whatever it has - a redeploy
    # must not flip a legacy (root) server to a user its container may not have yet. A caller
    # that knows the container (the broker, a deploy that created `gamepanel`) says so explicitly.
    ssh_user: str = ""
    game_port: str = ""
    notes: str = ""
    config_path: str = ""
    config_files: str = ""
    backup_paths: str = ""
    join_re: str = ""
    leave_re: str = ""
    log_path: str = ""
    query_port: int = 0
    player_source: str = ""
    # The broker instance this server came from (0 = manual registration/old deploy).
    broker_id: int = 0
    # Slots, from MAX_PLAYERS in the game's .env (0 = the counting source reports it, or nobody knows).
    max_players: int = 0


def _insert_server(conn: sqlite3.Connection, data: DeployServer) -> None:
    data = data._replace(ssh_user=data.ssh_user or remote_cmd.HELPER_USER)
    servers_repo.deploy_insert(
        conn,
        [getattr(data, c) for c in servers_repo.DEPLOY_FIELDS],
        now_iso(),
    )


def _merge_config_files(stored: str, incoming: str) -> str:
    """The files already registered plus the deploy ones, without repeating or losing any."""
    listing = [p for p in (stored or "").splitlines() if p.strip()]
    for fresh in incoming.splitlines():
        if fresh.strip() and fresh.strip() not in listing:
            listing.append(fresh.strip())
    return "\n".join(listing[:CONFIG_FILES_MAX])


def _update_server(conn: sqlite3.Connection, current, data: DeployServer) -> None:
    """Redeploy: the container rules over what is its own, the panel rules over what is a choice.

    Name, service, ports and config path come from the deploy: they are facts about the container.
    Backup paths, the way to count players and log patterns, on the other hand, are usually
    tuned on the screen, and a redeploy must not erase them.
    """
    # The order FOLLOWS `servers_repo.DEPLOY_UPDATE_FIELDS`: the column list is there, and
    # here only the decision of who wins on each one.
    servers_repo.deploy_update(
        conn,
        [
            data.name, data.ssh_user or current["ssh_user"], data.service, data.game_port,
            data.notes or current["notes"],
            data.config_path or current["config_path"],
            _merge_config_files(current["config_files"], data.config_files),
            current["backup_paths"] or data.backup_paths,
            data.query_port,
            current["player_source"] or data.player_source,
            current["join_re"] or data.join_re,
            current["leave_re"] or data.leave_re,
            current["log_path"] or data.log_path,
            current["max_players"] or data.max_players,
        ],
        current["id"],
    )


def ensure_server(data: DeployServer) -> bool:
    """Register (or update) a server without going through the screen. Return True if it created one.

    This is how the deploy registers the newly created container in the panel, including the
    game's configuration file, so the "Configuration" screen opens ready.
    """
    init_db()
    conn = _connect()
    try:
        with conn:
            current_one = servers_repo.by_address(conn, data.host, data.ssh_port)
            if current_one is None:
                _insert_server(conn, data)
                return True
            _update_server(conn, current_one, data)
            return False
    finally:
        conn.close()


init_db()

# Under gunicorn this module is IMPORTED, which is the right moment to start the clock. From the
# command line it is __main__ and this does not run: a `--register-server` in the middle of a
# deploy must not fire the scheduled task in passing (and the process dies right after,
# leaving the job hanging in 'running').
if __name__ != "__main__":
    start_scheduler()
    resume_broker_jobs()


# At the end of the file on purpose: each blueprint does `from gamepanel import app as
# panel` and calls `panel.X`, so it can only be imported after `X` exists.
register_all(app)


if __name__ == "__main__":
    # The command line lives in gamepanel/cli.py; the bottom here still exists
    # because the README and CLAUDE.md document `python3 .../app.py --reset-2fa USER`,
    # and whoever needs that command is locked out of the panel.
    cli.main(cli.CliDeps(
        init_db=init_db, connect=_connect, ensure_admin_user=ensure_admin_user,
        ensure_server=ensure_server, deploy_server=DeployServer,
        start_scheduler=start_scheduler, resume_broker_jobs=resume_broker_jobs,
        app=app, roles=ROLES,
    ))
