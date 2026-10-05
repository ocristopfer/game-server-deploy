"""The panel's database schema: the tables, the migrations and the startup.

`CREATE TABLE IF NOT EXISTS` does not alter a table that already exists, so a new column
needs its own ALTER in `MIGRATIONS` - which is why the two lists live side by side: the
second only makes sense when read with the first.

The per-REQUEST connection (the `db()` tied to Flask's `g`) stays in `app.py`; here there
is only the raw connection, which the background threads also use.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  -- 'admin' (everything, including registering servers, shell and files) or 'operador'
  -- (operates the servers already registered). See ROLES right below.
  role          TEXT NOT NULL DEFAULT 'operador',
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  host       TEXT NOT NULL,
  ssh_port   INTEGER NOT NULL DEFAULT 22,
  ssh_user   TEXT NOT NULL DEFAULT 'root',
  service    TEXT NOT NULL,
  game_port  TEXT NOT NULL DEFAULT '',
  notes      TEXT NOT NULL DEFAULT '',
  config_path TEXT NOT NULL DEFAULT '',
  -- Files (one per line) that the "Config" screen opens directly, without browsing folders.
  config_files TEXT NOT NULL DEFAULT '',
  -- Folders/files (one per line) included in the backup. Empty = use config_path.
  backup_paths TEXT NOT NULL DEFAULT '',
  query_port INTEGER NOT NULL DEFAULT 0,
  -- Server slots, so the screen can show "2/6". Only used when the counting source
  -- does not report the total (log, active connections); A2S brings its own. 0 = unknown.
  max_players INTEGER NOT NULL DEFAULT 0,
  player_source TEXT NOT NULL DEFAULT '',
  join_re    TEXT NOT NULL DEFAULT '',
  leave_re   TEXT NOT NULL DEFAULT '',
  -- Where to read the log to count players. Empty = the service journalctl. When set,
  -- it is a path (may contain *) to a FILE inside the container: several games only
  -- write who joins to a file of their own, never to stdout. DayZ works
  -- like that (profiles/*.ADM, enabled by -adminlog).
  log_path   TEXT NOT NULL DEFAULT '',
  -- Counting through the game's own HTTP API (Palworld, Satisfactory, ...).
  http_url   TEXT NOT NULL DEFAULT '',
  -- 'basic:user:password', 'bearer:token' or a ready-made Authorization header.
  http_auth  TEXT NOT NULL DEFAULT '',
  -- JSON body: empty sends GET, filled sends POST.
  http_body  TEXT NOT NULL DEFAULT '',
  -- Paths inside the JSON (e.g. 'data.players'); empty = discover automatically.
  http_list_path  TEXT NOT NULL DEFAULT '',
  http_count_path TEXT NOT NULL DEFAULT '',
  -- Automatic login (APIs whose token expires, like the Satisfactory one): the panel
  -- posts http_login_body to http_login_url, takes the token from http_token_path and
  -- stores it in http_token. When the API answers 401/403, it logs in again.
  http_login_url  TEXT NOT NULL DEFAULT '',
  http_login_body TEXT NOT NULL DEFAULT '',
  http_token_path TEXT NOT NULL DEFAULT '',
  http_token      TEXT NOT NULL DEFAULT '',
  -- "Error in log" alert: regular expression searched in the last lines of the game log
  -- (the same log used for counting - journalctl or log_path). Empty disables the check.
  error_re   TEXT NOT NULL DEFAULT '',
  -- Instance id in the broker (0 = server registered by hand). It links the instances
  -- screen to the server, and removing the instance uses it to delete this record.
  broker_id  INTEGER NOT NULL DEFAULT 0,
  -- Mods the server SHOULD have (Workshop IDs, one per line), pasted on the Mods screen.
  -- It is the reference list: the screen compares it with what the server actually loads.
  mods_expected TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (host, ssh_port)
);

CREATE TABLE IF NOT EXISTS jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id   INTEGER REFERENCES servers(id) ON DELETE SET NULL,
  target      TEXT NOT NULL DEFAULT '',
  action      TEXT NOT NULL,
  status      TEXT NOT NULL,             -- running | ok | error
  exit_code   INTEGER,
  output      TEXT NOT NULL DEFAULT '',
  command     TEXT NOT NULL DEFAULT '',  -- preenchido apenas pelo console
  username    TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  finished_at TEXT,
  -- Broker operation this job follows (empty for other jobs). Survives a panel
  -- restart: it is how following the operation is resumed.
  broker_op   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_jobs_server ON jobs(server_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS schedules (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  -- CASCADE: removing the server from the panel also removes what was scheduled for it.
  server_id   INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  action      TEXT NOT NULL,             -- restart | stop | start | update | backup
  -- 'diario' (fixed time), 'semanal' (weekday + time), 'intervalo' (every N hours)
  kind        TEXT NOT NULL,
  hour        INTEGER NOT NULL DEFAULT 5,
  minute      INTEGER NOT NULL DEFAULT 0,
  weekday     INTEGER NOT NULL DEFAULT 0,   -- 0 = segunda ... 6 = domingo
  every_hours INTEGER NOT NULL DEFAULT 6,
  enabled     INTEGER NOT NULL DEFAULT 1,
  -- When it last fired, in LOCAL time with offset (the same clock as the
  -- schedule). It keeps the same occurrence from running twice.
  last_run    TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sched_server ON schedules(server_id);

-- One row per server every SAMPLE_EVERY: it answers "why did it freeze
-- last night" after the night is over. CASCADE with the server.
CREATE TABLE IF NOT EXISTS samples (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  taken_at  TEXT NOT NULL,
  cpu_pct   REAL,
  mem_pct   REAL,
  players   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_samples ON samples(server_id, taken_at);

-- Settings changed on screen that must survive a panel restart (today only
-- the alerts). Kept here, not in an environment variable, so no redeploy is needed.
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);

-- Alert destinations. Each row is a channel (a Discord, a Slack, a custom
-- endpoint) with ITS OWN list of events: everything can go to the team channel and only
-- 'server down' to the general channel, without both receiving the same thing.
CREATE TABLE IF NOT EXISTS webhooks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL DEFAULT '',
  url        TEXT NOT NULL,
  events     TEXT NOT NULL DEFAULT '',
  enabled    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT ''
);

-- Alert log: one row per delivery ATTEMPT, and also one per alert that
-- had no destination at all. A silent channel has two opposite causes - nothing happened,
-- or it happened and was not sent - and from outside they look the same. Without this log
-- the only option is guessing.
CREATE TABLE IF NOT EXISTS alert_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  event      TEXT NOT NULL DEFAULT '',
  title      TEXT NOT NULL DEFAULT '',
  detail     TEXT NOT NULL DEFAULT '',
  target     TEXT NOT NULL DEFAULT '',
  -- 'enviado', 'falhou', 'sem-destino' or 'erro-interno'
  status     TEXT NOT NULL DEFAULT '',
  error      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_alert_log_id ON alert_log (id DESC);

-- Passkeys: sign in with the device biometrics (WebAuthn). One row per registered device;
-- only the PUBLIC key is stored here - the private key never leaves the device. CASCADE:
-- deleting the user removes their devices. `user_handle` is the random id the device keeps
-- with the passkey (WebAuthn asks for an opaque id; the table `id` would leak the user count).
CREATE TABLE IF NOT EXISTS passkeys (
  id           TEXT PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_handle  TEXT NOT NULL,
  public_key   BLOB NOT NULL,
  sign_count   INTEGER NOT NULL DEFAULT 0,
  label        TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL,
  last_used_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_passkeys_user ON passkeys (user_id);
"""



MIGRATIONS = (
    # Roles: before this column everyone who logged in could do everything, and the only
    # user was the one created by the deploy. So existing users become admin - the
    # column's 'operador' default only applies to users created from then on.
    ("users", "role", (
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'operador'",
        "UPDATE users SET role = 'admin'",
    )),
    ("servers", "config_path", "ALTER TABLE servers ADD COLUMN config_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "query_port", "ALTER TABLE servers ADD COLUMN query_port INTEGER NOT NULL DEFAULT 0"),
    # Total slots for servers counted without A2S: Dragonwilds (EOS) does not publish the
    # limit anywhere the panel can reach, and the screen showed "0 players" instead of "0/6".
    ("servers", "max_players", "ALTER TABLE servers ADD COLUMN max_players INTEGER NOT NULL DEFAULT 0"),
    ("servers", "player_source", "ALTER TABLE servers ADD COLUMN player_source TEXT NOT NULL DEFAULT ''"),
    ("servers", "join_re", "ALTER TABLE servers ADD COLUMN join_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "leave_re", "ALTER TABLE servers ADD COLUMN leave_re TEXT NOT NULL DEFAULT ''"),
    # Log in a file: without this column the count only saw journalctl, and the DayZ
    # player's name (which only exists in the .ADM) was out of reach.
    ("servers", "log_path", "ALTER TABLE servers ADD COLUMN log_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "config_files", "ALTER TABLE servers ADD COLUMN config_files TEXT NOT NULL DEFAULT ''"),
    # Backup: what to keep from each server. An old registration stays empty and falls
    # back to config_path, which is the behavior it would have had if the column had
    # always existed.
    ("servers", "backup_paths", "ALTER TABLE servers ADD COLUMN backup_paths TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_url", "ALTER TABLE servers ADD COLUMN http_url TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_auth", "ALTER TABLE servers ADD COLUMN http_auth TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_body", "ALTER TABLE servers ADD COLUMN http_body TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_list_path", "ALTER TABLE servers ADD COLUMN http_list_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_count_path", "ALTER TABLE servers ADD COLUMN http_count_path TEXT NOT NULL DEFAULT ''"),
    # Automatic login: APIs that issue expiring tokens (Satisfactory) break the count when
    # the token expires. With these fields the panel trades the password for a token on its
    # own and renews it when the API answers 401/403.
    ("servers", "http_login_url", "ALTER TABLE servers ADD COLUMN http_login_url TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_login_body", "ALTER TABLE servers ADD COLUMN http_login_body TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_token_path", "ALTER TABLE servers ADD COLUMN http_token_path TEXT NOT NULL DEFAULT ''"),
    ("servers", "http_token", "ALTER TABLE servers ADD COLUMN http_token TEXT NOT NULL DEFAULT ''"),
    # Log error alert: the expression is per server because each game screams its own way.
    # Empty (the default) turns the check off - including its SSH round trip.
    ("servers", "error_re", "ALTER TABLE servers ADD COLUMN error_re TEXT NOT NULL DEFAULT ''"),
    ("servers", "broker_id", "ALTER TABLE servers ADD COLUMN broker_id INTEGER NOT NULL DEFAULT 0"),
    # Second factor (TOTP). The secret is stored in plain text because the server needs it to
    # check the code; what protects it is the database file (0600, inside the CT). Recovery
    # codes are stored only as hashes (JSON with the list). `totp_last_step` is the anti-replay.
    ("users", "totp_secret", "ALTER TABLE users ADD COLUMN totp_secret TEXT NOT NULL DEFAULT ''"),
    ("users", "totp_enabled", "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0"),
    ("users", "totp_last_step", "ALTER TABLE users ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0"),
    ("users", "totp_recovery", "ALTER TABLE users ADD COLUMN totp_recovery TEXT NOT NULL DEFAULT ''"),
    ("jobs", "broker_op", "ALTER TABLE jobs ADD COLUMN broker_op TEXT NOT NULL DEFAULT ''"),
    # Screen language, per person. Empty on purpose: whoever never chose follows what the
    # browser asks for, not a choice the panel made for them.
    ("users", "lang", "ALTER TABLE users ADD COLUMN lang TEXT NOT NULL DEFAULT ''"),
    # Expected mod list of the Mods screen. Empty = nobody pasted a list, and the screen only
    # shows what is there.
    ("servers", "mods_expected", "ALTER TABLE servers ADD COLUMN mods_expected TEXT NOT NULL DEFAULT ''"),
)


# Columns whose NAME changed. Kept apart from `MIGRATIONS` because the question differs:
# there it is "does the column exist?", here it is "does it still have the old name?". A
# new database is born with the new name through SCHEMA and enters neither.
#
# SQLite's `RENAME COLUMN` (3.25+) rewrites the index and references on its own, and
# keeps the data - no new table plus copy, which is where rows get lost.
RENAMES = (
    ("webhooks", "nome", "name"),
    ("webhooks", "eventos", "events"),
    ("webhooks", "ativo", "enabled"),
    ("webhooks", "criado_em", "created_at"),
    ("alert_log", "criado_em", "created_at"),
    ("alert_log", "evento", "event"),
    ("alert_log", "titulo", "title"),
    ("alert_log", "detalhe", "detail"),
    ("alert_log", "destino", "target"),
    ("alert_log", "erro", "error"),
)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL: the background job does not block the screen's reads.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(db_path: str, default_webhook: str, default_events: str,
            now: Callable[[], str]) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                for command in (ddl if isinstance(ddl, tuple) else (ddl,)):
                    conn.execute(command)
        for table, old, new in RENAMES:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            # Both checks together: only rename if the old one is there AND the new one is
            # not. So running again does nothing, and a new database (born right) is skipped.
            if old in cols and new not in cols:
                conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
        _migrate_single_webhook(conn, default_webhook, default_events, now)
    conn.close()


def _migrate_single_webhook(conn: sqlite3.Connection, default_webhook: str,
                            default_events: str, now: Callable[[], str]) -> None:
    """Move the old webhook (settings.webhook_url) into the destinations table.

    The 'webhooks_migrado' marker is what prevents it from coming back: without it, whoever
    deleted the only destination would see the old one reborn on the next restart.
    """
    already = conn.execute(
        "SELECT 1 FROM settings WHERE key = 'webhooks_migrado'"
    ).fetchone()
    if already:
        return
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('webhooks_migrado', '1')"
        " ON CONFLICT(key) DO NOTHING"
    )
    old_one = conn.execute(
        "SELECT value FROM settings WHERE key = 'webhook_url'"
    ).fetchone()
    # With nothing in the database the deploy's value wins: GAMEPANEL_WEBHOOK_URL was the
    # initial value of the single URL and remains that of the first destination.
    url = (old_one["value"] if old_one else "").strip() or default_webhook.strip()
    if not url:
        return
    ev = conn.execute(
        "SELECT value FROM settings WHERE key = 'webhook_events'"
    ).fetchone()
    conn.execute(
        "INSERT INTO webhooks (name, url, events, enabled, created_at)"
        " VALUES (?, ?, ?, 1, ?)",
        ("Webhook", url, (ev["value"] if ev else default_events), now()),
    )


