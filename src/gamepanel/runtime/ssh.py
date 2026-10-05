"""SSH transport layer: talks to the game container (LXC or Docker) by running the
system's `ssh`, never a Python SSH library - the panel container only has
`openssh-client` from apt, no pip.

Every remote command goes through here. `SshClient.run` is the only path: it receives the
command already built by `runtime.remote_cmd` (which decides, per server, whether it runs as
root, through a fixed sudo helper or as steam), never a raw argument coming from a form.
"""
from __future__ import annotations

import contextlib
import os
import shlex
import sqlite3
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# A registered server, as this layer needs to see it: either the SQLite row, or a dict
# copy of it (used by long tasks, which cannot carry a connection from another thread).
# Both answer `server["host"]`, which is all that matters here.
ServerLike = sqlite3.Row | Mapping[str, Any]


class RemoteError(RuntimeError):
    pass


def quote_command(*parts: str) -> str:
    return " ".join(shlex.quote(p) for p in parts)


@dataclass(frozen=True)
class SshConfig:
    """What the client needs to know to talk to ANY game container."""

    key: str
    known_hosts: str
    control_dir: str
    control_persist: str
    quick_timeout: int = 20


class SshClient:
    """One instance per panel (the key is the same for every game container).

    Takes the config as a FUNCTION, not a value: tests swap `SSH_CONTROL_DIR` etc. via
    `monkeypatch.setattr(panel, "SSH_CONTROL_DIR", ...)` at any moment, and every call
    here must see the latest value - a config captured once at import would leave that
    test swap with no effect at all (silently).
    """

    def __init__(self, config: Callable[[], SshConfig]) -> None:
        self._config_provider = config

    @property
    def _config(self) -> SshConfig:
        return self._config_provider()

    def _mux_argv(self) -> list[str]:
        """Options that make several calls share ONE TCP connection.

        Without this every monitor read pays TCP + key exchange + authentication + a new
        process - about 100ms on the LAN just to then run a 5ms `systemctl show`. With the
        master connection up, the second call onward costs almost nothing.

        %C is the hash of (host, port, user): a short, unique name per target, which
        matters because unix sockets have a low path length limit.
        """
        try:
            os.makedirs(self._config.control_dir, mode=0o700, exist_ok=True)
        except OSError:
            # With nowhere to put the socket, going on without reuse beats not speaking SSH.
            return []
        return ["-o", "ControlMaster=auto",
                "-o", f"ControlPath={os.path.join(self._config.control_dir, '%C')}",
                "-o", f"ControlPersist={self._config.control_persist}"]

    def argv(self, server: ServerLike, connect_timeout: int = 10,
              extra: tuple[str, ...] = (), multiplex: bool = False) -> list[str]:
        """Common ssh client arguments (used by the commands and by the terminal).

        `multiplex` only for the monitor's SHORT, frequent calls. It is off by default
        because the other three do not want to share a connection: the terminal holds the
        session for hours, and uploading/downloading a multi-GB file would clog the shared
        TCP and stall every monitor read behind the transfer.
        """
        return [
            "ssh",
            "-i", self._config.key,
            "-p", str(server["ssh_port"]),
            "-o", "BatchMode=yes",
            "-o", f"UserKnownHostsFile={self._config.known_hosts}",
            # accept-new: learns the host key on first access, but warns if it changes.
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={connect_timeout}",
            *(self._mux_argv() if multiplex else ()),
            *extra,
            f"{server['ssh_user']}@{server['host']}",
        ]

    def run(
        self,
        server: ServerLike,
        remote_cmd: str,
        timeout: int | None = None,
        stdin_data: bytes | None = None,
        multiplex: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a command in the game container over SSH.

        `remote_cmd` comes already built with shlex.quote by the caller's helpers; SSH
        hands it whole to the target's shell, so nothing here may come raw from a form.
        `stdin_data` feeds the remote command's input (used to write files).

        `multiplex=False` for slow work: a one-hour update would hold the master
        connection the whole time, and any hiccup in it would also take down the monitor
        reads riding along.
        """
        timeout = self._config.quick_timeout if timeout is None else timeout
        cmd = [*self.argv(server, connect_timeout=min(timeout, 10), multiplex=multiplex), remote_cmd]
        # Argument list (never shell=True) and `remote_cmd` always pre-quoted by the
        # caller's shlex.quote (see docstring) - it is not a raw command from a form.
        try:
            if stdin_data is not None:
                proc = subprocess.run(  # noqa: S603  # NOSONAR
                    cmd, input=stdin_data, capture_output=True, timeout=timeout, check=False
                )
                # Binary on input, text on output: error messages are always text.
                return subprocess.CompletedProcess(
                    proc.args,
                    proc.returncode,
                    proc.stdout.decode("utf-8", "replace"),
                    proc.stderr.decode("utf-8", "replace"),
                )
            return subprocess.run(  # noqa: S603  # NOSONAR
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            raise RemoteError(f"tempo esgotado ({timeout}s) executando no host {server['host']}") from None
        except OSError as exc:
            raise RemoteError(f"falha ao executar ssh: {exc}") from exc

    def output(self, server: ServerLike, remote_cmd: str, timeout: int | None = None) -> str:
        proc = self.run(server, remote_cmd, timeout=timeout)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RemoteError(detail or f"comando falhou (exit {proc.returncode})")
        return proc.stdout.strip()

    def forget_host(self, host: str, port: int = 22) -> None:
        """Remove from known_hosts the key the panel learned for `host`.

        Only for a caller that KNOWS the machine at that address is a different one: the
        broker just created a CT on an IP that used to belong to a removed CT. Without this,
        `accept-new` keeps the old CT's key and rejects the new one as an attack, and the
        freshly created server is born with no status, no console and nothing that goes
        over SSH.

        `ssh-keygen -R` rather than editing the file here: with `HashKnownHosts yes` (the
        Debian default) the line does not hold the IP in plain text, only a hash of it.

        Never raises: the caller is registering a server, and having nothing to delete (or
        no file yet) is the common case.
        """
        target = host if port == 22 else f"[{host}]:{port}"
        # Via PATH, like the `ssh` in `argv`: both come from the same openssh-client from apt.
        cmd = ["ssh-keygen", "-f", self._config.known_hosts, "-R", target]
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            # Argument list, and `host` already went through the caller's HOST_RE.
            subprocess.run(  # noqa: S603  # NOSONAR
                cmd, capture_output=True, timeout=self._config.quick_timeout, check=False)

    def public_key(self) -> str:
        try:
            with open(f"{self._config.key}.pub", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""
