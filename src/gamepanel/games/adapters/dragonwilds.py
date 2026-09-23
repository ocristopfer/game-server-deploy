"""Campos de configuracao de RuneScape: Dragonwilds (le DedicatedServer.ini)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec

# O painel escolhe o catalogo pelo NOME do arquivo, que e o mesmo criterio
# que ele ja usa para escolher o leitor.
FILENAME = re.compile(r"^DedicatedServer\.ini$", re.I)

# ------------------------------ RuneScape: Dragonwilds (le DedicatedServer.ini)
# O .ini so cuida de identidade e acesso do servidor. As regras do MUNDO (capacidade de
# carga, estabilidade e custo de construcao, PvP, dificuldade...) NAO estao aqui: moram
# no save do mundo (.sav), e mods como o "No Carry Capacity" so as expoem no menu
# "Edit Settings" do jogo. Nao inventar chave dessas neste catalogo: o jogo ignora.
FIELDS = {
    "OwnerId": FieldSpec("ID do dono",
                         "Seu Player ID, no rodape do menu de Configuracoes do jogo (nao e "
                         "o Steam ID de 17 digitos). Sem ele o servidor NAO sobe."),
    "ServerName": FieldSpec(LABEL_NAME, "Como ele aparece para quem entra."),
    "DefaultWorldName": FieldSpec("Nome do mundo padrao",
                                  "Nome do mundo criado no primeiro start. "
                                  "Trocar depois nao renomeia um mundo que ja existe."),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "Quem souber esta senha abre a aba Server Management no menu "
                               "do jogo e vira admin. TROQUE antes de expor o servidor.",
                               kind="password"),
    "WorldPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.",
                               kind="password"),
    "ServerGuid": FieldSpec("GUID do servidor", "Gerado pelo proprio jogo. Nao edite a mao."),
    "KnownPlayerList": FieldSpec("Jogadores conhecidos",
                                 "Preenchido pelo proprio jogo (quem ja entrou, privilegios "
                                 "e banimentos). Nao edite a mao."),
}
