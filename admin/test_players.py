#!/usr/bin/env python3
"""Testes da contagem de jogadores por API HTTP e da descoberta de portas.

Sem dependencia externa alem do Flask que o painel ja usa:

    docker compose exec panel python3 /opt/gamepanel/test_players.py

O que estes testes garantem e a promessa do recurso: o painel le a resposta de uma API
que ele nunca viu antes, sem nada codificado por jogo. Se um jogo novo devolver JSON com
os campos de sempre (players/name, currentplayernum, maxPlayers...), tem que funcionar
sem tocar no codigo.
"""
import os
import tempfile

# O import de app.py cria/migra o banco: aponta para um arquivo descartavel.
os.environ.setdefault("GAMEPANEL_DB", os.path.join(tempfile.mkdtemp(), "teste.db"))

import app as panel  # noqa: E402

falhas = []


def check(nome, condicao, detalhe=""):
    if condicao:
        print(f"  ok   {nome}")
    else:
        print(f"  FALHOU {nome} {detalhe}")
        falhas.append(nome)


def igual(nome, obtido, esperado):
    check(nome, obtido == esperado, f"\n    obtido:   {obtido!r}\n    esperado: {esperado!r}")


def erro(nome, funcao, *args):
    try:
        funcao(*args)
    except panel.QueryError:
        print(f"  ok   {nome}")
        return
    print(f"  FALHOU {nome} (nao levantou QueryError)")
    falhas.append(nome)


def nomes(resultado):
    return [p["name"] for p in resultado["list"]]


# ------------------------------------------------------------------ respostas reais

# Formato do /v1/api/players do Palworld.
PALWORLD_PLAYERS = {
    "players": [
        {"name": "Cristopfer", "accountName": "steam_0", "playerId": "0000000A",
         "userId": "steam_76561198000000001", "ip": "10.0.0.20", "ping": 12.5,
         "location_x": 1.0, "location_y": 2.0, "level": 8, "building_count": 3},
        {"name": "Ana", "accountName": "steam_1", "playerId": "0000000B",
         "userId": "steam_76561198000000002", "ip": "10.0.0.21", "ping": 30.0,
         "location_x": 3.0, "location_y": 4.0, "level": 5, "building_count": 0},
    ]
}

# Formato do /v1/api/metrics do Palworld: so numeros, nenhuma lista.
PALWORLD_METRICS = {
    "serverfps": 60, "currentplayernum": 3, "serverframetime": 16.67,
    "maxplayernum": 32, "uptime": 4210, "days": 5, "basecampnum": 2,
}

# Formato do QueryServerState do Satisfactory: tudo aninhado dentro de data.
SATISFACTORY = {
    "data": {
        "serverGameState": {
            "activeSessionName": "Fabrica",
            "numConnectedPlayers": 2,
            "playerLimit": 4,
            "techTier": 6,
            "isGamePaused": False,
        }
    }
}


print("API HTTP: descoberta automatica")
r = panel.read_players_json(PALWORLD_PLAYERS)
igual("Palworld /players conta pela lista", r["players"], 2)
igual("Palworld /players pega os nomes", nomes(r), ["Cristopfer", "Ana"])

r = panel.read_players_json(PALWORLD_METRICS)
igual("Palworld /metrics conta por currentplayernum", r["players"], 3)
igual("Palworld /metrics acha o maximo", r["max_players"], 32)
igual("Palworld /metrics nao inventa nomes", nomes(r), [])

r = panel.read_players_json(SATISFACTORY)
igual("Satisfactory conta aninhado", r["players"], 2)
igual("Satisfactory acha o playerLimit", r["max_players"], 4)

# Ninguem online e uma resposta valida: a chave 'players' identifica a lista mesmo vazia.
r = panel.read_players_json({"players": []})
igual("lista vazia vira zero, nao erro", r["players"], 0)

# Lista solta na raiz, sem objeto em volta.
r = panel.read_players_json([{"name": "Bea"}, {"name": "Caio"}])
igual("lista na raiz da resposta", nomes(r), ["Bea", "Caio"])

# Chave de nome diferente: o jogo novo nao precisa usar exatamente 'name'.
r = panel.read_players_json({"onlinePlayers": [{"playerName": "Duda", "ping": 9}]})
igual("nome em playerName", nomes(r), ["Duda"])

r = panel.read_players_json({"result": {"numPlayers": 7, "maxPlayers": 16}})
igual("contagem em numPlayers", r["players"], 7)

igual("nome do servidor quando existe",
      panel.read_players_json({"serverName": "Casa", "numPlayers": 1})["server_name"], "Casa")

erro("resposta sem jogador nenhum reclama", panel.read_players_json, {"status": "ok"})


print("API HTTP: caminhos apontados a mao")
igual("caminho da lista",
      nomes(panel.read_players_json(PALWORLD_PLAYERS, "players")), ["Cristopfer", "Ana"])
igual("caminho da contagem",
      panel.read_players_json(SATISFACTORY, "", "data.serverGameState.numConnectedPlayers")["players"], 2)
igual("caminho com indice",
      nomes(panel.read_players_json({"a": [{"lista": [{"name": "Edu"}]}]}, "a[0].lista")), ["Edu"])
igual("contagem apontada para uma lista usa o tamanho",
      panel.read_players_json(PALWORLD_PLAYERS, "", "players")["players"], 2)
erro("caminho que nao existe reclama", panel.read_players_json, PALWORLD_PLAYERS, "jogadores")
erro("caminho de lista que nao e lista reclama", panel.read_players_json, PALWORLD_METRICS, "serverfps")


print("API HTTP: autenticacao e status")
igual("basic vira base64", panel.auth_header("basic:admin:troque-me"),
      "Basic YWRtaW46dHJvcXVlLW1l")
igual("basic com ':' na senha", panel.auth_header("basic:admin:a:b"),
      "Basic YWRtaW46YTpi")
igual("bearer", panel.auth_header("bearer:abc123"), "Bearer abc123")
igual("cabecalho pronto passa direto", panel.auth_header("ApiKey xyz"), "ApiKey xyz")
igual("vazio nao vira cabecalho", panel.auth_header("  "), "")

igual("status separado do corpo",
      panel._split_status('{"a":1}\n__HTTP_STATUS__200'), ('{"a":1}', 200))
igual("sem marcador o status fica zero",
      panel._split_status("resposta crua"), ("resposta crua", 0))


print("API HTTP: URL")
check("URL local aceita", bool(panel.URL_RE.match("http://127.0.0.1:8212/v1/api/players")))
check("HTTPS aceito", bool(panel.URL_RE.match("https://127.0.0.1:7777/api/v1")))
check("sem esquema recusado", not panel.URL_RE.match("127.0.0.1:8212/x"))
check("file:// recusado", not panel.URL_RE.match("file:///etc/passwd"))
check("espaco recusado", not panel.URL_RE.match("http://127.0.0.1:8212/a b"))


print("Descoberta de portas")
igual("portas do texto livre",
      panel._portas_do_texto("8211/udp 27015/udp"), [8211, 27015])
igual("sem repetir e sem a porta do ssh",
      panel._sem_repetir([8211, 22, 8211, 27015, 99999]), [8211, 27015])

# Os tres estados que a tela precisa diferenciar, vindos do mapa porta -> dono.
DONOS = {
    ("tcp", 8212): {"pid": 40, "proc": "PalServer-Linu", "infra": False},
    ("tcp", 22): {"pid": 1, "proc": "sshd", "infra": True},
    ("tcp", 33039): {"pid": 0, "proc": "?", "infra": False},
}
itens = panel._com_dono(
    [{"port": 8212}, {"port": 22}, {"port": 33039}, {"port": 7777}], DONOS, "tcp")
igual("porta do jogo tem processo dono",
      (itens[0]["origem"], itens[0]["proc"], itens[0]["pid"]), ("detectada", "PalServer-Linu", 40))
igual("sshd marcado como infra", (itens[1]["origem"], itens[1]["infra"]), ("detectada", True))
igual("socket aberto sem processo dono no container", itens[2]["origem"], "sem-dono")
igual("porta que nunca esteve aberta e chute", itens[3]["origem"], "nao-vista")

# A sondagem so vale a pena onde ha resposta util: porta que devolve 404 em tudo vira
# uma linha marcada, nao uma para cada caminho testado.
BRUTOS = [
    {"port": 33039, "path": p, "status": 404, "content_type": "text/html",
     "scheme": "http", "url": f"http://127.0.0.1:33039{p}"}
    for p in ("/", "/v1/api/info", "/v1/api/players", "/status")
] + [
    {"port": 8212, "path": "/v1/api/players", "status": 401,
     "content_type": "application/json", "scheme": "http", "url": "x"},
    {"port": 8212, "path": "/status", "status": 404,
     "content_type": "application/json", "scheme": "http", "url": "x"},
]
resumo = panel._resume_genericos(BRUTOS)
igual("porta 404-em-tudo vira uma linha so",
      [(i["port"], i["path"], i.get("generico", False)) for i in resumo if i["port"] == 33039],
      [(33039, "/", True)])
igual("porta com API guarda so as rotas uteis",
      [(i["port"], i["path"]) for i in resumo if i["port"] == 8212],
      [(8212, "/v1/api/players")])

print("Nomes vindos do log")
LINHAS_ADM = [
    '16:21:58 | Player "Cristopfer" is connected (id=QnVIrhpDQ=)',
    '16:22:04 | Player "Guilherme" is connected (id=AbCdEfGh=)',
    '16:23:10 | Player "Cristopfer"(id=QnVIrhpDQ=) has been disconnected',
    '16:24:00 | Player "Ana" is connected (id=ZZZZ0000=)',
]
ENTRA_DZ = panel.compile_pattern(r'Player "(?P<name>[^"]+)" is connected', "entrada")
SAI_DZ = panel.compile_pattern(
    r'Player "(?P<name>[^"]+)"\(id=[^)]*\) has been disconnected', "saida")

# Nome nos DOIS lados (DayZ pelo .ADM): da para dizer exatamente quem ficou.
r = panel._apply_log_events(LINHAS_ADM, ENTRA_DZ, SAI_DZ)
igual("com nome nos dois lados, a lista e exata",
      [p["name"] for p in r["list"]], ["Guilherme", "Ana"])
igual("e a contagem bate", r["players"], 2)
check("e nao se declara aproximada", not r.get("aproximado"))

# Nome nos DOIS lados (Enshrouded pelo journalctl):
LINHAS_ENSH = [
    "Sep 03 13:46:31 enshrouded start-enshrouded.sh[83856]: [server] Player 'Cristopfer' logged in with Permissions:",
    "Sep 03 13:46:35 enshrouded start-enshrouded.sh[83856]: [server] Player 'Amigo' logged in with Permissions:",
    "Sep 03 13:47:36 enshrouded start-enshrouded.sh[83856]: [server] Remove Player 'Cristopfer'",
]
ENTRA_ENSH = panel.compile_pattern(r"\[server\] Player '(?P<name>[^']+)' logged in", "entrada")
SAI_ENSH = panel.compile_pattern(r"\[server\] Remove Player '(?P<name>[^']+)'", "saida")
r = panel._apply_log_events(LINHAS_ENSH, ENTRA_ENSH, SAI_ENSH)
igual("Enshrouded lista quem ficou online", [p["name"] for p in r["list"]], ["Amigo"])
igual("Enshrouded contagem bate", r["players"], 1)
check("Enshrouded lista nao e aproximada", not r.get("aproximado"))

# Nome so na ENTRADA (Satisfactory): o log avisa que alguem saiu, sem dizer quem.
LINHAS_SAT = [
    "LogNet: Join succeeded: Cristopfer",
    "LogNet: Join succeeded: Guilherme",
    "LogNet: UNetConnection::Close: [UNetConnection] ...",
    "LogNet: Join succeeded: Ana",
]
ENTRA_SF = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
SAI_SF = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
r = panel._apply_log_events(LINHAS_SAT, ENTRA_SF, SAI_SF)
# A contagem continua sendo entradas menos saidas, igual a de antes desta melhoria.
igual("contagem exata mesmo sem saber quem saiu", r["players"], 2)
igual("mostra os ultimos a entrar", [p["name"] for p in r["list"]], ["Guilherme", "Ana"])
check("e se declara aproximada", r.get("aproximado"))

# Reconexao nao pode duplicar o mesmo nome na lista.
r = panel._apply_log_events(
    ["LogNet: Join succeeded: Ana", "LogNet: Join succeeded: Ana"], ENTRA_SF, SAI_SF)
igual("reconexao nao duplica o nome", [p["name"] for p in r["list"]], ["Ana"])

# Sem nome em lugar nenhum: sobra a contagem, como sempre foi.
r = panel._apply_log_events(
    ["alguem entrou", "alguem entrou", "alguem saiu"],
    panel.compile_pattern("alguem entrou", "entrada"),
    panel.compile_pattern("alguem saiu", "saida"))
igual("sem nome nenhum, so a contagem", (r["players"], r["list"]), (1, []))

# Mais saidas do que entradas (log cortado no comeco) nao pode virar contagem negativa.
r = panel._apply_log_events(
    ["LogNet: UNetConnection::Close: x", "LogNet: UNetConnection::Close: y"],
    ENTRA_SF, SAI_SF)
igual("saida sem entrada nao fica negativo", r["players"], 0)


print("Caminho do arquivo de log")
igual("vazio continua vazio (usa o journalctl)", panel.log_path_valido(""), "")
igual("caminho simples passa", panel.log_path_valido("/opt/game/game.log"), "/opt/game/game.log")
igual("com * passa (o DayZ abre um .ADM por sessao)",
      panel.log_path_valido("/opt/game/profiles/*.ADM"), "/opt/game/profiles/*.ADM")
# O caminho entra SEM aspas no comando remoto (para o shell expandir o '*'), entao tudo
# que o shell interpretaria de outro jeito tem de morrer aqui.
for ruim in ("/tmp/x.log; touch /tmp/invadiu", "/opt/game/$(id).log", "/opt/game/`id`.log",
             "/opt/game/x.log|id", "/opt/game/a b.log", "relativo/x.log",
             "/opt/../../etc/shadow", "/opt/game/x.log&", "/opt/game/'x'.log"):
    try:
        panel.log_path_valido(ruim)
        check(f"recusa {ruim!r}", False, "(aceitou!)")
    except ValueError:
        check(f"recusa {ruim!r}", True)


print("Acoes sobre jogadores")
# Kick e ban pedem um identificador; o nome nao serve porque muda e repete.
igual("acha o userId", panel._id_do_item({"name": "Ana", "userId": "steam_123"}), "steam_123")
igual("aceita outras grafias", panel._id_do_item({"name": "Ana", "player_uid": "AB01"}), "AB01")
igual("numero tambem vale", panel._id_do_item({"name": "Ana", "playerid": 42}), "42")
igual("sem identificador devolve vazio", panel._id_do_item({"name": "Ana", "ping": 12}), "")
igual("booleano nao e identificador", panel._id_do_item({"name": "Ana", "uid": True}), "")

# O id entra na lista normalizada, ao lado do nome.
lido = panel.read_players_json({"players": [{"name": "Ana", "userId": "steam_1"},
                                            {"name": "Bea"}]})
igual("id vem junto na lista", [p["id"] for p in lido["list"]], ["steam_1", ""])


def servidor(url, origem="http"):
    return {"http_url": url, "player_source": origem, "query_port": 0,
            "join_re": "", "leave_re": ""}


api = panel.api_de_acoes(servidor("http://127.0.0.1:8212/v1/api/players"))
check("reconhece a API do Palworld", api is not None)
igual("acha a raiz da API", api["base"], "http://127.0.0.1:8212/v1/api")
igual("oferece as tres acoes", sorted(api["acoes"]), ["announce", "ban", "kick"])
igual("com barra no fim tambem",
      panel.api_de_acoes(servidor("http://127.0.0.1:8212/v1/api/players/"))["base"],
      "http://127.0.0.1:8212/v1/api")

# URL que nao e de API conhecida nao pode oferecer botao nenhum: a tela so mostra o que
# existe do outro lado.
for url in ("http://127.0.0.1:7777/api/v1", "http://127.0.0.1:8212/v1/api/metrics",
            "http://127.0.0.1:8212/players", ""):
    igual(f"nao inventa acao para {url!r}", panel.acoes_de_jogador(servidor(url)), [])
igual("contagem pelo log nao tem acao",
      panel.acoes_de_jogador(servidor("http://127.0.0.1:8212/v1/api/players", "log")), [])

# A mensagem vem de quem digita: uma chave solta nao pode estourar a montagem do corpo.
igual("chave solta na mensagem nao quebra",
      panel._preenche("{mensagem}", "b", "j", "olha o {isso} ai"), "olha o {isso} ai")
igual("troca os tres marcadores",
      panel._preenche("{base}/x/{jogador}/{mensagem}", "http://a/v1", "id7", "oi"),
      "http://a/v1/x/id7/oi")

print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    raise SystemExit(1)
print("todos os testes passaram")
