#!/usr/bin/env python3
"""Testes do catalogo de campos por jogo.

    pytest admin/test_gamefields.py

O que estes testes protegem e a promessa do recurso: o valor que a pessoa digita na
tela (minutos, multiplicador) e o valor que vai para o arquivo (nanossegundos) sao
unidades diferentes, e a conversao tem que ser reversivel. Um erro aqui grava
silenciosamente uma noite de 1 segundo - foi exatamente o que motivou o recurso.
"""
import pytest

from gamepanel.games import gamefields


def field(arquivo: str, chave: str) -> gamefields.FieldSpec:
    """O campo do catalogo, falhando alto se ele sumir.

    Sem isto, uma chave removida do catalogo faria os testes abaixo estourarem com
    `AttributeError: 'NoneType'` - erro que nao diz nada sobre o que se perdeu.
    """
    spec = gamefields.describe(arquivo, chave)
    assert spec is not None, f"{chave} sumiu do catalogo de {arquivo}"
    return spec


def test_duracao_arquivo_em_ns_tela_em_minutos():
    day = field("enshrouded_server.json", "dayTimeDuration")
    assert day.from_display("30") == "1800000000000"
    assert day.to_display("1800000000000") == "30"
    assert day.to_display(day.from_display("2")) == "2", "ida e volta tem de preservar"


@pytest.mark.parametrize("minutos, aceita", [
    ("1", False),    # abaixo do minimo de 2 min
    ("2", True),
    ("60", True),
    ("61", False),   # acima do maximo
])
def test_duracao_respeita_os_limites_do_jogo(minutos, aceita):
    day = field("enshrouded_server.json", "dayTimeDuration")
    assert (day.validate(minutos) == "") is aceita


def test_o_caso_real_noite_de_um_segundo_no_arquivo():
    """1e9 ns = 1 segundo = 0,0167 min, bem abaixo do minimo de 2 min.

    E o bug que originou o catalogo: quem digitava "1" achando que era um minuto
    gravava 1 nanossegundo, e o jogo passava a noite inteira num piscar de olhos.
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


@pytest.mark.parametrize("value, aceita", [
    ("1", True),
    ("4", True),
    ("5", False),       # acima do teto
    ("0", False),       # abaixo do piso
    ("muito", False),   # nem numero e
])
def test_fator_e_multiplicador_com_limite(value, aceita):
    lifetime = field("enshrouded_server.json", "playerHealthFactor")
    assert (lifetime.validate(value) == "") is aceita


def test_fator_nao_converte_unidade():
    """O que se digita e o que vai para o arquivo - diferente da duracao."""
    assert field("enshrouded_server.json", "playerHealthFactor").from_display("1.5") == "1.5"


@pytest.mark.parametrize("value, aceita", [("0.5", True), ("1", True), ("2", False)])
def test_reciclagem_de_perk_vai_de_zero_a_um(value, aceita):
    rec = field("enshrouded_server.json", "perkUpgradeRecyclingFactor")
    assert (rec.validate(value) == "") is aceita


def test_outros_jogos_tem_catalogo_proprio():
    assert field("PalWorldSettings.ini", "ServerPlayerMaxNum").kind == "number"
    assert field("ServerSettings.ini", "ShutdownIfEmptyFor").unit == "s"
    assert field("serverDZ.cfg", "steamQueryPort").kind == "number"
    assert field("DedicatedServer.ini", "WorldPassword").kind == "password"
    assert field("/opt/game/RSDragonwilds/Saved/Config/LinuxServer/DedicatedServer.ini",
                 "AdminPassword").kind == "password"


def test_o_catalogo_e_achado_pelo_nome_do_arquivo_no_caminho_completo():
    assert field("/opt/game/enshrouded_server.json", "slotCount").kind == "number"


def test_o_que_nao_esta_no_catalogo_nao_e_inventado():
    """Campo sem descricao continua editavel como texto livre - nunca some da tela."""
    assert gamefields.describe("enshrouded_server.json", "campoQueNaoExiste") is None
    assert gamefields.describe("qualquer.ini", "name") is None


def test_campo_sem_catalogo_nao_valida_nem_converte():
    empty = gamefields.FieldSpec()
    assert empty.validate("qualquer coisa") == ""
    assert empty.from_display("123") == "123"
