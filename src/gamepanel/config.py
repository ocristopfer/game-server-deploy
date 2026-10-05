"""Every `GAMEPANEL_*` variable, read and checked in one place.

Before this there were ~45 `os.environ.get` calls scattered across `app.py`, each with
its own inline conversion. Two consequences, both in production:

- **An invalid value took the panel down without saying which one.** `int(os.environ.get(...))`
  with garbage raises `ValueError: invalid literal for int() with base 10: 'abc'`, and the
  message does not name the variable. Whoever was reading the journal had to guess among 45.
- **There were no ranges.** `GAMEPANEL_MONITOR_EVERY=0` made the monitor spin nonstop, and
  nothing warned about it.

The design follows the broker's (`gamebroker/config.py`): list ALL problems at
once, only by the variable NAME, never the value, because this goes to the journal and some
of them are secrets. Bad config fails the START, not a request: a panel that is up with
half its configuration is worse than one that does not start.
"""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from typing import NamedTuple
from urllib.parse import urlsplit

PREFIX = "GAMEPANEL_"
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigError(ValueError):
    """One or more configuration problems, each already carrying its variable name."""


class _Reader:
    """Read and convert, collecting the problems instead of stopping at the first.

    Stopping at the first makes whoever configures discover one error per deploy. Here the
    whole list comes out, and the next attempt can already be right.
    """

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self.problems: list[str] = []

    def _raw(self, name: str) -> str | None:
        return self._env.get(PREFIX + name)

    def text(self, name: str, default: str = "") -> str:
        value = self._raw(name)
        return default if value is None else value

    def flag(self, name: str, default: bool) -> bool:
        value = self._raw(name)
        if value is None:
            return default
        low = value.strip().lower()
        if low in TRUE_VALUES:
            return True
        if low in FALSE_VALUES:
            return False
        self.problems.append(f"{PREFIX}{name}: esperado 1/0 (ou true/false)")
        return default

    def integer(self, name: str, default: int, minimum: int | None = None,
                maximum: int | None = None) -> int:
        return int(self._number(name, default, minimum, maximum, whole=True))

    def number(self, name: str, default: float, minimum: float | None = None,
               maximum: float | None = None) -> float:
        return self._number(name, default, minimum, maximum, whole=False)

    def _number(self, name: str, default: float, minimum: float | None,
                maximum: float | None, whole: bool) -> float:
        raw = self._raw(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            value = int(raw) if whole else float(raw)
        except ValueError:
            kind = "um numero inteiro" if whole else "um numero"
            self.problems.append(f"{PREFIX}{name}: esperado {kind}")
            return default
        if minimum is not None and value < minimum:
            self.problems.append(f"{PREFIX}{name}: minimo {minimum}")
            return default
        if maximum is not None and value > maximum:
            self.problems.append(f"{PREFIX}{name}: maximo {maximum}")
            return default
        return value

    def origin(self, name: str) -> str:
        """Panel address for the passkey: `https://<domain>[:port]`, or `http://localhost`.

        The browser only offers WebAuthn in a secure context (https, or localhost), and the passkey
        is bound to the DOMAIN: an IP does not work as RP ID. Empty = feature off.
        """
        raw = self.text(name).strip().rstrip("/")
        if not raw:
            return ""
        parts = urlsplit(raw)
        host = parts.hostname or ""
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            is_ip = False
        secure = parts.scheme == "https" or (parts.scheme == "http" and host == "localhost")
        if not host or is_ip or not secure or parts.path or parts.query or parts.fragment:
            self.problems.append(f"{PREFIX}{name}: esperado https://<dominio> (IP nao serve), ou http://localhost")
            return ""
        return raw

    def path_list(self, name: str, default: str) -> tuple[str, ...]:
        raw = self.text(name, default)
        return tuple(p.strip() for p in raw.split(",") if p.strip())


# Comma-separated, like every list option here.
DEFAULT_FILE_ROOTS = "/opt/game,/home/steam"


class Settings(NamedTuple):
    """Everything the panel reads from the environment. The names follow those in `app.py`."""

    # --- files and remote access ---
    db_path: str
    secret_file: str
    ssh_key: str
    known_hosts: str
    ssh_control_dir: str
    ssh_control_persist: str
    # --- command execution ---
    job_timeout: int
    shell_timeout: int
    allow_shell: bool
    term_max_sessions: int
    term_idle_timeout: int
    # --- broker ---
    broker_url: str
    broker_token_file: str
    broker_cert_sha256: str
    broker_poll: float
    allow_broker: bool
    dev: bool
    # --- container files ---
    allow_files: bool
    file_max_bytes: int
    file_preview_bytes: int
    file_download_max: int
    file_upload_max: int
    file_roots: tuple[str, ...]
    file_default_path: str
    # --- backups ---
    backup_dir: str
    backup_keep: int
    backup_timeout: int
    panel_backup_dir: str
    panel_backup_keep: int
    # --- scheduler and cleanup ---
    schedule_tick: float
    schedule_grace: int
    jobs_keep_days: int
    sample_every: float
    samples_keep_days: int
    # --- alerts ---
    webhook_url: str
    webhook_timeout: float
    webhook_ua: str
    webhook_max: int
    alert_log_keep: int
    alert_quiet: float
    mute_rounds: int
    monitor_every: float
    player_check_every: float
    disk_check_every: float
    log_check_every: float
    log_err_cooldown: float
    log_stream: bool
    log_stream_debounce: float
    log_stream_retry: float
    # --- queries ---
    metrics_ttl: float
    query_timeout: float
    players_ttl: float
    http_timeout: float
    http_probe_timeout: float
    # --- screen ---
    lang: str
    require_2fa: bool
    # Sign in with the device biometrics (passkey): the panel's https address. Empty = off.
    webauthn_origin: str
    # --- development server (`python -m gamepanel.cli`) ---
    port: int


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Read the environment and return everything ready. Raises `ConfigError` with the full list.

    The minimums are not decoration: a zero interval makes a loop spin nonstop, and a
    `TERM_MAX=0` leaves the terminal unusable without saying why.
    """
    reader = _Reader(os.environ if env is None else env)

    known_hosts = reader.text("KNOWN_HOSTS", "/var/lib/gamepanel/known_hosts")
    db_path = reader.text("DB", "/var/lib/gamepanel/panel.db")
    settings = Settings(
        db_path=db_path,
        secret_file=reader.text("SECRET_FILE", "/etc/gamepanel/secret_key"),
        ssh_key=reader.text("SSH_KEY", "/etc/gamepanel/id_ed25519"),
        known_hosts=known_hosts,
        # Next to known_hosts by default: both are SSH state and live on the same
        # volume, so a deploy that moves one moves the other along.
        ssh_control_dir=reader.text(
            "SSH_CONTROL_DIR", os.path.join(os.path.dirname(known_hosts), "ssh-control")),
        ssh_control_persist=reader.text("SSH_CONTROL_PERSIST", "60"),

        job_timeout=reader.integer("JOB_TIMEOUT", 5400, minimum=1),
        shell_timeout=reader.integer("SHELL_TIMEOUT", 600, minimum=1),
        allow_shell=reader.flag("ALLOW_SHELL", True),
        term_max_sessions=reader.integer("TERM_MAX", 4, minimum=1),
        term_idle_timeout=reader.integer("TERM_IDLE", 900, minimum=1),

        broker_url=reader.text("BROKER_URL"),
        broker_token_file=reader.text("BROKER_TOKEN_FILE"),
        broker_cert_sha256=reader.text("BROKER_CERT_SHA256"),
        broker_poll=reader.number("BROKER_POLL", 2.0, minimum=0.1),
        allow_broker=reader.flag("ALLOW_BROKER", False),
        dev=reader.flag("DEV", False),

        allow_files=reader.flag("ALLOW_FILES", True),
        file_max_bytes=reader.integer("FILE_MAX", 4 * 1024 * 1024, minimum=1),
        file_preview_bytes=reader.integer("FILE_PREVIEW", 256 * 1024, minimum=1),
        file_download_max=reader.integer("FILE_DOWNLOAD_MAX", 2 * 1024 * 1024 * 1024, minimum=1),
        file_upload_max=reader.integer("UPLOAD_MAX", 512 * 1024 * 1024, minimum=0),
        # The game install and steam's home: where every config, save and mod lives. Not `/`:
        # the file manager writes as root on a legacy server, and the whole disk one form away
        # is more than any game needs. An operator who really wants more lists it explicitly.
        file_roots=reader.path_list("FILE_ROOTS", DEFAULT_FILE_ROOTS),
        file_default_path=reader.text("FILE_DEFAULT", "/opt/game"),

        backup_dir=reader.text("BACKUP_DIR", "/var/backups/gamepanel"),
        backup_keep=reader.integer("BACKUP_KEEP", 5, minimum=1),
        backup_timeout=reader.integer("BACKUP_TIMEOUT", 3600, minimum=1),
        # The second copy, on the PANEL: next to the database by default, on the same volume, which is
        # what the deploy already treats as state to preserve. 0 = never delete by retention.
        panel_backup_dir=reader.text(
            "PANEL_BACKUP_DIR", os.path.join(os.path.dirname(db_path), "backups")),
        panel_backup_keep=reader.integer("PANEL_BACKUP_KEEP", 10, minimum=0),

        schedule_tick=reader.number("SCHEDULE_TICK", 15.0, minimum=1),
        schedule_grace=reader.integer("SCHEDULE_GRACE", 3600, minimum=0),
        jobs_keep_days=reader.integer("JOBS_KEEP_DAYS", 60, minimum=0),
        sample_every=reader.number("SAMPLE_EVERY", 300.0, minimum=1),
        samples_keep_days=reader.integer("SAMPLES_KEEP_DAYS", 7, minimum=0),

        webhook_url=reader.text("WEBHOOK_URL"),
        webhook_timeout=reader.number("WEBHOOK_TIMEOUT", 6.0, minimum=0.1),
        webhook_ua=reader.text("WEBHOOK_UA", "GamePanel/1.0 (alertas)"),
        webhook_max=reader.integer("WEBHOOK_MAX", 10, minimum=1),
        alert_log_keep=reader.integer("ALERT_LOG_KEEP", 500, minimum=1),
        alert_quiet=reader.number("ALERT_QUIET", 180.0, minimum=0),
        mute_rounds=reader.integer("MUTE_ROUNDS", 3, minimum=1),
        monitor_every=reader.number("MONITOR_EVERY", 60.0, minimum=1),
        player_check_every=reader.number("PLAYER_CHECK_EVERY", 15.0, minimum=1),
        disk_check_every=reader.number("DISK_CHECK_EVERY", 600.0, minimum=1),
        log_check_every=reader.number("LOG_CHECK_EVERY", 120.0, minimum=1),
        log_err_cooldown=reader.number("LOG_ERR_COOLDOWN", 600.0, minimum=0),
        log_stream=reader.flag("LOG_STREAM", True),
        log_stream_debounce=reader.number("LOG_STREAM_DEBOUNCE", 3.0, minimum=0),
        log_stream_retry=reader.number("LOG_STREAM_RETRY", 30.0, minimum=1),

        metrics_ttl=reader.number("METRICS_TTL", 4.0, minimum=0),
        query_timeout=reader.number("QUERY_TIMEOUT", 3.0, minimum=0.1),
        players_ttl=reader.number("PLAYERS_TTL", 5.0, minimum=0),
        http_timeout=reader.number("HTTP_TIMEOUT", 6.0, minimum=0.1),
        http_probe_timeout=reader.number("PROBE_TIMEOUT", 2.0, minimum=0.1),

        lang=reader.text("LANG"),
        require_2fa=reader.flag("REQUIRE_2FA", False),
        webauthn_origin=reader.origin("WEBAUTHN_ORIGIN"),
        port=reader.integer("PORT", 8080, minimum=1, maximum=65535),
    )
    if reader.problems:
        raise ConfigError("configuracao do painel invalida:\n  - "
                          + "\n  - ".join(reader.problems))
    return settings
