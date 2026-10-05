"""Restart and backup at the scheduled time."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from gamepanel import app as panel
from gamepanel.persistence.repositories import schedules as schedules_repo

bp = Blueprint("schedules", __name__)


@bp.get("/servers/<int:sid>/schedules")
@panel.login_required
def index(sid: int):
    server = panel._server_or_404(sid)
    conn = panel.db()
    tasks = schedules_repo.of_server(conn, sid)
    now_ts = panel.local_now()
    # The screen shows the next time each task runs: without it "every day at 5am" does not
    # make clear whether it already ran today or is still going to run.
    next_ones = {}
    for t in tasks:
        next_ones[t["id"]] = panel._next_occurrence(t, now_ts).strftime(panel.SHORT_DATE_FORMAT)
    return render_template(
        "schedules.html", server=server, tasks=tasks, next_runs=next_ones,
        actions=panel.SCHEDULE_ACTIONS, job_labels=panel.labels_of(panel.JOB_LABELS),
        days=[panel.translate(d) for d in panel.WEEKDAYS],
        label=panel.schedule_label, now=now_ts, max_hours=panel.EVERY_HOURS_MAX,
    )


@bp.post("/servers/<int:sid>/schedules")
@panel.admin_required
def new(sid: int):
    panel._server_or_404(sid)
    errors: list[str] = []
    data = panel._schedule_form(request.form, errors)
    if errors:
        for err in errors:
            flash(panel.translate(err), "error")
        return redirect(url_for("schedules.index", sid=sid))

    # 'intervalo' starts counting from now: without this, "every 6h" would fire the instant
    # it was saved, which nobody expects from a schedule.
    start = panel.local_now().isoformat() if data["kind"] == "intervalo" else ""
    conn = panel.db()
    with conn:
        schedules_repo.insert(conn, sid, data, start, panel.now_iso())
    flash(panel.translate("flash.task_scheduled", task=panel.job_label(data["action"])), "ok")
    return redirect(url_for("schedules.index", sid=sid))


@bp.post("/schedules/<int:aid>/toggle")
@panel.admin_required
def toggle(aid: int):
    sched = panel._schedule_or_404(aid)
    conn = panel.db()
    with conn:
        schedules_repo.set_enabled(conn, aid, not sched["enabled"])
    flash(panel.translate("flash.task_off" if sched["enabled"] else "flash.task_on"), "ok")
    return redirect(url_for("schedules.index", sid=sched["server_id"]))


@bp.post("/schedules/<int:aid>/delete")
@panel.admin_required
def delete(aid: int):
    sched = panel._schedule_or_404(aid)
    conn = panel.db()
    with conn:
        schedules_repo.delete(conn, aid)
    flash(panel.translate("flash.task_removed"), "ok")
    return redirect(url_for("schedules.index", sid=sched["server_id"]))


@bp.post("/schedules/<int:aid>/run")
@panel.admin_required
def run(aid: int):
    """Run the task now, without waiting for its time: that is how one checks that it works."""
    sched = panel._schedule_or_404(aid)
    job_id = panel.fire_schedule(panel.db(), sched)
    if not job_id:
        flash(panel.translate("flash.could_not_trigger"), "error")
        return redirect(url_for("schedules.index", sid=sched["server_id"]))
    return redirect(url_for("jobs.detail", jid=job_id))
