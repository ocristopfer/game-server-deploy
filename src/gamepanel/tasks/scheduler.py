"""The panel's clock: a thread that wakes up from time to time and calls the tasks.

There are five (schedules, monitor, live log, samples and cleanup) and they live in
`app.py`, each with its own internal clock - there is no rule here about WHEN each one
should run, only the beat.

It relies on the panel running with ONE worker (that is how gunicorn is configured here,
see provision-admin-lxc.sh): with two processes, each would have its own thread and the
same task would fire twice.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

# (name for the log, what to run).
Task = tuple[str, Callable[[], Any]]


def tick(tasks: Iterable[Task], on_failure: Callable[[str], None]) -> None:
    """One round of the clock.

    Each task gets ITS OWN try. Sharing a single try, a broken schedule took the monitor
    and the samples down with it: the exception rose from the first task and the other
    three never ran - forever, because the broken task broke again every round. From the
    outside the panel looked whole, and the test-webhook button (which does not go through
    here) kept working and steering suspicion away from the right place.
    """
    for name, task in tasks:
        try:
            task()
        # One task does not take down the others.
        except Exception:  # noqa: BLE001
            on_failure(name)


class Clock:
    """The thread itself. `start()` is idempotent: two calls do not make two threads."""

    def __init__(self, interval: float, one_round: Callable[[], None],
                 logger: logging.Logger) -> None:
        self._interval = interval
        self._one_round = one_round
        self._logger = logger
        self._started = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def _loop(self) -> None:
        # Event.wait instead of sleep: this way `stop()` cuts the wait immediately instead
        # of leaving the thread hanging until the end of the interval.
        while not self._stop_event.wait(self._interval):
            try:
                self._one_round()
            # The thread must not die because of one tick.
            except Exception:
                self._logger.exception("falha no agendador")

    # The thread has a NAME, and it is not decoration: without it a stack dump
    # (`faulthandler`, `py-spy`) shows `Thread-1 (_loop)` and nobody can tell which of the
    # panel's background threads is stuck. The name is also what lets a test count the
    # threads of THIS clock instead of `threading.active_count()`, which counts unrelated
    # ones - importing `app.py` already starts one.
    THREAD_NAME = "gamepanel-scheduler"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True, name=self.THREAD_NAME).start()

    def stop(self) -> None:
        """Stop the thread. The panel does not use it (the whole process dies with it); it
        exists so a test does not leave a clock ticking for the rest of the suite."""
        self._stop_event.set()
