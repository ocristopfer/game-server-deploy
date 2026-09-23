"""O repositorio de `servers`: cada consulta, contra um banco de verdade.

Repositorio e o unico lugar onde nome de coluna aparece escrito. Um teste por funcao
custa pouco e e o que faz uma coluna renomeada quebrar AQUI, em vez de na primeira
visita a tela que usa a copia que ficou para tras.
"""
from __future__ import annotations

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as repo

CAMPOS = dict.fromkeys(repo.EDITABLE_FIELDS, "")


def _novo(**extra) -> dict:
    data = {**CAMPOS, "name": "Alfa", "host": "10.0.0.1", "ssh_port": 22,
            "ssh_user": "root", "service": "alfa.service", "game_port": 7777,
            "query_port": 27015, "player_source": "a2s"}
    data.update(extra)
    return data


def test_a_lista_de_colunas_bate_com_a_tabela(database):
    """Coluna que existe no `EDITABLE_FIELDS` e nao na tabela so quebraria no INSERT."""
    na_tabela = {r["name"] for r in database.execute("PRAGMA table_info(servers)")}
    assert set(repo.EDITABLE_FIELDS) <= na_tabela
    assert set(repo.DEPLOY_FIELDS) <= na_tabela
    assert set(repo.DEPLOY_UPDATE_FIELDS) <= na_tabela


def test_insere_e_le_por_id(database):
    with database:
        repo.insert(database, _novo(), panel.now_iso())
    linha = repo.all_ordered(database)[0]
    assert repo.by_id(database, linha["id"])["name"] == "Alfa"


def test_by_id_de_quem_nao_existe_e_none(database):
    assert repo.by_id(database, 9999) is None


def test_a_lista_sai_ordenada_por_nome(database):
    with database:
        repo.insert(database, _novo(name="Zulu", host="10.0.0.9"), panel.now_iso())
        repo.insert(database, _novo(name="Alfa", host="10.0.0.1"), panel.now_iso())
    assert [r["name"] for r in repo.all_ordered(database)] == ["Alfa", "Zulu"]


def test_o_endereco_e_a_identidade(database):
    """`(host, ssh_port)` e UNIQUE: e por ele que o redeploy reconhece o que ja existe."""
    with database:
        repo.insert(database, _novo(host="10.0.0.7", ssh_port=2222), panel.now_iso())
    assert repo.by_address(database, "10.0.0.7", 2222)["name"] == "Alfa"
    assert repo.by_address(database, "10.0.0.7", 22) is None


def test_atualiza_so_a_linha_pedida(database):
    with database:
        repo.insert(database, _novo(name="Alfa", host="10.0.0.1"), panel.now_iso())
        repo.insert(database, _novo(name="Beta", host="10.0.0.2"), panel.now_iso())
    alvo = repo.by_address(database, "10.0.0.1", 22)
    with database:
        repo.update(database, _novo(name="Novo", host="10.0.0.1"), alvo["id"])
    assert repo.by_id(database, alvo["id"])["name"] == "Novo"
    assert repo.by_address(database, "10.0.0.2", 22)["name"] == "Beta"


def test_apagar_leva_so_o_escolhido(database):
    with database:
        repo.insert(database, _novo(host="10.0.0.1"), panel.now_iso())
        repo.insert(database, _novo(host="10.0.0.2"), panel.now_iso())
    alvo = repo.by_address(database, "10.0.0.1", 22)
    with database:
        repo.delete(database, alvo["id"])
    assert repo.by_id(database, alvo["id"]) is None
    assert len(repo.all_ordered(database)) == 1


def test_so_os_do_broker_aparecem_em_from_broker(database):
    with database:
        repo.insert(database, _novo(host="10.0.0.1"), panel.now_iso())
        repo.deploy_insert(
            database,
            [getattr(panel.DeployServer(name="Broker", host="10.0.0.2",
                                        service="b.service", broker_id=7), c)
             for c in repo.DEPLOY_FIELDS],
            panel.now_iso())
    achados = repo.from_broker(database)
    assert [r["broker_id"] for r in achados] == [7]


def test_cada_fonte_de_contagem_liga_o_player_source_junto(database):
    """Gravar os campos de uma fonte sem ligar a fonte deixa o servidor apontando para
    uma contagem que ninguem preencheu."""
    with database:
        repo.insert(database, _novo(player_source=""), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]

    with database:
        repo.use_query_port(database, sid, 27016)
    linha = repo.by_id(database, sid)
    assert (linha["query_port"], linha["player_source"]) == (27016, "a2s")

    with database:
        repo.use_log(database, sid, "entrou", "saiu", "/var/log/jogo.log")
    linha = repo.by_id(database, sid)
    assert (linha["join_re"], linha["log_path"], linha["player_source"]) == (
        "entrou", "/var/log/jogo.log", "log")

    with database:
        repo.use_http(database, sid, dict.fromkeys(repo.HTTP_FIELDS, "x"))
    linha = repo.by_id(database, sid)
    assert (linha["http_url"], linha["player_source"]) == ("x", "http")


def test_trocar_a_fonte_http_zera_o_token_guardado(database):
    """Se a URL ou a credencial mudou, o token antigo nao vale mais — e a proxima
    consulta faz login sozinha com o que ficou."""
    with database:
        repo.insert(database, _novo(), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]
    with database:
        repo.set_http_token(database, sid, "token-velho")
    assert repo.by_id(database, sid)["http_token"] == "token-velho"
    with database:
        repo.use_http(database, sid, dict.fromkeys(repo.HTTP_FIELDS, "y"))
    assert repo.by_id(database, sid)["http_token"] == ""


def test_config_files_guarda_uma_linha_por_caminho(database):
    with database:
        repo.insert(database, _novo(), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]
    with database:
        repo.set_config_files(database, sid, ["/a.ini", "/b.json"])
    assert repo.by_id(database, sid)["config_files"] == "/a.ini\n/b.json"
