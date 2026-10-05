"""Configuration fields for Icarus (reads ServerSettings.ini)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_ADMIN_PASSWORD, LABEL_JOIN_PASSWORD, LABEL_NAME, UNIT_SECONDS, FieldSpec, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^ServerSettings\.ini$", re.I)

# ----------------------------------------------- Icarus (reads ServerSettings.ini)
FIELDS = {
    "SessionName": FieldSpec(LABEL_NAME, "game.icarus.sessionname.help"),
    "JoinPassword": FieldSpec(LABEL_JOIN_PASSWORD, "game.icarus.joinpassword.help",
                              kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "game.icarus.adminpassword.help",
                               kind="password"),
    "MaxPlayers": FieldSpec("game.icarus.maxplayers.label",
                            "game.icarus.maxplayers.help",
                            kind="number", minimum=1, maximum=64, step=1),
    "AllowNonAdminsToLaunchProspects": flag(
        "game.icarus.allownonadminstolaunchprospects.label",
        "game.icarus.allownonadminstolaunchprospects.help"),
    "AllowNonAdminsToDeleteProspects": flag(
        "game.icarus.allownonadminstodeleteprospects.label",
        "game.icarus.allownonadminstodeleteprospects.help"),
    "ShutdownIfNotJoinedFor": FieldSpec(
        "game.icarus.shutdownifnotjoinedfor.label",
        "game.icarus.shutdownifnotjoinedfor.help",
        kind="number", minimum=0, maximum=86400, step=60, unit=UNIT_SECONDS),
    "ShutdownIfEmptyFor": FieldSpec(
        "game.icarus.shutdownifemptyfor.label",
        "game.icarus.shutdownifemptyfor.help",
        kind="number", minimum=0, maximum=86400, step=60, unit=UNIT_SECONDS),
    "ResumeProspect": flag("game.icarus.resumeprospect.label",
                           "game.icarus.resumeprospect.help"),
    "LoadProspect": FieldSpec("game.icarus.loadprospect.label",
                              "game.icarus.loadprospect.help"),
    "CreateProspect": FieldSpec("game.icarus.createprospect.label",
                                "game.icarus.createprospect.help"),
    "LastProspectName": FieldSpec("game.icarus.lastprospectname.label",
                                  "game.icarus.lastprospectname.help"),
}
