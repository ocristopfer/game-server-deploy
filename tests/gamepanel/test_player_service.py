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
def cache_limpo():
    """O cache e do processo: sem isto um caso herdaria a contagem do anterior."""
    ps._players_cache.clear()
    yield
    ps._players_cache.clear()


def servidor(**campos) -> dict:
    base = {
        "id": 1, "host": "10.0.0.1", "query_port": 0, "player_source": "",
        "http_url": "", "http_auth": "", "http_body": "", "http_list_path": "",
        "http_count_path": "", "http_login_url": "", "http_login_body": "",
        "http_token_path": "", "http_token": "", "join_re": "", "leave_re": "",
    }
    return {**base, **campos}


def deps(**trocas) -> ps.PlayerDeps:
    padrao = {
        "http_json": lambda *a, **k: {},
        "connect": lambda: sqlite3.connect(":memory:"),
        "read_log_lines": lambda *a, **k: [],
        "query_players": lambda host, porta: {"players": 0, "list": []},
        "players_ttl": 5.0,
    }
    return ps.PlayerDeps(**{**padrao, **trocas})


# ----------------------------------------------------------- fonte da contagem

def test_player_source_respeita_a_escolha_do_cadastro():
    assert ps.player_source(servidor(player_source="http")) == "http"


def test_player_source_none_e_desligado_explicito():
    """'none' e diferente de vazio: quem escolheu desligar nao pode cair no palpite."""
    assert ps.player_source(servidor(player_source="none", query_port=27015)) == ""


def test_player_source_vazio_deduz_a2s_pela_porta_de_consulta():
    """Cadastro anterior ao campo: porta de query preenchida quer dizer A2S."""
    assert ps.player_source(servidor(query_port=27015)) == "a2s"


def test_player_source_vazio_sem_porta_fica_desligado():
    assert ps.player_source(servidor()) == ""


def test_player_source_valor_estranho_cai_no_palpite_antigo():
    assert ps.player_source(servidor(player_source="rcon", query_port=27015)) == "a2s"


# --------------------------------------------------------------- server_players

def test_servidor_sem_fonte_nao_consulta_nada():
    chamou = []
    d = deps(query_players=lambda *a: chamou.append(a) or {})
    out = ps.server_players(d, servidor())
    assert out == {"configured": False, "error": "", "players": None, "list": [], "source": ""}
    assert chamou == []


def test_a2s_usa_a_porta_de_consulta_e_marca_a_fonte():
    vistos = []

    def falso(host, porta):
        vistos.append((host, porta))
        return {"players": 3, "list": []}

    out = ps.server_players(deps(query_players=falso), servidor(player_source="a2s", query_port=27015))
    assert vistos == [("10.0.0.1", 27015)]
    assert out["players"] == 3
    assert out["configured"] is True
    assert out["source"] == "a2s"


def test_a2s_sem_porta_vira_erro_na_tela_e_nao_excecao():
    """A tela precisa dizer o que falta; estourar aqui derrubaria a lista inteira."""
    out = ps.server_players(deps(), servidor(player_source="a2s"))
    assert out["configured"] is True
    assert out["players"] is None
    assert "porta de consulta" in out["error"]


def test_contagem_vem_do_cache_dentro_do_prazo():
    chamadas = []

    def falso(host, porta):
        chamadas.append(porta)
        return {"players": len(chamadas), "list": []}

    d = deps(query_players=falso)
    alvo = servidor(player_source="a2s", query_port=27015)
    primeira = ps.server_players(d, alvo)
    segunda = ps.server_players(d, alvo)
    assert primeira["players"] == segunda["players"] == 1
    assert len(chamadas) == 1


def test_force_ignora_o_cache():
    chamadas = []

    def falso(host, porta):
        chamadas.append(porta)
        return {"players": len(chamadas), "list": []}

    d = deps(query_players=falso)
    alvo = servidor(player_source="a2s", query_port=27015)
    ps.server_players(d, alvo)
    segunda = ps.server_players(d, alvo, force=True)
    assert segunda["players"] == 2
    assert len(chamadas) == 2


def test_prazo_zero_nunca_aproveita_o_cache():
    chamadas = []

    def falso(host, porta):
        chamadas.append(porta)
        return {"players": 1, "list": []}

    d = deps(query_players=falso, players_ttl=0)
    alvo = servidor(player_source="a2s", query_port=27015)
    ps.server_players(d, alvo)
    ps.server_players(d, alvo)
    assert len(chamadas) == 2


def test_invalidate_esquece_o_servidor():
    chamadas = []

    def falso(host, porta):
        chamadas.append(porta)
        return {"players": 1, "list": []}

    d = deps(query_players=falso)
    alvo = servidor(player_source="a2s", query_port=27015)
    ps.server_players(d, alvo)
    ps.invalidate(1)
    ps.server_players(d, alvo)
    assert len(chamadas) == 2


def test_erro_tambem_fica_em_cache():
    """Servidor fora do ar custa 3s de espera: repetir isso a cada tela nao se paga."""
    chamadas = []

    def falso(host, porta):
        chamadas.append(porta)
        raise QueryError("fora do ar")

    d = deps(query_players=falso)
    alvo = servidor(player_source="a2s", query_port=27015)
    ps.server_players(d, alvo)
    out = ps.server_players(d, alvo)
    assert out["error"] == "fora do ar"
    assert len(chamadas) == 1


# ----------------------------------------------------------------- all_players

def test_all_players_junta_por_id():
    servidores = [servidor(id=1), servidor(id=2)]
    out = ps.all_players(lambda s: {"players": int(s["id"]) * 10}, servidores, 5, "tempo esgotado")
    assert out[1]["players"] == 10
    assert out[2]["players"] == 20


def test_all_players_preenche_quem_nao_respondeu_a_tempo():
    """Thread que nao voltou no prazo nao pode sumir da lista da tela."""
    def trava(s):
        if int(s["id"]) == 2:
            import time
            time.sleep(0.5)
        return {"players": 1}

    out = ps.all_players(trava, [servidor(id=1), servidor(id=2)], 0.05, "tempo esgotado")
    assert out[1]["players"] == 1
    assert out[2]["error"] == "tempo esgotado"
    assert out[2]["configured"] is True


# ------------------------------------------------------------ login e token

@pytest.fixture
def banco_de_servidores(tmp_path):
    """sqlite com a unica coluna que o login escreve."""
    caminho = tmp_path / "painel.db"
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE servers (id INTEGER PRIMARY KEY, http_token TEXT)")
    con.execute("INSERT INTO servers (id, http_token) VALUES (1, '')")
    con.commit()
    con.close()

    def connect():
        c = sqlite3.connect(caminho)
        c.row_factory = sqlite3.Row
        return c

    return connect


def _token_guardado(connect) -> str:
    con = connect()
    try:
        return con.execute("SELECT http_token FROM servers WHERE id = 1").fetchone()[0]
    finally:
        con.close()


def test_http_login_grava_o_token_no_cadastro(banco_de_servidores):
    d = deps(http_json=lambda *a, **k: {"data": {"token": "abc123"}},
             connect=banco_de_servidores)
    alvo = servidor(http_login_url="http://x/login", http_token_path="data.token")
    assert ps.http_login(d, alvo) == "abc123"
    assert _token_guardado(banco_de_servidores) == "abc123"


def test_http_login_sem_configuracao_completa_recusa():
    with pytest.raises(QueryError, match="login automatico incompleto"):
        ps.http_login(deps(), servidor(http_login_url="http://x/login"))


def test_http_login_sem_token_na_resposta_diz_onde_procurou():
    d = deps(http_json=lambda *a, **k: {"data": {}})
    alvo = servidor(http_login_url="http://x/login", http_token_path="data.token")
    with pytest.raises(QueryError, match=r"data\.token"):
        ps.http_login(d, alvo)


def test_login_vai_sem_authorization():
    """E ele quem PRODUZ a credencial: mandar a antiga junto so confunde a API."""
    vistos = []

    def falso(server, url, auth, corpo, exigir_json=True):
        vistos.append(auth)
        return {"token": "t"}

    d = deps(http_json=falso, connect=lambda: sqlite3.connect(":memory:"))
    alvo = servidor(http_login_url="http://x/login", http_token_path="token")
    with pytest.raises(sqlite3.OperationalError):
        ps.http_login(d, alvo)      # o :memory: nao tem a tabela; o que importa e o auth
    assert vistos == [""]


def test_sem_login_configurado_usa_a_credencial_do_cadastro():
    vistos = []

    def falso(server, url, auth, corpo, exigir_json=True):
        vistos.append(auth)
        return {}

    ps.chama_api_do_jogo(deps(http_json=falso), servidor(http_auth="basic:a:b"), "http://x/p")
    assert vistos == ["basic:a:b"]


def test_com_login_e_sem_token_guardado_faz_login_antes(banco_de_servidores):
    vistos = []

    def falso(server, url, auth, corpo, exigir_json=True):
        vistos.append((url, auth))
        return {"token": "novo"}

    d = deps(http_json=falso, connect=banco_de_servidores)
    alvo = servidor(http_login_url="http://x/login", http_token_path="token")
    ps.chama_api_do_jogo(d, alvo, "http://x/players")
    assert vistos[0] == ("http://x/login", "")
    assert vistos[1] == ("http://x/players", "bearer:novo")


def test_token_vencido_renova_uma_vez_e_repete(banco_de_servidores):
    vistos = []

    def falso(server, url, auth, corpo, exigir_json=True):
        vistos.append((url, auth))
        if url == "http://x/login":
            return {"token": "novo"}
        if auth == "bearer:velho":
            raise AuthError("401")
        return {"ok": True}

    d = deps(http_json=falso, connect=banco_de_servidores)
    alvo = servidor(http_login_url="http://x/login", http_token_path="token",
                    http_token="velho")
    assert ps.chama_api_do_jogo(d, alvo, "http://x/players") == {"ok": True}
    assert [a for _, a in vistos] == ["bearer:velho", "", "bearer:novo"]


def test_sem_login_configurado_o_401_sobe():
    """Sem como renovar, insistir so gasta chamada: o problema e a credencial."""
    def falso(*a, **k):
        raise AuthError("401")

    with pytest.raises(AuthError):
        ps.chama_api_do_jogo(deps(http_json=falso), servidor(http_auth="x"), "http://x/p")


def test_players_from_http_sem_url_recusa():
    with pytest.raises(QueryError, match="URL da API"):
        ps.players_from_http(deps(), servidor())


# ------------------------------------------------------------ contagem por log

def test_players_from_log_sem_padrao_de_entrada_recusa():
    with pytest.raises(QueryError, match="padrao da linha de entrada"):
        ps.players_from_log(deps(), servidor())


def test_players_from_log_conta_quem_ficou():
    linhas = ["Ana joined", "Bea joined", "Ana left"]
    d = deps(read_log_lines=lambda *a, **k: linhas)
    alvo = servidor(join_re=r"(?P<name>\w+) joined", leave_re=r"(?P<name>\w+) left")
    out = ps.players_from_log(d, alvo)
    assert out["players"] == 1
    assert [p["name"] for p in out["list"]] == ["Bea"]
    assert out["error"] == ""


def test_falha_de_ssh_no_log_vira_erro_de_consulta():
    """QueryError e o que a tela sabe mostrar; RemoteError vazaria como erro interno."""
    def explode(*a, **k):
        raise RemoteError("sem rota para o host")

    d = deps(read_log_lines=explode)
    alvo = servidor(join_re=r"(?P<name>\w+) joined")
    with pytest.raises(QueryError, match="sem rota"):
        ps.players_from_log(d, alvo)


# ------------------------------------------------------------------- acoes

def test_acao_desconhecida_e_recusada():
    alvo = servidor(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="nao publica essa acao"):
        ps.acao_de_jogador(deps(), alvo, "explodir", "id", "")


def test_expulsar_sem_identificador_e_recusado():
    """Kick pelo nome nao serve: nome muda e repete, id nao."""
    alvo = servidor(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="nao sei quem expulsar"):
        ps.acao_de_jogador(deps(), alvo, "kick", "", "tchau")


def test_avisar_sem_mensagem_e_recusado():
    alvo = servidor(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    with pytest.raises(QueryError, match="escreva o aviso"):
        ps.acao_de_jogador(deps(), alvo, "announce", "", "")


def test_kick_monta_rota_e_corpo_do_catalogo():
    vistos = []

    def falso(server, url, auth, corpo, exigir_json=True):
        vistos.append((url, corpo, exigir_json))
        return {}

    alvo = servidor(player_source="http", http_url="http://127.0.0.1:8212/v1/api/players")
    rotulo = ps.acao_de_jogador(deps(http_json=falso), alvo, "kick", "steam_1", "tchau")
    url, corpo, exigir_json = vistos[0]
    assert url == "http://127.0.0.1:8212/v1/api/kick"
    assert '"userid": "steam_1"' in corpo
    assert '"message": "tchau"' in corpo
    # As rotas de acao respondem 200 com corpo vazio.
    assert exigir_json is False
    # CHAVE de catalogo, nao a frase: o servico nao sabe em que idioma a tela esta
    # aberta, e quem traduz e o `app.py`, que tem o pedido em maos.
    assert rotulo == "player_action.kick"
