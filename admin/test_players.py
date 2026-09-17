#!/usr/bin/env python3
"""Testes da contagem de jogadores por API HTTP e da descoberta de portas.

    pytest admin/test_players.py

O que estes testes garantem e a promessa do recurso: o painel le a resposta de uma API
que ele nunca viu antes, sem nada codificado por jogo. Se um jogo novo devolver JSON com
os campos de sempre (players/name, currentplayernum, maxPlayers...), tem que funcionar
sem tocar no codigo.
"""
import os

import pytest

import app as panel

# Permissao de pasta (0o700) e "todo caminho fora de /proc e gravavel" sao POSIX puro:
# o Windows nao aplica bit de dono/grupo/outros do jeito que `os.stat().st_mode`
# reporta, e nao tem um `/proc` que recusa `mkdir`. As duas suites abaixo so fazem
# sentido no container (Debian), que e onde o painel roda de verdade - ver CLAUDE.md.
posix_apenas = pytest.mark.skipif(
    os.name != "posix", reason="permissao de pasta e /proc sao POSIX; valem no container")


def nomes(resultado):
    return [p["name"] for p in resultado["list"]]


def servidor(url, origem="http"):
    return {"http_url": url, "player_source": origem, "query_port": 0,
            "join_re": "", "leave_re": ""}


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


def test_palworld_players_conta_pela_lista():
    r = panel.read_players_json(PALWORLD_PLAYERS)
    assert r["players"] == 2
    assert nomes(r) == ["Cristopfer", "Ana"]


def test_palworld_metrics_conta_por_currentplayernum():
    r = panel.read_players_json(PALWORLD_METRICS)
    assert r["players"] == 3
    assert r["max_players"] == 32
    assert nomes(r) == [], "essa resposta nao tem nome nenhum"


def test_satisfactory_conta_aninhado_em_data():
    r = panel.read_players_json(SATISFACTORY)
    assert r["players"] == 2
    assert r["max_players"] == 4


def test_lista_vazia_vira_zero_nao_erro():
    """A chave 'players' identifica a lista mesmo vazia: ninguem online e resposta valida."""
    assert panel.read_players_json({"players": []})["players"] == 0


def test_lista_solta_na_raiz_da_resposta():
    r = panel.read_players_json([{"name": "Bea"}, {"name": "Caio"}])
    assert nomes(r) == ["Bea", "Caio"]


def test_chave_de_nome_diferente_de_name():
    """O jogo novo nao precisa usar exatamente 'name'."""
    r = panel.read_players_json({"onlinePlayers": [{"playerName": "Duda", "ping": 9}]})
    assert nomes(r) == ["Duda"]


def test_contagem_em_chave_numPlayers():
    assert panel.read_players_json({"result": {"numPlayers": 7, "maxPlayers": 16}})["players"] == 7


def test_nome_do_servidor_quando_existe():
    r = panel.read_players_json({"serverName": "Casa", "numPlayers": 1})
    assert r["server_name"] == "Casa"


def test_resposta_sem_jogador_nenhum_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json({"status": "ok"})


# ------------------------------------------------------- caminhos apontados a mao

def test_caminho_da_lista_apontado_a_mao():
    assert nomes(panel.read_players_json(PALWORLD_PLAYERS, "players")) == ["Cristopfer", "Ana"]


def test_caminho_da_contagem_apontado_a_mao():
    r = panel.read_players_json(
        SATISFACTORY, "", "data.serverGameState.numConnectedPlayers")
    assert r["players"] == 2


def test_caminho_com_indice_de_lista():
    r = panel.read_players_json({"a": [{"lista": [{"name": "Edu"}]}]}, "a[0].lista")
    assert nomes(r) == ["Edu"]


def test_contagem_apontada_para_uma_lista_usa_o_tamanho():
    assert panel.read_players_json(PALWORLD_PLAYERS, "", "players")["players"] == 2


def test_caminho_que_nao_existe_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json(PALWORLD_PLAYERS, "jogadores")


def test_caminho_de_lista_que_nao_e_lista_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json(PALWORLD_METRICS, "serverfps")


# --------------------------------------------------------------- TeamSpeak (WebQuery)

# Resposta real do /1/clientlist: tudo string, nome em client_nickname, e as conexoes de
# ServerQuery misturadas na mesma lista. Uma delas e a DO PAINEL, que acabou de perguntar.
TEAMSPEAK = {
    "body": [
        {"clid": "1", "cid": "1", "client_nickname": "Ana", "client_type": "0"},
        {"clid": "2", "cid": "1", "client_nickname": "Cristopfer", "client_type": "0"},
        {"clid": "9", "cid": "0", "client_nickname": "serveradmin from 127.0.0.1:5",
         "client_type": "1"},
    ],
    "status": {"code": 0, "message": "ok"},
}


def test_teamspeak_le_os_nomes_sem_nada_codificado():
    r = panel.read_players_json(TEAMSPEAK, "body")
    assert nomes(r) == ["Ana", "Cristopfer"]
    assert r["players"] == 2, "a conexao de consulta nao entra na conta"
    assert all("serveradmin" not in n for n in nomes(r)), "o painel nao aparece como usuario"


def test_teamspeak_so_com_a_query_online_da_zero():
    """So de query online: e zero gente no canal, nao "um usuario"."""
    r = panel.read_players_json(
        {"body": [{"clid": "9", "client_nickname": "serveradmin", "client_type": "1"}]}, "body")
    assert r["players"] == 0


def test_jogo_sem_client_type_nao_e_filtrado():
    """client_type ausente (todo o resto dos jogos) nao pode sumir com jogador nenhum."""
    assert nomes(panel.read_players_json([{"name": "Bea"}, {"name": "Caio"}])) == ["Bea", "Caio"]


def test_client_type_ilegivel_nao_derruba_o_jogador():
    """Valor estranho no campo tambem nao: na duvida, o jogador fica."""
    assert nomes(panel.read_players_json([{"name": "Duda", "client_type": "x"}])) == ["Duda"]


# --------------------------------------------------------- autenticacao e status

@pytest.mark.parametrize("bruto, esperado", [
    ("basic:admin:troque-me", "Authorization: Basic YWRtaW46dHJvcXVlLW1l"),
    ("basic:admin:a:b", "Authorization: Basic YWRtaW46YTpi"),  # ':' na senha
    ("bearer:abc123", "Authorization: Bearer abc123"),
    # Cadastro antigo guardava o VALOR solto; continua saindo como Authorization, senao
    # trocar esta funcao calaria a contagem de quem ja tinha um token gravado.
    ("ApiKey xyz", "Authorization: ApiKey xyz"),
    ("header:x-api-key: SEGREDO", "x-api-key: SEGREDO"),
    ("  ", ""),
    # 'header:' sem os dois pontos do nome nao e cabecalho nenhum; cai na regra antiga.
    ("header:coisa", "Authorization: header:coisa"),
])
def test_auth_header(bruto, esperado):
    """auth_header devolve o cabecalho INTEIRO ('Nome: valor'), nao so o valor: ha API
    que nao autentica por Authorization, e com so o valor o nome seria sempre o mesmo."""
    assert panel.auth_header(bruto) == esperado


def test_split_status_separa_do_corpo():
    assert panel._split_status('{"a":1}\n__HTTP_STATUS__200') == ('{"a":1}', 200)


def test_split_status_sem_marcador_fica_zero():
    assert panel._split_status("resposta crua") == ("resposta crua", 0)


# ---------------------------------------------------------------------------- URL

@pytest.mark.parametrize("url, aceita", [
    ("http://127.0.0.1:8212/v1/api/players", True),
    ("https://127.0.0.1:7777/api/v1", True),
    ("127.0.0.1:8212/x", False),          # sem esquema
    ("file:///etc/passwd", False),
    ("http://127.0.0.1:8212/a b", False), # espaco
])
def test_url_re(url, aceita):
    assert bool(panel.URL_RE.match(url)) is aceita


# ------------------------------------------------------------- descoberta de portas

def test_portas_do_texto_livre():
    assert panel._portas_do_texto("8211/udp 27015/udp") == [8211, 27015]


def test_sem_repetir_e_sem_a_porta_do_ssh():
    assert panel._sem_repetir([8211, 22, 8211, 27015, 99999]) == [8211, 27015]


# Os tres estados que a tela precisa diferenciar, vindos do mapa porta -> dono.
DONOS = {
    ("tcp", 8212): {"pid": 40, "proc": "PalServer-Linu", "infra": False},
    ("tcp", 22): {"pid": 1, "proc": "sshd", "infra": True},
    ("tcp", 33039): {"pid": 0, "proc": "?", "infra": False},
}


def test_com_dono_classifica_cada_porta():
    itens = panel._com_dono(
        [{"port": 8212}, {"port": 22}, {"port": 33039}, {"port": 7777}], DONOS, "tcp")
    assert (itens[0]["origem"], itens[0]["proc"], itens[0]["pid"]) == (
        "detectada", "PalServer-Linu", 40)
    assert (itens[1]["origem"], itens[1]["infra"]) == ("detectada", True), "sshd e infra"
    assert itens[2]["origem"] == "sem-dono", "socket aberto sem processo dono no container"
    assert itens[3]["origem"] == "nao-vista", "porta que nunca esteve aberta e chute"


def test_resume_genericos_agrupa_porta_404_em_tudo():
    """A sondagem so vale a pena onde ha resposta util: porta que devolve 404 em tudo
    vira uma linha marcada, nao uma para cada caminho testado."""
    brutos = [
        {"port": 33039, "path": p, "status": 404, "content_type": "text/html",
         "scheme": "http", "url": f"http://127.0.0.1:33039{p}"}
        for p in ("/", "/v1/api/info", "/v1/api/players", "/status")
    ] + [
        {"port": 8212, "path": "/v1/api/players", "status": 401,
         "content_type": "application/json", "scheme": "http", "url": "x"},
        {"port": 8212, "path": "/status", "status": 404,
         "content_type": "application/json", "scheme": "http", "url": "x"},
    ]
    resumo = panel._resume_genericos(brutos)
    assert [(i["port"], i["path"], i.get("generico", False))
            for i in resumo if i["port"] == 33039] == [(33039, "/", True)]
    assert [(i["port"], i["path"]) for i in resumo if i["port"] == 8212] == [
        (8212, "/v1/api/players")], "guarda so as rotas uteis"


# ------------------------------------------------------------------ nomes do log

def test_dayz_adm_nome_nos_dois_lados_da_lista_exata():
    """Nome nos DOIS lados (DayZ pelo .ADM): da para dizer exatamente quem ficou."""
    linhas = [
        '16:21:58 | Player "Cristopfer" is connected (id=QnVIrhpDQ=)',
        '16:22:04 | Player "Guilherme" is connected (id=AbCdEfGh=)',
        '16:23:10 | Player "Cristopfer"(id=QnVIrhpDQ=) has been disconnected',
        '16:24:00 | Player "Ana" is connected (id=ZZZZ0000=)',
    ]
    entra = panel.compile_pattern(r'Player "(?P<name>[^"]+)" is connected', "entrada")
    sai = panel.compile_pattern(
        r'Player "(?P<name>[^"]+)"\(id=[^)]*\) has been disconnected', "saida")
    r = panel._apply_log_events(linhas, entra, sai)
    assert [p["name"] for p in r["list"]] == ["Guilherme", "Ana"]
    assert r["players"] == 2
    assert not r.get("aproximado")


def test_enshrouded_journalctl_nome_nos_dois_lados():
    linhas = [
        "Sep 03 13:46:31 enshrouded start-enshrouded.sh[83856]: [server] Player 'Cristopfer' logged in with Permissions:",
        "Sep 03 13:46:35 enshrouded start-enshrouded.sh[83856]: [server] Player 'Amigo' logged in with Permissions:",
        "Sep 03 13:47:36 enshrouded start-enshrouded.sh[83856]: [server] Remove Player 'Cristopfer'",
    ]
    entra = panel.compile_pattern(r"\[server\] Player '(?P<name>[^']+)' logged in", "entrada")
    sai = panel.compile_pattern(r"\[server\] Remove Player '(?P<name>[^']+)'", "saida")
    r = panel._apply_log_events(linhas, entra, sai)
    assert [p["name"] for p in r["list"]] == ["Amigo"]
    assert r["players"] == 1
    assert not r.get("aproximado")


def test_satisfactory_nome_so_na_entrada_e_aproximado():
    """O log avisa que alguem saiu, sem dizer quem."""
    linhas = [
        "LogNet: Join succeeded: Cristopfer",
        "LogNet: Join succeeded: Guilherme",
        "LogNet: UNetConnection::Close: [UNetConnection] ...",
        "LogNet: Join succeeded: Ana",
    ]
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    sai = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(linhas, entra, sai)
    # A contagem continua sendo entradas menos saidas, igual a de antes desta melhoria.
    assert r["players"] == 2
    assert [p["name"] for p in r["list"]] == ["Guilherme", "Ana"], "mostra os ultimos a entrar"
    assert r.get("aproximado")


def test_reconexao_nao_duplica_o_nome():
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    sai = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(
        ["LogNet: Join succeeded: Ana", "LogNet: Join succeeded: Ana"], entra, sai)
    assert [p["name"] for p in r["list"]] == ["Ana"]


def test_sem_nome_em_lugar_nenhum_so_a_contagem():
    entra = panel.compile_pattern("alguem entrou", "entrada")
    sai = panel.compile_pattern("alguem saiu", "saida")
    r = panel._apply_log_events(["alguem entrou", "alguem entrou", "alguem saiu"], entra, sai)
    assert (r["players"], r["list"]) == (1, [])


def test_mais_saidas_que_entradas_nao_fica_negativo():
    """Log cortado no comeco: mais saidas do que entradas nao pode virar contagem negativa."""
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    sai = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(
        ["LogNet: UNetConnection::Close: x", "LogNet: UNetConnection::Close: y"], entra, sai)
    assert r["players"] == 0


# ------------------------------------------------------------ caminho de log

def test_log_path_vazio_continua_vazio():
    """Vazio significa "usa o journalctl"."""
    assert panel.log_path_valido("") == ""


def test_log_path_simples_passa():
    assert panel.log_path_valido("/opt/game/game.log") == "/opt/game/game.log"


def test_log_path_com_asterisco_passa():
    """O DayZ abre um .ADM por sessao; o '*' pega sempre o mais novo."""
    assert panel.log_path_valido("/opt/game/profiles/*.ADM") == "/opt/game/profiles/*.ADM"


@pytest.mark.parametrize("ruim", [
    "/tmp/x.log; touch /tmp/invadiu", "/opt/game/$(id).log", "/opt/game/`id`.log",
    "/opt/game/x.log|id", "/opt/game/a b.log", "relativo/x.log",
    "/opt/../../etc/shadow", "/opt/game/x.log&", "/opt/game/'x'.log",
])
def test_log_path_torto_e_recusado(ruim):
    """O caminho entra SEM aspas no comando remoto (para o shell expandir o '*'), entao
    tudo que o shell interpretaria de outro jeito tem de morrer aqui."""
    with pytest.raises(ValueError):
        panel.log_path_valido(ruim)


# --------------------------------------------------------------- acoes sobre jogadores

@pytest.mark.parametrize("item, esperado", [
    ({"name": "Ana", "userId": "steam_123"}, "steam_123"),
    ({"name": "Ana", "player_uid": "AB01"}, "AB01"),           # outra grafia
    ({"name": "Ana", "playerid": 42}, "42"),                   # numero tambem vale
    ({"name": "Ana", "ping": 12}, ""),                         # sem identificador
    ({"name": "Ana", "uid": True}, ""),                        # booleano nao e id
])
def test_id_do_item(item, esperado):
    """Kick e ban pedem um identificador; o nome nao serve porque muda e repete."""
    assert panel._id_do_item(item) == esperado


def test_id_entra_na_lista_normalizada_ao_lado_do_nome():
    lido = panel.read_players_json(
        {"players": [{"name": "Ana", "userId": "steam_1"}, {"name": "Bea"}]})
    assert [p["id"] for p in lido["list"]] == ["steam_1", ""]


def test_api_de_acoes_reconhece_o_palworld():
    api = panel.api_de_acoes(servidor("http://127.0.0.1:8212/v1/api/players"))
    assert api is not None
    assert api["base"] == "http://127.0.0.1:8212/v1/api"
    assert sorted(api["acoes"]) == ["announce", "ban", "kick"]


def test_api_de_acoes_aceita_barra_no_fim():
    api = panel.api_de_acoes(servidor("http://127.0.0.1:8212/v1/api/players/"))
    assert api is not None
    assert api["base"] == "http://127.0.0.1:8212/v1/api"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:7777/api/v1", "http://127.0.0.1:8212/v1/api/metrics",
    "http://127.0.0.1:8212/players", "",
])
def test_acoes_de_jogador_nao_inventa_para_url_desconhecida(url):
    """A tela so mostra o que existe do outro lado."""
    assert panel.acoes_de_jogador(servidor(url)) == []


def test_contagem_pelo_log_nao_tem_acao():
    assert panel.acoes_de_jogador(
        servidor("http://127.0.0.1:8212/v1/api/players", "log")) == []


def test_preenche_nao_quebra_com_chave_solta_na_mensagem():
    """A mensagem vem de quem digita: uma chave solta nao pode estourar a montagem."""
    assert panel._preenche("{mensagem}", "b", "j", "olha o {isso} ai") == "olha o {isso} ai"


def test_preenche_troca_os_tres_marcadores():
    assert panel._preenche("{base}/x/{jogador}/{mensagem}", "http://a/v1", "id7", "oi") == \
        "http://a/v1/x/id7/oi"


# --------------------------------------------------------------- SSH: reaproveitar

@pytest.fixture
def diretorio_de_controle(tmp_path, monkeypatch):
    """Aponta `SSH_CONTROL_DIR` para uma pasta descartavel, e a devolve pronta para uso."""
    caminho = tmp_path / "ssh-control"
    monkeypatch.setattr(panel, "SSH_CONTROL_DIR", str(caminho))
    return caminho


ALVO_SSH = {"ssh_port": 22, "ssh_user": "root", "host": "10.0.0.9"}


def test_conexao_curta_reaproveita_via_control_master(diretorio_de_controle):
    """Sem reaproveitar, cada leitura do monitor paga TCP + troca de chaves +
    autenticacao para depois rodar um comando de milissegundos. Com varias leituras
    por minuto por servidor, o aperto de mao vira o grosso do custo."""
    curto = panel.ssh_argv(ALVO_SSH, multiplex=True)
    assert "ControlMaster=auto" in curto
    assert any(o.startswith("ControlPath=") for o in curto)
    assert any(o.startswith("ControlPersist=") for o in curto)
    assert os.path.isdir(panel.SSH_CONTROL_DIR)


@posix_apenas
def test_pasta_do_socket_so_o_dono_enxerga(diretorio_de_controle):
    """O socket da acesso a uma sessao JA autenticada nos containers: ninguem alem do
    painel pode entrar nessa pasta."""
    panel.ssh_argv(ALVO_SSH, multiplex=True)
    assert oct(os.stat(panel.SSH_CONTROL_DIR).st_mode)[-3:] == "700"


def test_padrao_e_nao_reaproveitar_conexao():
    """Terminal, upload e download NAO dividem conexao: o terminal segura a sessao por
    horas e um arquivo de varios GB entupiria o TCP compartilhado, travando o monitor
    atras dele."""
    assert [o for o in panel.ssh_argv(ALVO_SSH) if "Control" in o] == []


@posix_apenas
def test_pasta_impossivel_nao_derruba_o_ssh(monkeypatch):
    """Sem poder criar a pasta, seguir sem reaproveitar e melhor do que nao falar SSH."""
    monkeypatch.setattr(panel, "SSH_CONTROL_DIR", "/proc/impossivel/ssh-control")
    assert [o for o in panel.ssh_argv(ALVO_SSH, multiplex=True) if "Control" in o] == []
