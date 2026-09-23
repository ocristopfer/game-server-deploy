"""Reinicio e backup na hora marcada."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from gamepanel import app as panel

bp = Blueprint("schedules", __name__)


@bp.get("/servers/<int:sid>/schedules")
@panel.login_required
def index(sid: int):
    server = panel._server_or_404(sid)
    conn = panel.db()
    tasks = conn.execute(
        "SELECT * FROM schedules WHERE server_id = ? ORDER BY id", (sid,)
    ).fetchall()
    now_ts = panel.local_now()
    # A tela mostra a proxima vez que cada tarefa roda: sem isso "todo dia as 5h" nao
    # deixa claro se ela ja rodou hoje ou se ainda vai rodar.
    next_ones = {}
    for t in tasks:
        next_ones[t["id"]] = panel._next_occurrence(t, now_ts).strftime(panel.FORMATO_DATA_CURTA)
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

    # 'intervalo' comeca a contar de agora: sem isto, "a cada 6h" dispararia no instante
    # em que fosse salvo, o que ninguem espera de um agendamento.
    start = panel.local_now().isoformat() if data["kind"] == "intervalo" else ""
    conn = panel.db()
    with conn:
        conn.execute(
            "INSERT INTO schedules (server_id, action, kind, hour, minute, weekday,"
            " every_hours, enabled, last_run, created_at) VALUES (?,?,?,?,?,?,?,1,?,?)",
            (sid, data["action"], data["kind"], data["hour"], data["minute"],
             data["weekday"], data["every_hours"], start, panel.now_iso()),
        )
    flash(panel.translate("flash.task_scheduled", task=panel.job_label(data["action"])), "ok")
    return redirect(url_for("schedules.index", sid=sid))


@bp.post("/schedules/<int:aid>/toggle")
@panel.admin_required
def toggle(aid: int):
    sched = panel._schedule_or_404(aid)
    conn = panel.db()
    with conn:
        conn.execute("UPDATE schedules SET enabled = ? WHERE id = ?",
                     (0 if sched["enabled"] else 1, aid))
    flash(panel.translate("flash.task_off" if sched["enabled"] else "flash.task_on"), "ok")
    return redirect(url_for("schedules.index", sid=sched["server_id"]))


@bp.post("/schedules/<int:aid>/delete")
@panel.admin_required
def delete(aid: int):
    sched = panel._schedule_or_404(aid)
    conn = panel.db()
    with conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (aid,))
    flash(panel.translate("flash.task_removed"), "ok")
    return redirect(url_for("schedules.index", sid=sched["server_id"]))


@bp.post("/schedules/<int:aid>/run")
@panel.admin_required
def run(aid: int):
    """Roda a tarefa agora, sem esperar a hora — e como se confere se ela funciona."""
    sched = panel._schedule_or_404(aid)
    job_id = panel.fire_schedule(panel.db(), sched)
    if not job_id:
        flash(panel.translate("flash.could_not_trigger"), "error")
        return redirect(url_for("schedules.index", sid=sched["server_id"]))
    return redirect(url_for("jobs.detail", jid=job_id))
