#!/usr/bin/env python3
"""Testes do leitor/gravador de configuracao (gameconf.py).

Sem dependencia externa — roda com o python3 do container do painel:

    docker compose exec panel python3 /opt/gamepanel/test_gameconf.py
    python3 admin/test_gameconf.py

O que cada teste garante e o combinado da tela "Config": mexer numa chave nao pode
reescrever o arquivo inteiro, perder comentario nem estragar as chaves vizinhas.
"""
import json
import sys

import gameconf as gc

falhas = []


def check(nome, condicao, detalhe=""):
    if condicao:
        print(f"  ok   {nome}")
    else:
        print(f"  FALHOU {nome} {detalhe}")
        falhas.append(nome)


def igual(nome, obtido, esperado):
    check(nome, obtido == esperado, f"\n    obtido:   {obtido!r}\n    esperado: {esperado!r}")


# ------------------------------------------------------------------ palworld

PALWORLD = """[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,bIsPvP=False,DeathPenalty=All,ServerPlayerMaxNum=32,ServerName="Servidor antigo",AdminPassword="troque-me",PublicPort=8211)
"""


def teste_palworld():
    print("palworld (OptionSettings=(...))")
    doc = gc.load("PalWorldSettings.ini", PALWORLD)
    igual("formato", doc.formato, "ini")
    nomes = [s.key for s in doc.settings]
    igual("todas as chaves viraram campos", len(nomes), 8)
    check("secao com rotulo legivel", any("OptionSettings" in s.label for s in doc.sections))

    nome = doc.find(doc.settings[0].section, "ServerName")
    igual("valor sem aspas na tela", nome.value, "Servidor antigo")
    igual("bool detectado", doc.find(nome.section, "bIsPvP").kind, "bool")
    igual("numero detectado", doc.find(nome.section, "PublicPort").kind, "number")

    novo = doc.apply([
        gc.Edit(id=nome.id, section=nome.section, key="ServerName", value="Servidor do Cris"),
        gc.Edit(id="", section=nome.section, key="ServerPlayerMaxNum", value="16"),
        gc.Edit(id="", section=nome.section, key="ServerDescription", value="mundo novo"),
    ])
    check("arquivo continua com 2 linhas", novo.count("\n") == PALWORLD.count("\n"))
    check("string reganha as aspas", 'ServerName="Servidor do Cris"' in novo)
    check("numero sai sem aspas", "ServerPlayerMaxNum=16," in novo)
    check("chave nova ganha aspas por ter espaco", 'ServerDescription="mundo novo"' in novo)
    check("vizinhos intactos", "Difficulty=None,DayTimeSpeedRate=1.000000,bIsPvP=False" in novo)
    check("senha preservada", 'AdminPassword="troque-me"' in novo)

    relido = gc.load("PalWorldSettings.ini", novo)
    sec = relido.settings[0].section
    igual("releitura ve o nome novo", relido.find(sec, "ServerName").value, "Servidor do Cris")
    igual("releitura ve a chave nova", relido.find(sec, "ServerDescription").value, "mundo novo")


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


def teste_ini():
    print("ini com secoes e comentarios")
    doc = gc.load("DedicatedServer.ini", INI)
    igual("chaves lidas", [s.key for s in doc.settings],
          ["ServerName", "AdminPassword", "MaxPlayers", "FrameRateLimit"])
    igual("comentario vira ajuda",
          doc.find("/Script/Dragonwilds.DedicatedServerSettings", "AdminPassword").comment,
          "senha de quem administra")

    sec = "/Script/Dragonwilds.DedicatedServerSettings"
    novo = doc.apply([
        gc.Edit(id=doc.find(sec, "MaxPlayers").id, section=sec, key="MaxPlayers", value="12"),
        gc.Edit(id="", section=sec, key="WorldName", value="Gielinor"),
        gc.Edit(id="", section="/Script/Engine.GameUserSettings", key="bUseVSync", value="False"),
    ])
    check("comentarios preservados", "; senha de quem administra" in novo)
    check("valor trocado", "MaxPlayers=12" in novo)
    check("chave nova entra na secao certa",
          novo.index("WorldName=Gielinor") < novo.index("[/Script/Engine.GameUserSettings]"))
    check("chave nova na segunda secao",
          novo.index("bUseVSync=False") > novo.index("FrameRateLimit"))

    relido = gc.load("x.ini", novo)
    igual("releitura: 6 chaves", len(relido.settings), 6)
    igual("releitura: MaxPlayers", relido.find(sec, "MaxPlayers").value, "12")


def teste_ini_sem_secao():
    print("ini sem secao (.properties)")
    doc = gc.load("server.properties", "max-players=10\nmotd=Bem vindo\n")
    igual("secao raiz", doc.settings[0].section, "")
    novo = doc.apply([
        gc.Edit(id=doc.settings[0].id, section="", key="max-players", value="20"),
        gc.Edit(id="", section="", key="pvp", value="true"),
    ])
    igual("gravado", novo, "max-players=20\nmotd=Bem vindo\npvp=true\n")


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


def teste_json():
    print("json (enshrouded_server.json)")
    doc = gc.load("enshrouded_server.json", ENSHROUDED)
    igual("formato", doc.formato, "json")
    igual("campo aninhado tem caminho completo",
          doc.get("userGroups.0.password").key, "password")
    igual("tipo bool", doc.get("enableVoiceChat").kind, "bool")
    igual("tipo numero", doc.get("slotCount").kind, "number")

    novo = doc.apply([
        gc.Edit(id="name", section="", key="name", value="Servidor do Cris"),
        gc.Edit(id="slotCount", section="", key="slotCount", value="8"),
        gc.Edit(id="enableVoiceChat", section="", key="enableVoiceChat", value="true"),
        gc.Edit(id="userGroups.0.password", section="userGroups.0", key="password", value="s3nh4"),
        gc.Edit(id="", section="", key="gamePort", value="15636"),
    ])
    dados = json.loads(novo)
    igual("texto", dados["name"], "Servidor do Cris")
    igual("numero continua numero", dados["slotCount"], 8)
    igual("bool continua bool", dados["enableVoiceChat"], True)
    igual("aninhado", dados["userGroups"][0]["password"], "s3nh4")
    igual("chave nova tipada pelo texto", dados["gamePort"], 15636)
    igual("nao mexeu no vizinho", dados["userGroups"][0]["canKickBan"], True)

    erro = ""
    try:
        doc.apply([gc.Edit(id="slotCount", section="", key="slotCount", value="dezesseis")])
    except gc.ConfigError as exc:
        erro = str(exc)
    check("numero invalido e recusado", "numero" in erro, erro)


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


def teste_dayz():
    print("dayz (serverDZ.cfg)")
    doc = gc.load("serverDZ.cfg", DAYZ)
    igual("formato", doc.formato, "dayz")
    igual("chave dentro de class",
          doc.get(f"Missions.DayZ{gc.SEP}template").value, "dayzOffline.chernarusplus")
    check("comentario da linha vira ajuda",
          "navegador" in doc.find("", "hostname").comment)

    novo = doc.apply([
        gc.Edit(id=doc.find("", "hostname").id, section="", key="hostname", value="Cris DayZ"),
        gc.Edit(id=doc.find("", "maxPlayers").id, section="", key="maxPlayers", value="40"),
        gc.Edit(id=f"Missions.DayZ{gc.SEP}template", section="Missions.DayZ",
                key="template", value="dayzOffline.enoch"),
        gc.Edit(id="", section="", key="motd", value="Bem vindo"),
    ])
    check("string com aspas", 'hostname = "Cris DayZ";' in novo)
    check("comentario da linha preservado", "// nome no navegador de servidores" in novo)
    check("numero sem aspas", "maxPlayers = 40;" in novo)
    check("dentro da class", 'template = "dayzOffline.enoch";' in novo)
    check("chave nova no fim do bloco raiz", 'motd = "Bem vindo";' in novo)
    check("estrutura das classes intacta", novo.count("class ") == 2 and "};" in novo)

    relido = gc.load("serverDZ.cfg", novo)
    igual("releitura", relido.find("", "motd").value, "Bem vindo")
    igual("releitura aninhada",
          relido.get(f"Missions.DayZ{gc.SEP}template").value, "dayzOffline.enoch")


# -------------------------------------------------------------------- limites


def teste_validacao():
    print("validacao de entrada")
    doc = gc.load("a.ini", "[s]\nk=1\n")
    for rotulo, edit, trecho in [
        ("chave vazia", gc.Edit(id="", section="s", key="", value="1"), "invalido"),
        ("chave com = no nome", gc.Edit(id="", section="s", key="x=y", value="1"), "invalido"),
        ("quebra de linha no valor",
         gc.Edit(id="", section="s", key="x", value="a\nb"), "quebra de linha"),
    ]:
        erro = ""
        try:
            doc.apply([edit])
        except gc.ConfigError as exc:
            erro = str(exc)
        check(rotulo, trecho in erro, f"erro={erro!r}")

    espacos = gc.load("a.ini", "[s]\nk=1\n").apply(
        [gc.Edit(id="", section="s", key="  x  ", value="  2  ")])
    check("chave e valor sao aparados", "x=2" in espacos, espacos)

    pal = gc.load("PalWorldSettings.ini", PALWORLD)
    alvo = pal.find(pal.settings[0].section, "ServerName")
    erro = ""
    try:
        pal.apply([gc.Edit(id=alvo.id, section=alvo.section, key="ServerName", value='a"b')])
    except gc.ConfigError as exc:
        erro = str(exc)
    check("aspas no meio do valor sao recusadas", "aspas" in erro, erro)

    # Sem alteracao nenhuma o arquivo tem de voltar byte a byte: e o que garante que
    # abrir a tela e salvar sem mexer em nada nao reformata a configuracao do jogo.
    for rotulo, nome, texto in [("ini", "a.ini", INI), ("palworld", "P.ini", PALWORLD),
                                ("dayz", "serverDZ.cfg", DAYZ), ("json", "x.json", ENSHROUDED)]:
        igual(f"{rotulo}: sem edicao o arquivo volta igual", gc.load(nome, texto).apply([]), texto)


def teste_deteccao():
    print("deteccao de formato")
    igual("json pela extensao", gc.load("x.json", "{}").formato, "json")
    igual("json pelo conteudo", gc.load("config", '{"a": 1}').formato, "json")
    igual("dayz pelo class", gc.load("serverDZ.cfg", DAYZ).formato, "dayz")
    igual("cfg simples cai no dayz", gc.load("s.cfg", 'a = "b";\n').formato, "dayz")
    igual("ini padrao", gc.load("qualquer.txt", "a=1\n").formato, "ini")


for teste in (teste_palworld, teste_ini, teste_ini_sem_secao, teste_json, teste_dayz,
              teste_validacao, teste_deteccao):
    teste()

print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam: {', '.join(falhas)}")
    sys.exit(1)
print("tudo certo.")
