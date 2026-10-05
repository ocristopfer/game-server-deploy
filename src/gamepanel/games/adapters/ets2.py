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
    "lobby_name": FieldSpec(LABEL_NAME, "game.ets2.lobby_name.help"),
    "description": FieldSpec("game.ets2.description.label",
                             "game.ets2.description.help"),
    "welcome_message": FieldSpec("game.ets2.welcome_message.label",
                                 "game.ets2.welcome_message.help"),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "game.ets2.password.help",
                          kind="password"),
    # This warning is what cost us a "vanished" server: above 8, anyone who has not set
    # g_max_convoy_size 128 in the game's own config.cfg does not even see the server in the list.
    "max_players": FieldSpec("game.ets2.max_players.label",
                             "game.ets2.max_players.help",
                             kind="number", minimum=1, maximum=128, step=1),
    "max_vehicles_total": FieldSpec("game.ets2.max_vehicles_total.label",
                                    "game.ets2.max_vehicles_total.help",
                                    kind="number", minimum=0, step=1),
    "max_ai_vehicles_player": FieldSpec("game.ets2.max_ai_vehicles_player.label",
                                        "game.ets2.max_ai_vehicles_player.help",
                                        kind="number", minimum=0, step=1),
    "player_damage": flag("game.ets2.player_damage.label",
                          "game.ets2.player_damage.help"),
    "traffic": flag("game.ets2.traffic.label", "game.ets2.traffic.help"),
    "hide_colliding": flag("game.ets2.hide_colliding.label",
                           "game.ets2.hide_colliding.help"),
    "force_speed_limiter": flag("game.ets2.force_speed_limiter.label",
                                "game.ets2.force_speed_limiter.help"),
    "friends_only": flag("game.ets2.friends_only.label",
                         "game.ets2.friends_only.help"),
    "show_server": flag("game.ets2.show_server.label",
                        "game.ets2.show_server.help"),
    "name_tags": flag("game.ets2.name_tags.label",
                      "game.ets2.name_tags.help"),
    "server_logon_token": FieldSpec("game.ets2.server_logon_token.label",
                                    "game.ets2.server_logon_token.help",
                                    kind="password"),
}
