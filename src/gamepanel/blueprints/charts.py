"""CPU, memoria e jogadores ao longo do tempo."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import Blueprint, render_template, request

from gamepanel import app as panel

bp = Blueprint("charts", __name__)


@bp.get("/servers/<int:sid>/charts")
@panel.login_required
def index(sid: int):
    """CPU, memoria e jogadores ao longo do tempo.

    Sao DOIS graficos e nao um: porcentagem e contagem de gente nao cabem no mesmo eixo,
    e forcar as duas escalas num plot so inventa uma relacao que nao existe nos dados.
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
    lines_of = panel.db().execute(
        "SELECT taken_at, cpu_pct, mem_pct, players FROM samples"
        " WHERE server_id = ? AND taken_at >= ? ORDER BY taken_at",
        (sid, start.isoformat()),
    ).fetchall()

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
         {"key": "mem", "label": "Memoria", "color": panel.CHART_MEM, "suffix": "%"}],
        100, start, end_at, shape,
    )
    peak = max((v["players"] for _, v in samples if v["players"] is not None), default=0)
    players = panel.build_chart(
        samples,
        [{"key": "players", "label": "Jogadores", "color": panel.CHART_CPU}],
        panel._clean_ceiling(peak), start, end_at, shape,
    )

    # A tabela e o par acessivel do grafico: mesmos numeros, sem depender de cor nem de
    # passar o mouse. Do mais novo para o mais velho, que e como se procura um pico.
    table = [
        {"quando": q.astimezone().strftime(panel.FORMATO_DATA_CURTA), **v}
        for q, v in reversed(samples)
    ][:200]

    return render_template(
        "charts.html", server=server, usage=usage, players=players, table=table,
        hours=hours, ranges=panel.CHART_RANGES, total=len(samples), peak=peak,
        every=int(panel.SAMPLE_EVERY / 60), keep_days=panel.SAMPLES_KEEP_DAYS,
        colors={"cpu": panel.CHART_CPU, "mem": panel.CHART_MEM},
    )
