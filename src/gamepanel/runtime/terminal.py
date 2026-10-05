"""Interactive terminal session: an `ssh -tt` attached to a local PTY.

The browser does not talk to the PTY directly - it pushes keys by POST and pulls the
output by long-poll, stating with a byte offset what it has already read. No WebSocket on
purpose: the panel runs on gunicorn with sync workers, which do not support them.

Only exists on POSIX (the PTY has no Windows equivalent); `HAVE_PTY` tells the caller.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import struct
import subprocess
import threading
import time
from collections.abc import Callable

from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import RemoteError, ServerLike

try:
    import fcntl
    import pty
    import signal
    import termios

    HAVE_PTY = True
except ImportError:  # pragma: no cover - Windows
    HAVE_PTY = False

# server, extra=(...) -> ssh argv (see SshClient.argv).
SshArgv = Callable[..., list[str]]


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def _become_tty_leader() -> None:
    """Runs in the child, between fork and exec: new session + PTY as controlling terminal.

    Without TIOCSCTTY ssh sees a terminal that is not its own and refuses raw mode, and
    keyboard input starts arriving in line blocks instead of key by key.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class TermSession:
    """A live interactive SSH session: an `ssh -tt` tied to a local PTY."""

    def __init__(
        self,
        ssh_argv: SshArgv,
        server: ServerLike,
        uid: int,
        username: str,
        cols: int,
        rows: int,
        *,
        known_hosts: str,
        buffer_bytes: int,
    ) -> None:
        self.id = secrets.token_urlsafe(24)
        self.uid = uid
        self.username = username
        self.server_id = int(server["id"])
        self.opened_at = time.time()
        self.last_seen = time.time()
        self.cols, self.rows = cols, rows
        self.alive = True
        self.exit_code: int | None = None
        self._buffer_bytes = buffer_bytes

        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._wake = threading.Event()
        self._buf = bytearray()
        self._base = 0  # absolute offset of the first byte still kept

        self.master, slave = pty.openpty()
        try:
            _set_winsize(self.master, cols, rows)
            argv = ssh_argv(
                server,
                extra=("-tt", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3"),
            )
            # Legacy mode: no command, ssh opens root's login shell as it always did. Helper
            # mode: a login shell of steam - the login user itself has nothing to do in there.
            shell = remote_cmd.interactive_shell(server)
            if shell is not None:
                argv = [*argv, shell]
            # Minimal, explicit environment: the TERM here decides which codes the
            # browser's emulator will have to understand.
            env = {
                "TERM": "xterm-256color",
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                # ssh only uses HOME to look for ~/.ssh, and here the key and the
                # known_hosts are passed explicitly; the data folder is a safe fallback.
                "HOME": os.environ.get("HOME") or os.path.dirname(known_hosts),
                "LANG": "C.UTF-8",
            }
            self.proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv comes from SshClient, never raw from a form
                argv, stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, preexec_fn=_become_tty_leader, env=env,
            )
        except OSError as exc:
            os.close(self.master)
            raise RemoteError(f"falha ao abrir a sessao: {exc}") from exc
        finally:
            os.close(slave)

        threading.Thread(target=self._reader, daemon=True).start()

    # -- output ------------------------------------------------------------
    def _reader(self) -> None:
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:  # PTY closed = ssh finished
                break
            with self._lock:
                self._buf += chunk
                excess = len(self._buf) - self._buffer_bytes
                if excess > 0:
                    del self._buf[:excess]
                    self._base += excess
            self._wake.set()
        try:
            self.exit_code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.exit_code = None
        self.alive = False
        self._wake.set()

    def read(self, offset: int, wait: float) -> tuple[bytes, int, bool]:
        """Return (data, new_offset, lost_bytes), waiting up to `wait` for something new."""
        deadline = time.monotonic() + wait
        while True:
            with self._lock:
                end = self._base + len(self._buf)
                start = max(offset, self._base)
                if start < end:
                    data = bytes(self._buf[start - self._base:])
                    return data, start + len(data), start > offset
                # Nothing new: clear the signal while still holding the lock so an append
                # happening between the check and wait() is not lost.
                self._wake.clear()
            remaining = deadline - time.monotonic()
            if not self.alive or remaining <= 0:
                return b"", max(offset, self._base), False
            self._wake.wait(timeout=min(1.0, remaining))

    # -- input and control -------------------------------------------------
    def write(self, data: bytes) -> None:
        with self._write_lock:
            while data:
                try:
                    sent = os.write(self.master, data)
                except (OSError, ValueError) as exc:
                    raise RemoteError(f"sessao encerrada: {exc}") from exc
                data = data[sent:]

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        with contextlib.suppress(OSError):
            _set_winsize(self.master, cols, rows)

    def close(self) -> None:
        self.alive = False
        # ProcessLookupError (an OSError subclass) when ssh already died on its own.
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGHUP)
        with contextlib.suppress(OSError):
            os.close(self.master)
        self._wake.set()
