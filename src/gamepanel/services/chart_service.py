"""Draws the usage charts: from the samples to the SVG points.

There are TWO charts and not one: a percentage and a head count do not fit on the same
axis, and forcing both scales into a single plot invents a relation that does not exist
in the data.

Everything here is pure: it takes samples already read from the database and returns
what the template draws. The SVG comes ready from the server on purpose: the screen has
to work without JavaScript (see CLAUDE.md), and the table of numbers beside it is the
accessible counterpart of the drawing.
"""
from __future__ import annotations

from datetime import timedelta

# The SVG box and its margins (axis label on the left, legend on the right).
CHART_W, CHART_H = 720, 220
CHART_L, CHART_R, CHART_T, CHART_B = 44, 64, 12, 28
CHART_GAP = 2.5
CHART_TICKS = 5
# Minimum distance between two end-of-line labels for both to stay readable.
TIP_MIN = 16

# The label is a catalog KEY: the route translates it for whoever is looking.
CHART_RANGES = ((6, "charts.range_6h"), (24, "charts.range_24h"), (168, "charts.range_7d"))

# Slots 1 and 2 of the categorical palette (dark background version), validated against
# the panel background: color-blind separation well above the minimum. The color goes on
# the LINE; text, axis and legend use the panel's text colors.
CHART_CPU = "#3987e5"
CHART_MEM = "#d95926"

# "Round" ceilings for the players axis: 3 players do not deserve an axis that stops at 3.
CEILINGS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 64, 80, 100,
         150, 200, 300, 500, 750, 1000)


def clean_ceiling(peak: float) -> int:
    for ceiling in CEILINGS:
        if peak <= ceiling:
            return ceiling
    return int(peak) + 1


def _series_segments(samples, key: str, px, py,
                        sample_step: float) -> tuple[list[list[str]], dict | None]:
    """A series becomes a list of coordinate SEGMENTS, plus its end point.

    Segments, and not a single line, because the chart has two kinds of gaps: a sample
    with no value for this series (player counting turned off, for example) and the panel
    being down between two samples (see CHART_GAP). Joining across either would draw a
    straight line claiming something nobody measured.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    previous = None
    edge = None

    def close_segment():
        nonlocal current
        if current:
            segments.append(current)
        current = []

    for when_at, values in samples:
        value = values.get(key)
        if value is None:
            close_segment()
            previous = None
            continue
        if previous is not None and (when_at - previous).total_seconds() > sample_step * CHART_GAP:
            close_segment()
        current.append(f"{px(when_at)},{py(value)}")
        edge = {"x": px(when_at), "y": py(value), "valor": value}
        previous = when_at

    close_segment()
    return segments, edge


def build_chart(samples, series, ceiling: float, start, end, time_format: str,
                  sample_step: float) -> dict:
    """Turns the samples into coordinates ready for the SVG.

    `series` says which columns to draw; each one becomes a list of SEGMENTS, because the
    chart may have gaps (see CHART_GAP).
    """
    span = max(1.0, (end - start).total_seconds())
    width = CHART_W - CHART_L - CHART_R
    tall = CHART_H - CHART_T - CHART_B

    def px(quando) -> float:
        return round(CHART_L + width * ((quando - start).total_seconds() / span), 1)

    def py(value) -> float:
        slice_of = 0.0 if ceiling <= 0 else min(1.0, max(0.0, value / ceiling))
        return round(CHART_T + tall * (1 - slice_of), 1)

    lines_of = []
    for one_series in series:
        segments, edge = _series_segments(
            samples, one_series["key"], px, py, sample_step)
        if not segments:
            continue
        lines_of.append({
            "key": one_series["key"],
            "label": one_series["label"],
            "color": one_series["color"],
            "suffix": one_series.get("suffix", ""),
            # A one-point segment does not become a polyline (it would have no length): it
            # becomes a drawn dot, otherwise the lone sample would vanish from the screen.
            "tracos": [" ".join(s) for s in segments if len(s) > 1],
            "pontos": [s[0] for s in segments if len(s) == 1],
            "ponta": edge,
        })

    # A direct label only works while the end points do not touch. When the lines converge
    # in the right corner, pushing one label above the other detaches them from their lines
    # and turns into noise; better to let the legend, the crosshair and the table carry it,
    # which they already do.
    edges = [line["ponta"]["y"] for line in lines_of if line["ponta"]]
    label_edge = all(
        abs(a - b) >= TIP_MIN
        for i, a in enumerate(edges) for b in edges[i + 1:]
    )

    grade = []
    for slice_of in (0.0, 0.5, 1.0):
        value = ceiling * slice_of
        grade.append({
            "y": py(value),
            "label": f"{value:g}" + (series[0].get("suffix", "") if series else ""),
        })

    times = []
    for i in range(CHART_TICKS):
        when_at = start + timedelta(seconds=span * i / (CHART_TICKS - 1))
        times.append({"x": px(when_at), "label": when_at.astimezone().strftime(time_format)})

    return {
        "linhas": lines_of,
        "grade": grade,
        "tempos": times,
        "vazio": not lines_of,
        "rotula_ponta": label_edge,
        "w": CHART_W, "h": CHART_H,
        "l": CHART_L, "r": CHART_W - CHART_R, "t": CHART_T, "b": CHART_H - CHART_B,
        # What the crosshair needs to turn a coordinate back into a value and a time,
        # without the panel sending the data twice (the SVG already carries it).
        "teto": ceiling,
        "inicio_ms": int(start.timestamp() * 1000),
        "span_s": span,
    }


