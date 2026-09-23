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
    validas = [h for h, _ in panel.CHART_RANGES]
    try:
        horas = int(request.args.get("h", "24"))
    except ValueError:
        horas = 24
    if horas not in validas:
        horas = 24

    fim = datetime.now(UTC)
    start = fim - timedelta(hours=horas)
    lines_of = panel.db().execute(
        "SELECT taken_at, cpu_pct, mem_pct, players FROM samples"
        " WHERE server_id = ? AND taken_at >= ? ORDER BY taken_at",
        (sid, start.isoformat()),
    ).fetchall()

    amostras = []
    for line in lines_of:
        quando = panel._parse_dt(line["taken_at"])
        if quando:
            amostras.append((quando, {"cpu": line["cpu_pct"], "mem": line["mem_pct"],
                                      "players": line["players"]}))

    formato = "%d/%m" if horas > 48 else "%H:%M"
    uso = panel.build_chart(
        amostras,
        [{"key": "cpu", "label": "CPU", "color": panel.CHART_CPU, "suffix": "%"},
         {"key": "mem", "label": "Memoria", "color": panel.CHART_MEM, "suffix": "%"}],
        100, start, fim, formato,
    )
    pico = max((v["players"] for _, v in amostras if v["players"] is not None), default=0)
    jogadores = panel.build_chart(
        amostras,
        [{"key": "players", "label": "Jogadores", "color": panel.CHART_CPU}],
        panel._clean_ceiling(pico), start, fim, formato,
    )

    # A tabela e o par acessivel do grafico: mesmos numeros, sem depender de cor nem de
    # passar o mouse. Do mais novo para o mais velho, que e como se procura um pico.
    tabela = [
        {"quando": q.astimezone().strftime(panel.FORMATO_DATA_CURTA), **v}
        for q, v in reversed(amostras)
    ][:200]

    return render_template(
        "charts.html", server=server, uso=uso, jogadores=jogadores, tabela=tabela,
        horas=horas, faixas=panel.CHART_RANGES, total=len(amostras), pico=pico,
        a_cada=int(panel.SAMPLE_EVERY / 60), guarda_dias=panel.SAMPLES_KEEP_DAYS,
        cores={"cpu": panel.CHART_CPU, "mem": panel.CHART_MEM},
    )
