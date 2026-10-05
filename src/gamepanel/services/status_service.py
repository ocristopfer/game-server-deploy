"""Is it up? The state of the game service inside the container, with a short cache.

`systemctl show` instead of `is-active` because the same SSH trip already brings what
tells "I stopped it" apart from "it broke" (Result) and the automatic restart counter
(NRestarts). Without it a crash loop is invisible: between one crash and the next
`is-active` answers 'active' and the panel never sees a thing.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import RemoteError, ServerLike

# (server, command) -> output; RemoteError when the SSH trip fails.
SshOutput = Callable[..., str]

# Process cache, shared with whoever publishes these names in `app.py`: the same screen
# asks for the state several times per second (list, gauge, tab open next to it).
_status_cache: dict[int, tuple[float, dict]] = {}
_status_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    with _status_lock:
        _status_cache.pop(int(server_id), None)


def _systemctl_fields(ssh_output: SshOutput, server: ServerLike) -> dict[str, str]:
    # It exits with 0 even for a unit that does not exist, so no '|| true' is needed.
    # `systemctl show` reads the unit over D-Bus with no right at all, in either mode.
    raw = ssh_output(server, remote_cmd.unprivileged(
        "systemctl", "show", server["service"],
        "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "Result",
    ))
    fields = {}
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def server_status(ssh_output: SshOutput, server: ServerLike, ttl: float,
                  force: bool = False) -> dict:
    key = int(server["id"])
    now = time.monotonic()
    if not force:
        with _status_lock:
            cached = _status_cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]

    state = {"reachable": False, "service": "desconhecido", "error": "",
             "sub": "", "restarts": 0, "result": ""}
    try:
        fields = _systemctl_fields(ssh_output, server)
        state["reachable"] = True
        state["service"] = fields.get("ActiveState") or "inactive"
        state["sub"] = fields.get("SubState", "")
        state["result"] = fields.get("Result", "")
        # NRestarts only exists on systemd >= 235; without it the restart loop cannot be
        # detected and the panel simply does not alert on that event for this server.
        try:
            state["restarts"] = int(fields.get("NRestarts", "0") or 0)
        except ValueError:
            state["restarts"] = 0
    except RemoteError as exc:
        state["error"] = str(exc)
        state["service"] = "inacessivel"

    with _status_lock:
        _status_cache[key] = (now, state)
    return state
