#!/usr/bin/env python3
"""Tests for the per-game field catalog.

    pytest tests/gamepanel/test_game_fields.py

What these tests protect is the feature's promise: the value the person types on screen
(minutes, multiplier) and the value that goes into the file (nanoseconds) are different
units, and the conversion has to be reversible. A mistake here silently writes a 1-second
night - which is exactly what prompted the feature.
"""
import pytest

from gamepanel.games import registry as game_fields


def field(arquivo: str, key: str) -> game_fields.FieldSpec:
    """The catalog field, failing loudly if it disappears.

    Without this, a key removed from the catalog would make the tests below blow up with
    `AttributeError: 'NoneType'` - an error that says nothing about what was lost.
    """
    spec = game_fields.describe(arquivo, key)
    assert spec is not None, f"{key} sumiu do catalogo de {arquivo}"
    return spec


def test_duracao_arquivo_em_ns_tela_em_minutos():
    day = field("enshrouded_server.json", "dayTimeDuration")
    assert day.from_display("30") == "1800000000000"
    assert day.to_display("1800000000000") == "30"
    assert day.to_display(day.from_display("2")) == "2", "ida e volta tem de preservar"


@pytest.mark.parametrize("minutes, accepted", [
    ("1", False),    # below the 2 min minimum
    ("2", True),
    ("60", True),
    ("61", False),   # above the maximum
])
def test_duracao_respeita_os_limites_do_jogo(minutes, accepted):
    day = field("enshrouded_server.json", "dayTimeDuration")
    assert (day.validate(minutes) == "") is accepted


def test_o_caso_real_noite_de_um_segundo_no_arquivo():
    """1e9 ns = 1 second = 0.0167 min, well below the 2 min minimum.

    It is the bug that gave rise to the catalog: whoever typed "1" thinking it was one minute
    wrote 1 nanosecond, and the game went through the whole night in the blink of an eye.
    """
    night = field("enshrouded_server.json", "nightTimeDuration")
    assert night.to_display("1000000000") == "0.0166667"
    assert night.validate("0.0166667") != "", "tem de ser recusado ao salvar"


def test_enum_so_aceita_valor_que_o_jogo_entende():
    grave = field("enshrouded_server.json", "tombstoneMode")
    assert grave.validate("AddBackpackMaterials") == ""
    assert grave.validate("NoTombstone") == ""
    assert grave.validate("PerdeTudo") != ""
    assert len(grave.options) == 3


@pytest.mark.parametrize("value, accepted", [
    ("1", True),
    ("4", True),
    ("5", False),       # above the ceiling
    ("0", False),       # below the floor
    ("muito", False),   # not even a number
])
def test_fator_e_multiplicador_com_limite(value, accepted):
    lifetime = field("enshrouded_server.json", "playerHealthFactor")
    assert (lifetime.validate(value) == "") is accepted


def test_fator_nao_converte_unidade():
    """What is typed is what goes into the file - unlike the duration."""
    assert field("enshrouded_server.json", "playerHealthFactor").from_display("1.5") == "1.5"


@pytest.mark.parametrize("value, accepted", [("0.5", True), ("1", True), ("2", False)])
def test_reciclagem_de_perk_vai_de_zero_a_um(value, accepted):
    rec = field("enshrouded_server.json", "perkUpgradeRecyclingFactor")
    assert (rec.validate(value) == "") is accepted


def test_outros_jogos_tem_catalogo_proprio():
    assert field("PalWorldSettings.ini", "ServerPlayerMaxNum").kind == "number"
    assert field("ServerSettings.ini", "ShutdownIfEmptyFor").unit == "game.unit.seconds"
    assert field("serverDZ.cfg", "steamQueryPort").kind == "number"
    assert field("DedicatedServer.ini", "WorldPassword").kind == "password"
    assert field("/opt/game/RSDragonwilds/Saved/Config/LinuxServer/DedicatedServer.ini",
                 "AdminPassword").kind == "password"


def test_o_catalogo_e_achado_pelo_nome_do_arquivo_no_caminho_completo():
    assert field("/opt/game/enshrouded_server.json", "slotCount").kind == "number"


def test_o_que_nao_esta_no_catalogo_nao_e_inventado():
    """A field without a description stays editable as free text - it never disappears from the screen."""
    assert game_fields.describe("enshrouded_server.json", "campoQueNaoExiste") is None
    assert game_fields.describe("qualquer.ini", "name") is None


def test_campo_sem_catalogo_nao_valida_nem_converte():
    empty = game_fields.FieldSpec()
    assert empty.validate("qualquer coisa") == ""
    assert empty.from_display("123") == "123"
