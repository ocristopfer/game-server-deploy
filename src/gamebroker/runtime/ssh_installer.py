"""SSH installer: brings the game into the newly created CT and removes the broker key.

Flow (all with the system's `ssh`/`scp`, never through a shell):

  1. waits for the CT's sshd to answer (the Debian template already ships sshd);
  2. sends `ct-install.sh`, `ct-phases.sh` and an `install.env` to the CT;
  3. runs `bash ct-install.sh install.env` INSIDE the CT, relaying the log line by line;
  4. ALWAYS (success or not) deletes what it sent and **removes the broker key** from
     authorized_keys. If the key does not come out, the creation FAILS: a new CT must not be
     born with permanent broker access. After a successful install the same command also
     **locks root login** (the panel gets in as `gamepanel`, lib/ct-panel-access.sh).

The panel key is NOT injected into root by Proxmox any more: it travels in `install.env` and
the CT installs it for the unprivileged `gamepanel` user.

The `install.env` quotes every value (`shlex.quote`): nothing from the catalog is concatenated
into a command line or interpreted as shell by the CT's `source`. The broker's Steam account
only goes into the `install.env` of a CURATED game that requires it (`Game.needs_account`,
DayZ): an API game never asks for it, and the file is deleted at the end by `_cleanup`, success
or not. Inside the CT only the token SteamCMD writes on the first login remains, which is what
updates use.

The same phases run in the manual deploy (lib/ct-phases.sh via provision-game-lxc.sh); the
sandbox `docker/ct-sandbox/compare.sh` proves both paths produce exactly the same CT.
"""
from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from gamebroker.services.allocator import ROLE_GAME, ROLE_QUERY, AllocatedPort, port_from_base, port_with_role
from gamebroker.services.catalog import RECIPE_XVFB, RECIPES_WINDOWS, Game

REMOTE_DEST = "/root/gamepanel-install"
SUCCESS_MARK = "INSTALACAO CONCLUIDA"
LIB_FILES = ("ct-install.sh", "ct-phases.sh", "ct-firewall.sh", "ct-panel-access.sh")
# Where ct-phases.sh leaves lib/ct-panel-access.sh inside the CT (PANEL_ACCESS_IN_CT there). The
# cleanup calls it from there, not from REMOTE_DEST: that folder is deleted in the same command.
PANEL_ACCESS_IN_CT = "/usr/local/lib/gamepanel/ct-panel-access.sh"
# Exit code of the cleanup when the broker key DID come out but root could not be locked.
LOCK_FAILED = 3
MAX_LINE = 400
LINE_BATCH = 20
BATCH_SECONDS = 1.5
ERROR_TAIL = 6
_BLOB_RE = re.compile(r"[A-Za-z0-9+/=]{20,}", re.ASCII)
# Steam account: ct-phases.sh puts it in a `su - steam -c '... +login USUARIO SENHA'` line.
# A single quote would close the line, and a space would split the password into two SteamCMD arguments.
_STEAM_USER_RE = re.compile(r"[A-Za-z0-9_.@-]{2,64}", re.ASCII)
_STEAM_PASS_RE = re.compile(r"[!-&(-~]{1,128}", re.ASCII)


class InstallError(RuntimeError):
    """The installation (or the key cleanup) failed. The message goes to the operation log."""


class Executor(Protocol):
    def run(self, argv: Sequence[str], on_line: Callable[[str], None] | None,
              timeout: float, cancel: threading.Event | None = None) -> int:
        """Runs `argv` (no shell), relays each output line and returns the exit code.
        Past `timeout` seconds, or when `cancel` is triggered: kills the process and returns a
        negative code."""


# How often the watcher checks for a cancellation request. Short enough for "cancel" to feel
# immediate; long enough not to be a hot loop.
CANCEL_POLL = 1.0


class ExecutorReal:
    def run(self, argv: Sequence[str], on_line: Callable[[str], None] | None,
              timeout: float, cancel: threading.Event | None = None) -> int:
        try:
            # The argv always comes from `_ssh`/`_options` in this file, with `shlex.quote` on
            # what is data; there is no shell in between and nothing from outside enters as a command.
            proc = subprocess.Popen(  # noqa: S603
                list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", bufsize=1)
        except OSError as error:
            raise InstallError(f"nao consegui executar {argv[0]}: {error.strerror}") from None
        # Reading lines blocks; the deadline is enforced by a timer that kills the process.
        clock = threading.Timer(timeout, proc.kill)
        clock.start()
        if cancel is not None:
            # Reading lines blocks until the process speaks: SteamCMD stays silent for minutes
            # while downloading. That is why cancellation has its own watcher, and not a check
            # between one line and the next - which would only fire on the next output line.
            threading.Thread(target=_kill_on_cancel, args=(proc, cancel), daemon=True,
                             name="broker-cancelar").start()
        try:
            # `raise` and not `assert`: with `python -O` the assert goes away and the `for` below
            # would blow up with `TypeError: 'NoneType' is not iterable`, which tells nothing to
            # whoever reads the log of a failed installation. Same design as the panel's
            # `ssh.no_stdout`.
            if proc.stdout is None:
                raise InstallError(f"{argv[0]}: nao consegui ler a saida do processo")
            for line in proc.stdout:
                if on_line is not None:
                    on_line(line.rstrip("\r\n"))
            return proc.wait()
        finally:
            clock.cancel()
            if proc.poll() is None:
                proc.kill()


def _kill_on_cancel(proc: subprocess.Popen, cancel: threading.Event) -> None:
    while proc.poll() is None:
        if cancel.wait(CANCEL_POLL):
            proc.kill()
            return


@dataclass(frozen=True)
class SteamAccount:
    """Steam account the broker uses for a game that does not download anonymously (DayZ).

    It must be an account DEDICATED to servers and without Steam Guard: the first login of each
    new CT happens minutes after the request, and there is nobody to type a code there.
    """

    user: str
    # Kept out of the repr: the configuration shows up in tracebacks and debug logs.
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        # Message without the value: it goes to the journal when the broker starts.
        if not _STEAM_USER_RE.fullmatch(self.user):
            raise ValueError("usuario: so letras, numeros e . _ @ - (2 a 64)")
        if not _STEAM_PASS_RE.fullmatch(self.password):
            raise ValueError("senha: sem espaco e sem aspa simples (a linha do SteamCMD as quebraria)")


@dataclass(frozen=True)
class ConfigSsh:
    private_key: Path
    public_key: str          # full line of the broker key, the one injected into the CT
    lib_dir: Path             # where ct-install.sh and ct-phases.sh are
    user: str = "root"
    ssh_wait: float = 180.0
    interval: float = 3.0
    install_timeout: float = 7200.0
    command_timeout: float = 120.0
    steam: SteamAccount | None = None
    # Who may open SSH to the CT after installation (panel and broker): becomes FW_MGMT_SOURCES of
    # the firewall inside the CT. Empty = the CT is born WITHOUT a firewall (and the installer warns).
    firewall_sources: tuple[str, ...] = ()
    # The PANEL key. It no longer goes into root through Proxmox: it travels in install.env and
    # ct-phases.sh installs it for the unprivileged `gamepanel` user. Empty = the CT is born
    # without panel access and root is not locked (there would be nobody left to get in).
    panel_public_key: str = ""

    def __post_init__(self) -> None:
        parts = self.public_key.split()
        if len(parts) < 2 or not _BLOB_RE.fullmatch(parts[1]):
            raise ValueError("public_key: esperada uma linha de chave publica OpenSSH")
        if self.panel_public_key:
            panel = self.panel_public_key.split()
            # No newline and no quote: it is written into authorized_keys and passed inside a
            # single-quoted command line in the CT.
            if (len(panel) < 2 or not _BLOB_RE.fullmatch(panel[1])
                    or any(c in self.panel_public_key for c in "\n\r'")):
                raise ValueError("panel_public_key: esperada uma linha de chave publica OpenSSH")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", self.user):
            raise ValueError("user: nome de conta invalido")

    @property
    def blob(self) -> str:
        return self.public_key.split()[1]


def build_env(game: Game, ports: Sequence[AllocatedPort], steam: SteamAccount | None = None,
              firewall_sources: Sequence[str] = (), panel_public_key: str = "") -> str:
    """The CT's `install.env`. Every value quoted: it is DATA, never a command."""
    if game.needs_account and steam is None:
        # The catalog already does not offer the game without an account; this is the second
        # door, for a request that arrives between a configuration change and the catalog reload.
        raise InstallError(f"{game.name} exige conta Steam e o broker nao tem STEAM_USER/STEAM_PASS")
    runtimes = [r for r in game.recipes if r in RECIPES_WINDOWS]
    if len(runtimes) > 1:
        raise InstallError("escolha 'wine' OU 'proton', nao os dois")
    # Internal port == external (see services/allocator.py): the game is told the ports ALREADY allocated.
    game_port = port_with_role(ports, ROLE_GAME) or game.game_port
    query_port = (port_with_role(ports, ROLE_QUERY) or game.query_port) if game.query_port else 0
    extra_port = (port_from_base(ports, game.extra_port) or game.extra_port) if game.extra_port else 0
    variables = {
        "GAME_KEY": game.key, "GAME_DISPLAY_NAME": game.name, "STEAM_APP_ID": str(game.app_id),
        "STEAM_PLATFORM": game.platform, "STEAM_ANONYMOUS": "0" if game.needs_account else "1",
        "START_SCRIPT": game.start_script, "START_ARGS": game.start_args,
        "GAME_PORT": str(game_port), "QUERY_PORT": str(query_port), "EXTRA_PORT": str(extra_port),
        "GAME_PORTS": " ".join(str(p) for p in ports),
        "WINDOWS_RUNTIME": runtimes[0] if runtimes else "",
        "WINDOWS_RUNTIME_XVFB": "1" if RECIPE_XVFB in game.recipes else "0",
        # vulkan stays in RECIPES: apply_recipes in ct-phases.sh installs the driver.
        "RECIPES": " ".join(r for r in game.recipes if r not in (*RECIPES_WINDOWS, RECIPE_XVFB)),
        # Shell only exists in the curated catalog, reviewed in git; a game registered via the API comes empty.
        "PRE_INSTALL_CMD": game.pre_install, "POST_INSTALL_CMD": game.post_install,
    }
    if game.client_app_id:
        # Only when set: an empty value would still reach /etc/game-runtime.env, harmlessly,
        # but the install.env of every other game would change for nothing.
        variables["CLIENT_APP_ID"] = str(game.client_app_id)
    if game.wine_overrides:
        # Only when the curated .env says so: without it, ct-phases.sh applies its own default.
        variables["WINE_DLL_OVERRIDES"] = game.wine_overrides
    variables.update(_access_variables(firewall_sources, panel_public_key))
    if game.needs_account and steam is not None:
        # Only for whoever needs it: an anonymous game has no reason to carry the password to the CT.
        variables["STEAM_USER"] = steam.user
        variables["STEAM_PASS"] = steam.password
    return "".join(f"{name}={shlex.quote(value)}\n" for name, value in variables.items())


def _access_variables(firewall_sources: Sequence[str], panel_public_key: str) -> dict[str, str]:
    """Who gets into the CT afterwards: the firewall sources and the panel key, each only when set."""
    variables: dict[str, str] = {}
    if panel_public_key:
        # ct-phases.sh (setup_panel_access) creates `gamepanel` with this key; without it the CT
        # has no panel access at all, as before.
        variables["PANEL_PUBKEY"] = panel_public_key
    if firewall_sources:
        variables["FW_MGMT_SOURCES"] = " ".join(firewall_sources)
    return variables


def _masking(log: Callable[[str], None], secret: str) -> Callable[[str], None]:
    return lambda text: log(text.replace(secret, "******"))


class _Batch:
    """Batches lines to write to the log in blocks: SteamCMD dumps thousands, and each write
    is a database transaction."""

    def __init__(self, log: Callable[[str], None], now: Callable[[], float]):
        self._log, self._now = log, now
        self._lines: list[str] = []
        self._last_at = now()
        self.cauda: list[str] = []
        self.concluida = False

    def line(self, text: str) -> None:
        text = text.strip()[:MAX_LINE]
        if not text:
            return
        if SUCCESS_MARK in text:
            self.concluida = True
        self.cauda = [*self.cauda, text][-ERROR_TAIL:]
        self._lines.append(text)
        if len(self._lines) >= LINE_BATCH or self._now() - self._last_at >= BATCH_SECONDS:
            self.flush()

    def flush(self) -> None:
        if self._lines:
            self._log("\n".join(self._lines))
            self._lines = []
        self._last_at = self._now()


class SshInstaller:
    def __init__(self, config: ConfigSsh, executor: Executor | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], float] = time.monotonic):
        self._cfg = config
        self._exec = executor or ExecutorReal()
        self._sleep = sleep
        self._now = now
        missing_ones = [a for a in LIB_FILES if not (config.lib_dir / a).is_file()]
        if missing_ones:
            raise ValueError(f"faltam em {config.lib_dir}: {', '.join(missing_ones)}")

    # --- commands ------------------------------------------------------------------------

    def _options(self) -> list[str]:
        # A newly created CT has a new key: there is no known host key, and the IP is reused
        # after the instance is removed (a fixed known_hosts would reject the next CT).
        return ["-i", str(self._cfg.private_key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10"]

    def _ssh(self, target: str, command: str) -> list[str]:
        return ["ssh", *self._options(), target, command]

    def _target(self, ip: str) -> str:
        return f"{self._cfg.user}@{ip}"

    # --- flow -----------------------------------------------------------------------------------

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None], cancel: threading.Event | None = None) -> None:
        ip = str(ipaddress.IPv4Address(ip))
        target = self._target(ip)
        env = build_env(game, ports, self._cfg.steam, self._cfg.firewall_sources,
                        self._cfg.panel_public_key)
        if game.needs_account and self._cfg.steam is not None:
            # Second defense: ct-install.sh already masks the password in errors, but the CT's whole
            # output becomes the operation log, which the panel shows and keeps in the history.
            log = _masking(log, self._cfg.steam.password)
        self._wait_for_ssh(target, ip, log, cancel)
        failure: Exception | None = None
        try:
            self._send(target, env)
            self._install(target, log, cancel)
        except Exception as error:
            failure = error
            raise
        finally:
            self._cleanup(target, log, failure)

    def _wait_for_ssh(self, target: str, ip: str, log: Callable[[str], None],
                      cancel: threading.Event | None = None) -> None:
        log(f"aguardando o SSH de {ip}")
        limit = self._now() + self._cfg.ssh_wait
        while True:
            if cancel is not None and cancel.is_set():
                raise InstallError("instalacao cancelada")
            if self._exec.run(self._ssh(target, "true"), None, 20) == 0:
                return
            if self._now() >= limit:
                raise InstallError(f"o SSH de {ip} nao respondeu em {int(self._cfg.ssh_wait)} s")
            self._sleep(self._cfg.interval)

    def _send(self, target: str, env: str) -> None:
        folder = shlex.quote(REMOTE_DEST)
        self._command(self._ssh(target, f"install -d -m 700 {folder}"), "criar a pasta no CT")
        with tempfile.TemporaryDirectory(prefix="broker-install-") as tmp:
            env_file = Path(tmp) / "install.env"
            env_file.write_text(env, encoding="utf-8", newline="\n")
            sources = [str(self._cfg.lib_dir / a) for a in LIB_FILES] + [str(env_file)]
            self._command(["scp", *self._options(), *sources, f"{target}:{REMOTE_DEST}/"],
                          "enviar o instalador ao CT")

    def _command(self, argv: Sequence[str], action: str) -> None:
        code = self._exec.run(argv, None, self._cfg.command_timeout)
        if code != 0:
            raise InstallError(f"falhou ao {action} (codigo {code})")

    def _install(self, target: str, log: Callable[[str], None],
                 cancel: threading.Event | None = None) -> None:
        batch = _Batch(log, self._now)
        command = f"cd {shlex.quote(REMOTE_DEST)} && bash ct-install.sh install.env"
        code = self._exec.run(self._ssh(target, command), batch.line, self._cfg.install_timeout,
                              cancel=cancel)
        batch.flush()
        if cancel is not None and cancel.is_set():
            raise InstallError("instalacao cancelada")
        if code != 0:
            summary = " | ".join(batch.cauda)
            raise InstallError(f"a instalacao falhou (codigo {code}): {summary}")
        if not batch.concluida:
            raise InstallError("o instalador terminou sem confirmar a conclusao")

    def _cleanup(self, target: str, log: Callable[[str], None], failure: Exception | None) -> None:
        """Deletes what was sent, locks root and removes the broker key. ALWAYS runs.

        The root lock (lib/ct-panel-access.sh `lock`: sshd refuses root, only `gamepanel` gets in)
        lives in THIS command because it is the last root SSH session the CT will ever see: a
        separate command after the key removal would have no way in. The piece checks first that
        `gamepanel` reaches steam and the helpers, and locks nothing otherwise. Only after a
        successful install: a failed one may not even have created `gamepanel`, and the CT is
        about to be undone anyway. The sshd reload keeps this session alive.
        """
        blob = self._cfg.blob
        file = "/root/.ssh/authorized_keys"
        key_removal = (f"rm -rf {shlex.quote(REMOTE_DEST)}; "
                       f"grep -vF -- {shlex.quote(blob)} {file} > {file}.tmp; "
                       f"cat {file}.tmp > {file}; rm -f {file}.tmp; "
                       f"! grep -qF -- {shlex.quote(blob)} {file}")
        lock = failure is None and bool(self._cfg.panel_public_key)
        command = key_removal
        if lock:
            # The key comes out EVEN when the lock fails (a CT must not keep broker access); the
            # exit code then says which of the two went wrong.
            command = (f"lock_rc=0; bash {PANEL_ACCESS_IN_CT} lock || lock_rc={LOCK_FAILED}; "
                       f"{key_removal} && exit $lock_rc")
        # With the lock, its lines (what failed in the check) go to the operation log.
        code = self._exec.run(self._ssh(target, command), log if lock else None,
                              self._cfg.command_timeout)
        if code == 0:
            log("chave do broker removida do container")
            return
        if lock and code == LOCK_FAILED:
            raise InstallError("a chave do broker saiu, mas nao consegui trancar o root do container: "
                               "o acesso pelo usuario gamepanel nao passou na verificacao")
        message = f"nao consegui remover a chave do broker do container (codigo {code})"
        if failure is None:
            raise InstallError(message)
        # There is already a more important error to report; the failed cleanup is only recorded.
        log(f"AVISO: {message}")
