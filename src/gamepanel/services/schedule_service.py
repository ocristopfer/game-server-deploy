"""When a scheduled task is due, and what it is called on the screen.

Only clock arithmetic: no database, no SSH, no Flask. What wakes up every so often is
`tasks.scheduler`; what fires and records `last_run` is in `app.py`, next to `start_job`.

The rule that explains almost everything here is the occurrence rule: a daily/weekly task
is not "due every X"; it has a TIME, and the question is whether the most recent
occurrence of that time has already run. That is what keeps the panel from firing twice
on restart, and from firing anything when it was down for hours (see `SCHEDULE_GRACE` in
`is_due`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from gamepanel.i18n import Message

SCHEDULE_KINDS = ("diario", "semanal", "intervalo")
SCHEDULE_ACTIONS = ("restart", "stop", "start", "update", "backup")
# Keys, not text: the screen's `<select>` shows the day name in the viewer's language.
WEEKDAYS = ("weekday.monday", "weekday.tuesday", "weekday.wednesday", "weekday.thursday",
            "weekday.friday", "weekday.saturday", "weekday.sunday")
# The same thing with the article attached: "toda segunda" but "todo sabado" (the weekdays
# come from "segunda-feira", feminine; sabado and domingo are masculine). English has no
# article at all here, so the difference lives in the catalog and not in the code.
WEEKDAY_WITH_ARTICLE = ("weekday.on_monday", "weekday.on_tuesday", "weekday.on_wednesday",
                        "weekday.on_thursday", "weekday.on_friday", "weekday.on_saturday",
                        "weekday.on_sunday")
EVERY_HOURS_MAX = 168  # one week
DAYS_IN_WEEK = 7


def local_now() -> datetime:
    """The panel's local time, with time zone. It is the clock the scheduler sees."""
    return datetime.now().astimezone().replace(microsecond=0)


def _parse_dt(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def schedule_label(sched: Any) -> Message:
    """How the task is described on the screen and in the history.

    Returns a `Message`, and not ready-made text, because this label lands in TWO places
    with different rules: the screen, which follows the viewer's language, and the job's
    `command` column, which is stored and follows the deploy language. Being a `Message`
    (which is a `str`), the second case keeps working without anyone changing anything.
    """
    time = f"{int(sched['hour']):02d}:{int(sched['minute']):02d}"
    if sched["kind"] == "intervalo":
        hours = int(sched["every_hours"])
        if hours == 1:
            return Message("schedule.every_hour")
        return Message("schedule.every_n_hours", n=hours)
    if sched["kind"] == "semanal":
        index = int(sched["weekday"]) % DAYS_IN_WEEK
        # The day already comes with its article ("toda segunda", "todo sabado"): in
        # Portuguese it changes with the word's gender, and in English it does not even
        # exist. Building "{article} {day}" in the phrase would force English to carry an
        # empty field.
        return Message("schedule.weekly", weekday=Message(WEEKDAY_WITH_ARTICLE[index]),
                       time=time)
    return Message("schedule.daily", time=time)


def previous_occurrence(sched: Any, now: datetime) -> datetime | None:
    """The last time this task should have run ('intervalo' has none)."""
    if sched["kind"] == "intervalo":
        return None
    target = now.replace(hour=int(sched["hour"]), minute=int(sched["minute"]),
                         second=0, microsecond=0)
    if sched["kind"] == "semanal":
        back = (now.weekday() - int(sched["weekday"])) % DAYS_IN_WEEK
        target -= timedelta(days=back)
        if target > now:
            target -= timedelta(days=DAYS_IN_WEEK)
        return target
    if target > now:
        target -= timedelta(days=1)
    return target


def is_due(sched: Any, now: datetime, tolerance_s: float) -> bool:
    """Should the task fire now?"""
    last_one = _parse_dt(sched["last_run"])
    if sched["kind"] == "intervalo":
        if last_one is None:
            return True
        return (now - last_one) >= timedelta(hours=max(1, int(sched["every_hours"])))

    target = previous_occurrence(sched, now)
    if target is None:
        return False  # only 'intervalo' has no occurrence, and it already returned above
    if last_one is not None and last_one >= target:
        return False  # this occurrence already ran
    # Too late: the panel was down when the time passed. It does not fire and records
    # nothing; at the next occurrence the arithmetic above closes again on its own.
    return (now - target).total_seconds() <= tolerance_s
