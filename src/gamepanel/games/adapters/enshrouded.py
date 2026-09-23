"""Campos de configuracao de Enshrouded (le enshrouded_server.json)."""
from __future__ import annotations

import re

from gamepanel.games.base import LABEL_NAME, FieldSpec, duration, enum_of, factor, flag

# O painel escolhe o catalogo pelo NOME do arquivo, que e o mesmo criterio
# que ele ja usa para escolher o leitor.
FILENAME = re.compile(r"^enshrouded_server\.json$", re.I)

# ------------------------------------------- Enshrouded (le enshrouded_server.json)
FIELDS = {
    "name": FieldSpec(LABEL_NAME, "Como ele aparece na lista de servidores do jogo."),
    "slotCount": FieldSpec("Vagas", "Quantos jogadores podem estar conectados ao mesmo tempo.",
                           kind="number", minimum=1, maximum=16, step=1),
    "queryPort": FieldSpec("Porta", "Porta que o jogador digita para entrar. Mudar aqui exige "
                                    "mudar tambem o redirecionamento no roteador.",
                           kind="number", minimum=1024, maximum=65535, step=1),
    "ip": FieldSpec("IP de escuta", "0.0.0.0 aceita conexao por qualquer interface. "
                                    "So mude se souber exatamente por que."),
    "enableVoiceChat": flag("Voz", "Liga o chat de voz no servidor."),
    "enableTextChat": flag("Texto", "Liga o chat de texto no servidor."),
    "voiceChatMode": enum_of("Modo de voz",
                           "Proximity: so ouve quem esta perto. Global: todo mundo se ouve.",
                           {"Proximity": "Proximidade (padrao)", "Global": "Global"}),
    "gameSettingsPreset": enum_of(
        "Preset de dificuldade",
        "ATENCAO: escolher um preset diferente de Custom faz o jogo IGNORAR os ajustes "
        "individuais abaixo. Se voce personalizou algo, deixe em Custom.",
        {"Default": "Padrao (primeira vez)", "Relaxed": "Relaxado (construcao)",
         "Hard": "Dificil (combate)", "Survival": "Sobrevivencia (punitivo)",
         "Custom": "Custom (usa os ajustes abaixo)"}),

    # --- jogador
    "playerHealthFactor": factor("Vida do jogador", "Multiplica a vida maxima. 2 = o dobro de vida."),
    "playerManaFactor": factor("Mana do jogador", "Multiplica a mana maxima."),
    "playerStaminaFactor": factor("Stamina do jogador", "Multiplica a stamina maxima."),
    "playerBodyHeatFactor": factor("Calor corporal",
                                   "Multiplica a resistencia ao frio. Maior = aguenta mais tempo "
                                   "em regiao gelada."),
    "playerDivingTimeFactor": factor("Folego", "Multiplica o tempo que da para ficar submerso."),
    "enableDurability": flag("Durabilidade",
                              "Desligado, equipamento nunca quebra e nao precisa de reparo."),
    "enableStarvingDebuff": flag("Penalidade de fome",
                                  "Ligado, ficar sem comer aplica penalidade (nao so remove os buffs)."),
    "foodBuffDurationFactor": factor("Duracao do buff de comida",
                                     "Multiplica quanto tempo o efeito da comida dura."),
    "fromHungerToStarving": duration(
        "Da fome ate passar fome",
        "Tempo entre ficar com fome e comecar a sofrer a penalidade.", 5, 20),
    "shroudTimeFactor": factor("Tempo dentro da Bruma",
                               "Multiplica quanto tempo da para ficar na Bruma antes de morrer."),
    "tombstoneMode": enum_of(
        "Ao morrer",
        "O que fica na lapide. 'Perde tudo' inclui o que estava equipado.",
        {"AddBackpackMaterials": "Perde os materiais da mochila (padrao)",
         "Everything": "Perde tudo",
         "NoTombstone": "Mantem tudo (sem lapide)"}),
    "enableGliderTurbulences": flag("Turbulencia no planador",
                                     "Desligado, o planador voa estavel, sem correntes de ar."),

    # --- mundo
    "dayTimeDuration": duration(
        "Duracao do dia",
        "Quanto tempo REAL dura o dia no jogo. O arquivo guarda em nanossegundos; "
        "aqui voce edita em minutos.", 2, 60),
    "nightTimeDuration": duration(
        "Duracao da noite",
        "Quanto tempo REAL dura a noite. Minimo de 2 minutos - valor menor que isso o "
        "jogo descarta.", 2, 60),
    "weatherFrequency": enum_of("Frequencia do clima",
                              "Com que frequencia o tempo muda (chuva, tempestade).",
                              {"Disabled": "Desligado", "Rare": "Raro",
                               "Normal": "Normal", "Often": "Frequente"}),
    "fishingDifficulty": enum_of("Dificuldade da pesca",
                               "Quao dificil e o minigame de fisgar o peixe.",
                               {"VeryEasy": "Muito facil", "Easy": "Facil", "Normal": "Normal",
                                "Hard": "Dificil", "VeryHard": "Muito dificil"}),
    "curseModifier": enum_of("Maldicao",
                           "Chance de receber maldicao. 'Facil' desliga o sistema.",
                           {"Easy": "Facil (desligado)", "Normal": "Normal",
                            "Hard": "Dificil (chance dobrada)"}),
    "randomSpawnerAmount": enum_of("Inimigos pelo mundo",
                                 "Quantos inimigos aparecem fora das bases inimigas.",
                                 {"Few": "Poucos", "Normal": "Normal",
                                  "Many": "Muitos", "Extreme": "Extremo"}),
    "aggroPoolAmount": enum_of("Inimigos que atacam juntos",
                             "Quantos inimigos podem perseguir o jogador ao mesmo tempo.",
                             {"Few": "Poucos", "Normal": "Normal",
                              "Many": "Muitos", "Extreme": "Extremo"}),

    # --- coleta e producao
    "miningDamageFactor": factor("Dano de mineracao",
                                 "Multiplica o quanto a picareta quebra por golpe. Maior = mina mais rapido.",
                                 0.25, 2.0),
    "plantGrowthSpeedFactor": factor("Velocidade das plantacoes",
                                     "Multiplica a velocidade de crescimento das plantas.", 0.25, 2.0),
    "resourceDropStackAmountFactor": factor("Recursos por coleta",
                                            "Multiplica a quantidade que cai ao coletar.", 0.25, 2.0),
    "factoryProductionSpeedFactor": factor("Velocidade de producao",
                                           "Multiplica a velocidade das bancadas e fornalhas.", 0.25, 2.0),
    "perkUpgradeRecyclingFactor": FieldSpec(
        "Retorno ao reciclar perk", "Fracao do material devolvida ao desfazer um upgrade de arma. "
                                    "0,5 = devolve metade; 1 = devolve tudo.",
        kind="factor", minimum=0, maximum=1.0, step=0.05, unit="x"),
    "perkCostFactor": factor("Custo dos perks", "Multiplica o material necessario para melhorar armas.",
                             0.25, 2.0),

    # --- progressao
    "experienceCombatFactor": factor("XP de combate", "Multiplica a experiencia ganha lutando."),
    "experienceMiningFactor": factor("XP de mineracao", "Multiplica a experiencia ganha minerando."),
    "experienceExplorationQuestsFactor": factor(
        "XP de exploracao e missoes", "Multiplica a experiencia de explorar e completar missoes."),

    # --- inimigos
    "enemyDamageFactor": factor("Dano dos inimigos", "Multiplica o dano que os inimigos causam.", 0.25, 5.0),
    "enemyHealthFactor": factor("Vida dos inimigos", "Multiplica a vida dos inimigos.", 0.25, 5.0),
    "enemyStaminaFactor": factor("Stamina dos inimigos",
                                 "Multiplica a stamina deles (quanto conseguem atacar seguido).", 0.25, 5.0),
    "enemyPerceptionRangeFactor": factor("Alcance de percepcao",
                                         "Multiplica a distancia em que os inimigos notam voce.", 0.25, 5.0),
    "bossDamageFactor": factor("Dano dos chefes", "Multiplica o dano dos chefes.", 0.2, 5.0),
    "bossHealthFactor": factor("Vida dos chefes", "Multiplica a vida dos chefes.", 0.2, 5.0),
    "threatBonus": factor("Agressividade", "Multiplica a facilidade com que os inimigos se irritam.", 0.25, 5.0),
    "pacifyAllEnemies": flag("Inimigos pacificos",
                              "Ligado, nenhum inimigo ataca - modo construcao/exploracao."),
    "tamingStartleRepercussion": enum_of(
        "Ao assustar animal domesticavel",
        "Quanto do progresso de domesticacao se perde quando o animal se assusta.",
        {"KeepProgress": "Mantem todo o progresso",
         "LoseSomeProgress": "Perde parte (padrao)",
         "LoseAllProgress": "Perde tudo"}),

    # --- grupos de usuario (dentro de userGroups[])
    "password": FieldSpec("Senha do grupo",
                          "Senha que o jogador digita para entrar NESTE grupo. Cada grupo "
                          "(Admin/Friend/Guest) tem a sua - nao existe senha unica de servidor.",
                          kind="password"),
    "canKickBan": flag("Pode expulsar/banir", "Permite remover jogadores do servidor."),
    "canAccessInventories": flag("Pode abrir inventarios", "Permite mexer em bau de outros jogadores."),
    "canEditBase": flag("Pode editar base", "Permite construir e destruir dentro da base."),
    "canExtendBase": flag("Pode ampliar base", "Permite aumentar a area da base."),
    "canEditWorld": flag("Pode editar o mundo", "Permite alterar terreno fora das bases."),
    "reservedSlots": FieldSpec("Vagas reservadas",
                               "Vagas garantidas para este grupo, mesmo com o servidor cheio.",
                               kind="number", minimum=0, maximum=16, step=1),
}
