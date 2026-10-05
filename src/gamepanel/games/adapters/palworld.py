"""Configuration fields for Palworld (reads PalWorldSettings.ini, all of it."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec, enum_of, factor, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^PalWorldSettings\.ini$", re.I)

# ------------------------------------------- Palworld (reads PalWorldSettings.ini, all of it
# inside OptionSettings=(...))
FIELDS = {
    "ServerName": FieldSpec(LABEL_NAME, "Como ele aparece na lista da comunidade."),
    "ServerPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "Usada nos comandos administrativos e na API REST.", kind="password"),
    "ServerPlayerMaxNum": FieldSpec("Vagas", "Máximo de jogadores simultâneos (limite de 32).",
                                    kind="number", minimum=1, maximum=32, step=1),
    "PublicPort": FieldSpec("Porta pública", "Precisa bater com a porta redirecionada no roteador.",
                            kind="number", minimum=1024, maximum=65535, step=1),
    "RESTAPIEnabled": flag("API REST",
                            "Liga a API que o painel usa para mostrar os NOMES dos jogadores."),
    "RESTAPIPort": FieldSpec("Porta da API REST", "Nunca redirecione esta porta no roteador.",
                             kind="number", minimum=1024, maximum=65535, step=1),
    "RCONEnabled": flag("RCON", "Console remoto. Depreciado pela Pocketpair em favor da API REST."),
    "DeathPenalty": enum_of("Penalidade de morte", "O que você perde ao morrer.",
                          {"None": "Nada", "Item": "Itens (sem equipamento)",
                           "ItemAndEquipment": "Itens e equipamento",
                           "All": "Tudo (inclui Pals)"}),
    "DayTimeSpeedRate": factor("Velocidade do dia", "Maior = dia passa mais rápido.", 0.1, 5.0),
    "NightTimeSpeedRate": factor("Velocidade da noite", "Maior = noite passa mais rápido.", 0.1, 5.0),
    "ExpRate": factor("Ganho de XP", "Multiplica toda a experiência recebida.", 0.1, 20.0),
    "PalCaptureRate": factor("Taxa de captura", "Multiplica a chance de capturar Pals.", 0.5, 2.0),
    "PalSpawnNumRate": factor("Quantidade de Pals", "Multiplica quantos Pals aparecem no mundo.", 0.5, 3.0),
    "PalDamageRateAttack": factor("Dano dos Pals", "Multiplica o dano causado pelos Pals.", 0.1, 5.0),
    "PalDamageRateDefense": factor("Defesa dos Pals", "Multiplica a resistência dos Pals.", 0.1, 5.0),
    "PlayerDamageRateAttack": factor("Dano do jogador", "Multiplica o dano que você causa.", 0.1, 5.0),
    "PlayerDamageRateDefense": factor("Defesa do jogador", "Multiplica sua resistência.", 0.1, 5.0),
    "CollectionDropRate": factor("Recursos coletados", "Multiplica o que cai ao coletar.", 0.5, 3.0),
    "EnablePlayerToPlayerDamage": flag("PvP", "Permite jogadores se atacarem."),
    "bEnableDefenseOtherGuild": flag("Defesa de outras guildas",
                                      "Permite que sua base seja atacada por outras guildas."),
}
