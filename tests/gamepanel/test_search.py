"""Busca de jogo por nome ou App ID (busca_de_jogos.py) sobre a lista gerada do LinuxGSM."""
from __future__ import annotations

from gamepanel.games.catalog import search as busca
from gamepanel.games.catalog import suggestions as sugestoes_de_jogos


def _nomes(achados):
    return [s["name"] for s in achados]


def test_app_id_exato():
    assert _nomes(busca.search("2394010")) == ["Palworld"]


def test_app_id_que_nao_existe():
    assert busca.search("999999999") == []


def test_nome_sem_acento_e_sem_caixa():
    assert "Palworld" in _nomes(busca.search("PALWORLD"))
    assert "Palworld" in _nomes(busca.search("  pAlWoRlD  "))


def test_palavras_soltas_em_qualquer_ordem():
    assert "Counter-Strike 1.6" in _nomes(busca.search("1 6 counter"))


def test_quem_comeca_pela_consulta_vem_primeiro():
    achados = busca.search("pal")
    assert achados
    assert achados[0]["name"].lower().startswith("pal")


def test_limite():
    assert len(busca.search("a", limit=3)) <= 3


def test_consulta_vazia_ou_so_simbolo_nao_acha_nada():
    for consulta in ("", "   ", None, "!!!", "%%%", "...", "()"):
        assert busca.search(consulta) == []


def test_consulta_nunca_vira_regex_nem_derruba_a_busca():
    for consulta in ("(a+)+$", "[", "\\", "a" * 5000, "'; drop table x; --"):
        assert isinstance(busca.search(consulta), list)


def test_consulta_gigante_e_cortada():
    assert busca.search("palworld " + "x" * 500) == [], "corta em 60 caracteres, e 'palworld xxxx' nao existe"


def test_valores_do_formulario_sempre_trazem_todas_as_chaves():
    chaves = {"key", "name", "app_id", "ports", "game_port", "query_port", "extra_port",
              "start_script", "start_args", "shiftable"}
    for s in sugestoes_de_jogos.SUGGESTIONS:
        assert set(busca.to_form(s)) == chaves
        assert all(isinstance(v, str) for v in busca.to_form(s).values())


def test_sugestao_sem_porta_limpa_os_campos_de_porta_do_jogo_anterior():
    """Escolher um jogo sem porta depois de um com porta nao pode deixar a porta velha no campo."""
    parcial = next(s for s in sugestoes_de_jogos.SUGGESTIONS if not s["ports"])
    valores = busca.to_form(parcial)
    assert valores["ports"] == ""
    assert valores["game_port"] == ""
    assert valores["query_port"] == ""


def test_deslocavel_vira_um_ou_vazio():
    palworld = busca.search("2394010")[0]
    assert busca.to_form(palworld)["shiftable"] == "1"
    satisfactory = busca.search("1690800")[0]
    assert busca.to_form(satisfactory)["shiftable"] == ""
