"""Sessao de terminal interativo: um `ssh -tt` preso a um PTY local.

O navegador nao fala com o PTY direto - empurra teclas por POST e puxa a saida por
long-poll, dizendo por um offset em bytes o que ja leu. Sem WebSocket de proposito: o
painel roda em gunicorn com workers sync, que nao os suporta.

So existe em POSIX (o PTY nao tem equivalente no Windows); `HAVE_PTY` avisa quem chama.
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

from gamepanel.runtime.ssh import RemoteError, ServerLike

try:
    import fcntl
    import pty
    import signal
    import termios

    HAVE_PTY = True
except ImportError:  # pragma: no cover - Windows
    HAVE_PTY = False

# server, extra=(...) -> argv do ssh (ver SshClient.argv).
SshArgv = Callable[..., list[str]]


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


def _become_tty_leader() -> None:
    """Roda no filho, entre fork e exec: sessao nova + PTY como terminal de controle.

    Sem o TIOCSCTTY o ssh enxerga um terminal que nao e o dele e recusa o modo raw, e o
    teclado passa a chegar em blocos de linha em vez de tecla a tecla.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


class TermSession:
    """Uma sessao SSH interativa viva: um `ssh -tt` amarrado a um PTY local."""

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
        self._base = 0  # offset absoluto do primeiro byte ainda guardado

        self.master, slave = pty.openpty()
        try:
            _set_winsize(self.master, cols, rows)
            argv = ssh_argv(
                server,
                extra=("-tt", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3"),
            )
            # Ambiente minimo e explicito: e o TERM daqui que decide os codigos que o
            # emulador do navegador vai ter de entender.
            env = {
                "TERM": "xterm-256color",
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                # O ssh so usa o HOME para procurar ~/.ssh, e aqui a chave e o
                # known_hosts vao explicitos; a pasta de dados serve de porto seguro.
                "HOME": os.environ.get("HOME") or os.path.dirname(known_hosts),
                "LANG": "C.UTF-8",
            }
            self.proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv vem do SshClient, nunca cru de formulario
                argv, stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, preexec_fn=_become_tty_leader, env=env,
            )
        except OSError as exc:
            os.close(self.master)
            raise RemoteError(f"falha ao abrir a sessao: {exc}") from exc
        finally:
            os.close(slave)

        threading.Thread(target=self._reader, daemon=True).start()

    # -- saida ------------------------------------------------------------
    def _reader(self) -> None:
        while True:
            try:
                chunk = os.read(self.master, 65536)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:  # PTY fechou = ssh terminou
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
        """Devolve (dados, novo_offset, perdeu_bytes) esperando ate `wait` por novidade."""
        deadline = time.monotonic() + wait
        while True:
            with self._lock:
                end = self._base + len(self._buf)
                start = max(offset, self._base)
                if start < end:
                    data = bytes(self._buf[start - self._base:])
                    return data, start + len(data), start > offset
                # Sem novidade: limpa o sinal ainda com o lock para nao perder um
                # append que aconteca entre a checagem e o wait().
                self._wake.clear()
            remaining = deadline - time.monotonic()
            if not self.alive or remaining <= 0:
                return b"", max(offset, self._base), False
            self._wake.wait(timeout=min(1.0, remaining))

    # -- entrada e controle ------------------------------------------------
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
        # ProcessLookupError (subclasse de OSError) quando o ssh ja morreu sozinho.
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(self.proc.pid), signal.SIGHUP)
        with contextlib.suppress(OSError):
            os.close(self.master)
        self._wake.set()
