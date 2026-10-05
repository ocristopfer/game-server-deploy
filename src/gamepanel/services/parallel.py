"""Asking several servers the same thing at the same time.

State, gauges and player count each cost one network trip per server. In series the
screen pays the sum, and with a container down, the sum of the timeouts. This used to be
the same thirty lines written three times (status, resources, players), each copy with a
different detail.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from gamepanel.runtime.ssh import ServerLike


def per_server(
    query: Callable[[ServerLike], dict],
    servers: Sequence[ServerLike],
    timeout: float,
    fallback: dict,
) -> dict[int, dict]:
    """Runs `query` for each server in parallel; returns {server id: answer}.

    Whoever did not come back within `timeout` gets a COPY of `fallback`: a copy, and not
    the same object under several keys, because the screen and the monitor write on top
    of what they receive, and a shared dict would make one server's note show up on another.
    """
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def work(srv: ServerLike) -> None:
        data = query(srv)
        with lock:
            results[int(srv["id"])] = data

    threads = [threading.Thread(target=work, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    for srv in servers:
        results.setdefault(int(srv["id"]), dict(fallback))
    return results
