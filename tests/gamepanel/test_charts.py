#!/usr/bin/env python3
"""Testes dos graficos de uso: coleta, retencao e a matematica das coordenadas.

    pytest admin/test_charts.py

A parte que erra num grafico nao e o desenho, e a conta: um buraco virando linha reta faz
o grafico MENTIR (diz que o servidor rodou liso enquanto estava fora do ar), e um valor
fora da moldura vaza por cima do resto da tela. E isso que esta testado aqui.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from gamepanel import app as panel

INICIO = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
FIM = INICIO + timedelta(hours=24)
SERIE_CPU = [{"key": "cpu", "label": "CPU", "color": "#3987e5", "suffix": "%"}]
DUAS_SERIES = SERIE_CPU + [
    {"key": "mem", "label": "Memoria", "color": "#d95926", "suffix": "%"}]


def samples(valores, passo_min=5, start=None):
    """Lista de (quando, {cpu: v}) espacada de `passo_min`; None vira buraco."""
    base = start or INICIO
    return [(base + timedelta(minutes=passo_min * i), {"cpu": v})
            for i, v in enumerate(valores)]


def chart_of(data, series=None, teto=100):
    return panel.build_chart(data, series or SERIE_CPU, teto, INICIO, FIM, "%H:%M")


def ys_of(g):
    """Todo y desenhado, de tracos e de pontos soltos."""
    all_of = [p for l in g["linhas"] for s in (l["tracos"] + l["pontos"]) for p in s.split()]
    return [float(p.split(",")[1]) for p in all_of]


# ------------------------------------------------------------------ o eixo

@pytest.mark.parametrize("pico, teto", [
    (11, 12),      # pico 11 nao merece um eixo que vai ate 20
    (0, 1),        # servidor parado ainda precisa de eixo
    (10, 10),      # pico exato usa o proprio degrau
    (5000, 5001),  # acima do maior degrau conhecido, sem quebrar
])
def test_teto_do_eixo(pico, teto):
    assert panel._clean_ceiling(pico) == teto


# ------------------------------------------------------------ coordenadas

def test_valor_vira_altura_dentro_da_moldura():
    g = chart_of(samples([0, 50, 100]))
    assert len(g["linhas"]) == 1
    ys = [float(p.split(",")[1]) for p in g["linhas"][0]["tracos"][0].split()]
    assert ys[0] == float(g["b"]), "0 fica na base"
    assert ys[2] == float(g["t"]), "100 fica no topo"
    assert abs(ys[1] - (g["t"] + g["b"]) / 2) < 0.6, f"50 devia ficar no meio (y={ys[1]})"


def test_valor_acima_do_teto_e_preso_na_moldura():
    """Sem isso a linha sai por cima do cartao e invade o resto da tela."""
    g = chart_of(samples([250]))
    assert all(g["t"] <= y <= g["b"] for y in ys_of(g))


def test_x_fica_dentro_da_moldura():
    g = chart_of(samples([10] * 40))
    xs = [float(p.split(",")[0]) for p in g["linhas"][0]["tracos"][0].split()]
    assert all(g["l"] - 0.5 <= x <= g["r"] + 0.5 for x in xs), f"x de {min(xs)} a {max(xs)}"


# ------------------------------------------- buracos nao viram linha reta

def test_painel_fora_do_ar_parte_a_linha():
    """Sem amostra a linha tem de PARTIR: ligar as pontas diria que rodou liso na queda."""
    far = samples([10, 20], passo_min=5)
    far += [(INICIO + timedelta(hours=6), {"cpu": 30}),
              (INICIO + timedelta(hours=6, minutes=5), {"cpu": 40})]
    assert len(chart_of(far)["linhas"][0]["tracos"]) == 2


def test_amostras_seguidas_ficam_num_traco_so():
    assert len(chart_of(samples([10, 20, 30, 40]))["linhas"][0]["tracos"]) == 1


def test_leitura_que_falhou_tambem_e_buraco():
    """None no meio = o medidor nao respondeu naquela volta."""
    with_failure = [(INICIO + timedelta(minutes=5 * i), {"cpu": v})
                 for i, v in enumerate([10, 20, None, 40, 50])]
    assert len(chart_of(with_failure)["linhas"][0]["tracos"]) == 2


def test_amostra_sozinha_vira_ponto_em_vez_de_sumir():
    """Um segmento de um ponto so nao tem comprimento para virar polyline."""
    alone = [(INICIO, {"cpu": 10}),
                (INICIO + timedelta(hours=5), {"cpu": 55}),
                (INICIO + timedelta(hours=10), {"cpu": 20})]
    g = chart_of(alone)
    assert len(g["linhas"][0]["pontos"]) == 3
    assert len(g["linhas"][0]["tracos"]) == 0


def test_grafico_sem_dado_se_declara_vazio():
    assert chart_of([])["vazio"] is True
    assert chart_of([(INICIO, {"cpu": None})])["vazio"] is True, "serie so com buraco"


# ----------------------------------------------------- rotulo das pontas

def series_pair(cpu_fim, mem_fim):
    return [(INICIO + timedelta(minutes=5 * i), {"cpu": c, "mem": m})
            for i, (c, m) in enumerate([(10, 90), (cpu_fim, mem_fim)])]


def test_pontas_separadas_ganham_rotulo():
    assert chart_of(series_pair(20, 80), DUAS_SERIES)["rotula_ponta"]


def test_pontas_coladas_perdem_o_rotulo_mas_nao_o_ponto():
    """Dois rotulos que se tocam se desgrudam das linhas e viram ruido: melhor nenhum."""
    g = chart_of(series_pair(50, 51), DUAS_SERIES)
    assert not g["rotula_ponta"]
    assert all(l["ponta"] for l in g["linhas"]), "o ponto da ponta continua la"


# ------------------------------------------------------ grade e eixo do tempo

def test_grade_leva_o_sufixo_da_serie():
    g = chart_of(samples([10, 20]))
    assert [l["label"] for l in g["grade"]] == ["0%", "50%", "100%"]
    assert len(g["tempos"]) == panel.CHART_TICKS


def test_grade_sem_sufixo_quando_a_serie_nao_tem():
    without_suffix = [dict(SERIE_CPU[0], suffix="")]
    g = chart_of(samples([1, 2]), without_suffix, teto=12)
    assert [l["label"] for l in g["grade"]] == ["0", "6", "12"]


# ------------------------------------------------------- coleta e retencao

def register_server(conn, name="alvo", host="nao-existe.invalid") -> int:
    with conn:
        conn.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES (?, ?, 22, 'root', 'jogo.service', ?)",
            (name, host, panel.now_iso()))
    return conn.execute("SELECT id FROM servers WHERE name = ?", (name,)).fetchone()["id"]


def test_medidor_com_erro_nao_grava_amostra(database, monkeypatch):
    """Zero seria mentira ("usou 0% de CPU"); o buraco e a informacao certa."""
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

    old_one_f = (datetime.now(timezone.utc)
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
    """CASCADE: sem isso o banco acumularia amostra de servidor que nao existe mais."""
    sid = register_server(database)
    with database:
        database.execute("INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                      " VALUES (?,?,?,?,?)", (sid, panel.now_iso(), 1.0, 2.0, 0))
        database.execute("DELETE FROM servers WHERE id = ?", (sid,))
    assert database.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


# ------------------------------------------------------------------- a tela
# (a fixture `chefe` - administrador cadastrado e logado - vem do conftest.py)

def test_a_tela_abre_sem_amostra_nenhuma(database, admin):
    sid = register_server(database, "alvo2", "outro.invalid")
    assert admin.get(f"/servers/{sid}/charts").status_code == 200


@pytest.mark.parametrize("faixa", ["6", "24", "168", "999", "abc"])
def test_faixa_de_tempo_nunca_quebra_a_tela(database, admin, faixa):
    """Faixa inventada cai na de 24h em vez de estourar."""
    sid = register_server(database, "alvo2", "outro.invalid")
    assert admin.get(f"/servers/{sid}/charts?h={faixa}").status_code == 200


def test_servidor_que_nao_existe_da_404(admin):
    assert admin.get("/servers/9999/charts").status_code == 404


def test_o_svg_desenhado_traz_os_rotulos_dos_eixos(database, admin):
    """Renderiza a TELA, e nao so o dicionario que a alimenta.

    Havia teste de sobra para `build_chart` e nenhum para o `charts.html`, e foi por ali
    que passou um defeito de verdade: renomear a chave `rotulo` do dicionario sem mexer
    no template deixou todo `<text class="tick">` VAZIO. A pagina continuou respondendo
    200, o SVG continuou no lugar, e nenhum teste piscou -- o eixo e que ficou sem
    numero. E o caso que o CLAUDE.md descreve: template quebrado nao aparece em teste.
    """
    sid = register_server(database, "alvo3", "outro3.invalid")
    now_at = datetime.now(timezone.utc)
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
