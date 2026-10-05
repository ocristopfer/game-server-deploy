"""Configuration fields for Enshrouded (reads enshrouded_server.json)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_NAME, UNIT_FACTOR, FieldSpec, duration, enum_of, factor, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^enshrouded_server\.json$", re.I)

# ------------------------------------------- Enshrouded (reads enshrouded_server.json)
FIELDS = {
    "name": FieldSpec(LABEL_NAME, "game.enshrouded.name.help"),
    "slotCount": FieldSpec("game.enshrouded.slotcount.label", "game.enshrouded.slotcount.help",
                           kind="number", minimum=1, maximum=16, step=1),
    "queryPort": FieldSpec("game.enshrouded.queryport.label", "game.enshrouded.queryport.help",
                           kind="number", minimum=1024, maximum=65535, step=1),
    "ip": FieldSpec("game.enshrouded.ip.label", "game.enshrouded.ip.help"),
    "enableVoiceChat": flag("game.enshrouded.enablevoicechat.label", "game.enshrouded.enablevoicechat.help"),
    "enableTextChat": flag("game.enshrouded.enabletextchat.label", "game.enshrouded.enabletextchat.help"),
    "voiceChatMode": enum_of("game.enshrouded.voicechatmode.label",
                             "game.enshrouded.voicechatmode.help",
                             {"Proximity": "game.enshrouded.voicechatmode.opt.proximity",
                              "Global": "game.enshrouded.voicechatmode.opt.global"}),
    "gameSettingsPreset": enum_of(
        "game.enshrouded.gamesettingspreset.label",
        "game.enshrouded.gamesettingspreset.help",
        {"Default": "game.enshrouded.gamesettingspreset.opt.default",
         "Relaxed": "game.enshrouded.gamesettingspreset.opt.relaxed",
         "Hard": "game.enshrouded.gamesettingspreset.opt.hard",
         "Survival": "game.enshrouded.gamesettingspreset.opt.survival",
         "Custom": "game.enshrouded.gamesettingspreset.opt.custom"}),

    # --- player
    "playerHealthFactor": factor("game.enshrouded.playerhealthfactor.label",
                                 "game.enshrouded.playerhealthfactor.help"),
    "playerManaFactor": factor("game.enshrouded.playermanafactor.label",
                               "game.enshrouded.playermanafactor.help"),
    "playerStaminaFactor": factor("game.enshrouded.playerstaminafactor.label",
                                  "game.enshrouded.playerstaminafactor.help"),
    "playerBodyHeatFactor": factor("game.enshrouded.playerbodyheatfactor.label",
                                   "game.enshrouded.playerbodyheatfactor.help"),
    "playerDivingTimeFactor": factor("game.enshrouded.playerdivingtimefactor.label",
                                     "game.enshrouded.playerdivingtimefactor.help"),
    "enableDurability": flag("game.enshrouded.enabledurability.label",
                             "game.enshrouded.enabledurability.help"),
    "enableStarvingDebuff": flag("game.enshrouded.enablestarvingdebuff.label",
                                 "game.enshrouded.enablestarvingdebuff.help"),
    "foodBuffDurationFactor": factor("game.enshrouded.foodbuffdurationfactor.label",
                                     "game.enshrouded.foodbuffdurationfactor.help"),
    "fromHungerToStarving": duration(
        "game.enshrouded.fromhungertostarving.label",
        "game.enshrouded.fromhungertostarving.help", 5, 20),
    "shroudTimeFactor": factor("game.enshrouded.shroudtimefactor.label",
                               "game.enshrouded.shroudtimefactor.help"),
    "tombstoneMode": enum_of(
        "game.enshrouded.tombstonemode.label",
        "game.enshrouded.tombstonemode.help",
        {"AddBackpackMaterials": "game.enshrouded.tombstonemode.opt.addbackpackmaterials",
         "Everything": "game.enshrouded.tombstonemode.opt.everything",
         "NoTombstone": "game.enshrouded.tombstonemode.opt.notombstone"}),
    "enableGliderTurbulences": flag("game.enshrouded.enablegliderturbulences.label",
                                    "game.enshrouded.enablegliderturbulences.help"),

    # --- world
    "dayTimeDuration": duration(
        "game.enshrouded.daytimeduration.label",
        "game.enshrouded.daytimeduration.help", 2, 60),
    "nightTimeDuration": duration(
        "game.enshrouded.nighttimeduration.label",
        "game.enshrouded.nighttimeduration.help", 2, 60),
    "weatherFrequency": enum_of("game.enshrouded.weatherfrequency.label",
                                "game.enshrouded.weatherfrequency.help",
                                {"Disabled": "game.enshrouded.weatherfrequency.opt.disabled",
                                 "Rare": "game.enshrouded.weatherfrequency.opt.rare",
                                 "Normal": "game.enshrouded.weatherfrequency.opt.normal",
                                 "Often": "game.enshrouded.weatherfrequency.opt.often"}),
    "fishingDifficulty": enum_of("game.enshrouded.fishingdifficulty.label",
                                 "game.enshrouded.fishingdifficulty.help",
                                 {"VeryEasy": "game.enshrouded.fishingdifficulty.opt.veryeasy",
                                  "Easy": "game.enshrouded.fishingdifficulty.opt.easy",
                                  "Normal": "game.enshrouded.fishingdifficulty.opt.normal",
                                  "Hard": "game.enshrouded.fishingdifficulty.opt.hard",
                                  "VeryHard": "game.enshrouded.fishingdifficulty.opt.veryhard"}),
    "curseModifier": enum_of("game.enshrouded.cursemodifier.label",
                             "game.enshrouded.cursemodifier.help",
                             {"Easy": "game.enshrouded.cursemodifier.opt.easy",
                              "Normal": "game.enshrouded.cursemodifier.opt.normal",
                              "Hard": "game.enshrouded.cursemodifier.opt.hard"}),
    "randomSpawnerAmount": enum_of("game.enshrouded.randomspawneramount.label",
                                   "game.enshrouded.randomspawneramount.help",
                                   {"Few": "game.enshrouded.randomspawneramount.opt.few",
                                    "Normal": "game.enshrouded.randomspawneramount.opt.normal",
                                    "Many": "game.enshrouded.randomspawneramount.opt.many",
                                    "Extreme": "game.enshrouded.randomspawneramount.opt.extreme"}),
    "aggroPoolAmount": enum_of("game.enshrouded.aggropoolamount.label",
                               "game.enshrouded.aggropoolamount.help",
                               {"Few": "game.enshrouded.aggropoolamount.opt.few",
                                "Normal": "game.enshrouded.aggropoolamount.opt.normal",
                                "Many": "game.enshrouded.aggropoolamount.opt.many",
                                "Extreme": "game.enshrouded.aggropoolamount.opt.extreme"}),

    # --- gathering and production
    "miningDamageFactor": factor("game.enshrouded.miningdamagefactor.label",
                                 "game.enshrouded.miningdamagefactor.help",
                                 0.25, 2.0),
    "plantGrowthSpeedFactor": factor("game.enshrouded.plantgrowthspeedfactor.label",
                                     "game.enshrouded.plantgrowthspeedfactor.help", 0.25, 2.0),
    "resourceDropStackAmountFactor": factor("game.enshrouded.resourcedropstackamountfactor.label",
                                            "game.enshrouded.resourcedropstackamountfactor.help", 0.25, 2.0),
    "factoryProductionSpeedFactor": factor("game.enshrouded.factoryproductionspeedfactor.label",
                                           "game.enshrouded.factoryproductionspeedfactor.help", 0.25, 2.0),
    "perkUpgradeRecyclingFactor": FieldSpec(
        "game.enshrouded.perkupgraderecyclingfactor.label",
        "game.enshrouded.perkupgraderecyclingfactor.help",
        kind="factor", minimum=0, maximum=1.0, step=0.05, unit=UNIT_FACTOR),
    "perkCostFactor": factor("game.enshrouded.perkcostfactor.label",
                             "game.enshrouded.perkcostfactor.help", 0.25, 2.0),

    # --- progression
    "experienceCombatFactor": factor("game.enshrouded.experiencecombatfactor.label",
                                     "game.enshrouded.experiencecombatfactor.help"),
    "experienceMiningFactor": factor("game.enshrouded.experienceminingfactor.label",
                                     "game.enshrouded.experienceminingfactor.help"),
    "experienceExplorationQuestsFactor": factor(
        "game.enshrouded.experienceexplorationquestsfactor.label",
        "game.enshrouded.experienceexplorationquestsfactor.help"),

    # --- enemies
    "enemyDamageFactor": factor("game.enshrouded.enemydamagefactor.label",
                                "game.enshrouded.enemydamagefactor.help", 0.25, 5.0),
    "enemyHealthFactor": factor("game.enshrouded.enemyhealthfactor.label",
                                "game.enshrouded.enemyhealthfactor.help", 0.25, 5.0),
    "enemyStaminaFactor": factor("game.enshrouded.enemystaminafactor.label",
                                 "game.enshrouded.enemystaminafactor.help", 0.25, 5.0),
    "enemyPerceptionRangeFactor": factor("game.enshrouded.enemyperceptionrangefactor.label",
                                         "game.enshrouded.enemyperceptionrangefactor.help", 0.25, 5.0),
    "bossDamageFactor": factor("game.enshrouded.bossdamagefactor.label",
                               "game.enshrouded.bossdamagefactor.help", 0.2, 5.0),
    "bossHealthFactor": factor("game.enshrouded.bosshealthfactor.label",
                               "game.enshrouded.bosshealthfactor.help", 0.2, 5.0),
    "threatBonus": factor("game.enshrouded.threatbonus.label",
                          "game.enshrouded.threatbonus.help", 0.25, 5.0),
    "pacifyAllEnemies": flag("game.enshrouded.pacifyallenemies.label",
                             "game.enshrouded.pacifyallenemies.help"),
    "tamingStartleRepercussion": enum_of(
        "game.enshrouded.tamingstartlerepercussion.label",
        "game.enshrouded.tamingstartlerepercussion.help",
        {"KeepProgress": "game.enshrouded.tamingstartlerepercussion.opt.keepprogress",
         "LoseSomeProgress": "game.enshrouded.tamingstartlerepercussion.opt.losesomeprogress",
         "LoseAllProgress": "game.enshrouded.tamingstartlerepercussion.opt.loseallprogress"}),

    # --- user groups (inside userGroups[])
    "password": FieldSpec("game.enshrouded.password.label",
                          "game.enshrouded.password.help",
                          kind="password"),
    "canKickBan": flag("game.enshrouded.cankickban.label",
                       "game.enshrouded.cankickban.help"),
    "canAccessInventories": flag("game.enshrouded.canaccessinventories.label",
                                 "game.enshrouded.canaccessinventories.help"),
    "canEditBase": flag("game.enshrouded.caneditbase.label",
                        "game.enshrouded.caneditbase.help"),
    "canExtendBase": flag("game.enshrouded.canextendbase.label",
                          "game.enshrouded.canextendbase.help"),
    "canEditWorld": flag("game.enshrouded.caneditworld.label",
                         "game.enshrouded.caneditworld.help"),
    "reservedSlots": FieldSpec("game.enshrouded.reservedslots.label",
                               "game.enshrouded.reservedslots.help",
                               kind="number", minimum=0, maximum=16, step=1),
}
