"""Listen to the game log live, so that log-based counting is not slow.

Log-based counting was the only case with no way to be fast: each check is an SSH round
trip that drags the whole log, so asking every 15 seconds would cost megabytes per minute
to find two lines. The way out is to stop asking: a long SSH connection with
`journalctl -f` leaves the panel LISTENING, and the line arrives the second it is written.

The point of the design: the stream is a TRIGGER, not a second count. It only says
"something happened" and asks for the count to be redone the usual way. Reproducing the
log state machine here would be a second place to get it wrong - and worse, one that
would silently diverge from the number the screen shows.
"""
from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any, NamedTuple

from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.log_probe import (
    LOG_FOLLOW_SCRIPT,
    LOG_LINE_MAX,
    compile_pattern,
    valid_log_path,
)
from gamepanel.runtime.ssh import ServerLike

PLAYER_EVENTS = frozenset({"jogador-entrou", "jogador-saiu"})
SHUTDOWN_WAIT = 5


class LogStreamDeps(NamedTuple):
    """What a log connection needs from the rest of the panel.

    The thread lives OUTSIDE the request context, so nothing here can come from Flask's
    `g`: the database connection is opened by `connect` and closed in the same round.
    """

    ssh_argv: Callable[..., list[str]]
    # The SAME dict as the monitor's: both write to the same server's state.
    monitor_state: dict[int, dict]
    invalidate_players: Callable[[int], None]
    connect: Callable[[], sqlite3.Connection]
    webhook_config: Callable[[Any], dict]
    players_lock: Callable[[int], threading.Lock]
    players_alert: Callable[..., None]
    logger: logging.Logger
    debounce: float
    retry: float


def player_line(line: str, enter: re.Pattern[str] | None,
                     leave: re.Pattern[str] | None) -> bool:
    """Is this log line a player joining or leaving?"""
    short_label = line[:LOG_LINE_MAX]
    if enter and enter.search(short_label):
        return True
    return bool(leave and leave.search(short_label))


def stream_signature(server: ServerLike,
                         stored_value: Callable[[ServerLike, str], str]) -> tuple:
    """What, when it changes, forces the connection to be redone (new regex, log moved...)."""
    return (
        server["host"], int(server["ssh_port"] or 22), server["ssh_user"],
        server["service"], stored_value(server, "log_path"),
        stored_value(server, "join_re"), stored_value(server, "leave_re"),
    )


def wanted_streams(servers: Iterable[ServerLike], cfg: dict, enabled: bool,
                      player_source: Callable[[ServerLike], str],
                      stored_value: Callable[[ServerLike, str], str]) -> dict[int, tuple]:
    """Which servers deserve an open log connection, and with which signature."""
    if not (enabled and cfg["events"] & PLAYER_EVENTS):
        return {}
    # Only those counting by log: A2S and HTTP already answer for free on the short round,
    # and opening a permanent connection for them would be paying for nothing.
    return {int(s["id"]): stream_signature(s, stored_value) for s in servers
            if player_source(s) == "log" and stored_value(s, "join_re")}


class LogStream:
    """A long SSH connection listening to the log of ONE server."""

    def __init__(self, deps: LogStreamDeps, server: ServerLike, signature: tuple) -> None:
        self.deps = deps
        # A Row does not cross threads (it belongs to the request's connection): copy it.
        self.data = dict(server)
        self.sid = int(server["id"])
        self.signature = signature
        self.proc: subprocess.Popen | None = None
        self._stop_signal = threading.Event()
        self.last_fire = 0.0
        self.error = ""
        # A configuration error (regex that does not compile, invalid log path) is not
        # fixed by retrying. Without this flag the supervisor would recreate the thread every
        # round only for it to die the same way - a loop that just fills the log with errors.
        self.gave_up = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop_signal.set()
        proc = self.proc
        if proc and proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self) -> None:
        while not self._stop_signal.is_set():
            try:
                self._follow()
            # The thread does not die from one stumble.
            except Exception as exc:
                self.error = str(exc)
                self.deps.logger.exception("o acompanhamento de log de '%s' caiu",
                                           self.data.get("name"))
            # A server that is off must not turn into one SSH loop per second.
            if self._stop_signal.wait(self.deps.retry):
                return

    def _give_up(self, motivo: str) -> None:
        self.error = motivo
        self.gave_up = True
        self._stop_signal.set()

    def _follow(self) -> None:
        # A broken registration stops here: reconnecting against a regex that does not
        # compile is pointless.
        try:
            enter = compile_pattern(self.data.get("join_re"), "pattern.join")
            leave = compile_pattern(self.data.get("leave_re"), "pattern.leave")
            target = valid_log_path(self.data.get("log_path") or "")
        except (QueryError, ValueError) as exc:
            return self._give_up(str(exc))
        if not enter:
            return self._give_up("sem padrao de entrada, nao ha o que ouvir")
        # No multiplexing: this connection stays up for hours, and the shared master exists
        # precisely for the monitor's short calls.
        argv = [
            *self.deps.ssh_argv(
                self.data, connect_timeout=10,
                extra=("-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3"),
            ),
            # The journal is read through the systemd-journal group, the log file is the game's
            # (world-readable): the same command in both modes.
            remote_cmd.unprivileged("bash", "-lc", LOG_FOLLOW_SCRIPT, "gp", self.data["service"], target),
        ]
        self.proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv comes from SshClient
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", bufsize=1,
        )
        # Kept in a local variable: `self.proc.stdout` is Optional (Popen without PIPE has
        # no output), and this is where the loop that reads for hours comes from.
        output = self.proc.stdout
        if output is None:
            return self._give_up("nao consegui abrir a saida do ssh")
        self.error = ""
        try:
            for line in output:
                if self._stop_signal.is_set():
                    break
                if player_line(line, enter, leave):
                    self._check()
        finally:
            self.stop_proc()
        return None

    def stop_proc(self) -> None:
        proc, self.proc = self.proc, None
        if not proc:
            return
        for stream_of in (proc.stdout, proc.stderr):
            if stream_of:
                with contextlib.suppress(OSError):
                    stream_of.close()
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()
        try:
            proc.wait(timeout=SHUTDOWN_WAIT)  # without this a zombie is left on each reconnect
        except subprocess.TimeoutExpired:
            proc.kill()

    def _check(self) -> None:
        """The line arrived: redo the count the normal way and alert if it changed."""
        now_ts = time.monotonic()
        if now_ts - self.last_fire < self.deps.debounce:
            return                     # a group joining together is ONE check
        self.last_fire = now_ts
        previous = self.deps.monitor_state.get(self.sid)
        if previous is None:
            return                     # no baseline yet: the monitor round does it
        # The cache holds the number from BEFORE the line that just arrived.
        self.deps.invalidate_players(self.sid)
        conn = self.deps.connect()     # this thread lives outside the request context
        try:
            cfg = self.deps.webhook_config(conn)
            with self.deps.players_lock(self.sid):
                self.deps.players_alert(conn, self.data,
                                              previous.get("service", ""), previous, cfg)
        finally:
            conn.close()


class Supervisor:
    """The registry of open connections: starts, stops and revives them.

    `create` comes from outside (instead of being `LogStream` directly) because the
    supervisor test swaps the class for a double that only records open/close - no SSH.
    """

    def __init__(self, create: Callable[[ServerLike, tuple], Any]) -> None:
        self._create = create
        self.open_ones: dict[int, Any] = {}
        self._lock = threading.Lock()

    def alive_ids(self) -> int:
        """How many connections are really listening now (so the screen does not lie)."""
        with self._lock:
            return sum(1 for s in self.open_ones.values() if s.alive())

    def sync(self, servers: Sequence[ServerLike],
                   desejados: dict[int, tuple]) -> int:
        """Make what is open match `desejados`. Returns how many remain."""
        by_id = {int(s["id"]): s for s in servers}

        with self._lock:
            current_ones = list(self.open_ones.items())
        for sid, stream in current_ones:
            # Drop those no longer wanted and those whose configuration changed (new regex,
            # log at another path). A dead thread is dropped too, so the step below brings
            # it back up - except when it gave up over an invalid registration, which
            # recreating does not fix: that one stays as a tombstone until someone fixes
            # the registration and the signature changes.
            swapped = sid not in desejados or desejados[sid] != stream.signature
            if swapped or (not stream.alive() and not stream.gave_up):
                stream.stop()
                with self._lock:
                    self.open_ones.pop(sid, None)

        for sid, signature in desejados.items():
            with self._lock:
                if sid in self.open_ones:
                    continue
                fresh = self._create(by_id[sid], signature)
                self.open_ones[sid] = fresh
            fresh.start()

        with self._lock:
            return len(self.open_ones)
