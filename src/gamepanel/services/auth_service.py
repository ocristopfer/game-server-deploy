"""Attempt lockout: how many wrong tries fit in a window, and how long until it unlocks.

No Flask and no database. The state lives in the process MEMORY on purpose: the panel
runs with a single worker (see `provision-admin-lxc.sh`), and keeping this in the database
would cost one write per wrong attempt, which is exactly what an attack produces in volume.

Restarting the panel clears the lockouts. That is acceptable: whoever restarts it has
access to the container, and can already do more than this.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Lockout:
    """One lockout, with its own limit and its own window.

    Each login step has its own (password and code), rather than a single one with two
    limits: getting the password wrong five times must not use up the attempts of someone
    who is already past it and typing the code.
    """

    def __init__(self, tries: int, window: float,
                 clock: Callable[[], float] | None = None) -> None:
        self._tries = tries
        self._window = window
        # `clock=time.time` in the signature would look more direct and would BREAK the
        # tests: the default value is evaluated once, at definition time, and would keep the
        # original function, so the `monkeypatch.setattr(time, "time", ...)` in `test_2fa.py`
        # would have no effect at all. Storing None, the name is resolved in the module on
        # every call.
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        # The panel serves several tabs at once, and two simultaneous attempts would touch
        # the same list.
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._clock() if self._clock else time.time()

    def remaining(self, key: str) -> int:
        """Seconds left until it unlocks; 0 while there are attempts left.

        Prunes expired attempts along the way: the window slides, and without this an
        account would stay locked forever after five well-spaced mistakes.
        """
        with self._lock:
            now = self._now()
            fresh = [t for t in self._failures.get(key, []) if now - t < self._window]
            self._failures[key] = fresh
            if len(fresh) < self._tries:
                return 0
            # Round up: saying "0 seconds left" sends the person to try again only to get
            # the same 429.
            return int(self._window - (now - fresh[0])) + 1

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(self._now())

    def clear(self, key: str) -> None:
        """Got it right: the previous attempts stop counting.

        Without this, someone who errs four times, gets it right, and errs a fifth time
        tomorrow would be locked out because of yesterday's mistakes.
        """
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        """Forgets ALL keys. Only for `conftest.py`, between one test and the next."""
        with self._lock:
            self._failures.clear()
