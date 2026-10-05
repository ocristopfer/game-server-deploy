"""Configuration fields for Enshrouded (reads enshrouded_server.json)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_NAME, FieldSpec, duration, enum_of, factor, flag

# The panel picks the catalog by the file NAME, which is the same criterion
# it already uses to pick the reader.
FILENAME = re.compile(r"^enshrouded_server\.json$", re.I)

# ------------------------------------------- Enshrouded (reads enshrouded_server.json)
FIELDS = {
    "name": FieldSpec(LABEL_NAME, "Como ele aparece na lista de servidores do jogo."),
    "slotCount": FieldSpec("Vagas", "Quantos jogadores podem estar conectados ao mesmo tempo.",
                           kind="number", minimum=1, maximum=16, step=1),
    "queryPort": FieldSpec("Porta", "Porta que o jogador digita para entrar. Mudar aqui exige "
                                    "mudar também o redirecionamento no roteador.",
                           kind="number", minimum=1024, maximum=65535, step=1),
    "ip": FieldSpec("IP de escuta", "0.0.0.0 aceita conexão por qualquer interface. "
                                    "Só mude se souber exatamente por que."),
    "enableVoiceChat": flag("Voz", "Liga o chat de voz no servidor."),
    "enableTextChat": flag("Texto", "Liga o chat de texto no servidor."),
    "voiceChatMode": enum_of("Modo de voz",
                           "Proximity: só ouve quem está perto. Global: todo mundo se ouve.",
                           {"Proximity": "Proximidade (padrão)", "Global": "Global"}),
    "gameSettingsPreset": enum_of(
        "Preset de dificuldade",
        "ATENÇÃO: escolher um preset diferente de Custom faz o jogo IGNORAR os ajustes "
        "individuais abaixo. Se você personalizou algo, deixe em Custom.",
        {"Default": "Padrão (primeira vez)", "Relaxed": "Relaxado (construção)",
         "Hard": "Difícil (combate)", "Survival": "Sobrevivência (punitivo)",
         "Custom": "Custom (usa os ajustes abaixo)"}),

    # --- player
    "playerHealthFactor": factor("Vida do jogador", "Multiplica a vida máxima. 2 = o dobro de vida."),
    "playerManaFactor": factor("Mana do jogador", "Multiplica a mana máxima."),
    "playerStaminaFactor": factor("Stamina do jogador", "Multiplica a stamina máxima."),
    "playerBodyHeatFactor": factor("Calor corporal",
                                   "Multiplica a resistência ao frio. Maior = aguenta mais tempo "
                                   "em região gelada."),
    "playerDivingTimeFactor": factor("Fôlego", "Multiplica o tempo que dá para ficar submerso."),
    "enableDurability": flag("Durabilidade",
                              "Desligado, equipamento nunca quebra e não precisa de reparo."),
    "enableStarvingDebuff": flag("Penalidade de fome",
                                  "Ligado, ficar sem comer aplica penalidade (não só remove os buffs)."),
    "foodBuffDurationFactor": factor("Duração do buff de comida",
                                     "Multiplica quanto tempo o efeito da comida dura."),
    "fromHungerToStarving": duration(
        "Da fome até passar fome",
        "Tempo entre ficar com fome e começar a sofrer a penalidade.", 5, 20),
    "shroudTimeFactor": factor("Tempo dentro da Bruma",
                               "Multiplica quanto tempo dá para ficar na Bruma antes de morrer."),
    "tombstoneMode": enum_of(
        "Ao morrer",
        "O que fica na lápide. 'Perde tudo' inclui o que estava equipado.",
        {"AddBackpackMaterials": "Perde os materiais da mochila (padrão)",
         "Everything": "Perde tudo",
         "NoTombstone": "Mantém tudo (sem lápide)"}),
    "enableGliderTurbulences": flag("Turbulência no planador",
                                     "Desligado, o planador voa estável, sem correntes de ar."),

    # --- world
    "dayTimeDuration": duration(
        "Duração do dia",
        "Quanto tempo REAL dura o dia no jogo. O arquivo guarda em nanossegundos; "
        "aqui você edita em minutos.", 2, 60),
    "nightTimeDuration": duration(
        "Duração da noite",
        "Quanto tempo REAL dura a noite. Mínimo de 2 minutos - valor menor que isso o "
        "jogo descarta.", 2, 60),
    "weatherFrequency": enum_of("Frequência do clima",
                              "Com que frequência o tempo muda (chuva, tempestade).",
                              {"Disabled": "Desligado", "Rare": "Raro",
                               "Normal": "Normal", "Often": "Frequente"}),
    "fishingDifficulty": enum_of("Dificuldade da pesca",
                               "Quão difícil é o minigame de fisgar o peixe.",
                               {"VeryEasy": "Muito fácil", "Easy": "Fácil", "Normal": "Normal",
                                "Hard": "Difícil", "VeryHard": "Muito difícil"}),
    "curseModifier": enum_of("Maldição",
                           "Chance de receber maldição. 'Fácil' desliga o sistema.",
                           {"Easy": "Fácil (desligado)", "Normal": "Normal",
                            "Hard": "Difícil (chance dobrada)"}),
    "randomSpawnerAmount": enum_of("Inimigos pelo mundo",
                                 "Quantos inimigos aparecem fora das bases inimigas.",
                                 {"Few": "Poucos", "Normal": "Normal",
                                  "Many": "Muitos", "Extreme": "Extremo"}),
    "aggroPoolAmount": enum_of("Inimigos que atacam juntos",
                             "Quantos inimigos podem perseguir o jogador ao mesmo tempo.",
                             {"Few": "Poucos", "Normal": "Normal",
                              "Many": "Muitos", "Extreme": "Extremo"}),

    # --- gathering and production
    "miningDamageFactor": factor("Dano de mineração",
                                 "Multiplica o quanto a picareta quebra por golpe. Maior = mina mais rápido.",
                                 0.25, 2.0),
    "plantGrowthSpeedFactor": factor("Velocidade das plantações",
                                     "Multiplica a velocidade de crescimento das plantas.", 0.25, 2.0),
    "resourceDropStackAmountFactor": factor("Recursos por coleta",
                                            "Multiplica a quantidade que cai ao coletar.", 0.25, 2.0),
    "factoryProductionSpeedFactor": factor("Velocidade de produção",
                                           "Multiplica a velocidade das bancadas e fornalhas.", 0.25, 2.0),
    "perkUpgradeRecyclingFactor": FieldSpec(
        "Retorno ao reciclar perk", "Fração do material devolvida ao desfazer um upgrade de arma. "
                                    "0,5 = devolve metade; 1 = devolve tudo.",
        kind="factor", minimum=0, maximum=1.0, step=0.05, unit="x"),
    "perkCostFactor": factor("Custo dos perks", "Multiplica o material necessário para melhorar armas.",
                             0.25, 2.0),

    # --- progression
    "experienceCombatFactor": factor("XP de combate", "Multiplica a experiência ganha lutando."),
    "experienceMiningFactor": factor("XP de mineração", "Multiplica a experiência ganha minerando."),
    "experienceExplorationQuestsFactor": factor(
        "XP de exploração e missões", "Multiplica a experiência de explorar e completar missões."),

    # --- enemies
    "enemyDamageFactor": factor("Dano dos inimigos", "Multiplica o dano que os inimigos causam.", 0.25, 5.0),
    "enemyHealthFactor": factor("Vida dos inimigos", "Multiplica a vida dos inimigos.", 0.25, 5.0),
    "enemyStaminaFactor": factor("Stamina dos inimigos",
                                 "Multiplica a stamina deles (quanto conseguem atacar seguido).", 0.25, 5.0),
    "enemyPerceptionRangeFactor": factor("Alcance de percepção",
                                         "Multiplica a distância em que os inimigos notam você.", 0.25, 5.0),
    "bossDamageFactor": factor("Dano dos chefes", "Multiplica o dano dos chefes.", 0.2, 5.0),
    "bossHealthFactor": factor("Vida dos chefes", "Multiplica a vida dos chefes.", 0.2, 5.0),
    "threatBonus": factor("Agressividade", "Multiplica a facilidade com que os inimigos se irritam.", 0.25, 5.0),
    "pacifyAllEnemies": flag("Inimigos pacíficos",
                              "Ligado, nenhum inimigo ataca - modo construcao/exploracao."),
    "tamingStartleRepercussion": enum_of(
        "Ao assustar animal domesticável",
        "Quanto do progresso de domesticação se perde quando o animal se assusta.",
        {"KeepProgress": "Mantém todo o progresso",
         "LoseSomeProgress": "Perde parte (padrão)",
         "LoseAllProgress": "Perde tudo"}),

    # --- user groups (inside userGroups[])
    "password": FieldSpec("Senha do grupo",
                          "Senha que o jogador digita para entrar NESTE grupo. Cada grupo "
                          "(Admin/Friend/Guest) tem a sua - não existe senha única de servidor.",
                          kind="password"),
    "canKickBan": flag("Pode expulsar/banir", "Permite remover jogadores do servidor."),
    "canAccessInventories": flag("Pode abrir inventários", "Permite mexer em baú de outros jogadores."),
    "canEditBase": flag("Pode editar base", "Permite construir e destruir dentro da base."),
    "canExtendBase": flag("Pode ampliar base", "Permite aumentar a área da base."),
    "canEditWorld": flag("Pode editar o mundo", "Permite alterar terreno fora das bases."),
    "reservedSlots": FieldSpec("Vagas reservadas",
                               "Vagas garantidas para este grupo, mesmo com o servidor cheio.",
                               kind="number", minimum=0, maximum=16, step=1),
}
