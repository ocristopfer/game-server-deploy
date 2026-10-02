#!/usr/bin/env python3
"""Testes do leitor/gravador de configuracao (gameconf.py).

    pytest admin/test_config_format.py

O que cada teste garante e o combinado da tela "Configuracao": mexer numa chave nao
pode reescrever o arquivo inteiro, perder comentario nem estragar as chaves vizinhas.
"""
import json

import pytest

from gamepanel.games import config_format as gc


def field(doc: gc.ConfigFile, section: str, key: str) -> gc.Setting:
    """A chave pedida, falhando alto se o parser tiver deixado de enxerga-la."""
    found = doc.find(section, key)
    assert found is not None, f"{key!r} nao foi lido da secao {section!r}"
    return found


def by_id(doc: gc.ConfigFile, ident: str) -> gc.Setting:
    found = doc.get(ident)
    assert found is not None, f"nao achei o campo de id {ident!r}"
    return found


def apply_failure(doc: gc.ConfigFile, edit: gc.Edit) -> str:
    """A mensagem de recusa, ou string vazia se o gravador tiver aceitado."""
    try:
        doc.apply([edit])
    except gc.ConfigError as exc:
        return str(exc)
    return ""


# ------------------------------------------------------------------ palworld

PALWORLD = """[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,bIsPvP=False,DeathPenalty=All,ServerPlayerMaxNum=32,ServerName="Servidor antigo",AdminPassword="troque-me",PublicPort=8211)
"""


def test_palworld_abre_a_tupla_da_unreal_como_campos():
    """`OptionSettings=(...)` nao e um valor: e a configuracao inteira numa linha."""
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    assert doc.format_id == "ini"
    assert len([s.key for s in doc.settings]) == 8
    assert any("OptionSettings" in s.label for s in doc.sections)

    name = field(doc, doc.settings[0].section, "ServerName")
    assert name.value == "Servidor antigo", "o valor chega a tela sem as aspas"
    assert field(doc, name.section, "bIsPvP").kind == "bool"
    assert field(doc, name.section, "PublicPort").kind == "number"


def test_palworld_grava_sem_estragar_a_linha():
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    name = field(doc, doc.settings[0].section, "ServerName")
    fresh = doc.apply([
        gc.Edit(id=name.id, section=name.section, key="ServerName", value="Servidor do Cris"),
        gc.Edit(id="", section=name.section, key="ServerPlayerMaxNum", value="16"),
        gc.Edit(id="", section=name.section, key="ServerDescription", value="mundo novo"),
    ])
    assert fresh.count("\n") == PALWORLD.count("\n"), "continua com 2 linhas"
    assert 'ServerName="Servidor do Cris"' in fresh, "string reganha as aspas"
    assert "ServerPlayerMaxNum=16," in fresh, "numero sai sem aspas"
    assert 'ServerDescription="mundo novo"' in fresh, "chave nova ganha aspas por ter espaco"
    assert "Difficulty=None,DayTimeSpeedRate=1.000000,bIsPvP=False" in fresh, "vizinhos intactos"
    assert 'AdminPassword="troque-me"' in fresh, "senha preservada"

    reread = gc.load("PalWorldSettings.ini", fresh)
    sec = reread.settings[0].section
    assert field(reread, sec, "ServerName").value == "Servidor do Cris"
    assert field(reread, sec, "ServerDescription").value == "mundo novo"


# ----------------------------------------------------------------------- ini

INI_TEXT = """; Configuracao do servidor
[/Script/Dragonwilds.DedicatedServerSettings]
ServerName=Servidor antigo
; senha de quem administra
AdminPassword=troque-me
MaxPlayers=8

[/Script/Engine.GameUserSettings]
FrameRateLimit=30.000000
"""

SEC_DW = "/Script/Dragonwilds.DedicatedServerSettings"


def test_ini_le_secoes_e_comentarios():
    doc = gc.load("DedicatedServer.ini", INI_TEXT)
    assert [s.key for s in doc.settings] == [
        "ServerName", "AdminPassword", "MaxPlayers", "FrameRateLimit"]
    assert field(doc, SEC_DW, "AdminPassword").comment == "senha de quem administra"


def test_ini_grava_na_secao_certa():
    doc = gc.load("DedicatedServer.ini", INI_TEXT)
    fresh = doc.apply([
        gc.Edit(id=field(doc, SEC_DW, "MaxPlayers").id, section=SEC_DW,
                key="MaxPlayers", value="12"),
        gc.Edit(id="", section=SEC_DW, key="WorldName", value="Gielinor"),
        gc.Edit(id="", section="/Script/Engine.GameUserSettings", key="bUseVSync", value="False"),
    ])
    assert "; senha de quem administra" in fresh, "comentarios preservados"
    assert "MaxPlayers=12" in fresh
    assert fresh.index("WorldName=Gielinor") < fresh.index("[/Script/Engine.GameUserSettings]")
    assert fresh.index("bUseVSync=False") > fresh.index("FrameRateLimit")

    reread = gc.load("x.ini", fresh)
    assert len(reread.settings) == 6
    assert field(reread, SEC_DW, "MaxPlayers").value == "12"


def test_ini_sem_secao_e_um_properties():
    doc = gc.load("server.properties", "max-players=10\nmotd=Bem vindo\n")
    assert doc.settings[0].section == ""
    fresh = doc.apply([
        gc.Edit(id=doc.settings[0].id, section="", key="max-players", value="20"),
        gc.Edit(id="", section="", key="pvp", value="true"),
    ])
    assert fresh == "max-players=20\nmotd=Bem vindo\npvp=true\n"


# ---------------------------------------------------------------------- json

ENSHROUDED = """{
  "name": "Enshrouded Server",
  "slotCount": 16,
  "enableVoiceChat": false,
  "userGroups": [
    {
      "name": "Admin",
      "password": "TROQUE-ESTA-SENHA-ADMIN",
      "canKickBan": true
    }
  ]
}
"""


def test_json_le_objeto_aninhado_como_secao():
    doc = gc.load("enshrouded_server.json", ENSHROUDED)
    assert doc.format_id == "json"
    assert by_id(doc, "userGroups.0.password").key == "password"
    assert by_id(doc, "enableVoiceChat").kind == "bool"
    assert by_id(doc, "slotCount").kind == "number"


def test_json_preserva_o_tipo_de_cada_valor():
    """O arquivo e reescrito inteiro pelo dumps: o que nao pode mudar e o TIPO."""
    doc = gc.load("enshrouded_server.json", ENSHROUDED)
    data = json.loads(doc.apply([
        gc.Edit(id="name", section="", key="name", value="Servidor do Cris"),
        gc.Edit(id="slotCount", section="", key="slotCount", value="8"),
        gc.Edit(id="enableVoiceChat", section="", key="enableVoiceChat", value="true"),
        gc.Edit(id="userGroups.0.password", section="userGroups.0", key="password", value="s3nh4"),
        gc.Edit(id="", section="", key="gamePort", value="15636"),
    ]))
    assert data["name"] == "Servidor do Cris"
    assert data["slotCount"] == 8, "numero continua numero"
    assert data["enableVoiceChat"] is True, "bool continua bool"
    assert data["userGroups"][0]["password"] == "s3nh4"
    assert data["gamePort"] == 15636, "chave nova e tipada pelo texto"
    assert data["userGroups"][0]["canKickBan"] is True, "nao mexeu no vizinho"


def test_json_recusa_texto_onde_o_arquivo_tem_numero():
    doc = gc.load("enshrouded_server.json", ENSHROUDED)
    error = apply_failure(
        doc, gc.Edit(id="slotCount", section="", key="slotCount", value="dezesseis"))
    assert "numero" in error, error


# ---------------------------------------------------------------------- dayz

DAYZ = """hostname = "Servidor antigo";        // nome no navegador de servidores
password = "";                     // senha para entrar
maxPlayers = 20;
steamQueryPort = 27016;            // porta de consulta

class Missions
{
    class DayZ
    {
        template = "dayzOffline.chernarusplus";
    };
};
"""

ID_TEMPLATE = f"Missions.DayZ{gc.SEP}template"


def test_dayz_le_class_como_secao_e_comentario_como_ajuda():
    doc = gc.load("serverDZ.cfg", DAYZ)
    assert doc.format_id == "dayz"
    assert by_id(doc, ID_TEMPLATE).value == "dayzOffline.chernarusplus"
    assert "navegador" in field(doc, "", "hostname").comment


def test_dayz_grava_dentro_da_class_sem_estragar_a_estrutura():
    doc = gc.load("serverDZ.cfg", DAYZ)
    fresh = doc.apply([
        gc.Edit(id=field(doc, "", "hostname").id, section="", key="hostname", value="Cris DayZ"),
        gc.Edit(id=field(doc, "", "maxPlayers").id, section="", key="maxPlayers", value="40"),
        gc.Edit(id=ID_TEMPLATE, section="Missions.DayZ",
                key="template", value="dayzOffline.enoch"),
        gc.Edit(id="", section="", key="motd", value="Bem vindo"),
    ])
    assert 'hostname = "Cris DayZ";' in fresh, "string com aspas"
    assert "// nome no navegador de servidores" in fresh, "comentario da linha preservado"
    assert "maxPlayers = 40;" in fresh, "numero sem aspas"
    assert 'template = "dayzOffline.enoch";' in fresh, "dentro da class"
    assert 'motd = "Bem vindo";' in fresh, "chave nova no fim do bloco raiz"
    assert fresh.count("class ") == 2, "as duas class continuam la"
    assert "};" in fresh, "e o fechamento delas tambem"

    reread = gc.load("serverDZ.cfg", fresh)
    assert field(reread, "", "motd").value == "Bem vindo"
    assert by_id(reread, ID_TEMPLATE).value == "dayzOffline.enoch"


# -------------------------------------------------------------------- limites

@pytest.mark.parametrize("label,key,value,chunk", [
    ("chave vazia", "", "1", "invalido"),
    ("chave com = no nome", "x=y", "1", "invalido"),
    # O nome da chave vai para dentro do arquivo do jogo, gravado por SSH: ele e ASCII e
    # ponto final. Isto aqui guarda o `re.ASCII` do KEY_RE - sem a flag, `\w` em Python
    # aceitaria acento e mais uns 900 caracteres Unicode.
    ("chave com acento", "opção", "1", "invalido"),
    ("chave com ; no nome", "a;b", "1", "invalido"),
    ("chave comecando com ponto", ".x", "1", "invalido"),
    ("quebra de linha no valor", "x", "a\nb", "quebra de linha"),
])
def test_entrada_torta_e_recusada(label, key, value, chunk):
    doc = gc.load("a.ini", "[s]\nk=1\n")
    error = apply_failure(doc, gc.Edit(id="", section="s", key=key, value=value))
    assert chunk in error, f"{label}: erro={error!r}"


def test_chave_e_valor_sao_aparados():
    fresh = gc.load("a.ini", "[s]\nk=1\n").apply(
        [gc.Edit(id="", section="s", key="  x  ", value="  2  ")])
    assert "x=2" in fresh, fresh


def test_aspas_no_meio_do_valor_sao_recusadas():
    """No formato da Unreal a aspa fecha o valor: deixar passar corromperia a linha."""
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    target = field(doc, doc.settings[0].section, "ServerName")
    error = apply_failure(
        doc, gc.Edit(id=target.id, section=target.section, key="ServerName", value='a"b'))
    assert "aspas" in error, error


@pytest.mark.parametrize("name, text", [
    ("a.ini", INI_TEXT),
    ("P.ini", PALWORLD),
    ("serverDZ.cfg", DAYZ),
    ("x.json", ENSHROUDED),
])
def test_sem_edicao_o_arquivo_volta_igual(name, text):
    """Abrir a tela e salvar sem mexer em nada nao pode reformatar o arquivo do jogo."""
    assert gc.load(name, text).apply([]) == text


@pytest.mark.parametrize("name, text, file_format", [
    ("x.json", "{}", "json"),
    ("config", '{"a": 1}', "json"),        # pelo conteudo, sem extensao
    ("serverDZ.cfg", DAYZ, "dayz"),        # pelo `class`
    ("s.cfg", 'a = "b";\n', "dayz"),       # cfg simples tambem e dayz
    ("qualquer.txt", "a=1\n", "ini"),      # ini e o padrao
])
def test_deteccao_de_formato(name, text, file_format):
    assert gc.load(name, text).format_id == file_format


# ------------------------------------------------------------------ BOM

VRISING_HOST = '﻿{\n  "Name": "V Rising Server",\n  "Port": 9876,\n  "ListOnSteam": false\n}\n'


def test_json_com_bom_abre_no_formulario():
    """Os padroes do V Rising vem com BOM, e o json.loads o recusava: a tela Config nao abria."""
    doc = gc.load("ServerHostSettings.json", VRISING_HOST)
    assert isinstance(doc, gc.JsonConfig)
    assert doc.find(doc.settings[0].section, "Name").value == "V Rising Server"


def test_bom_volta_ao_gravar_e_so_uma_vez():
    doc = gc.load("ServerHostSettings.json", VRISING_HOST)
    name = doc.find(doc.settings[0].section, "Name")
    out = doc.apply([gc.Edit(id=name.id, section=name.section, key="Name", value="Castelo")])
    assert out.startswith("﻿{")
    assert out.count("﻿") == 1
    assert json.loads(out.removeprefix("﻿"))["Name"] == "Castelo"


def test_arquivo_sem_bom_continua_sem_bom():
    doc = gc.load("ServerHostSettings.json", VRISING_HOST.removeprefix("﻿"))
    name = doc.find(doc.settings[0].section, "Name")
    out = doc.apply([gc.Edit(id=name.id, section=name.section, key="Name", value="Castelo")])
    assert not out.startswith("﻿")


def test_ini_com_bom_nao_vira_parte_do_nome_da_secao():
    doc = gc.load("Game.ini", "﻿[/Script/Jogo]\nMaxPlayers=8\n")
    assert isinstance(doc, gc.IniConfig)
    setting = doc.find("/Script/Jogo", "MaxPlayers")
    assert setting is not None
    out = doc.apply([gc.Edit(id=setting.id, section=setting.section, key="MaxPlayers", value="16")])
    assert out.startswith("﻿[/Script/Jogo]")


def test_json_com_bom_e_extensao_estranha_ainda_e_json():
    assert isinstance(gc.load("settings.txt", VRISING_HOST), gc.JsonConfig)


# ---------------------------------------------------------------------- sii

# Copia do server_config.sii de um ETS2 de verdade (senha e token trocados). O
# `description: discordia` sem aspas e como o proprio servidor grava.
ETS2_SII = """SiiNunit
{
server_config : _nameless.39bc.86a0 {
 lobby_name: "server da discordia"
 description: discordia
 welcome_message: ""
 password: "segredo"
 max_players: 8
 connection_dedicated_port: 27018
 player_damage: true
 moderator_list: 1
 moderator_list[0]: 76561198000000000
}

}"""


def test_sii_abre_o_server_config_do_ets2_como_campos():
    """Antes caia no leitor de ini, sem `=` nenhum: "Configuracoes (0)" na tela."""
    doc = gc.load("server_config.sii", ETS2_SII)
    assert isinstance(doc, gc.SiiConfig)
    assert [s.label for s in doc.sections] == ["server_config"]
    assert doc.find("server_config", "lobby_name").value == "server da discordia"
    assert doc.find("server_config", "description").value == "discordia"
    assert doc.find("server_config", "max_players").kind == "number"
    assert doc.find("server_config", "player_damage").kind == "bool"
    assert doc.find("server_config", "moderator_list[0]").value == "76561198000000000"


def test_sii_grava_so_a_linha_alterada_e_respeita_as_aspas():
    doc = gc.load("server_config.sii", ETS2_SII)
    edits = []
    for key, value in (("max_players", "16"), ("description", "dois termos"),
                       ("lobby_name", "Caminhoneiros"), ("player_damage", "false")):
        s = doc.find("server_config", key)
        edits.append(gc.Edit(id=s.id, section=s.section, key=key, value=value))
    out = doc.apply(edits)
    assert " max_players: 16\n" in out
    # Palavra solta podia ficar sem aspas; frase com espaco, nao.
    assert ' description: "dois termos"\n' in out
    assert ' lobby_name: "Caminhoneiros"\n' in out
    assert " player_damage: false\n" in out
    assert out.replace(" max_players: 16", " max_players: 8").replace(
        ' description: "dois termos"', " description: discordia").replace(
        '"Caminhoneiros"', '"server da discordia"').replace(
        "player_damage: false", "player_damage: true") == ETS2_SII


def test_sii_chave_nova_entra_dentro_do_bloco():
    doc = gc.load("server_config.sii", ETS2_SII)
    out = doc.apply([gc.Edit(section="server_config", key="traffic", value="true")])
    lines = out.split("\n")
    assert lines[lines.index(" moderator_list[0]: 76561198000000000") + 1] == " traffic: true"


def test_sii_recusa_aspas_no_valor():
    doc = gc.load("server_config.sii", ETS2_SII)
    s = doc.find("server_config", "lobby_name")
    with pytest.raises(gc.ConfigError):
        doc.apply([gc.Edit(id=s.id, section=s.section, key=s.key, value='a"b')])


def test_sii_sem_edicao_volta_igual_e_e_detectado_pelo_conteudo():
    assert gc.load("server_config.sii", ETS2_SII).apply([]) == ETS2_SII
    assert isinstance(gc.load("config.txt", ETS2_SII), gc.SiiConfig)
