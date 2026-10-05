"""The `servers` repository: each query, against a real database.

The repository is the only place where a column name is written out. One test per function
is cheap, and it is what makes a renamed column break HERE, instead of on the first visit
to the screen that uses the copy left behind.
"""
from __future__ import annotations

from gamepanel import app as panel
from gamepanel.persistence.repositories import servers as repo

FIELDS = dict.fromkeys(repo.EDITABLE_FIELDS, "")


def _fresh(**extra) -> dict:
    data = {**FIELDS, "name": "Alfa", "host": "10.0.0.1", "ssh_port": 22,
            "ssh_user": "root", "service": "alfa.service", "game_port": 7777,
            "query_port": 27015, "player_source": "a2s"}
    data.update(extra)
    return data


def test_a_lista_de_colunas_bate_com_a_tabela(database):
    """A column that exists in `EDITABLE_FIELDS` but not in the table would only break on INSERT."""
    in_table = {r["name"] for r in database.execute("PRAGMA table_info(servers)")}
    assert set(repo.EDITABLE_FIELDS) <= in_table
    assert set(repo.DEPLOY_FIELDS) <= in_table
    assert set(repo.DEPLOY_UPDATE_FIELDS) <= in_table


def test_insere_e_le_por_id(database):
    with database:
        repo.insert(database, _fresh(), panel.now_iso())
    line = repo.all_ordered(database)[0]
    assert repo.by_id(database, line["id"])["name"] == "Alfa"


def test_by_id_de_quem_nao_existe_e_none(database):
    assert repo.by_id(database, 9999) is None


def test_a_lista_sai_ordenada_por_nome(database):
    with database:
        repo.insert(database, _fresh(name="Zulu", host="10.0.0.9"), panel.now_iso())
        repo.insert(database, _fresh(name="Alfa", host="10.0.0.1"), panel.now_iso())
    assert [r["name"] for r in repo.all_ordered(database)] == ["Alfa", "Zulu"]


def test_o_endereco_e_a_identidade(database):
    """`(host, ssh_port)` is UNIQUE: it is how a redeploy recognizes what already exists."""
    with database:
        repo.insert(database, _fresh(host="10.0.0.7", ssh_port=2222), panel.now_iso())
    assert repo.by_address(database, "10.0.0.7", 2222)["name"] == "Alfa"
    assert repo.by_address(database, "10.0.0.7", 22) is None


def test_atualiza_so_a_linha_pedida(database):
    with database:
        repo.insert(database, _fresh(name="Alfa", host="10.0.0.1"), panel.now_iso())
        repo.insert(database, _fresh(name="Beta", host="10.0.0.2"), panel.now_iso())
    alvo = repo.by_address(database, "10.0.0.1", 22)
    with database:
        repo.update(database, _fresh(name="Novo", host="10.0.0.1"), alvo["id"])
    assert repo.by_id(database, alvo["id"])["name"] == "Novo"
    assert repo.by_address(database, "10.0.0.2", 22)["name"] == "Beta"


def test_apagar_leva_so_o_escolhido(database):
    with database:
        repo.insert(database, _fresh(host="10.0.0.1"), panel.now_iso())
        repo.insert(database, _fresh(host="10.0.0.2"), panel.now_iso())
    alvo = repo.by_address(database, "10.0.0.1", 22)
    with database:
        repo.delete(database, alvo["id"])
    assert repo.by_id(database, alvo["id"]) is None
    assert len(repo.all_ordered(database)) == 1


def test_so_os_do_broker_aparecem_em_from_broker(database):
    with database:
        repo.insert(database, _fresh(host="10.0.0.1"), panel.now_iso())
        repo.deploy_insert(
            database,
            [getattr(panel.DeployServer(name="Broker", host="10.0.0.2",
                                        service="b.service", broker_id=7), c)
             for c in repo.DEPLOY_FIELDS],
            panel.now_iso())
    achados = repo.from_broker(database)
    assert [r["broker_id"] for r in achados] == [7]


def test_cada_fonte_de_contagem_liga_o_player_source_junto(database):
    """Saving a source's fields without switching the source on leaves the server pointing at
    a count nobody filled in."""
    with database:
        repo.insert(database, _fresh(player_source=""), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]

    with database:
        repo.use_query_port(database, sid, 27016)
    line = repo.by_id(database, sid)
    assert (line["query_port"], line["player_source"]) == (27016, "a2s")

    with database:
        repo.use_log(database, sid, "entrou", "saiu", "/var/log/jogo.log")
    line = repo.by_id(database, sid)
    assert (line["join_re"], line["log_path"], line["player_source"]) == (
        "entrou", "/var/log/jogo.log", "log")

    with database:
        repo.use_http(database, sid, dict.fromkeys(repo.HTTP_FIELDS, "x"))
    line = repo.by_id(database, sid)
    assert (line["http_url"], line["player_source"]) == ("x", "http")


def test_trocar_a_fonte_http_zera_o_token_guardado(database):
    """If the URL or the credential changed, the old token is no longer valid - and the next
    query logs in by itself with what is left."""
    with database:
        repo.insert(database, _fresh(), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]
    with database:
        repo.set_http_token(database, sid, "token-velho")
    assert repo.by_id(database, sid)["http_token"] == "token-velho"
    with database:
        repo.use_http(database, sid, dict.fromkeys(repo.HTTP_FIELDS, "y"))
    assert repo.by_id(database, sid)["http_token"] == ""


def test_config_files_guarda_uma_linha_por_caminho(database):
    with database:
        repo.insert(database, _fresh(), panel.now_iso())
    sid = repo.all_ordered(database)[0]["id"]
    with database:
        repo.set_config_files(database, sid, ["/a.ini", "/b.json"])
    assert repo.by_id(database, sid)["config_files"] == "/a.ini\n/b.json"
