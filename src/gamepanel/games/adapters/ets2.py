"""Configuration fields for Euro Truck Simulator 2 (reads server_config.sii)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader. American Truck Simulator uses the same file.
FILENAME = re.compile(r"^server_config\.sii$", re.I)

# The physical ports (connection/query_dedicated_port) are left out on purpose:
# start-ets2.sh rewrites them on every start with the systemd ones, and changing them here would do nothing.
FIELDS = {
    "lobby_name": FieldSpec(LABEL_NAME, "Como aparece na lista de servidores do jogo."),
    "description": FieldSpec("Descrição", "Texto curto mostrado junto do nome na lista."),
    "welcome_message": FieldSpec("Mensagem de boas-vindas", "Aparece no chat para quem entra."),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    # This warning is what cost us a "vanished" server: above 8, anyone who has not set
    # g_max_convoy_size 128 in the game's own config.cfg does not even see the server in the list.
    "max_players": FieldSpec("Vagas",
                             "Acima de 8, CADA jogador precisa de g_max_convoy_size 128 no "
                             "config.cfg do jogo, senão o servidor some da lista dele.",
                             kind="number", minimum=1, maximum=128, step=1),
    "max_vehicles_total": FieldSpec("Veículos no total", "Limite de veículos no mundo.",
                                    kind="number", minimum=0, step=1),
    "max_ai_vehicles_player": FieldSpec("Tráfego por jogador", "Veículos de IA em volta de cada um.",
                                        kind="number", minimum=0, step=1),
    "player_damage": flag("Dano entre jogadores", "Colisão entre caminhões causa dano."),
    "traffic": flag("Tráfego", "Liga os veículos de IA."),
    "hide_colliding": flag("Esconder quem colide", "Caminhão parado em cima do outro some."),
    "force_speed_limiter": flag("Limitador de velocidade", "Obriga o limitador ligado."),
    "friends_only": flag("Só amigos", "Só amigos da Steam de quem está no servidor entram."),
    "show_server": flag("Mostrar na lista", "Desligado = só entra quem procura pelo ID."),
    "name_tags": flag("Nomes sobre os caminhões", "Mostra o nome de cada jogador."),
    "server_logon_token": FieldSpec("Token de logon",
                                    "Mantém a mesma identidade do servidor entre reinícios.",
                                    kind="password"),
}
