"""Counts players by reading the game log over SSH, for games that publish neither A2S nor
an HTTP API (RuneScape Dragonwilds, for example). The panel replays the join/leave
events since the service's last start and sees who is left.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.ssh import ServerLike

LOG_SCAN_MAX = 20000
RE_MAX_LEN = 300
# Words that commonly appear in join/leave lines - used only by the wizard that helps
# discover the game's pattern.
LOG_HINT_WORDS = (
    "join", "joined", "left", "leave", "connect", "disconnect", "login", "logout",
    "player", "jogador", "entrou", "saiu",
)
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")
# A giant line (stack trace) must not get expensive in the regex.
LOG_LINE_MAX = 500

# Path of the log file. The '*' is allowed (DayZ opens one .ADM per session), but nothing
# the container's shell would interpret as something else: no spaces, quotes, $, ; or &.
LOG_PATH_RE = re.compile(r"^/[A-Za-z0-9._*?/-]{1,200}$")

# Reads from the service start onward: events from earlier runs would count players
# who left long ago.
# $3 = log file path (may contain *). Empty falls back to the service's journalctl.
# Follows the log and keeps emitting new lines while the SSH session is up. `-n 0`/`tail -n
# 0` on purpose: the past does not matter here: the regular count is what says who is
# online now, and this script only signals that something HAPPENED. That way the panel
# does not have to replicate the log state machine in two different places.
LOG_FOLLOW_SCRIPT = r"""
set -u
unit=$1
alvo=${2:-}

if [ -n "$alvo" ]; then
  # Unquoted so the shell expands the '*' - the panel LOG_PATH_RE guarantees there is
  # no space, quote, $ or ';' in here.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  # -F (not -f) to survive log rotation.
  exec tail -n 0 -F -- "$arq"
fi

exec journalctl -u "$unit" -n 0 -f -o short-iso --no-pager
"""

LOG_PLAYERS_SCRIPT = r"""
set -u
unit=$1
max=$2
alvo=${3:-}

if [ -n "$alvo" ]; then
  # $alvo is UNQUOTED on purpose, so the container shell expands the '*'. What makes
  # this safe is the panel LOG_PATH_RE, which only lets through an absolute path
  # with letters, digits, . _ - / * ? - no spaces, quotes, $ or ;.
  arq=$(ls -1t $alvo 2>/dev/null | head -n 1)
  [ -n "$arq" ] || { echo "nenhum arquivo de log casa com $alvo" >&2; exit 3; }
  [ -r "$arq" ] || { echo "sem permissao de leitura em $arq" >&2; exit 4; }
  tail -n "$max" -- "$arq"
  exit 0
fi

inicio=$(systemctl show -p ActiveEnterTimestamp --value "$unit" 2>/dev/null || true)
if [ -n "$inicio" ]; then
  journalctl -u "$unit" --since "$inicio" --no-pager -o short-iso 2>/dev/null | tail -n "$max"
else
  journalctl -u "$unit" --no-pager -o short-iso -n "$max" 2>/dev/null
fi
"""


def compile_pattern(raw: str | None, label: str) -> re.Pattern[str] | None:
    """Compiles a pattern coming from the screen; returns None when it is empty."""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) > RE_MAX_LEN:
        raise QueryError(Message("pattern.too_long", label=Message(label),
                                      n=RE_MAX_LEN))
    try:
        return re.compile(text)
    except re.error as exc:
        raise QueryError(Message("pattern.invalid", label=Message(label),
                                      reason=exc)) from exc


def _log_timestamp(line: str) -> str:
    m = TS_RE.match(line)
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _events_by_name(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Both patterns capture (?P<name>...): it is possible to tell WHO is online."""
    online: dict[str, str] = {}
    for line in lines:
        short = line[:LOG_LINE_MAX]
        entered = enter.search(short)
        if entered:
            name = (entered.groupdict().get("name") or "").strip()
            if name:
                online[name] = _log_timestamp(line)
            continue
        left = leave.search(short) if leave else None
        if left:
            online.pop((left.groupdict().get("name") or "").strip(), None)
    return {
        "players": len(online),
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in online.items()],
    }


def _events_by_count(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """No name on leave (many Unreal servers only report that someone left):
    all that is left is adding the joins and subtracting the leaves."""
    total = 0
    for line in lines:
        short = line[:LOG_LINE_MAX]
        if enter.search(short):
            total += 1
        elif leave and leave.search(short):
            total = max(0, total - 1)
    return {"players": total, "list": []}


def _events_half_named(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Named join, unnamed leave - the Satisfactory case.

    The log says someone left, but not who. The COUNT stays the same as before (joins
    minus leaves, exact); the list shows the most recent joiners, as many as the count
    says. It is a guess, and the screen says so - but throwing the names away, which is
    what the panel used to do, helped nobody.
    """
    total = 0
    order: list[tuple[str, str]] = []
    for line in lines:
        short = line[:LOG_LINE_MAX]
        entered = enter.search(short)
        if entered:
            total += 1
            name = (entered.groupdict().get("name") or "").strip()
            if name:
                # A reconnect goes back to the end of the queue instead of duplicating.
                order = [p for p in order if p[0] != name]
                order.append((name, _log_timestamp(line)))
            continue
        if leave and leave.search(short):
            total = max(0, total - 1)
            if order:
                order.pop(0)  # the longest-present one leaves: the least bad guess
    approximate_list = order[-total:] if total else []
    return {
        "players": total,
        "list": [{"name": n, "since": t, "score": 0, "seconds": 0} for n, t in approximate_list],
        "aproximado": True,
    }


def apply_log_events(lines: list[str], enter: re.Pattern[str], leave: re.Pattern[str] | None) -> dict[str, Any]:
    """Replays the log events in order and returns who is left.

    Three cases, from best to worst: name on both sides (we know who is online), name
    only on join (we know how many, and probably who), name nowhere (only the count).
    """
    if not enter.groupindex.get("name"):
        return _events_by_count(lines, enter, leave)
    if not leave or leave.groupindex.get("name"):
        return _events_by_name(lines, enter, leave)
    return _events_half_named(lines, enter, leave)


def valid_log_path(raw: str | None) -> str:
    """Checks the log path before it goes into a remote command."""
    path = (raw or "").strip()
    if not path:
        return ""
    if not LOG_PATH_RE.match(path) or ".." in path:
        raise ValueError(
            "caminho de log invalido - use um caminho absoluto, sem espacos"
            " (o '*' e permitido, ex.: /opt/game/profiles/*.ADM)"
        )
    return path


SshOutput = Callable[[ServerLike, str, int], str]


def read_log_lines(
    ssh_output: SshOutput, server: ServerLike, service: str, log_path: str, limit: int = LOG_SCAN_MAX,
) -> list[str]:
    """Log lines: from a file, when the server has one; otherwise from journalctl.

    The limit is a parameter because the two uses need very different sizes: the player
    count needs the whole history since startup (who joined and did not leave), and the
    error scan only wants the tail of the log, minute by minute.
    """
    try:
        target = valid_log_path(log_path)
    except ValueError as exc:
        raise QueryError(str(exc)) from exc
    # journalctl through the systemd-journal group, the log file is world-readable: no right needed.
    command = remote_cmd.unprivileged("bash", "-lc", LOG_PLAYERS_SCRIPT, "gp", service, str(limit), target)
    raw = ssh_output(server, command, 60)
    return raw.splitlines()
