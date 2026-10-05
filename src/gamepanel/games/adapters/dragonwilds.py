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
    "OwnerId": FieldSpec("game.dragonwilds.ownerid.label",
                         "game.dragonwilds.ownerid.help"),
    "ServerName": FieldSpec(LABEL_NAME, "game.dragonwilds.servername.help"),
    "DefaultWorldName": FieldSpec("game.dragonwilds.defaultworldname.label",
                                  "game.dragonwilds.defaultworldname.help"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "game.dragonwilds.adminpassword.help",
                               kind="password"),
    "WorldPassword": FieldSpec(LABEL_JOIN_PASSWORD, "game.dragonwilds.worldpassword.help",
                               kind="password"),
    "ServerGuid": FieldSpec("game.dragonwilds.serverguid.label",
                            "game.dragonwilds.serverguid.help"),
    "KnownPlayerList": FieldSpec("game.dragonwilds.knownplayerlist.label",
                                 "game.dragonwilds.knownplayerlist.help"),
}
