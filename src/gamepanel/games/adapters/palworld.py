"""Configuration fields for Palworld (reads PalWorldSettings.ini, all of it."""
from __future__ import annotations

import re

from gamepanel.games.base import (
    LABEL_ADMIN_PASSWORD,
    LABEL_JOIN_PASSWORD,
    LABEL_NAME,
    FieldSpec,
    enum_of,
    factor,
    flag,
)

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^PalWorldSettings\.ini$", re.I)

# ------------------------------------------- Palworld (reads PalWorldSettings.ini, all of it
# inside OptionSettings=(...)). The English texts (i18n/en.py) follow the game's own world
# settings menu ("EXP rate", "Death penalty", "Pal capture rate"), which is what the person looks for.
FIELDS = {
    "ServerName": FieldSpec(LABEL_NAME, "game.palworld.servername.help"),
    "ServerPassword": FieldSpec(LABEL_JOIN_PASSWORD, "game.palworld.serverpassword.help",
                                kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "game.palworld.adminpassword.help", kind="password"),
    "ServerPlayerMaxNum": FieldSpec("game.palworld.serverplayermaxnum.label",
                                    "game.palworld.serverplayermaxnum.help",
                                    kind="number", minimum=1, maximum=32, step=1),
    "PublicPort": FieldSpec("game.palworld.publicport.label",
                            "game.palworld.publicport.help",
                            kind="number", minimum=1024, maximum=65535, step=1),
    "RESTAPIEnabled": flag("game.palworld.restapienabled.label",
                           "game.palworld.restapienabled.help"),
    "RESTAPIPort": FieldSpec("game.palworld.restapiport.label",
                             "game.palworld.restapiport.help",
                             kind="number", minimum=1024, maximum=65535, step=1),
    "RCONEnabled": flag("game.palworld.rconenabled.label",
                        "game.palworld.rconenabled.help"),
    "DeathPenalty": enum_of("game.palworld.deathpenalty.label",
                            "game.palworld.deathpenalty.help",
                            {"None": "game.palworld.deathpenalty.opt.none",
                             "Item": "game.palworld.deathpenalty.opt.item",
                             "ItemAndEquipment": "game.palworld.deathpenalty.opt.itemandequipment",
                             "All": "game.palworld.deathpenalty.opt.all"}),
    "DayTimeSpeedRate": factor("game.palworld.daytimespeedrate.label",
                               "game.palworld.daytimespeedrate.help",
                               0.1, 5.0),
    "NightTimeSpeedRate": factor("game.palworld.nighttimespeedrate.label",
                                 "game.palworld.nighttimespeedrate.help",
                                 0.1, 5.0),
    "ExpRate": factor("game.palworld.exprate.label",
                      "game.palworld.exprate.help",
                      0.1, 20.0),
    "PalCaptureRate": factor("game.palworld.palcapturerate.label",
                             "game.palworld.palcapturerate.help", 0.5, 2.0),
    "PalSpawnNumRate": factor("game.palworld.palspawnnumrate.label",
                              "game.palworld.palspawnnumrate.help", 0.5, 3.0),
    "PalDamageRateAttack": factor("game.palworld.paldamagerateattack.label",
                                  "game.palworld.paldamagerateattack.help", 0.1, 5.0),
    "PalDamageRateDefense": factor("game.palworld.paldamageratedefense.label",
                                   "game.palworld.paldamageratedefense.help",
                                   0.1, 5.0),
    "PlayerDamageRateAttack": factor("game.palworld.playerdamagerateattack.label",
                                     "game.palworld.playerdamagerateattack.help", 0.1, 5.0),
    "PlayerDamageRateDefense": factor("game.palworld.playerdamageratedefense.label",
                                      "game.palworld.playerdamageratedefense.help",
                                      0.1, 5.0),
    "CollectionDropRate": factor("game.palworld.collectiondroprate.label",
                                 "game.palworld.collectiondroprate.help", 0.5, 3.0),
    "EnablePlayerToPlayerDamage": flag("game.palworld.enableplayertoplayerdamage.label",
                                       "game.palworld.enableplayertoplayerdamage.help"),
    "bEnableDefenseOtherGuild": flag("game.palworld.benabledefenseotherguild.label",
                                     "game.palworld.benabledefenseotherguild.help"),
}
