"""Desenha os graficos de uso: das amostras para os pontos do SVG.

Sao DOIS graficos e nao um: porcentagem e contagem de gente nao cabem no mesmo eixo, e
forcar as duas escalas num plot so inventa uma relacao que nao existe nos dados.

Tudo aqui e puro — recebe amostras ja lidas do banco e devolve o que o template
desenha. O SVG sai pronto do servidor de proposito: a tela tem de funcionar sem
JavaScript (ver CLAUDE.md), e a tabela de numeros ao lado e o par acessivel do desenho.
"""
from __future__ import annotations

from datetime import timedelta

# Caixa do SVG e as margens (rotulo do eixo a esquerda, legenda a direita).
CHART_W, CHART_H = 720, 220
CHART_L, CHART_R, CHART_T, CHART_B = 44, 64, 12, 28
CHART_GAP = 2.5
CHART_TICKS = 5
# Distancia minima entre dois rotulos de ponta para os dois continuarem legiveis.
TIP_MIN = 16

CHART_RANGES = ((6, "6 horas"), (24, "24 horas"), (168, "7 dias"))

# Slots 1 e 2 do catalogo categorico (versao para fundo escuro), validados contra o fundo
# do painel: separacao para daltonismo muito acima do minimo. A cor fica na LINHA; texto,
# eixo e legenda usam as cores de texto do painel.
CHART_CPU = "#3987e5"
CHART_MEM = "#d95926"

# Tetos "limpos" para o eixo de jogadores: 3 jogadores nao merecem um eixo ate 3.
CEILINGS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 64, 80, 100,
         150, 200, 300, 500, 750, 1000)


def clean_ceiling(peak: float) -> int:
    for ceiling in CEILINGS:
        if peak <= ceiling:
            return ceiling
    return int(peak) + 1


def _series_segments(samples, key: str, px, py,
                        sample_step: float) -> tuple[list[list[str]], dict | None]:
    """Uma serie vira uma lista de SEGMENTOS de coordenadas, mais a ponta.

    Segmentos, e nao uma linha so, porque o grafico tem buracos de dois tipos: amostra
    sem valor para esta serie (a contagem de jogadores desligada, por exemplo) e painel
    que ficou fora do ar entre duas amostras (ver CHART_GAP). Emendar por cima dos dois
    desenharia uma reta que afirma algo que ninguem mediu.
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
    """Transforma as amostras em coordenadas prontas para o SVG.

    `series` diz quais colunas desenhar; cada uma vira uma lista de SEGMENTOS, porque o
    grafico pode ter buracos (ver CHART_GAP).
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
            # Um segmento de um ponto so nao vira polyline (nao teria comprimento): vira
            # um ponto desenhado, senao a amostra solta sumiria da tela.
            "tracos": [" ".join(s) for s in segments if len(s) > 1],
            "pontos": [s[0] for s in segments if len(s) == 1],
            "ponta": edge,
        })

    # Rotulo direto so vale enquanto as pontas nao se encostam. Quando as linhas
    # convergem no canto direito, empurrar um rotulo para cima do outro os desgruda das
    # linhas e vira ruido — melhor deixar a legenda, a mira e a tabela carregarem, que e
    # o que elas ja fazem.
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
        # O que a mira precisa para converter uma coordenada de volta em valor e em hora,
        # sem o painel ter de mandar os dados duas vezes (o SVG ja os carrega).
        "teto": ceiling,
        "inicio_ms": int(start.timestamp() * 1000),
        "span_s": span,
    }


