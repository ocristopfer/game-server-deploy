"""CPU, memory and players over time."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import Blueprint, render_template, request

from gamepanel import app as panel
from gamepanel.persistence.repositories import samples as samples_repo

bp = Blueprint("charts", __name__)


@bp.get("/servers/<int:sid>/charts")
@panel.login_required
def index(sid: int):
    """CPU, memory and players over time.

    There are TWO charts, not one: a percentage and a headcount do not fit on the same axis,
    and forcing both scales into a single plot invents a relationship that does not exist in the data.
    """
    server = panel._server_or_404(sid)
    valid_ones = [h for h, _ in panel.CHART_RANGES]
    try:
        hours = int(request.args.get("h", "24"))
    except ValueError:
        hours = 24
    if hours not in valid_ones:
        hours = 24

    end_at = datetime.now(UTC)
    start = end_at - timedelta(hours=hours)
    lines_of = samples_repo.of_server_since(panel.db(), sid, start.isoformat())

    samples = []
    for line in lines_of:
        when_at = panel._parse_dt(line["taken_at"])
        if when_at:
            samples.append((when_at, {"cpu": line["cpu_pct"], "mem": line["mem_pct"],
                                      "players": line["players"]}))

    shape = "%d/%m" if hours > 48 else "%H:%M"
    usage = panel.build_chart(
        samples,
        [{"key": "cpu", "label": "CPU", "color": panel.CHART_CPU, "suffix": "%"},
         {"key": "mem", "label": panel.translate("charts.memory"), "color": panel.CHART_MEM, "suffix": "%"}],
        100, start, end_at, shape,
    )
    peak = max((v["players"] for _, v in samples if v["players"] is not None), default=0)
    players = panel.build_chart(
        samples,
        [{"key": "players", "label": panel.translate("charts.players"), "color": panel.CHART_CPU}],
        panel._clean_ceiling(peak), start, end_at, shape,
    )

    # The table is the chart's accessible counterpart: same numbers, without relying on color or
    # hovering. Newest to oldest, which is how one looks for a peak.
    table = [
        {"quando": q.astimezone().strftime(panel.SHORT_DATE_FORMAT), **v}
        for q, v in reversed(samples)
    ][:200]

    return render_template(
        "charts.html", server=server, usage=usage, players=players, table=table,
        hours=hours, ranges=[(h, panel.translate(label)) for h, label in panel.CHART_RANGES],
        total=len(samples), peak=peak,
        every=int(panel.SAMPLE_EVERY / 60), keep_days=panel.SAMPLES_KEEP_DAYS,
        colors={"cpu": panel.CHART_CPU, "mem": panel.CHART_MEM},
    )
