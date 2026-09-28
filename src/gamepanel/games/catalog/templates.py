#!/usr/bin/env python3
"""Modelos para o formulario "Adicionar jogo" do catalogo.

Um modelo NAO e um jogo: e um conjunto de valores que o formulario preenche de uma vez,
para a pessoa so completar o que muda (nome, app id, nome da pasta do projeto). Quem
valida de verdade continua sendo o broker — o modelo nao da poder nenhum, so poupa
digitacao e o erro de esquecer um marcador.

E o caminho de quem busca um jogo que nao esta em fonte nenhuma: a busca nao acha, mas a
MOTOR do jogo quase sempre se sabe (Unreal, Unity, Source), e cada motor tem o seu jeito
de receber porta, escrever log e guardar save.

Puro de proposito (sem Flask, sem banco), como `navigation.py`: e dado, e o
`tests/gamebroker/unit/test_templates.py` carrega este arquivo e confere que cada modelo
passa no validador do broker.

Os nomes das chaves de `values` sao os `name=` dos campos do formulario. `recipes` e a
lista de caixas marcadas, separadas por espaco. Rotulo e descricao sao CHAVES do catalogo
de i18n: texto escrito aqui sairia em portugues na tela em ingles.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# O projeto da Unreal e a pasta que aparece dentro de /opt/game depois da instalacao
# (Pal, RSDragonwilds, FactoryGame). Nao ha como saber sem instalar; por isso o modelo
# traz um nome de mentira bem visivel em vez de um chute silencioso.
PROJECT = "NomeDoProjeto"
# O mesmo para o executavel de um jogo Unity (VRisingServer.exe, CoreKeeperServer).
EXECUTABLE = "NomeDoExecutavel"
# E para a pasta do mod de um jogo Source (-game cstrike, -game tf).
MOD = "pasta_do_jogo"


@dataclass(frozen=True)
class Template:
    key: str
    label_key: str
    description_key: str
    values: dict[str, str] = field(default_factory=dict)


# Todo modelo diz TODOS os campos que conhece, inclusive os vazios: trocar de modelo tem de
# limpar o que o anterior deixou (a plataforma Windows e o Proton de um, no jogo Linux do
# outro, virariam uma instalacao de Wine que ninguem pediu).
_BLANK = {
    "start_script": "", "start_args": "", "ports": "", "game_port": "", "query_port": "",
    "extra_port": "", "memory_mb": "", "cores": "", "disk_gb": "", "config_path": "",
    "config_files": "", "backup_paths": "", "player_source": "log", "join_re": "",
    "leave_re": "", "platform": "", "recipes": "", "shiftable": "",
}

# As duas linhas saem do log real do Satisfactory. A de saida nao traz o nome de quem saiu,
# entao a lista de jogadores fica aproximada (a contagem certa).
_UNREAL_JOIN = "LogNet: Join succeeded: (?P<name>.+)"
_UNREAL_LEAVE = "LogNet: UNetConnection::Close:"


UNREAL_LINUX = Template(
    key="unreal-linux",
    label_key="catalog.template.unreal_linux",
    description_key="catalog.template.unreal_linux_help",
    values={
        **_BLANK,
        # `-log` manda o log para o stdout (o journald guarda e o painel le); `-Port` e o
        # padrao da Unreal para a porta de jogo (UDP).
        "start_args": "-log -Port={PORT}",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "30",
        # Todo servidor Unreal guarda config e save sob <Projeto>/Saved.
        "config_path": f"/opt/game/{PROJECT}/Saved/Config/LinuxServer",
        "config_files": (
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/Game.ini\n"
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/GameUserSettings.ini"
        ),
        "backup_paths": f"/opt/game/{PROJECT}/Saved/SaveGames",
        "join_re": _UNREAL_JOIN,
        "leave_re": _UNREAL_LEAVE,
        # Os argumentos acima recebem {PORT}: o broker pode sortear a porta.
        "shiftable": "1",
    },
)

UNREAL_WINDOWS = Template(
    key="unreal-windows",
    label_key="catalog.template.unreal_windows",
    description_key="catalog.template.unreal_windows_help",
    values={
        **_BLANK,
        # O .exe da raiz de um servidor Unreal e so o bootstrap: sem interface ele fica de pe
        # sem nunca gerar o servidor (foi o caso do Icarus). O Shipping e o que abre porta.
        "start_script": f"{PROJECT}/Binaries/Win64/{PROJECT}Server-Win64-Shipping.exe",
        # -log abriria uma JANELA de console, presa num X que ninguem ve; o par -stdout
        # -FullStdOutLogOutput e o que faz o log chegar ao journal (ver games/icarus.env).
        "start_args": "-stdout -FullStdOutLogOutput -Port={PORT} -QueryPort={QUERY_PORT}",
        "ports": "7777/udp 27015/udp",
        "game_port": "7777",
        "query_port": "27015",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "30",
        "config_path": f"/opt/game/{PROJECT}/Saved/Config/WindowsServer",
        "config_files": (
            f"/opt/game/{PROJECT}/Saved/Config/WindowsServer/Game.ini\n"
            f"/opt/game/{PROJECT}/Saved/Config/WindowsServer/GameUserSettings.ini"
        ),
        "backup_paths": f"/opt/game/{PROJECT}/Saved/SaveGames",
        # A query da Steam ja esta aberta para a lista de servidores; e mais confiavel que o
        # log, que muda de jogo para jogo.
        "player_source": "a2s",
        # Proton, e nao wine: fsync/ntsync, que o wine da distro nao tem. Wine so se o
        # Proton comprovadamente nao funcionar com o jogo.
        "platform": "windows",
        "recipes": "proton",
        "shiftable": "1",
    },
)

UNITY_LINUX = Template(
    key="unity-linux",
    label_key="catalog.template.unity_linux",
    description_key="catalog.template.unity_linux_help",
    values={
        **_BLANK,
        "start_script": f"{EXECUTABLE}.x86_64",
        # -batchmode -nographics: sem isso a Unity tenta abrir placa de video. `-logFile -`
        # manda o log para o stdout (journal), e nao para ~/.config/unity3d/.../Player.log.
        "start_args": "-batchmode -nographics -logFile -",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "4096",
        "cores": "2",
        "disk_gb": "20",
        "config_path": "/opt/game",
    },
)

UNITY_WINDOWS = Template(
    key="unity-windows",
    label_key="catalog.template.unity_windows",
    description_key="catalog.template.unity_windows_help",
    values={
        **_BLANK,
        "start_script": f"{EXECUTABLE}.exe",
        "start_args": "-batchmode -nographics -logFile -",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "20",
        "config_path": "/opt/game",
        "platform": "windows",
        # O X virtual custa pouco e poupa o erro mais comum de servidor Unity sob Proton:
        # criar janela na largada e morrer sem display (o V Rising faz isso).
        "recipes": "proton xvfb",
    },
)

SOURCE = Template(
    key="source",
    label_key="catalog.template.source",
    description_key="catalog.template.source_help",
    values={
        **_BLANK,
        "start_script": "srcds_run",
        # -strictportbind: sem ele o srcds pula para a proxima porta livre em silencio, e o
        # firewall fica aberto numa porta onde o jogo nao esta.
        "start_args": f"-game {MOD} -console -strictportbind -port {{PORT}} +map MAPA +maxplayers 16",
        "ports": "27015/udp 27015/tcp",
        "game_port": "27015",
        "memory_mb": "2048",
        "cores": "2",
        "disk_gb": "20",
        # Sem config_files: o server.cfg do Source e uma lista de comandos de console, nao um
        # .ini, e o formulario campo a campo o leria errado. A pasta abre no editor de arquivo.
        "config_path": f"/opt/game/{MOD}/cfg",
        # O que o console do srcds escreve ao entrar e ao sair, com o nome nos dois lados.
        "join_re": 'Client "(?P<name>.+?)" connected',
        "leave_re": "Dropped (?P<name>.+?) from server",
        "recipes": "steamclient-sdk64",
        "shiftable": "1",
    },
)

TEMPLATES = (UNREAL_LINUX, UNREAL_WINDOWS, UNITY_LINUX, UNITY_WINDOWS, SOURCE)
