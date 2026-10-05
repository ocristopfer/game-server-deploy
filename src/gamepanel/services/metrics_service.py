"""The container's CPU, memory, disk and network, with a short cache.

The remote script and the parsing of the numbers live in `runtime.metrics_probe`; what
is left here is the decision: when it is worth reusing the previous reading, and what the
screen gets when the container does not answer.

Each reading costs an SSH trip of ~1s (two samples spaced apart inside the container).
Without the cache, three tabs open on the same screen become three SSH sessions per
second on the same server.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gamepanel.runtime import metrics_probe, remote_cmd
from gamepanel.runtime.ssh import RemoteError, ServerLike

# (server, command, timeout) -> output; RemoteError when the SSH trip fails.
SshOutput = Callable[..., str]

_metrics_cache: dict[int, tuple[float, dict]] = {}
_metrics_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    with _metrics_lock:
        _metrics_cache.pop(int(server_id), None)


def server_metrics(ssh_output: SshOutput, server: ServerLike, dir_padrao: str, ttl: float,
                   force: bool = False) -> dict:
    """The container's CPU, memory, disk and network usage."""
    key = int(server["id"])
    now_ts = time.monotonic()
    if not force:
        with _metrics_lock:
            cached = _metrics_cache.get(key)
        if cached and now_ts - cached[0] < ttl:
            return cached[1]

    target = server["config_path"] or dir_padrao
    try:
        raw = ssh_output(
            server,
            # /proc, the cgroup files and `df` are world-readable: no right needed in either mode.
            remote_cmd.unprivileged("bash", "-lc", metrics_probe.METRICS_SCRIPT, "gp", server["service"], target),
            timeout=30,
        )
        data = metrics_probe.parse_metrics(raw)
        data["error"] = ""
    except RemoteError as exc:
        data = {"error": str(exc)}

    with _metrics_lock:
        _metrics_cache[key] = (now_ts, data)
    return data
