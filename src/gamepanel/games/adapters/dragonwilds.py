"""Configuration fields for RuneScape: Dragonwilds (reads DedicatedServer.ini)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^DedicatedServer\.ini$", re.I)

# ------------------------------ RuneScape: Dragonwilds (reads DedicatedServer.ini)
# The .ini only handles the server identity and access. The WORLD rules (carry capacity,
# building stability and cost, PvP, difficulty...) are NOT here: they live in the world
# save (.sav), and mods like "No Carry Capacity" only expose them in the game's "Edit
# Settings" menu. Do not invent such keys in this catalog: the game ignores them.
FIELDS = {
    "OwnerId": FieldSpec("ID do dono",
                         "Seu Player ID, no rodapé do menu de Configurações do jogo (não é "
                         "o Steam ID de 17 dígitos). Sem ele o servidor NÃO sobe."),
    "ServerName": FieldSpec(LABEL_NAME, "Como ele aparece para quem entra."),
    "DefaultWorldName": FieldSpec("Nome do mundo padrão",
                                  "Nome do mundo criado no primeiro start. "
                                  "Trocar depois não renomeia um mundo que já existe."),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "Quem souber esta senha abre a aba Server Management no menu "
                               "do jogo e vira admin. TROQUE antes de expor o servidor.",
                               kind="password"),
    "WorldPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.",
                               kind="password"),
    "ServerGuid": FieldSpec("GUID do servidor", "Gerado pelo próprio jogo. Não edite à mão."),
    "KnownPlayerList": FieldSpec("Jogadores conhecidos",
                                 "Preenchido pelo próprio jogo (quem já entrou, privilégios "
                                 "e banimentos). Não edite à mão."),
}
