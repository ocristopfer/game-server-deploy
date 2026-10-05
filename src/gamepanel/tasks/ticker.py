"""A "is it time yet?" clock - one per rhythm, instead of one `global` per rhythm.

The panel has six different steps running on the same background thread (monitor,
service state, resource meter, log, sample, history cleanup), and each one used to be a
module variable with `global` on top. Two consequences, both already paid for:

- `conftest.py` had to reset all six BY NAME, and one silently renamed would make a test
  inherit the previous one's clock - no error, just an alert that does not fire;
- deciding "is it time yet?" could only be tested by poking at `global`, so nobody did.

It is on purpose that `due` does NOT record the pass: the resource meter's clock only
advances when some resource alert is enabled. Asking and recording are two things, and
merging them would let the window be consumed by a round that read nothing.
"""
from __future__ import annotations


class Ticker:
    def __init__(self) -> None:
        # Zero (not "now") so the first round always counts: whoever just started the
        # panel wants the first reading right away, not one interval from now.
        self._last = 0.0

    def due(self, now: float, interval: float, force: bool = False) -> bool:
        """Has enough time passed? `force` is the screen's "check now" button."""
        return force or now - self._last >= interval

    def mark(self, now: float) -> None:
        self._last = now

    def reset(self) -> None:
        """Back to the just-started panel state. Only for `conftest.py`."""
        self._last = 0.0
