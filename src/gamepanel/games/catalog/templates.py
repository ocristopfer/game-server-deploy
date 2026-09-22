#!/usr/bin/env python3
"""Modelos para o formulario "Adicionar jogo" do catalogo.

Um modelo NAO e um jogo: e um conjunto de valores que o formulario preenche de uma vez,
para a pessoa so completar o que muda (nome, app id, nome da pasta do projeto). Quem
valida de verdade continua sendo o broker — o modelo nao da poder nenhum, so poupa
digitacao e o erro de esquecer um marcador.

Puro de proposito (sem Flask, sem banco), como `ui.py`: e dado, e o `broker/test_modelos.py`
carrega este arquivo e confere que cada modelo passa no validador do broker.

Os nomes das chaves de `valores` sao os `name=` dos campos do formulario.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# O projeto da Unreal e a pasta que aparece dentro de /opt/game depois da instalacao
# (Pal, RSDragonwilds, FactoryGame). Nao ha como saber sem instalar; por isso o modelo
# traz um nome de mentira bem visivel em vez de um chute silencioso.
PROJECT = "NomeDoProjeto"


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    description: str
    values: dict[str, str] = field(default_factory=dict)


UNREAL_LINUX = Template(
    key="unreal-linux",
    label="Unreal Engine (servidor nativo Linux)",
    description=(
        "Vale para Palworld, Satisfactory, RuneScape Dragonwilds e a maioria dos jogos da "
        f"Unreal. Depois de escolher, troque {PROJECT} pelo nome da pasta do projeto (a que "
        "aparece em /opt/game depois de instalar) e ponha o App ID do servidor dedicado."
    ),
    values={
        # `-log` manda o log para o stdout (o journald guarda e o painel le); `-Port` e o
        # padrao da Unreal para a porta de jogo (UDP).
        "start_args": "-log -Port={PORT}",
        "portas": "7777/udp",
        "porta_jogo": "7777",
        "porta_query": "",
        "porta_extra": "",
        "memoria_mb": "8192",
        "cores": "4",
        "disco_gb": "30",
        # Todo servidor Unreal guarda config e save sob <Projeto>/Saved.
        "config_path": f"/opt/game/{PROJECT}/Saved/Config/LinuxServer",
        "config_files": (
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/Game.ini\n"
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/GameUserSettings.ini"
        ),
        "backup_paths": f"/opt/game/{PROJECT}/Saved/SaveGames",
        # As duas linhas abaixo saem do log real do Satisfactory. A de saida nao traz o
        # nome de quem saiu, entao a lista de jogadores fica aproximada (a contagem certa).
        "player_source": "log",
        "join_re": "LogNet: Join succeeded: (?P<name>.+)",
        "leave_re": "LogNet: UNetConnection::Close:",
        # Os argumentos acima recebem {PORT}: o broker pode sortear a porta.
        "deslocavel": "1",
    },
)

TEMPLATES = (UNREAL_LINUX,)
