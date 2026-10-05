#!/usr/bin/env python3
"""Tests for the usage charts: collection, retention and the coordinate math.

    pytest admin/test_charts.py

The part that goes wrong in a chart is not the drawing, it is the arithmetic: a gap turned into
a straight line makes the chart LIE (it says the server ran smoothly while it was down), and a
value outside the frame leaks over the rest of the screen. That is what is tested here.
"""
import re
from datetime import UTC, datetime, timedelta

import pytest

from gamepanel import app as panel

START = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
END = START + timedelta(hours=24)
SERIE_CPU = [{"key": "cpu", "label": "CPU", "color": "#3987e5", "suffix": "%"}]
DUAS_SERIES = [*SERIE_CPU,
               {"key": "mem", "label": "Memoria", "color": "#d95926", "suffix": "%"}]


def samples(values, min_step=5, start=None):
    """List of (when, {cpu: v}) spaced `passo_min` apart; None becomes a gap."""
    base = start or START
    return [(base + timedelta(minutes=min_step * i), {"cpu": v})
            for i, v in enumerate(values)]


def chart_of(data, series=None, teto=100):
    return panel.build_chart(data, series or SERIE_CPU, teto, START, END, "%H:%M")


def ys_of(g):
    """Every y drawn, from strokes and from isolated points."""
    all_of = [p for line in g["linhas"] for s in (line["tracos"] + line["pontos"]) for p in s.split()]
    return [float(p.split(",")[1]) for p in all_of]


# ------------------------------------------------------------------ the axis

@pytest.mark.parametrize("pico, teto", [
    (11, 12),      # a peak of 11 does not deserve an axis going up to 20
    (0, 1),        # a stopped server still needs an axis
    (10, 10),      # an exact peak uses its own step
    (5000, 5001),  # above the largest known step, without breaking
])
def test_teto_do_eixo(pico, teto):
    assert panel._clean_ceiling(pico) == teto


# ------------------------------------------------------------ coordinates

def test_valor_vira_altura_dentro_da_moldura():
    g = chart_of(samples([0, 50, 100]))
    assert len(g["linhas"]) == 1
    ys = [float(p.split(",")[1]) for p in g["linhas"][0]["tracos"][0].split()]
    assert ys[0] == float(g["b"]), "0 fica na base"
    assert ys[2] == float(g["t"]), "100 fica no topo"
    assert abs(ys[1] - (g["t"] + g["b"]) / 2) < 0.6, f"50 devia ficar no meio (y={ys[1]})"


def test_valor_acima_do_teto_e_preso_na_moldura():
    """Without this the line goes over the card and invades the rest of the screen."""
    g = chart_of(samples([250]))
    assert all(g["t"] <= y <= g["b"] for y in ys_of(g))


def test_x_fica_dentro_da_moldura():
    g = chart_of(samples([10] * 40))
    xs = [float(p.split(",")[0]) for p in g["linhas"][0]["tracos"][0].split()]
    assert all(g["l"] - 0.5 <= x <= g["r"] + 0.5 for x in xs), f"x de {min(xs)} a {max(xs)}"


# ------------------------------------------- gaps do not become straight lines

def test_painel_fora_do_ar_parte_a_linha():
    """Without a sample the line has to BREAK: joining the ends would say it ran smoothly during the outage."""
    far = samples([10, 20], min_step=5)
    far += [(START + timedelta(hours=6), {"cpu": 30}),
              (START + timedelta(hours=6, minutes=5), {"cpu": 40})]
    assert len(chart_of(far)["linhas"][0]["tracos"]) == 2


def test_amostras_seguidas_ficam_num_traco_so():
    assert len(chart_of(samples([10, 20, 30, 40]))["linhas"][0]["tracos"]) == 1


def test_leitura_que_falhou_tambem_e_buraco():
    """None in the middle = the meter did not answer on that round."""
    with_failure = [(START + timedelta(minutes=5 * i), {"cpu": v})
                 for i, v in enumerate([10, 20, None, 40, 50])]
    assert len(chart_of(with_failure)["linhas"][0]["tracos"]) == 2


def test_amostra_sozinha_vira_ponto_em_vez_de_sumir():
    """A one-point segment has no length to become a polyline."""
    alone = [(START, {"cpu": 10}),
                (START + timedelta(hours=5), {"cpu": 55}),
                (START + timedelta(hours=10), {"cpu": 20})]
    g = chart_of(alone)
    assert len(g["linhas"][0]["pontos"]) == 3
    assert len(g["linhas"][0]["tracos"]) == 0


def test_grafico_sem_dado_se_declara_vazio():
    assert chart_of([])["vazio"] is True
    assert chart_of([(START, {"cpu": None})])["vazio"] is True, "serie so com buraco"


# ----------------------------------------------------- end labels

def series_pair(cpu_end, mem_end):
    return [(START + timedelta(minutes=5 * i), {"cpu": c, "mem": m})
            for i, (c, m) in enumerate([(10, 90), (cpu_end, mem_end)])]


def test_pontas_separadas_ganham_rotulo():
    assert chart_of(series_pair(20, 80), DUAS_SERIES)["rotula_ponta"]


def test_pontas_coladas_perdem_o_rotulo_mas_nao_o_ponto():
    """Two labels touching each other come loose from their lines and become noise: better none."""
    g = chart_of(series_pair(50, 51), DUAS_SERIES)
    assert not g["rotula_ponta"]
    assert all(line["ponta"] for line in g["linhas"]), "o ponto da ponta continua la"


# ------------------------------------------------------ grid and time axis

def test_grade_leva_o_sufixo_da_serie():
    g = chart_of(samples([10, 20]))
    assert [line["label"] for line in g["grade"]] == ["0%", "50%", "100%"]
    assert len(g["tempos"]) == panel.CHART_TICKS


def test_grade_sem_sufixo_quando_a_serie_nao_tem():
    without_suffix = [dict(SERIE_CPU[0], suffix="")]
    g = chart_of(samples([1, 2]), without_suffix, teto=12)
    assert [line["label"] for line in g["grade"]] == ["0", "6", "12"]


# ------------------------------------------------------- collection and retention

def register_server(conn, name="alvo", host="nao-existe.invalid") -> int:
    with conn:
        conn.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES (?, ?, 22, 'root', 'jogo.service', ?)",
            (name, host, panel.now_iso()))
    return conn.execute("SELECT id FROM servers WHERE name = ?", (name,)).fetchone()["id"]


def test_medidor_com_erro_nao_grava_amostra(database, monkeypatch):
    """Zero would be a lie ("used 0% CPU"); the gap is the right information."""
    register_server(database)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {"error": "tempo esgotado"})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        assert panel.collect_samples(force=True) == 0


def test_medidor_bom_grava_os_numeros_lidos(database, monkeypatch):
    register_server(database)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {
        "error": "", "cpu_pct": 41.5, "mem": {"pct": 62.0}, "disks": []})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        assert panel.collect_samples(force=True) == 1

    line = database.execute("SELECT * FROM samples").fetchone()
    assert (line["cpu_pct"], line["mem_pct"]) == (41.5, 62.0)
    assert line["players"] is None, "sem contagem ligada no cadastro, fica vazio"


def test_amostra_velha_sai_na_limpeza(database, monkeypatch):
    sid = register_server(database)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {
        "error": "", "cpu_pct": 41.5, "mem": {"pct": 62.0}, "disks": []})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        panel.collect_samples(force=True)

    old_one_f = (datetime.now(UTC)
             - timedelta(days=panel.SAMPLES_KEEP_DAYS + 2)).isoformat()
    with database:
        for _ in range(5):
            database.execute(
                "INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                " VALUES (?,?,?,?,?)", (sid, old_one_f, 1.0, 2.0, 0))
    assert database.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 6

    with panel.app.app_context():
        panel.clean_history(force=True)
    assert database.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1


def test_apagar_o_servidor_leva_as_amostras_dele(database):
    """CASCADE: without it the database would pile up samples of servers that no longer exist."""
    sid = register_server(database)
    with database:
        database.execute("INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                      " VALUES (?,?,?,?,?)", (sid, panel.now_iso(), 1.0, 2.0, 0))
        database.execute("DELETE FROM servers WHERE id = ?", (sid,))
    assert database.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


# ------------------------------------------------------------------- the screen
# (the `chefe` fixture - an admin registered and logged in - comes from conftest.py)

def test_a_tela_abre_sem_amostra_nenhuma(database, admin):
    sid = register_server(database, "alvo2", "outro.invalid")
    assert admin.get(f"/servers/{sid}/charts").status_code == 200


@pytest.mark.parametrize("faixa", ["6", "24", "168", "999", "abc"])
def test_faixa_de_tempo_nunca_quebra_a_tela(database, admin, faixa):
    """A made-up range falls back to 24h instead of blowing up."""
    sid = register_server(database, "alvo2", "outro.invalid")
    assert admin.get(f"/servers/{sid}/charts?h={faixa}").status_code == 200


def test_servidor_que_nao_existe_da_404(admin):
    assert admin.get("/servers/9999/charts").status_code == 404


def test_o_svg_desenhado_traz_os_rotulos_dos_eixos(database, admin):
    """Renders the SCREEN, and not just the dictionary that feeds it.

    There were plenty of tests for `build_chart` and none for `charts.html`, and that is
    where a real defect got through: renaming the `rotulo` key of the dictionary without
    touching the template left every `<text class="tick">` EMPTY. The page kept answering
    200, the SVG stayed in place, and no test blinked -- the axis just lost its numbers.
    It is the case CLAUDE.md describes: a broken template does not show up in any test.
    """
    sid = register_server(database, "alvo3", "outro3.invalid")
    now_at = datetime.now(UTC)
    for i in range(5):
        database.execute(
            "INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
            " VALUES (?,?,?,?,?)",
            (sid, (now_at - timedelta(minutes=i * 5)).isoformat(),
             20.0 + i, 40.0 + i, 0))
    database.commit()

    html = admin.get(f"/servers/{sid}/charts").get_data(as_text=True)
    ticks = re.findall(r'<text class="tick"[^>]*>([^<]*)</text>', html)
    assert ticks, "o SVG nao trouxe nenhum rotulo de eixo"
    assert all(t.strip() for t in ticks), f"rotulo de eixo vazio: {ticks}"
