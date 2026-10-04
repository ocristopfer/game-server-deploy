"""Toda variavel `GAMEPANEL_*` lida e conferida num lugar so.

Antes disto eram ~45 chamadas de `os.environ.get` espalhadas pelo `app.py`, cada uma com
a sua conversao inline. Duas consequencias, as duas em producao:

- **Um valor invalido derrubava o painel sem dizer qual era.** `int(os.environ.get(...))`
  com lixo levanta `ValueError: invalid literal for int() with base 10: 'abc'`, e a
  mensagem nao cita a variavel. Quem estava lendo o journal precisava adivinhar entre 45.
- **Nao havia faixa.** `GAMEPANEL_MONITOR_EVERY=0` fazia o monitor girar sem parar, e
  nada avisava.

O desenho segue o do broker (`gamebroker/config.py`): lista TODOS os problemas de uma
vez, so pelo NOME da variavel — nunca o valor, porque isso vai para o journal e ha
segredo entre elas. Config ruim derruba o START, e nao um pedido: um painel de pe com
metade da configuracao e pior que um que nao sobe.
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
    """Um ou mais problemas de configuracao, ja com o nome de cada variavel."""


class _Reader:
    """Le e converte, juntando os problemas em vez de parar no primeiro.

    Parar no primeiro faz quem configura descobrir um erro por deploy. Aqui a lista sai
    inteira, e a proxima tentativa ja pode estar certa.
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
        """Endereco do painel para a passkey: `https://<dominio>[:porta]`, ou `http://localhost`.

        O navegador so oferece WebAuthn em contexto seguro (https, ou localhost), e a passkey
        fica presa ao DOMINIO: IP nao serve de RP ID. Vazio = recurso desligado.
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


class Settings(NamedTuple):
    """Tudo que o painel le do ambiente. Os nomes seguem os do `app.py`."""

    # --- arquivos e acesso remoto ---
    db_path: str
    secret_file: str
    ssh_key: str
    known_hosts: str
    ssh_control_dir: str
    ssh_control_persist: str
    # --- execucao de comando ---
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
    # --- arquivos do container ---
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
    # --- agendador e limpeza ---
    schedule_tick: float
    schedule_grace: int
    jobs_keep_days: int
    sample_every: float
    samples_keep_days: int
    # --- alertas ---
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
    # --- consultas ---
    metrics_ttl: float
    query_timeout: float
    players_ttl: float
    http_timeout: float
    http_probe_timeout: float
    # --- tela ---
    lang: str
    require_2fa: bool
    # Entrar com a biometria do aparelho (passkey): o endereco https do painel. Vazio = desligado.
    webauthn_origin: str
    # --- servidor de desenvolvimento (`python -m gamepanel.cli`) ---
    port: int


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Le o ambiente e devolve tudo pronto. Levanta `ConfigError` com a lista completa.

    Os minimos nao sao enfeite: um intervalo zero faz um laco girar sem parar, e um
    `TERM_MAX=0` deixa o terminal inutilizavel sem dizer por que.
    """
    reader = _Reader(os.environ if env is None else env)

    known_hosts = reader.text("KNOWN_HOSTS", "/var/lib/gamepanel/known_hosts")
    db_path = reader.text("DB", "/var/lib/gamepanel/panel.db")
    settings = Settings(
        db_path=db_path,
        secret_file=reader.text("SECRET_FILE", "/etc/gamepanel/secret_key"),
        ssh_key=reader.text("SSH_KEY", "/etc/gamepanel/id_ed25519"),
        known_hosts=known_hosts,
        # Ao lado do known_hosts por padrao: os dois sao estado do SSH e vivem no mesmo
        # volume, entao um deploy que move um move o outro junto.
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
        file_roots=reader.path_list("FILE_ROOTS", "/"),
        file_default_path=reader.text("FILE_DEFAULT", "/opt/game"),

        backup_dir=reader.text("BACKUP_DIR", "/var/backups/gamepanel"),
        backup_keep=reader.integer("BACKUP_KEEP", 5, minimum=1),
        backup_timeout=reader.integer("BACKUP_TIMEOUT", 3600, minimum=1),
        # A segunda copia, no PAINEL: ao lado do banco por padrao, no mesmo volume, que e o
        # que o deploy ja trata como estado a preservar. 0 = nunca apagar por retencao.
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
