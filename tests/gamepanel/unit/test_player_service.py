"""Contagem e acoes de jogador (gamepanel.services.player_service).

O que este arquivo cobre nao tinha teste direto antes da Fase 4: `server_players`
(cache, despacho por fonte, erro virando dado da tela), `http_login` (token gravado no
banco), a renovacao de token do `chama_api_do_jogo` e o `all_players`. O que havia era
teste de ROTA com `server_players` inteiro trocado por um falso — util para a tela,
cego para a regra.

Como o service recebe tudo por `PlayerDeps`, aqui nao ha Flask, SSH nem container: as
quatro pecas sao falsas, e o banco e um sqlite de arquivo temporario com a unica tabela
que o login precisa.
"""
from __future__ import annotations

import sqlite3

import pytest

from gamepanel.runtime.a2s import AuthError, QueryError
from gamepanel.runtime.ssh import RemoteError
from gamepanel.services import player_service as ps


@pytest.fixture(autouse=True)
def clean_cache():
    """O cache e do processo: sem isto um caso herdaria a contagem do anterior."""
    ps._players_cache.clear()
    yield
    ps._players_cache.clear()


def server(**fields) -> dict:
    base = {
        "id": 1, "host": "10.0.0.1", "query_port": 0, "player_source": "",
        "http_url": "", "http_auth": "", "http_body": "", "http_list_path": "",
        "http_count_path": "", "http_login_url": "", "http_login_body": "",
        "http_token_path": "", "http_token": "", "join_re": "", "leave_re": "",
    }
    return {**base, **fields}


def deps(**trocas) -> ps.PlayerDeps:
    fallback = {
        "http_json": lambda *a, **k: {},
        "connect": lambda: sqlite3.connect(":memory:"),
        "read_log_lines": lambda *a, **k: [],
        "query_players": lambda host, port: {"players": 0, "list": []},
        "players_ttl": 5.0,
        "presence_players": lambda server: {"players": 0, "list": []},
    }
    return ps.PlayerDeps(**{**fallback, **trocas})


# ----------------------------------------------------------- fonte da contagem

def test_player_source_respeita_a_escolha_do_cadastro():
    assert ps.player_source(server(player_source="http")) == "http"


def test_player_source_none_e_desligado_explicito():
    """'none' e diferente de vazio: quem escolheu desligar nao pode cair no palpite."""
    assert ps.player_source(server(player_source="none", query_port=27015)) == ""


def test_player_source_vazio_deduz_a2s_pela_porta_de_consulta():
    """Cadastro anterior ao campo: porta de query preenchida quer dizer A2S."""
    assert ps.player_source(server(query_port=27015)) == "a2s"


def test_player_source_vazio_sem_porta_fica_desligado():
    assert ps.player_source(server()) == ""


def test_player_source_valor_estranho_cai_no_palpite_antigo():
    assert ps.player_source(server(player_source="rcon", query_port=27015)) == "a2s"


# --------------------------------------------------------------- server_players

def test_servidor_sem_fonte_nao_consulta_nada():
    called = []
    d = deps(query_players=lambda *a: called.append(a) or {})
    out = ps.server_players(d, server())
    assert out == {"configured": False, "error": "", "players": None, "list": [], "source": ""}
    assert called == []


def test_a2s_usa_a_porta_de_consulta_e_marca_a_fonte():
    seen_ones = []

    def fake(host, port):
        seen_ones.append((host, port))
        return {"players": 3, "list": []}

    out = ps.server_players(deps(query_players=fake), server(player_source="a2s", query_port=27015))
    assert seen_ones == [("10.0.0.1", 27015)]
    assert out["players"] == 3
    assert out["configured"] is True
    assert out["source"] == "a2s"


def test_a2s_sem_porta_vira_erro_na_tela_e_nao_excecao():
    """A tela precisa dizer o que falta; estourar aqui derrubaria a lista inteira."""
    out = ps.server_players(deps(), server(player_source="a2s"))
    assert out["configured"] is True
    assert out["players"] is None
    assert "porta de consulta" in out["error"]


def test_contagem_vem_do_cache_dentro_do_prazo():
    calls = []

    def fake(host, port):
        calls.append(port)
        return {"players": len(calls), "list": []}

    d = deps(query_players=fake)
    target = server(player_source="a2s", query_port=27015)
    first_one = ps.server_players(d, target)
    second_one = ps.server_players(d, target)
    assert first_one["players"] == second_one["players"] == 1
    assert len(calls) == 1


def test_force_ignora_o_cache():
    calls = []

    def fake(host, port):
        calls.append(port)
        return {"players": len(calls), "list": []}

    d = deps(query_players=fake)
    target = server(player_source="a2s", query_port=27015)
    ps.server_players(d, target)
    second_one = ps.server_players(d, target, force=True)
    assert second_one["players"] == 2
    assert len(calls) == 2


def test_prazo_zero_nunca_aproveita_o_cache():
    calls = []

    def fake(host, port):
        calls.append(port)
        return {"players": 1, "list": []}

    d = deps(query_players=fake, players_ttl=0)
    target = server(player_source="a2s", query_port=27015)
    ps.server_players(d, target)
    ps.server_players(d, target)
    assert len(calls) == 2


def test_invalidate_esquece_o_servidor():
    calls = []

    def fake(host, port):
        calls.append(port)
        return {"players": 1, "list": []}

    d = deps(query_players=fake)
    target = server(player_source="a2s", query_port=27015)
    ps.server_players(d, target)
    ps.invalidate(1)
    ps.server_players(d, target)
    assert len(calls) == 2


def test_erro_tambem_fica_em_cache():
    """Servidor fora do ar custa 3s de espera: repetir isso a cada tela nao se paga."""
    calls = []

    def fake(host, port):
        calls.append(port)
        raise QueryError("fora do ar")

    d = deps(query_players=fake)
    target = server(player_source="a2s", query_port=27015)
    ps.server_players(d, target)
    out = ps.server_players(d, target)
    assert out["error"] == "fora do ar"
    assert len(calls) == 1


# ------------------------------------------------------- fontes combinadas

JOIN = r"(?P<name>\w+) entrou"
LEAVE = r"(?P<name>\w+) saiu"


def log_lines(*lines):
    return lambda *a, **k: list(lines)


def test_fontes_combinadas_poem_a_escolhida_na_frente_e_o_log_por_ultimo():
    target = server(player_source="log", query_port=27015, http_url="http://x/players",
                    join_re=JOIN)
    assert ps.configured_sources(target) == ["log", "a2s", "http"]


def test_fonte_sem_campo_preenchido_nao_entra_na_combinacao():
    assert ps.configured_sources(server(player_source="a2s", query_port=27015)) == ["a2s"]


def test_none_desliga_ate_as_fontes_com_campo_preenchido():
    """Calar um servidor sem apagar o cadastro: o regex do log nao pode religar a contagem."""
    target = server(player_source="none", query_port=27015, join_re=JOIN)
    assert ps.configured_sources(target) == []


def test_a2s_conta_e_o_log_da_os_nomes():
    """O caso do Unreal: a consulta sabe QUANTOS, so o log sabe QUEM."""
    d = deps(query_players=lambda h, p: {"players": 2, "list": []},
             read_log_lines=log_lines("ana entrou", "bia entrou"))
    out = ps.server_players(d, server(player_source="a2s", query_port=27015,
                                      join_re=JOIN, leave_re=LEAVE))
    assert out["players"] == 2
    assert out["source"] == "a2s"
    assert [p["name"] for p in out["list"]] == ["ana", "bia"]
    assert out["names_from"] == "log"
    assert out["names_partial"] is False


def test_numero_e_da_consulta_mesmo_quando_o_log_lembra_de_mais_gente():
    """Quem caiu sem linha de saida ficou no log; a lista e cortada nos ultimos a entrar."""
    d = deps(query_players=lambda h, p: {"players": 1, "list": []},
             read_log_lines=log_lines("ana entrou", "bia entrou"))
    out = ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert out["players"] == 1
    assert [p["name"] for p in out["list"]] == ["bia"]
    assert out["names_partial"] is True


def test_ninguem_online_nao_gasta_ssh_lendo_o_log():
    read = []
    d = deps(query_players=lambda h, p: {"players": 0, "list": []},
             read_log_lines=lambda *a, **k: read.append(1) or [])
    ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert read == []


def test_consulta_que_ja_da_nomes_nao_pede_o_log():
    read = []
    d = deps(query_players=lambda h, p: {"players": 1, "list": [{"name": "ana"}]},
             read_log_lines=lambda *a, **k: read.append(1) or [])
    out = ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert read == []
    assert "names_from" not in out


def test_consulta_muda_cai_para_o_log_e_a_tela_sabe_por_que():
    def silent(host, port):
        raise QueryError("sem resposta em 3s na porta 27015/udp")

    d = deps(query_players=silent, read_log_lines=log_lines("ana entrou"))
    out = ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert out["players"] == 1
    assert out["source"] == "log"
    assert "27015" in out["fallback_error"]
    assert out["error"] == ""


def test_todas_as_fontes_falhando_mostra_o_erro_da_escolhida():
    def silent(host, port):
        raise QueryError("sem resposta da consulta")

    def no_ssh(*a, **k):
        raise RemoteError("ssh caiu")

    d = deps(query_players=silent, read_log_lines=no_ssh)
    out = ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert out["players"] is None
    assert out["error"] == "sem resposta da consulta"
    assert out["source"] == "a2s"


def test_log_que_falha_ao_completar_nomes_nao_estraga_a_contagem():
    def no_ssh(*a, **k):
        raise RemoteError("ssh caiu")

    d = deps(query_players=lambda h, p: {"players": 2, "list": []}, read_log_lines=no_ssh)
    out = ps.server_players(d, server(player_source="a2s", query_port=27015, join_re=JOIN))
    assert out["players"] == 2
    assert not out.get("error")
    assert out["list"] == []


def test_conexoes_ativas_contam_e_o_log_da_os_nomes():
    """O Dragonwilds: sem consulta (EOS), o numero sai do firewall e os nomes do log."""
    d = deps(presence_players=lambda srv: {"players": 1, "list": []},
             read_log_lines=log_lines("ana entrou", "bia entrou"))
    out = ps.server_players(d, server(player_source="net", join_re=JOIN))
    assert out["players"] == 1
    assert out["source"] == "net"
    assert [p["name"] for p in out["list"]] == ["bia"]
    assert out["names_from"] == "log"


def test_conexoes_ativas_sem_firewall_caem_para_o_log():
    def missing(srv):
        raise QueryError("O firewall deste CT nao conta conexoes ainda")

    d = deps(presence_players=missing, read_log_lines=log_lines("ana entrou"))
    out = ps.server_players(d, server(player_source="net", join_re=JOIN))
    assert out["players"] == 1
    assert out["source"] == "log"
    assert "firewall" in out["fallback_error"]


def test_conexoes_ativas_so_valem_quando_escolhidas():
    """Nao ha campo que diga se o CT tem o conjunto: como reserva ela so geraria erro."""
    target = server(player_source="a2s", query_port=27015, join_re=JOIN)
    assert "net" not in ps.configured_sources(target)


# ----------------------------------------------------------------- all_players

def test_all_players_junta_por_id():
    servers = [server(id=1), server(id=2)]
    out = ps.all_players(lambda s: {"players": int(s["id"]) * 10}, servers, 5, "tempo esgotado")
    assert out[1]["players"] == 10
    assert out[2]["players"] == 20


def test_all_players_preenche_quem_nao_respondeu_a_tempo():
    """Thread que nao voltou no prazo nao pode sumir da lista da tela."""
    def lock_it(s):
        if int(s["id"]) == 2:
            import time
            time.sleep(0.5)
        return {"players": 1}

    out = ps.all_players(lock_it, [server(id=1), server(id=2)], 0.05, "tempo esgotado")
    assert out[1]["players"] == 1
    assert out[2]["error"] == "tempo esgotado"
    assert out[2]["configured"] is True


# ------------------------------------------------------------ login e token

@pytest.fixture
def servers_database(tmp_path):
    """sqlite com a unica coluna que o login escreve."""
    path = tmp_path / "painel.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE servers (id INTEGER PRIMARY KEY, http_token TEXT)")
    con.execute("INSERT INTO servers (id, http_token) VALUES (1, '')")
    con.commit()
    con.close()

    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    return connect


def _stored_token(connect) -> str:
    con = connect()
    try:
        return con.execute("SELECT http_token FROM servers WHERE id = 1").fetchone()[0]
    finally:
        con.close()


def test_http_login_grava_o_token_no_cadastro(servers_database):
    d = deps(http_json=lambda *a, **k: {"data": {"token": "abc123"}},
             connect=servers_database)
    target = server(http_login_url="http://x/login", http_token_path="data.token")
    assert ps.http_login(d, target) == "abc123"
    assert _stored_token(servers_database) == "abc123"


def test_http_login_sem_configuracao_completa_recusa():
    with pytest.raises(QueryError, match="login automatico incompleto"):
        ps.http_login(deps(), server(http_login_url="http://x/login"))


def test_http_login_sem_token_na_resposta_diz_onde_procurou():
    d = deps(http_json=lambda *a, **k: {"data": {}})
    target = server(http_login_url="http://x/login", http_token_path="data.token")
    with pytest.raises(QueryError, match=r"data\.token"):
        ps.http_login(d, target)


def test_login_vai_sem_authorization():
    """E ele quem PRODUZ a credencial: mandar a antiga junto so confunde a API."""
    seen_ones = []

    def fake(server, url, auth, body, exigir_json=True):
        seen_ones.append(auth)
        return {"token": "t"}

    d = deps(http_json=fake, connect=lambda: sqlite3.connect(":memory:"))
    target = server(http_login_url="http://x/login", http_token_path="token")
    with pytest.raises(sqlite3.OperationalError):
        ps.http_login(d, target)      # o :memory: nao tem a tabela; o que importa e o auth
    assert seen_ones == [""]


def test_sem_login_configurado_usa_a_credencial_do_cadastro():
    seen_ones = []

    def fake(server, url, auth, body, exigir_json=True):
        seen_ones.append(auth)
        return {}

    ps.call_game_api(deps(http_json=fake), server(http_auth="basic:a:b"), "http://x/p")
    assert seen_ones == ["basic:a:b"]


def test_com_login_e_sem_token_guardado_faz_login_antes(servers_database):
    seen_ones = []

    def fake(server, url, auth, body, exigir_json=True):
        seen_ones.append((url, auth))
        return {"token": "novo"}

    d = deps(http_json=fake, connect=servers_database)
    target = server(http_login_url="http://x/login", http_token_path="token")
    ps.call_game_api(d, target, "http://x/players")
    assert seen_ones[0] == ("http://x/login", "")
    assert seen_ones[1] == ("http://x/players", "bearer:novo")


def test_token_vencido_renova_uma_vez_e_repete(servers_database):
    seen_ones = []

    def fake(server, url, auth, body, exigir_json=True):
        seen_ones.append((url, auth))
        if url == "http://x/login":
            return {"token": "novo"}
        if auth == "bearer:velho":
            raise AuthError("401")
        return {"ok": True}

    d = deps(http_json=fake, connect=servers_database)
    target = server(http_login_url="http://x/login", http_token_path="token",
                    http_token="velho")
    assert ps.call_game_api(d, target, "http://x/players") == {"ok": True}
    assert [a for _, a in seen_ones] == ["bearer:velho", "", "bearer:novo"]


def test_sem_login_configurado_o_401_sobe():
    """Sem como renovar, insistir so gasta chamada: o problema e a credencial."""
    def fake(*a, **k):
        raise AuthError("401")

    with pytest.raises(AuthError):
        ps.call_game_api(deps(http_json=fake), server(http_auth="x"), "http://x/p")


def test_players_from_http_sem_url_recusa():
    with pytest.raises(QueryError, match="URL da API"):
        ps.players_from_http(deps(), server())


# ------------------------------------------------------------ contagem por log

def test_players_from_log_sem_padrao_de_entrada_recusa():
    with pytest.raises(QueryError, match="padrao da linha de entrada"):
        ps.players_from_log(deps(), server())


def test_players_from_log_conta_quem_ficou():
    lines = ["Ana joined", "Bea joined", "Ana left"]
    d = deps(read_log_lines=lambda *a, **k: lines)
    target = server(join_re=r"(?P<name>\w+) joined", leave_re=r"(?P<name>\w+) left")
    out = ps.players_from_log(d, target)
    assert out["players"] == 1
    assert [p["name"] for p in out["list"]] == ["Bea"]
    assert out["error"] == ""


def test_falha_de_ssh_no_log_vira_erro_de_consulta():
    """QueryError e o que a tela sabe mostrar; RemoteError vazaria como erro interno."""
    def explode(*a, **k):
        raise RemoteError("sem rota para o host")

    d = deps(read_log_lines=explode)
    target = server(join_re=r"(?P<name>\w+) joined")
    with pytest.raises(QueryError, match="sem rota"):
        ps.players_from_log(d, target)


# ------------------------------------------------------------------- acoes

def test_acao_desconhecida_e_recusada():
    target = server(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="nao publica essa acao"):
        ps.player_action(deps(), target, "explodir", "id", "")


def test_expulsar_sem_identificador_e_recusado():
    """Kick pelo nome nao serve: nome muda e repete, id nao."""
    target = server(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="nao sei quem expulsar"):
        ps.player_action(deps(), target, "kick", "", "tchau")


def test_avisar_sem_mensagem_e_recusado():
    target = server(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="escreva o aviso"):
        ps.player_action(deps(), target, "announce", "", "")


def test_kick_monta_rota_e_corpo_do_catalogo():
    seen_ones = []

    def fake(server, url, auth, body, exigir_json=True):
        seen_ones.append((url, body, exigir_json))
        return {}

    target = server(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    label = ps.player_action(deps(http_json=fake), target, "kick", "steam_1", "tchau")
    url, body, require_json = seen_ones[0]
    assert url == "http://127.0.0.1:8212/v1/api/kick"
    assert '"userid": "steam_1"' in body
    assert '"message": "tchau"' in body
    # As rotas de acao respondem 200 com corpo vazio.
    assert require_json is False
    # CHAVE de catalogo, nao a frase: o servico nao sabe em que idioma a tela esta
    # aberta, e quem traduz e o `app.py`, que tem o pedido em maos.
    assert label == "player_action.kick"
