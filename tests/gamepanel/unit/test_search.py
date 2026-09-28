"""Busca de jogo por nome ou App ID (busca_de_jogos.py) sobre a lista gerada do LinuxGSM."""
from __future__ import annotations

from gamepanel.games.catalog import manual_suggestions
from gamepanel.games.catalog import search as busca
from gamepanel.games.catalog import suggestions as sugestoes_de_jogos


def _names(achados):
    return [s["name"] for s in achados]


def test_app_id_exato():
    assert _names(busca.search("2394010")) == ["Palworld"]


def test_app_id_que_nao_existe():
    assert busca.search("999999999") == []


def test_nome_sem_acento_e_sem_caixa():
    assert "Palworld" in _names(busca.search("PALWORLD"))
    assert "Palworld" in _names(busca.search("  pAlWoRlD  "))


def test_palavras_soltas_em_qualquer_ordem():
    assert "Counter-Strike 1.6" in _names(busca.search("1 6 counter"))


def test_quem_comeca_pela_consulta_vem_primeiro():
    results = busca.search("pal")
    assert results
    assert results[0]["name"].lower().startswith("pal")


def test_limite():
    assert len(busca.search("a", limit=3)) <= 3


def test_consulta_vazia_ou_so_simbolo_nao_acha_nada():
    for query_of in ("", "   ", None, "!!!", "%%%", "...", "()"):
        assert busca.search(query_of) == []


def test_consulta_nunca_vira_regex_nem_derruba_a_busca():
    for query_of in ("(a+)+$", "[", "\\", "a" * 5000, "'; drop table x; --"):
        assert isinstance(busca.search(query_of), list)


def test_consulta_gigante_e_cortada():
    assert busca.search("palworld " + "x" * 500) == [], "corta em 60 caracteres, e 'palworld xxxx' nao existe"


def test_valores_do_formulario_sempre_trazem_todas_as_chaves():
    keys = {"key", "name", "app_id", "ports", "game_port", "query_port", "extra_port",
              "start_script", "start_args", "shiftable", "config_path", "config_files",
              "player_source", "backup_paths", "join_re", "leave_re", "memory_mb", "cores",
              "disk_gb", "platform", "recipes"}
    for s in (*sugestoes_de_jogos.SUGGESTIONS, *manual_suggestions.SUGGESTIONS):
        assert set(busca.to_form(s)) == keys
        assert all(isinstance(v, str) for v in busca.to_form(s).values())


def test_sugestao_sem_porta_limpa_os_campos_de_porta_do_jogo_anterior():
    """Escolher um jogo sem porta depois de um com porta nao pode deixar a porta velha no campo."""
    partial = next(s for s in sugestoes_de_jogos.SUGGESTIONS if not s["ports"])
    values = busca.to_form(partial)
    assert values["ports"] == ""
    assert values["game_port"] == ""
    assert values["query_port"] == ""


def test_deslocavel_vira_um_ou_vazio():
    palworld = busca.search("2394010")[0]
    assert busca.to_form(palworld)["shiftable"] == "1"
    satisfactory = busca.search("1690800")[0]
    assert busca.to_form(satisfactory)["shiftable"] == ""


def test_jogo_so_de_windows_que_o_linuxgsm_nao_tem_e_achado():
    """Era o buraco: servidor sem build Linux nao existe no LinuxGSM, e a busca voltava vazia."""
    found = busca.search("abiotic")
    assert _names(found) == ["Abiotic Factor"]
    values = busca.to_form(found[0])
    assert values["platform"] == "windows"
    assert values["recipes"] == "proton"
    assert busca.result(found[0])["source"] == manual_suggestions.SOURCE


def test_app_id_da_lista_manual_tambem_casa():
    assert _names(busca.search("2430930")) == ["ARK: Survival Ascended"]


def test_sugestao_do_linuxgsm_limpa_windows_e_proton_da_anterior():
    """Escolher Palworld depois do Abiotic Factor nao pode deixar o Proton marcado."""
    values = busca.to_form(busca.search("2394010")[0])
    assert values["platform"] == ""
    assert values["recipes"] == ""
    assert busca.result(busca.search("2394010")[0])["source"] == sugestoes_de_jogos.SOURCE
