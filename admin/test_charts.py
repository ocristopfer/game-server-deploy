#!/usr/bin/env python3
"""Testes dos graficos de uso: coleta, retencao e a matematica das coordenadas.

    docker compose exec panel python3 /opt/gamepanel/test_charts.py

A parte que erra num grafico nao e o desenho, e a conta: um buraco virando linha reta faz
o grafico MENTIR (diz que o servidor rodou liso enquanto estava fora do ar), e um valor
fora da moldura vaza por cima do resto da tela. E isso que esta testado aqui.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["GAMEPANEL_DB"] = os.path.join(tempfile.mkdtemp(), "teste.db")

import app as panel  # noqa: E402

falhas = []


def check(nome, condicao, detalhe=""):
    if condicao:
        print(f"  ok   {nome}")
    else:
        print(f"  FALHOU {nome} {detalhe}")
        falhas.append(nome)


def igual(nome, obtido, esperado):
    check(nome, obtido == esperado, f"(obtido {obtido!r}, esperado {esperado!r})")


INICIO = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
FIM = INICIO + timedelta(hours=24)
SERIE_CPU = [{"chave": "cpu", "rotulo": "CPU", "cor": "#3987e5", "sufixo": "%"}]


def amostras(valores, passo_min=5, inicio=None):
    """Lista de (quando, {cpu: v}) espacada de `passo_min`; None vira buraco."""
    base = inicio or INICIO
    return [(base + timedelta(minutes=passo_min * i), {"cpu": v})
            for i, v in enumerate(valores)]


print("Teto do eixo")
igual("pico 11 nao merece eixo ate 20", panel._teto_limpo(11), 12)
igual("pico 0 ainda tem eixo", panel._teto_limpo(0), 1)
igual("pico exato usa o proprio degrau", panel._teto_limpo(10), 10)
igual("pico acima do maior degrau nao quebra", panel._teto_limpo(5000), 5001)


print("Coordenadas")
g = panel.monta_grafico(amostras([0, 50, 100]), SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("uma serie desenhada", len(g["linhas"]), 1)
pontos = g["linhas"][0]["tracos"][0].split()
ys = [float(p.split(",")[1]) for p in pontos]
igual("0 fica na base", ys[0], float(g["b"]))
igual("100 fica no topo", ys[2], float(g["t"]))
check("50 fica no meio", abs(ys[1] - (g["t"] + g["b"]) / 2) < 0.6, f"(y={ys[1]})")

# Valor acima do teto e preso na moldura: sem isso a linha sai por cima do cartao.
g = panel.monta_grafico(amostras([250]), SERIE_CPU, 100, INICIO, FIM, "%H:%M")
todos = [p for l in g["linhas"] for s in (l["tracos"] + l["pontos"]) for p in s.split()]
ys = [float(p.split(",")[1]) for p in todos]
check("valor acima do teto nao vaza da moldura", all(g["t"] <= y <= g["b"] for y in ys))

# Nenhum ponto pode nascer fora da area de plotagem.
g = panel.monta_grafico(amostras([10] * 40), SERIE_CPU, 100, INICIO, FIM, "%H:%M")
xs = [float(p.split(",")[0]) for p in g["linhas"][0]["tracos"][0].split()]
check("x fica dentro da moldura", all(g["l"] - 0.5 <= x <= g["r"] + 0.5 for x in xs),
      f"(x de {min(xs)} a {max(xs)})")


print("Buracos nao viram linha reta")
# Servidor fora do ar: o painel nao grava amostra, e a linha tem de PARTIR. Ligar as duas
# pontas diria que ele rodou liso durante a queda.
longe = amostras([10, 20], passo_min=5)
longe += [(INICIO + timedelta(hours=6), {"cpu": 30}),
          (INICIO + timedelta(hours=6, minutes=5), {"cpu": 40})]
g = panel.monta_grafico(longe, SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("a linha parte em dois", len(g["linhas"][0]["tracos"]), 2)

seguido = amostras([10, 20, 30, 40], passo_min=5)
g = panel.monta_grafico(seguido, SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("amostras seguidas ficam num traco so", len(g["linhas"][0]["tracos"]), 1)

# None no meio (medidor falhou naquela volta) tambem e buraco.
com_falha = [(INICIO + timedelta(minutes=5 * i), {"cpu": v})
             for i, v in enumerate([10, 20, None, 40, 50])]
g = panel.monta_grafico(com_falha, SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("leitura falha parte a linha", len(g["linhas"][0]["tracos"]), 2)

# Amostra sozinha entre dois buracos nao tem comprimento para virar polyline: vira ponto,
# senao ela sumiria do grafico.
sozinha = [(INICIO, {"cpu": 10}),
           (INICIO + timedelta(hours=5), {"cpu": 55}),
           (INICIO + timedelta(hours=10), {"cpu": 20})]
g = panel.monta_grafico(sozinha, SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("amostras soltas viram pontos", len(g["linhas"][0]["pontos"]), 3)
igual("e nenhum traco", len(g["linhas"][0]["tracos"]), 0)

igual("sem amostra nenhuma o grafico se declara vazio",
      panel.monta_grafico([], SERIE_CPU, 100, INICIO, FIM, "%H:%M")["vazio"], True)
igual("serie so com buraco tambem",
      panel.monta_grafico([(INICIO, {"cpu": None})], SERIE_CPU, 100,
                          INICIO, FIM, "%H:%M")["vazio"], True)


print("Rotulo de ponta some quando as linhas se encontram")
DUAS = [{"chave": "cpu", "rotulo": "CPU", "cor": "#3987e5", "sufixo": "%"},
        {"chave": "mem", "rotulo": "Memoria", "cor": "#d95926", "sufixo": "%"}]


def par(cpu_fim, mem_fim):
    return [(INICIO + timedelta(minutes=5 * i), {"cpu": c, "mem": m})
            for i, (c, m) in enumerate([(10, 90), (cpu_fim, mem_fim)])]


g = panel.monta_grafico(par(20, 80), DUAS, 100, INICIO, FIM, "%H:%M")
check("pontas separadas ganham rotulo", g["rotula_ponta"])
# Empilhar dois rotulos que se tocam os desgruda das linhas e vira ruido: melhor nenhum.
g = panel.monta_grafico(par(50, 51), DUAS, 100, INICIO, FIM, "%H:%M")
check("pontas coladas perdem o rotulo", not g["rotula_ponta"])
check("mas o ponto da ponta continua la", all(l["ponta"] for l in g["linhas"]))


print("Grade e eixo do tempo")
g = panel.monta_grafico(amostras([10, 20]), SERIE_CPU, 100, INICIO, FIM, "%H:%M")
igual("tres linhas de grade", [l["rotulo"] for l in g["grade"]], ["0%", "50%", "100%"])
igual("marcas de tempo", len(g["tempos"]), panel.CHART_TICKS)
g = panel.monta_grafico(amostras([1, 2]), [dict(SERIE_CPU[0], chave="cpu", sufixo="")],
                        12, INICIO, FIM, "%H:%M")
igual("grade sem sufixo quando a serie nao tem",
      [l["rotulo"] for l in g["grade"]], ["0", "6", "12"])


print("Coleta e retencao")
conn = panel._connect()
with conn:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('alvo', 'nao-existe.invalid', 22, 'root', 'jogo.service', ?)",
        (panel.now_iso(),))
sid = conn.execute("SELECT id FROM servers").fetchone()["id"]
conn.close()

# Container fora do ar nao vira linha: zero seria mentira ("usou 0% de CPU"), e um buraco
# e a informacao certa.
panel.server_metrics = lambda server, force=False: {"error": "tempo esgotado"}
panel.server_players = lambda server, force=False: {"error": "", "players": 3}
with panel.app.app_context():
    igual("medidor com erro nao grava amostra", panel.coleta_amostras(forcar=True), 0)

panel.server_metrics = lambda server, force=False: {
    "error": "", "cpu_pct": 41.5, "mem": {"pct": 62.0}, "disks": []}
with panel.app.app_context():
    igual("medidor bom grava", panel.coleta_amostras(forcar=True), 1)

conn = panel._connect()
linha = conn.execute("SELECT * FROM samples").fetchone()
igual("gravou os numeros certos", (linha["cpu_pct"], linha["mem_pct"]), (41.5, 62.0))
igual("sem contagem ligada, jogadores fica vazio", linha["players"], None)

# Amostra velha sai junto com a limpeza do historico.
velha = (datetime.now(timezone.utc) - timedelta(days=panel.SAMPLES_KEEP_DAYS + 2)).isoformat()
with conn:
    for _ in range(5):
        conn.execute("INSERT INTO samples (server_id, taken_at, cpu_pct, mem_pct, players)"
                     " VALUES (?,?,?,?,?)", (sid, velha, 1.0, 2.0, 0))
igual("seis amostras no banco", conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 6)
conn.close()

with panel.app.app_context():
    panel.limpa_historico(forcar=True)
conn = panel._connect()
igual("as velhas sairam, a nova ficou",
      conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)

# CASCADE: apagar o servidor leva as amostras dele.
with conn:
    conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
igual("apagar o servidor leva as amostras",
      conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 0)
conn.close()


print("A tela")


def entrar():
    cli = panel.app.test_client()
    cli.get("/login")
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    cli.post("/login", data={"username": "chefe", "password": "senha-do-chefe",
                             "csrf": token})
    return cli


panel.ensure_admin_user("chefe", "senha-do-chefe")
panel._login_fails.clear()
conn = panel._connect()
with conn:
    conn.execute(
        "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
        " VALUES ('alvo2', 'outro.invalid', 22, 'root', 'jogo.service', ?)",
        (panel.now_iso(),))
sid2 = conn.execute("SELECT id FROM servers WHERE name = 'alvo2'").fetchone()["id"]
conn.close()

cli = entrar()
igual("abre sem amostra nenhuma", cli.get(f"/servers/{sid2}/graficos").status_code, 200)
for faixa in ("6", "24", "168"):
    igual(f"faixa de {faixa}h abre", cli.get(f"/servers/{sid2}/graficos?h={faixa}").status_code, 200)
# Faixa inventada cai na de 24h em vez de estourar.
igual("faixa invalida nao quebra", cli.get(f"/servers/{sid2}/graficos?h=999").status_code, 200)
igual("faixa nao numerica nao quebra", cli.get(f"/servers/{sid2}/graficos?h=abc").status_code, 200)
igual("servidor que nao existe da 404", cli.get("/servers/9999/graficos").status_code, 404)


print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
