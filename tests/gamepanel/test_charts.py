#!/usr/bin/env python3
"""Testes dos graficos de uso: coleta, retencao e a matematica das coordenadas.

    pytest admin/test_charts.py

A parte que erra num grafico nao e o desenho, e a conta: um buraco virando linha reta faz
o grafico MENTIR (diz que o servidor rodou liso enquanto estava fora do ar), e um valor
fora da moldura vaza por cima do resto da tela. E isso que esta testado aqui.
"""
from datetime import datetime, timedelta, timezone

import pytest

from gamepanel import app as panel

INICIO = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
FIM = INICIO + timedelta(hours=24)
SERIE_CPU = [{"chave": "cpu", "rotulo": "CPU", "cor": "#3987e5", "sufixo": "%"}]
DUAS_SERIES = SERIE_CPU + [
    {"chave": "mem", "rotulo": "Memoria", "cor": "#d95926", "sufixo": "%"}]


def amostras(valores, passo_min=5, inicio=None):
    """Lista de (quando, {cpu: v}) espacada de `passo_min`; None vira buraco."""
    base = inicio or INICIO
    return [(base + timedelta(minutes=passo_min * i), {"cpu": v})
            for i, v in enumerate(valores)]


def grafico(data, series=None, teto=100):
    return panel.build_chart(data, series or SERIE_CPU, teto, INICIO, FIM, "%H:%M")


def ys_de(g):
    """Todo y desenhado, de tracos e de pontos soltos."""
    todos = [p for l in g["linhas"] for s in (l["tracos"] + l["pontos"]) for p in s.split()]
    return [float(p.split(",")[1]) for p in todos]


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
    g = grafico(amostras([0, 50, 100]))
    assert len(g["linhas"]) == 1
    ys = [float(p.split(",")[1]) for p in g["linhas"][0]["tracos"][0].split()]
    assert ys[0] == float(g["b"]), "0 fica na base"
    assert ys[2] == float(g["t"]), "100 fica no topo"
    assert abs(ys[1] - (g["t"] + g["b"]) / 2) < 0.6, f"50 devia ficar no meio (y={ys[1]})"


def test_valor_acima_do_teto_e_preso_na_moldura():
    """Sem isso a linha sai por cima do cartao e invade o resto da tela."""
    g = grafico(amostras([250]))
    assert all(g["t"] <= y <= g["b"] for y in ys_de(g))


def test_x_fica_dentro_da_moldura():
    g = grafico(amostras([10] * 40))
    xs = [float(p.split(",")[0]) for p in g["linhas"][0]["tracos"][0].split()]
    assert all(g["l"] - 0.5 <= x <= g["r"] + 0.5 for x in xs), f"x de {min(xs)} a {max(xs)}"


# ------------------------------------------- buracos nao viram linha reta

def test_painel_fora_do_ar_parte_a_linha():
    """Sem amostra a linha tem de PARTIR: ligar as pontas diria que rodou liso na queda."""
    longe = amostras([10, 20], passo_min=5)
    longe += [(INICIO + timedelta(hours=6), {"cpu": 30}),
              (INICIO + timedelta(hours=6, minutes=5), {"cpu": 40})]
    assert len(grafico(longe)["linhas"][0]["tracos"]) == 2


def test_amostras_seguidas_ficam_num_traco_so():
    assert len(grafico(amostras([10, 20, 30, 40]))["linhas"][0]["tracos"]) == 1


def test_leitura_que_falhou_tambem_e_buraco():
    """None no meio = o medidor nao respondeu naquela volta."""
    com_falha = [(INICIO + timedelta(minutes=5 * i), {"cpu": v})
                 for i, v in enumerate([10, 20, None, 40, 50])]
    assert len(grafico(com_falha)["linhas"][0]["tracos"]) == 2


def test_amostra_sozinha_vira_ponto_em_vez_de_sumir():
    """Um segmento de um ponto so nao tem comprimento para virar polyline."""
    sozinhas = [(INICIO, {"cpu": 10}),
                (INICIO + timedelta(hours=5), {"cpu": 55}),
                (INICIO + timedelta(hours=10), {"cpu": 20})]
    g = grafico(sozinhas)
    assert len(g["linhas"][0]["pontos"]) == 3
    assert len(g["linhas"][0]["tracos"]) == 0


def test_grafico_sem_dado_se_declara_vazio():
    assert grafico([])["vazio"] is True
    assert grafico([(INICIO, {"cpu": None})])["vazio"] is True, "serie so com buraco"


# ----------------------------------------------------- rotulo das pontas

def par_de_series(cpu_fim, mem_fim):
    return [(INICIO + timedelta(minutes=5 * i), {"cpu": c, "mem": m})
            for i, (c, m) in enumerate([(10, 90), (cpu_fim, mem_fim)])]


def test_pontas_separadas_ganham_rotulo():
    assert grafico(par_de_series(20, 80), DUAS_SERIES)["rotula_ponta"]


def test_pontas_coladas_perdem_o_rotulo_mas_nao_o_ponto():
    """Dois rotulos que se tocam se desgrudam das linhas e viram ruido: melhor nenhum."""
    g = grafico(par_de_series(50, 51), DUAS_SERIES)
    assert not g["rotula_ponta"]
    assert all(l["ponta"] for l in g["linhas"]), "o ponto da ponta continua la"


# ------------------------------------------------------ grade e eixo do tempo

def test_grade_leva_o_sufixo_da_serie():
    g = grafico(amostras([10, 20]))
    assert [l["rotulo"] for l in g["grade"]] == ["0%", "50%", "100%"]
    assert len(g["tempos"]) == panel.CHART_TICKS


def test_grade_sem_sufixo_quando_a_serie_nao_tem():
    sem_sufixo = [dict(SERIE_CPU[0], sufixo="")]
    g = grafico(amostras([1, 2]), sem_sufixo, teto=12)
    assert [l["rotulo"] for l in g["grade"]] == ["0", "6", "12"]


# ------------------------------------------------------- coleta e retencao

def register_server(conn, nome="alvo", host="nao-existe.invalid") -> int:
    with conn:
        conn.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES (?, ?, 22, 'root', 'jogo.service', ?)",
            (nome, host, panel.now_iso()))
    return conn.execute("SELECT id FROM servers WHERE name = ?", (nome,)).fetchone()["id"]


def test_medidor_com_erro_nao_grava_amostra(banco, monkeypatch):
    """Zero seria mentira ("usou 0% de CPU"); o buraco e a informacao certa."""
    register_server(banco)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {"error": "tempo esgotado"})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        assert panel.collect_samples(forcar=True) == 0


def test_medidor_bom_grava_os_numeros_lidos(banco, monkeypatch):
    register_server(banco)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {
        "error": "", "cpu_pct": 41.5, "mem": {"pct": 62.0}, "disks": []})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        assert panel.collect_samples(forcar=True) == 1

    linha = banco.execute("SELECT * FROM samples").fetchone()
    assert (linha["cpu_pct"], linha["mem_pct"]) == (41.5, 62.0)
    assert linha["players"] is None, "sem contagem ligada no cadastro, fica vazio"


def test_amostra_velha_sai_na_limpeza(banco, monkeypatch):
    sid = register_server(banco)
    monkeypatch.setattr(panel, "server_metrics", lambda *a, **k: {
        "error": "", "cpu_pct": 41.5, "mem": {"pct": 62.0}, "disks": []})
    monkeypatch.setattr(panel, "server_players", lambda *a, **k: {"error": "", "players": 3})
    with panel.app.app_context():
        panel.collect_samples(forcar=True)

    velha = (datetime.now(timezone.utc)
             - timedelta(days=panel.SAMPLES_KEEP_DAYS + 2)).isoformat()
    with banco:
        for _ in range(5):
            banco.execute(
                "INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                " VALUES (?,?,?,?,?)", (sid, velha, 1.0, 2.0, 0))
    assert banco.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 6

    with panel.app.app_context():
        panel.clean_history(forcar=True)
    assert banco.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1


def test_apagar_o_servidor_leva_as_amostras_dele(banco):
    """CASCADE: sem isso o banco acumularia amostra de servidor que nao existe mais."""
    sid = register_server(banco)
    with banco:
        banco.execute("INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                      " VALUES (?,?,?,?,?)", (sid, panel.now_iso(), 1.0, 2.0, 0))
        banco.execute("DELETE FROM servers WHERE id = ?", (sid,))
    assert banco.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


# ------------------------------------------------------------------- a tela
# (a fixture `chefe` - administrador cadastrado e logado - vem do conftest.py)

def test_a_tela_abre_sem_amostra_nenhuma(banco, chefe):
    sid = register_server(banco, "alvo2", "outro.invalid")
    assert chefe.get(f"/servers/{sid}/graficos").status_code == 200


@pytest.mark.parametrize("faixa", ["6", "24", "168", "999", "abc"])
def test_faixa_de_tempo_nunca_quebra_a_tela(banco, chefe, faixa):
    """Faixa inventada cai na de 24h em vez de estourar."""
    sid = register_server(banco, "alvo2", "outro.invalid")
    assert chefe.get(f"/servers/{sid}/graficos?h={faixa}").status_code == 200


def test_servidor_que_nao_existe_da_404(chefe):
    assert chefe.get("/servers/9999/graficos").status_code == 404
