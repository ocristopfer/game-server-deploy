"""Campos de configuracao de Euro Truck Simulator 2 (le server_config.sii)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_JOIN_PASSWORD, LABEL_NAME, FieldSpec, flag

# O painel escolhe o catalogo pelo NOME do arquivo, que e o mesmo criterio
# que ele ja usa para escolher o leitor. O American Truck Simulator usa o mesmo arquivo.
FILENAME = re.compile(r"^server_config\.sii$", re.I)

# As portas fisicas (connection/query_dedicated_port) ficam de fora de proposito: o
# start-ets2.sh as reescreve a cada subida com as do systemd, e mudar aqui nao faria nada.
FIELDS = {
    "lobby_name": FieldSpec(LABEL_NAME, "Como aparece na lista de servidores do jogo."),
    "description": FieldSpec("Descricao", "Texto curto mostrado junto do nome na lista."),
    "welcome_message": FieldSpec("Mensagem de boas-vindas", "Aparece no chat para quem entra."),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    # O aviso e o que custou um servidor "sumido": acima de 8, quem nao pos
    # g_max_convoy_size 128 no config.cfg do proprio jogo nem ve o servidor na lista.
    "max_players": FieldSpec("Vagas",
                             "Acima de 8, CADA jogador precisa de g_max_convoy_size 128 no "
                             "config.cfg do jogo, senao o servidor some da lista dele.",
                             kind="number", minimum=1, maximum=128, step=1),
    "max_vehicles_total": FieldSpec("Veiculos no total", "Limite de veiculos no mundo.",
                                    kind="number", minimum=0, step=1),
    "max_ai_vehicles_player": FieldSpec("Trafego por jogador", "Veiculos de IA em volta de cada um.",
                                        kind="number", minimum=0, step=1),
    "player_damage": flag("Dano entre jogadores", "Colisao entre caminhoes causa dano."),
    "traffic": flag("Trafego", "Liga os veiculos de IA."),
    "hide_colliding": flag("Esconder quem colide", "Caminhao parado em cima do outro some."),
    "force_speed_limiter": flag("Limitador de velocidade", "Obriga o limitador ligado."),
    "friends_only": flag("So amigos", "So amigos da Steam de quem esta no servidor entram."),
    "show_server": flag("Mostrar na lista", "Desligado = so entra quem procura pelo ID."),
    "name_tags": flag("Nomes sobre os caminhoes", "Mostra o nome de cada jogador."),
    "server_logon_token": FieldSpec("Token de logon",
                                    "Mantem a mesma identidade do servidor entre reinicios.",
                                    kind="password"),
}
