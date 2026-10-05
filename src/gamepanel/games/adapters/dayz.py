"""Configuration fields for DayZ (reads serverDZ.cfg)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, UNIT_FACTOR, FieldSpec

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^serverDZ\.cfg$", re.I)

# --------------------------------------------------- DayZ (reads serverDZ.cfg)
FIELDS = {
    "hostname": FieldSpec(LABEL_NAME, "game.dayz.hostname.help"),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "game.dayz.password.help",
                          kind="password"),
    "passwordAdmin": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "game.dayz.passwordadmin.help",
                               kind="password"),
    "maxPlayers": FieldSpec("game.dayz.maxplayers.label",
                            "game.dayz.maxplayers.help",
                            kind="number", minimum=1, maximum=127, step=1),
    "steamQueryPort": FieldSpec("game.dayz.steamqueryport.label",
                                "game.dayz.steamqueryport.help",
                                kind="number", minimum=1024, maximum=65535, step=1),
    "verifySignatures": FieldSpec("game.dayz.verifysignatures.label",
                                  "game.dayz.verifysignatures.help",
                                  kind="number", minimum=0, maximum=2, step=1),
    "forceSameBuild": FieldSpec("game.dayz.forcesamebuild.label",
                                "game.dayz.forcesamebuild.help",
                                kind="number", minimum=0, maximum=1, step=1),
    "disable3rdPerson": FieldSpec("game.dayz.disable3rdperson.label",
                                  "game.dayz.disable3rdperson.help",
                                  kind="number", minimum=0, maximum=1, step=1),
    "disableVoN": FieldSpec("game.dayz.disablevon.label",
                            "game.dayz.disablevon.help",
                            kind="number", minimum=0, maximum=1, step=1),
    "serverTimeAcceleration": FieldSpec(
        "game.dayz.servertimeacceleration.label",
        "game.dayz.servertimeacceleration.help",
        kind="number", minimum=0, maximum=64, step=1, unit=UNIT_FACTOR),
    "instanceId": FieldSpec("game.dayz.instanceid.label",
                            "game.dayz.instanceid.help"),
}
