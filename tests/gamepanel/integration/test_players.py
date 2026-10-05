#!/usr/bin/env python3
"""Tests for counting players through an HTTP API and for port discovery.

    pytest admin/test_players.py

What these tests guarantee is the feature's promise: the panel reads the response of an API
it has never seen before, with nothing hardcoded per game. If a new game returns JSON with
the usual fields (players/name, currentplayernum, maxPlayers...), it has to work
without touching the code.
"""
import os

import pytest

from gamepanel import app as panel

# Folder permission (0o700) and "every path outside /proc is writable" are pure POSIX:
# Windows does not apply owner/group/other bits the way `os.stat().st_mode`
# reports them, and has no `/proc` that refuses `mkdir`. The two suites below only make
# sense in the container (Debian), which is where the panel really runs - see CLAUDE.md.
posix_apenas = pytest.mark.skipif(
    os.name != "posix", reason="permissao de pasta e /proc sao POSIX; valem no container")


def names(result):
    return [p["name"] for p in result["list"]]


def server(url, origin="http"):
    return {"http_url": url, "player_source": origin, "query_port": 0,
            "join_re": "", "leave_re": ""}


# ------------------------------------------------------------------ real responses

# Format of Palworld's /v1/api/players.
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

# Format of Palworld's /v1/api/metrics: numbers only, no list.
PALWORLD_METRICS = {
    "serverfps": 60, "currentplayernum": 3, "serverframetime": 16.67,
    "maxplayernum": 32, "uptime": 4210, "days": 5, "basecampnum": 2,
}

# Format of Satisfactory's QueryServerState: everything nested inside data.
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
    assert names(r) == ["Cristopfer", "Ana"]


def test_palworld_metrics_conta_por_currentplayernum():
    r = panel.read_players_json(PALWORLD_METRICS)
    assert r["players"] == 3
    assert r["max_players"] == 32
    assert names(r) == [], "essa resposta nao tem nome nenhum"


def test_satisfactory_conta_aninhado_em_data():
    r = panel.read_players_json(SATISFACTORY)
    assert r["players"] == 2
    assert r["max_players"] == 4


def test_lista_vazia_vira_zero_nao_erro():
    """The 'players' key identifies the list even when empty: nobody online is a valid answer."""
    assert panel.read_players_json({"players": []})["players"] == 0


def test_lista_solta_na_raiz_da_resposta():
    r = panel.read_players_json([{"name": "Bea"}, {"name": "Caio"}])
    assert names(r) == ["Bea", "Caio"]


def test_chave_de_nome_diferente_de_name():
    """The new game does not need to use exactly 'name'."""
    r = panel.read_players_json({"onlinePlayers": [{"playerName": "Duda", "ping": 9}]})
    assert names(r) == ["Duda"]


def test_contagem_em_chave_numPlayers():
    assert panel.read_players_json({"result": {"numPlayers": 7, "maxPlayers": 16}})["players"] == 7


def test_nome_do_servidor_quando_existe():
    r = panel.read_players_json({"serverName": "Casa", "numPlayers": 1})
    assert r["server_name"] == "Casa"


def test_resposta_sem_jogador_nenhum_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json({"status": "ok"})


# ------------------------------------------------------- paths pointed by hand

def test_caminho_da_lista_apontado_a_mao():
    assert names(panel.read_players_json(PALWORLD_PLAYERS, "players")) == ["Cristopfer", "Ana"]


def test_caminho_da_contagem_apontado_a_mao():
    r = panel.read_players_json(
        SATISFACTORY, "", "data.serverGameState.numConnectedPlayers")
    assert r["players"] == 2


def test_caminho_com_indice_de_lista():
    r = panel.read_players_json({"a": [{"lista": [{"name": "Edu"}]}]}, "a[0].lista")
    assert names(r) == ["Edu"]


def test_contagem_apontada_para_uma_lista_usa_o_tamanho():
    assert panel.read_players_json(PALWORLD_PLAYERS, "", "players")["players"] == 2


def test_caminho_que_nao_existe_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json(PALWORLD_PLAYERS, "jogadores")


def test_caminho_de_lista_que_nao_e_lista_reclama():
    with pytest.raises(panel.QueryError):
        panel.read_players_json(PALWORLD_METRICS, "serverfps")


# ----------------------------------------------------------- TeamSpeak through WebQuery

# Real /1/clientlist response: everything is a string, name in client_nickname, and the
# ServerQuery connections mixed into the same list. One of them is THE PANEL's, which just asked.
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
    assert names(r) == ["Ana", "Cristopfer"]
    assert r["players"] == 2, "a conexao de consulta nao entra na conta"
    assert all("serveradmin" not in n for n in names(r)), "o painel nao aparece como usuario"


def test_teamspeak_so_com_a_query_online_da_zero():
    """Only query clients online: that is zero people in the channel, not "one user"."""
    r = panel.read_players_json(
        {"body": [{"clid": "9", "client_nickname": "serveradmin", "client_type": "1"}]}, "body")
    assert r["players"] == 0


def test_jogo_sem_client_type_nao_e_filtrado():
    """A missing client_type (every other game) must not make any player disappear."""
    assert names(panel.read_players_json([{"name": "Bea"}, {"name": "Caio"}])) == ["Bea", "Caio"]


def test_client_type_ilegivel_nao_derruba_o_jogador():
    """A strange value in the field must not either: when in doubt, the player stays."""
    assert names(panel.read_players_json([{"name": "Duda", "client_type": "x"}])) == ["Duda"]


# --------------------------------------------------------- authentication and status

@pytest.mark.parametrize("raw, expected", [
    ("basic:admin:troque-me", "Authorization: Basic YWRtaW46dHJvcXVlLW1l"),
    ("basic:admin:a:b", "Authorization: Basic YWRtaW46YTpi"),  # ':' in the password
    ("bearer:abc123", "Authorization: Bearer abc123"),
    # Old registrations stored the bare VALUE; it still goes out as Authorization, otherwise
    # changing this function would silence the count for whoever already had a token saved.
    ("ApiKey xyz", "Authorization: ApiKey xyz"),
    ("header:x-api-key: SEGREDO", "x-api-key: SEGREDO"),
    ("  ", ""),
    # 'header:' without the colon of the name is no header at all; falls back to the old rule.
    ("header:coisa", "Authorization: header:coisa"),
])
def test_auth_header(raw, expected):
    """auth_header returns the WHOLE header ('Name: value'), not just the value: some APIs
    do not authenticate via Authorization, and with only the value the name would always be the same."""
    assert panel.auth_header(raw) == expected


def test_split_status_separa_do_corpo():
    assert panel._split_status('{"a":1}\n__HTTP_STATUS__200') == ('{"a":1}', 200)


def test_split_status_sem_marcador_fica_zero():
    assert panel._split_status("resposta crua") == ("resposta crua", 0)


# ---------------------------------------------------------------------------- URL

@pytest.mark.parametrize("url, accepted", [
    ("http://127.0.0.1:8212/v1/api/players", True),
    ("https://127.0.0.1:7777/api/v1", True),
    ("127.0.0.1:8212/x", False),          # no scheme
    ("file:///etc/passwd", False),
    ("http://127.0.0.1:8212/a b", False), # space
])
def test_url_re(url, accepted):
    assert bool(panel.URL_RE.match(url)) is accepted


# ------------------------------------------------------------- port discovery

def test_portas_do_texto_livre():
    assert panel._ports_from_text("8211/udp 27015/udp") == [8211, 27015]


def test_sem_repetir_e_sem_a_porta_do_ssh():
    assert panel._without_repeats([8211, 22, 8211, 27015, 99999]) == [8211, 27015]


# The three states the screen needs to tell apart, from the port -> owner map.
OWNERS = {
    ("tcp", 8212): {"pid": 40, "proc": "PalServer-Linu", "infra": False},
    ("tcp", 22): {"pid": 1, "proc": "sshd", "infra": True},
    ("tcp", 33039): {"pid": 0, "proc": "?", "infra": False},
}


def test_com_dono_classifica_cada_porta():
    entries = panel._with_owner(
        [{"port": 8212}, {"port": 22}, {"port": 33039}, {"port": 7777}], OWNERS, "tcp")
    assert (entries[0]["origem"], entries[0]["proc"], entries[0]["pid"]) == (
        "detectada", "PalServer-Linu", 40)
    assert (entries[1]["origem"], entries[1]["infra"]) == ("detectada", True), "sshd e infra"
    assert entries[2]["origem"] == "sem-dono", "socket aberto sem processo dono no container"
    assert entries[3]["origem"] == "nao-vista", "porta que nunca esteve aberta e chute"


def test_resume_genericos_agrupa_porta_404_em_tudo():
    """Probing is only worth it where there is a useful answer: a port that returns 404 on
    everything becomes one flagged row, not one per tested path."""
    raw_ones = [
        {"port": 33039, "path": p, "status": 404, "content_type": "text/html",
         "scheme": "http", "url": f"http://127.0.0.1:33039{p}"}
        for p in ("/", "/v1/api/info", "/v1/api/players", "/status")
    ] + [
        {"port": 8212, "path": "/v1/api/players", "status": 401,
         "content_type": "application/json", "scheme": "http", "url": "x"},
        {"port": 8212, "path": "/status", "status": 404,
         "content_type": "application/json", "scheme": "http", "url": "x"},
    ]
    summary = panel._summarize_generic(raw_ones)
    assert [(i["port"], i["path"], i.get("generico", False))
            for i in summary if i["port"] == 33039] == [(33039, "/", True)]
    assert [(i["port"], i["path"]) for i in summary if i["port"] == 8212] == [
        (8212, "/v1/api/players")], "guarda so as rotas uteis"


# ------------------------------------------------------------------ names from the log

def test_dayz_adm_nome_nos_dois_lados_da_lista_exata():
    """Name on BOTH sides (DayZ via .ADM): it is possible to tell exactly who stayed."""
    lines_of = [
        '16:21:58 | Player "Cristopfer" is connected (id=QnVIrhpDQ=)',
        '16:22:04 | Player "Bruno" is connected (id=AbCdEfGh=)',
        '16:23:10 | Player "Cristopfer"(id=QnVIrhpDQ=) has been disconnected',
        '16:24:00 | Player "Ana" is connected (id=ZZZZ0000=)',
    ]
    entra = panel.compile_pattern(r'Player "(?P<name>[^"]+)" is connected', "entrada")
    exits = panel.compile_pattern(
        r'Player "(?P<name>[^"]+)"\(id=[^)]*\) has been disconnected', "saida")
    r = panel._apply_log_events(lines_of, entra, exits)
    assert [p["name"] for p in r["list"]] == ["Bruno", "Ana"]
    assert r["players"] == 2
    assert not r.get("aproximado")


def test_enshrouded_journalctl_nome_nos_dois_lados():
    lines_of = [
        "Sep 03 13:46:31 enshrouded start-enshrouded.sh[83856]: [server] Player 'Cristopfer' logged in with Permissions:",
        "Sep 03 13:46:35 enshrouded start-enshrouded.sh[83856]: [server] Player 'Amigo' logged in with Permissions:",
        "Sep 03 13:47:36 enshrouded start-enshrouded.sh[83856]: [server] Remove Player 'Cristopfer'",
    ]
    entra = panel.compile_pattern(r"\[server\] Player '(?P<name>[^']+)' logged in", "entrada")
    exits = panel.compile_pattern(r"\[server\] Remove Player '(?P<name>[^']+)'", "saida")
    r = panel._apply_log_events(lines_of, entra, exits)
    assert [p["name"] for p in r["list"]] == ["Amigo"]
    assert r["players"] == 1
    assert not r.get("aproximado")


def test_satisfactory_nome_so_na_entrada_e_aproximado():
    """The log says someone left, without saying who."""
    lines_of = [
        "LogNet: Join succeeded: Cristopfer",
        "LogNet: Join succeeded: Bruno",
        "LogNet: UNetConnection::Close: [UNetConnection] ...",
        "LogNet: Join succeeded: Ana",
    ]
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    exits = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(lines_of, entra, exits)
    # The count is still joins minus leaves, same as before this improvement.
    assert r["players"] == 2
    assert [p["name"] for p in r["list"]] == ["Bruno", "Ana"], "mostra os ultimos a entrar"
    assert r.get("aproximado")


def test_reconexao_nao_duplica_o_nome():
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    exits = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(
        ["LogNet: Join succeeded: Ana", "LogNet: Join succeeded: Ana"], entra, exits)
    assert [p["name"] for p in r["list"]] == ["Ana"]


def test_sem_nome_em_lugar_nenhum_so_a_contagem():
    entra = panel.compile_pattern("alguem entrou", "entrada")
    exits = panel.compile_pattern("alguem saiu", "saida")
    r = panel._apply_log_events(["alguem entrou", "alguem entrou", "alguem saiu"], entra, exits)
    assert (r["players"], r["list"]) == (1, [])


def test_mais_saidas_que_entradas_nao_fica_negativo():
    """Log cut at the start: more leaves than joins must not become a negative count."""
    entra = panel.compile_pattern(r"LogNet: Join succeeded: (?P<name>.+)", "entrada")
    exits = panel.compile_pattern(r"LogNet: UNetConnection::Close:", "saida")
    r = panel._apply_log_events(
        ["LogNet: UNetConnection::Close: x", "LogNet: UNetConnection::Close: y"], entra, exits)
    assert r["players"] == 0


# ------------------------------------------------------------ log path

def test_log_path_vazio_continua_vazio():
    """Empty means "use journalctl"."""
    assert panel.valid_log_path("") == ""


def test_log_path_simples_passa():
    assert panel.valid_log_path("/opt/game/game.log") == "/opt/game/game.log"


def test_log_path_com_asterisco_passa():
    """DayZ opens one .ADM per session; the '*' always picks the newest."""
    assert panel.valid_log_path("/opt/game/profiles/*.ADM") == "/opt/game/profiles/*.ADM"


@pytest.mark.parametrize("bad", [
    "/tmp/x.log; touch /tmp/invadiu", "/opt/game/$(id).log", "/opt/game/`id`.log",
    "/opt/game/x.log|id", "/opt/game/a b.log", "relativo/x.log",
    "/opt/../../etc/shadow", "/opt/game/x.log&", "/opt/game/'x'.log",
])
def test_log_path_torto_e_recusado(bad):
    """The path goes UNQUOTED into the remote command (so the shell expands the '*'), so
    anything the shell would interpret differently has to die here."""
    with pytest.raises(ValueError):
        panel.valid_log_path(bad)


# --------------------------------------------------------------- actions on players

@pytest.mark.parametrize("item, expected", [
    ({"name": "Ana", "userId": "steam_123"}, "steam_123"),
    ({"name": "Ana", "player_uid": "AB01"}, "AB01"),           # another spelling
    ({"name": "Ana", "playerid": 42}, "42"),                   # a number also counts
    ({"name": "Ana", "ping": 12}, ""),                         # no identifier
    ({"name": "Ana", "uid": True}, ""),                        # a boolean is not an id
])
def test_id_do_item(item, expected):
    """Kick and ban need an identifier; the name does not do because it changes and repeats."""
    assert panel._id_do_item(item) == expected


def test_id_entra_na_lista_normalizada_ao_lado_do_nome():
    read_value = panel.read_players_json(
        {"players": [{"name": "Ana", "userId": "steam_1"}, {"name": "Bea"}]})
    assert [p["id"] for p in read_value["list"]] == ["steam_1", ""]


def test_api_de_acoes_reconhece_o_palworld():
    api = panel.actions_api(server("http://127.0.0.1:8212/v1/api/players"))
    assert api is not None
    assert api["base"] == "http://127.0.0.1:8212/v1/api"
    assert sorted(api["actions"]) == ["announce", "ban", "kick"]


def test_api_de_acoes_aceita_barra_no_fim():
    api = panel.actions_api(server("http://127.0.0.1:8212/v1/api/players/"))
    assert api is not None
    assert api["base"] == "http://127.0.0.1:8212/v1/api"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:7777/api/v1", "http://127.0.0.1:8212/v1/api/metrics",
    "http://127.0.0.1:8212/players", "",
])
def test_acoes_de_jogador_nao_inventa_para_url_desconhecida(url):
    """The screen only shows what exists on the other side."""
    assert panel.player_actions(server(url)) == []


def test_contagem_pelo_log_nao_tem_acao():
    assert panel.player_actions(
        server("http://127.0.0.1:8212/v1/api/players", "log")) == []


def test_preenche_nao_quebra_com_chave_solta_na_mensagem():
    """The message comes from whoever types it: a stray brace must not blow up the assembly."""
    assert panel._fill("{message}", "b", "j", "olha o {isso} ai") == "olha o {isso} ai"


def test_preenche_troca_os_tres_marcadores():
    assert panel._fill("{base}/x/{player}/{message}", "http://a/v1", "id7", "oi") == \
        "http://a/v1/x/id7/oi"


# --------------------------------------------------------------- SSH: reuse

@pytest.fixture
def control_dir(tmp_path, monkeypatch):
    """Points `SSH_CONTROL_DIR` at a throwaway folder, and returns it ready to use."""
    path = tmp_path / "ssh-control"
    monkeypatch.setattr(panel, "SSH_CONTROL_DIR", str(path))
    return path


ALVO_SSH = {"ssh_port": 22, "ssh_user": "root", "host": "10.0.0.9"}


def test_http_client_curta_reaproveita_via_control_master(control_dir):
    """Without reuse, each monitor read pays TCP + key exchange +
    authentication only to then run a millisecond command. With several reads
    per minute per server, the handshake becomes the bulk of the cost."""
    short_one = panel.ssh_argv(ALVO_SSH, multiplex=True)
    assert "ControlMaster=auto" in short_one
    assert any(o.startswith("ControlPath=") for o in short_one)
    assert any(o.startswith("ControlPersist=") for o in short_one)
    assert os.path.isdir(panel.SSH_CONTROL_DIR)


@posix_apenas
def test_pasta_do_socket_so_o_dono_enxerga(control_dir):
    """The socket gives access to an ALREADY authenticated session in the containers: nobody
    besides the panel may enter that folder."""
    panel.ssh_argv(ALVO_SSH, multiplex=True)
    assert oct(os.stat(panel.SSH_CONTROL_DIR).st_mode)[-3:] == "700"


def test_padrao_e_nao_reaproveitar_conexao():
    """Terminal, upload and download do NOT share a connection: the terminal holds the session
    for hours and a multi-GB file would clog the shared TCP, stalling the monitor
    behind it."""
    assert [o for o in panel.ssh_argv(ALVO_SSH) if "Control" in o] == []


@posix_apenas
def test_pasta_impossivel_nao_derruba_o_ssh(monkeypatch):
    """If the folder cannot be created, going on without reuse beats not speaking SSH."""
    monkeypatch.setattr(panel, "SSH_CONTROL_DIR", "/proc/impossivel/ssh-control")
    assert [o for o in panel.ssh_argv(ALVO_SSH, multiplex=True) if "Control" in o] == []


# ------------------------- the form x route pair of player moderation

@pytest.fixture
def moderated_server(database, admin) -> int:
    """Any server: the route only needs it to exist so it does not 404."""
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('alvo', 'nao-existe-de-proposito.invalid', 22, 'root',"
            " 'jogo.service', ?)", (panel.now_iso(),))
    return database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


def test_a_acao_do_formulario_chega_INTEIRA_a_rota(moderated_server, admin, post, monkeypatch):
    """The form field names (`action`, `player`, `name`, `message`) are a
    contract with the route, and both sides live as TEXT in different files.

    The two permission tests that existed only check the 302 - they would pass with
    any field name, and they did: when `acao` became `action` in the route, the template
    kept sending `acao` and kick/ban stopped working without any test
    complaining. This one checks what ARRIVED.
    """
    seen = {}

    def spy(server, action, player, message):
        seen.update(action=action, player=player, message=message)
        return "action.kick"

    monkeypatch.setattr(panel, "run_player_action", spy)
    response = post(admin, f"/servers/{moderated_server}/players/action",
                    {"action": "kick", "player": "76561198", "name": "Ana", "message": "tchau"})
    assert response.status_code == 302
    assert seen == {"action": "kick", "player": "76561198", "message": "tchau"}


def test_o_template_manda_os_MESMOS_campos_que_a_rota_le():
    """The macro's `fields={...}` is a literal dictionary in the template: no HTTP test
    sees it, because it only shows up in the rendered HTML. Here the comparison is direct."""
    import ast
    import re
    from pathlib import Path

    tpl = Path(panel.__file__).parent / "templates" / "server_detail.html"
    text = tpl.read_text(encoding="utf-8")
    sent = set()
    for raw in re.findall(r"fields=\{([^}]*)\}", text):
        sent |= set(re.findall(r"['\"]([\w]+)['\"]\s*:", raw))
    route = Path(panel.__file__).parent / "blueprints" / "players.py"
    read = set()
    for node in ast.walk(ast.parse(route.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and getattr(node.func.value, "attr", "") == "form"
                and node.args and isinstance(node.args[0], ast.Constant)):
            read.add(node.args[0].value)
    assert sent, "nenhum `fields={...}` encontrado — a varredura parou de valer"
    assert sent <= read, f"o template manda campo que a rota nao le: {sorted(sent - read)}"


def test_o_nome_de_aba_que_a_rota_conhece_e_o_que_o_template_manda():
    """The tab name is a VALUE, not an identifier - and that is why it escaped everything.

    Changing the route default from `porta` to `port` without changing the
    `{% if tab == 'porta' %}` in the template left the ports tab with no content and no
    highlight for whoever opens the screen WITHOUT a query string, which is the normal path.
    It answers 200, the HTML comes out whole, and no route test notices: what changes is a
    text comparison inside Jinja.
    """
    import re
    from pathlib import Path

    route = (Path(panel.__file__).parent / "blueprints" / "players.py").read_text(encoding="utf-8")
    tpl = (Path(panel.__file__).parent / "templates" / "players_setup.html").read_text(encoding="utf-8")

    # The default of `get("tab", X)` and the two values the route compares.
    default = re.search(r"""get\(["']tab["'],\s*["'](\w+)["']\)""", route)
    assert default, "a rota deixou de ler `tab` com um padrao explicito"
    known = {default.group(1)} | set(re.findall(r"""tab == ["'](\w+)["']""", route))

    from_template = set(re.findall(r"""tab\s*=\s*["'](\w+)["']""", tpl))
    from_template |= set(re.findall(r"""tab == ["'](\w+)["']""", tpl))
    from_template |= set(re.findall(r"""name="tab" value="(\w+)\"""", tpl))

    assert from_template == known, (
        "abas do template x abas que a rota conhece:\n"
        f"  so no template: {sorted(from_template - known)}\n"
        f"  so na rota:     {sorted(known - from_template)}")
