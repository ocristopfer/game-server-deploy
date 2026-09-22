#!/usr/bin/env python3
"""Testes do leitor/gravador de configuracao (gameconf.py).

    pytest admin/test_gameconf.py

O que cada teste garante e o combinado da tela "Configuracao": mexer numa chave nao
pode reescrever o arquivo inteiro, perder comentario nem estragar as chaves vizinhas.
"""
import json

import pytest

from gamepanel.games import config_format as gc


def campo(doc: gc.ConfigFile, secao: str, chave: str) -> gc.Setting:
    """A chave pedida, falhando alto se o parser tiver deixado de enxerga-la."""
    achado = doc.find(secao, chave)
    assert achado is not None, f"{chave!r} nao foi lido da secao {secao!r}"
    return achado


def por_id(doc: gc.ConfigFile, ident: str) -> gc.Setting:
    achado = doc.get(ident)
    assert achado is not None, f"nao achei o campo de id {ident!r}"
    return achado


def erro_ao_aplicar(doc: gc.ConfigFile, edit: gc.Edit) -> str:
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

    nome = campo(doc, doc.settings[0].section, "ServerName")
    assert nome.value == "Servidor antigo", "o valor chega a tela sem as aspas"
    assert campo(doc, nome.section, "bIsPvP").kind == "bool"
    assert campo(doc, nome.section, "PublicPort").kind == "number"


def test_palworld_grava_sem_estragar_a_linha():
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    nome = campo(doc, doc.settings[0].section, "ServerName")
    novo = doc.apply([
        gc.Edit(id=nome.id, section=nome.section, key="ServerName", value="Servidor do Cris"),
        gc.Edit(id="", section=nome.section, key="ServerPlayerMaxNum", value="16"),
        gc.Edit(id="", section=nome.section, key="ServerDescription", value="mundo novo"),
    ])
    assert novo.count("\n") == PALWORLD.count("\n"), "continua com 2 linhas"
    assert 'ServerName="Servidor do Cris"' in novo, "string reganha as aspas"
    assert "ServerPlayerMaxNum=16," in novo, "numero sai sem aspas"
    assert 'ServerDescription="mundo novo"' in novo, "chave nova ganha aspas por ter espaco"
    assert "Difficulty=None,DayTimeSpeedRate=1.000000,bIsPvP=False" in novo, "vizinhos intactos"
    assert 'AdminPassword="troque-me"' in novo, "senha preservada"

    relido = gc.load("PalWorldSettings.ini", novo)
    sec = relido.settings[0].section
    assert campo(relido, sec, "ServerName").value == "Servidor do Cris"
    assert campo(relido, sec, "ServerDescription").value == "mundo novo"


# ----------------------------------------------------------------------- ini

INI = """; Configuracao do servidor
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
    doc = gc.load("DedicatedServer.ini", INI)
    assert [s.key for s in doc.settings] == [
        "ServerName", "AdminPassword", "MaxPlayers", "FrameRateLimit"]
    assert campo(doc, SEC_DW, "AdminPassword").comment == "senha de quem administra"


def test_ini_grava_na_secao_certa():
    doc = gc.load("DedicatedServer.ini", INI)
    novo = doc.apply([
        gc.Edit(id=campo(doc, SEC_DW, "MaxPlayers").id, section=SEC_DW,
                key="MaxPlayers", value="12"),
        gc.Edit(id="", section=SEC_DW, key="WorldName", value="Gielinor"),
        gc.Edit(id="", section="/Script/Engine.GameUserSettings", key="bUseVSync", value="False"),
    ])
    assert "; senha de quem administra" in novo, "comentarios preservados"
    assert "MaxPlayers=12" in novo
    assert novo.index("WorldName=Gielinor") < novo.index("[/Script/Engine.GameUserSettings]")
    assert novo.index("bUseVSync=False") > novo.index("FrameRateLimit")

    relido = gc.load("x.ini", novo)
    assert len(relido.settings) == 6
    assert campo(relido, SEC_DW, "MaxPlayers").value == "12"


def test_ini_sem_secao_e_um_properties():
    doc = gc.load("server.properties", "max-players=10\nmotd=Bem vindo\n")
    assert doc.settings[0].section == ""
    novo = doc.apply([
        gc.Edit(id=doc.settings[0].id, section="", key="max-players", value="20"),
        gc.Edit(id="", section="", key="pvp", value="true"),
    ])
    assert novo == "max-players=20\nmotd=Bem vindo\npvp=true\n"


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
    assert por_id(doc, "userGroups.0.password").key == "password"
    assert por_id(doc, "enableVoiceChat").kind == "bool"
    assert por_id(doc, "slotCount").kind == "number"


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
    error = erro_ao_aplicar(
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
    assert por_id(doc, ID_TEMPLATE).value == "dayzOffline.chernarusplus"
    assert "navegador" in campo(doc, "", "hostname").comment


def test_dayz_grava_dentro_da_class_sem_estragar_a_estrutura():
    doc = gc.load("serverDZ.cfg", DAYZ)
    novo = doc.apply([
        gc.Edit(id=campo(doc, "", "hostname").id, section="", key="hostname", value="Cris DayZ"),
        gc.Edit(id=campo(doc, "", "maxPlayers").id, section="", key="maxPlayers", value="40"),
        gc.Edit(id=ID_TEMPLATE, section="Missions.DayZ",
                key="template", value="dayzOffline.enoch"),
        gc.Edit(id="", section="", key="motd", value="Bem vindo"),
    ])
    assert 'hostname = "Cris DayZ";' in novo, "string com aspas"
    assert "// nome no navegador de servidores" in novo, "comentario da linha preservado"
    assert "maxPlayers = 40;" in novo, "numero sem aspas"
    assert 'template = "dayzOffline.enoch";' in novo, "dentro da class"
    assert 'motd = "Bem vindo";' in novo, "chave nova no fim do bloco raiz"
    assert novo.count("class ") == 2, "as duas class continuam la"
    assert "};" in novo, "e o fechamento delas tambem"

    relido = gc.load("serverDZ.cfg", novo)
    assert campo(relido, "", "motd").value == "Bem vindo"
    assert por_id(relido, ID_TEMPLATE).value == "dayzOffline.enoch"


# -------------------------------------------------------------------- limites

@pytest.mark.parametrize("rotulo, chave, valor, trecho", [
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
def test_entrada_torta_e_recusada(rotulo, chave, valor, trecho):
    doc = gc.load("a.ini", "[s]\nk=1\n")
    error = erro_ao_aplicar(doc, gc.Edit(id="", section="s", key=chave, value=valor))
    assert trecho in error, f"{rotulo}: erro={error!r}"


def test_chave_e_valor_sao_aparados():
    novo = gc.load("a.ini", "[s]\nk=1\n").apply(
        [gc.Edit(id="", section="s", key="  x  ", value="  2  ")])
    assert "x=2" in novo, novo


def test_aspas_no_meio_do_valor_sao_recusadas():
    """No formato da Unreal a aspa fecha o valor: deixar passar corromperia a linha."""
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    alvo = campo(doc, doc.settings[0].section, "ServerName")
    error = erro_ao_aplicar(
        doc, gc.Edit(id=alvo.id, section=alvo.section, key="ServerName", value='a"b'))
    assert "aspas" in error, error


@pytest.mark.parametrize("nome, texto", [
    ("a.ini", INI),
    ("P.ini", PALWORLD),
    ("serverDZ.cfg", DAYZ),
    ("x.json", ENSHROUDED),
])
def test_sem_edicao_o_arquivo_volta_igual(nome, texto):
    """Abrir a tela e salvar sem mexer em nada nao pode reformatar o arquivo do jogo."""
    assert gc.load(nome, texto).apply([]) == texto


@pytest.mark.parametrize("nome, texto, formato", [
    ("x.json", "{}", "json"),
    ("config", '{"a": 1}', "json"),        # pelo conteudo, sem extensao
    ("serverDZ.cfg", DAYZ, "dayz"),        # pelo `class`
    ("s.cfg", 'a = "b";\n', "dayz"),       # cfg simples tambem e dayz
    ("qualquer.txt", "a=1\n", "ini"),      # ini e o padrao
])
def test_deteccao_de_formato(nome, texto, formato):
    assert gc.load(nome, texto).format_id == formato
