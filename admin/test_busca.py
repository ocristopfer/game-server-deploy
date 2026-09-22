"""Busca de jogo por nome ou App ID (busca_de_jogos.py) sobre a lista gerada do LinuxGSM."""
from __future__ import annotations

import busca_de_jogos as busca
import sugestoes_de_jogos


def _nomes(achados):
    return [s["nome"] for s in achados]


def test_app_id_exato():
    assert _nomes(busca.buscar("2394010")) == ["Palworld"]


def test_app_id_que_nao_existe():
    assert busca.buscar("999999999") == []


def test_nome_sem_acento_e_sem_caixa():
    assert "Palworld" in _nomes(busca.buscar("PALWORLD"))
    assert "Palworld" in _nomes(busca.buscar("  pAlWoRlD  "))


def test_palavras_soltas_em_qualquer_ordem():
    assert "Counter-Strike 1.6" in _nomes(busca.buscar("1 6 counter"))


def test_quem_comeca_pela_consulta_vem_primeiro():
    achados = busca.buscar("pal")
    assert achados
    assert achados[0]["nome"].lower().startswith("pal")


def test_limite():
    assert len(busca.buscar("a", limite=3)) <= 3


def test_consulta_vazia_ou_so_simbolo_nao_acha_nada():
    for consulta in ("", "   ", None, "!!!", "%%%", "...", "()"):
        assert busca.buscar(consulta) == []


def test_consulta_nunca_vira_regex_nem_derruba_a_busca():
    for consulta in ("(a+)+$", "[", "\\", "a" * 5000, "'; drop table x; --"):
        assert isinstance(busca.buscar(consulta), list)


def test_consulta_gigante_e_cortada():
    assert busca.buscar("palworld " + "x" * 500) == [], "corta em 60 caracteres, e 'palworld xxxx' nao existe"


def test_valores_do_formulario_sempre_trazem_todas_as_chaves():
    chaves = {"chave", "nome", "app_id", "portas", "porta_jogo", "porta_query", "porta_extra",
              "start_script", "start_args", "deslocavel"}
    for s in sugestoes_de_jogos.SUGESTOES:
        assert set(busca.para_o_formulario(s)) == chaves
        assert all(isinstance(v, str) for v in busca.para_o_formulario(s).values())


def test_sugestao_sem_porta_limpa_os_campos_de_porta_do_jogo_anterior():
    """Escolher um jogo sem porta depois de um com porta nao pode deixar a porta velha no campo."""
    parcial = next(s for s in sugestoes_de_jogos.SUGESTOES if not s["portas"])
    valores = busca.para_o_formulario(parcial)
    assert valores["portas"] == ""
    assert valores["porta_jogo"] == ""
    assert valores["porta_query"] == ""


def test_deslocavel_vira_um_ou_vazio():
    palworld = busca.buscar("2394010")[0]
    assert busca.para_o_formulario(palworld)["deslocavel"] == "1"
    satisfactory = busca.buscar("1690800")[0]
    assert busca.para_o_formulario(satisfactory)["deslocavel"] == ""
