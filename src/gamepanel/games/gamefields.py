#!/usr/bin/env python3
"""Catalogo de campos de configuracao por jogo.

O `gameconf.py` sabe LER e GRAVAR os arquivos (ini, json, serverDZ.cfg) sem conhecer
jogo nenhum - e isso e proposital: arquivo novo continua editavel sem tocar no codigo.
O que falta ali e SEMANTICA: que um campo e booleano, que outro e uma porcentagem, que
`dayTimeDuration` esta em nanossegundos e tem minimo de 2 minutos.

Este modulo acrescenta essa camada, e so ela:

* nada aqui e obrigatorio - campo sem descricao continua aparecendo como texto livre,
  exatamente como antes;
* o catalogo nunca esconde campo: se o jogo ganhar uma chave nova numa atualizacao,
  ela aparece na tela mesmo sem estar aqui.

Fonte dos limites do Enshrouded: documentacao oficial da Keen Games (Server Gameplay
Settings) e o template do AMP, que traz os valores exatos gravados no arquivo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Um segundo em nanossegundos. O Enshrouded grava duracao nessa unidade, e e a origem
# do erro mais comum no arquivo dele: quem digita "120" achando que sao segundos
# escreve 120 nanossegundos, e o jogo silenciosamente usa o minimo.
NS = 1_000_000_000

# Rotulos que aparecem em varios jogos com nomes tecnicos diferentes (`ServerName`,
# `SessionName`, `hostname`, `name`). O nome do CAMPO muda de jogo para jogo; o que a
# pessoa procura na tela, nao - e e justamente por isso que ele precisa sair igual nos
# quatro. Escritos a mao, um deles viraria "Nome de servidor" numa atualizacao e a
# busca por nome deixaria de achar aquele campo naquele jogo.
LABEL_NAME = "Nome do servidor"
# Rotulo de campo na tela, nao segredo - o analisador confunde por causa do nome da constante.
LABEL_JOIN_PASSWORD = "Senha de entrada"  # noqa: S105  # NOSONAR
LABEL_ADMIN_PASSWORD = "Senha de admin"  # noqa: S105  # NOSONAR


@dataclass
class FieldSpec:
    """Como um campo deve aparecer na tela e o que vale nele."""

    label: str = ""
    help: str = ""
    kind: str = "text"          # text | bool | number | factor | duration | enum | password
    options: dict[str, str] = field(default_factory=dict)   # valor gravado -> rotulo na tela
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""              # sufixo mostrado ao lado do campo
    # Para kind="duration": o arquivo guarda nanossegundos, a tela mostra minutos.
    scale: int = 1

    def to_display(self, raw: str) -> str:
        """Valor do arquivo -> valor mostrado na tela."""
        text = (raw or "").strip()
        if self.kind != "duration" or not text:
            return text
        try:
            minutes = float(text) / self.scale
        except ValueError:
            return text
        return f"{minutes:g}"

    def from_display(self, text: str) -> str:
        """Valor digitado na tela -> valor gravado no arquivo."""
        text = (text or "").strip()
        if self.kind != "duration" or not text:
            return text
        return str(round(float(text) * self.scale))

    def validate(self, text: str) -> str:
        """Devolve mensagem de erro, ou string vazia quando o valor serve.

        A conferencia e feita na unidade da TELA (minutos, multiplicador), que e onde
        a pessoa erra - reportar limite em nanossegundos nao ajudaria ninguem.

        Campo vazio nunca e erro: o jogo tem um padrao para a chave ausente, e apagar
        o valor e uma forma legitima de voltar para ele.
        """
        text = (text or "").strip()
        if not text:
            return ""
        if self.kind == "enum" and self.options:
            return self._validate_enum(text)
        if self.kind in ("number", "factor", "duration"):
            return self._validate_number(text)
        return ""

    def _validate_enum(self, text: str) -> str:
        if text in self.options:
            return ""
        return f"valor invalido; use um de: {', '.join(sorted(self.options))}"

    def _validate_number(self, text: str) -> str:
        try:
            value = float(text)
        except ValueError:
            return "precisa ser um numero"
        if self.minimum is not None and value < self.minimum:
            return f"minimo {self._with_unit(self.minimum)}"
        if self.maximum is not None and value > self.maximum:
            return f"maximo {self._with_unit(self.maximum)}"
        return ""

    def _with_unit(self, value: float) -> str:
        """"2 min", "0.25 x", ou so "16" quando o campo nao tem unidade."""
        return f"{value:g}{self.unit and ' ' + self.unit}"


def _factor(label: str, help_text: str, minimum: float = 0.25, maximum: float = 4.0) -> FieldSpec:
    """Multiplicador: 1 = padrao do jogo, 0,5 = metade, 2 = dobro."""
    return FieldSpec(label=label, help=help_text, kind="factor", minimum=minimum,
                     maximum=maximum, step=0.05, unit="x")


def _duration(label: str, help_text: str, min_minutes: float, max_minutes: float) -> FieldSpec:
    """Duracao gravada em nanossegundos, editada em minutos."""
    return FieldSpec(label=label, help=help_text, kind="duration", scale=60 * NS,
                     minimum=min_minutes, maximum=max_minutes, step=1, unit="min")


def _enum(label: str, help_text: str, options: dict[str, str]) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="enum", options=options)


def _bool(label: str, help_text: str) -> FieldSpec:
    return FieldSpec(label=label, help=help_text, kind="bool")


# ------------------------------------------- Enshrouded (le enshrouded_server.json)
ENSHROUDED = {
    "name": FieldSpec(LABEL_NAME, "Como ele aparece na lista de servidores do jogo."),
    "slotCount": FieldSpec("Vagas", "Quantos jogadores podem estar conectados ao mesmo tempo.",
                           kind="number", minimum=1, maximum=16, step=1),
    "queryPort": FieldSpec("Porta", "Porta que o jogador digita para entrar. Mudar aqui exige "
                                    "mudar tambem o redirecionamento no roteador.",
                           kind="number", minimum=1024, maximum=65535, step=1),
    "ip": FieldSpec("IP de escuta", "0.0.0.0 aceita conexao por qualquer interface. "
                                    "So mude se souber exatamente por que."),
    "enableVoiceChat": _bool("Voz", "Liga o chat de voz no servidor."),
    "enableTextChat": _bool("Texto", "Liga o chat de texto no servidor."),
    "voiceChatMode": _enum("Modo de voz",
                           "Proximity: so ouve quem esta perto. Global: todo mundo se ouve.",
                           {"Proximity": "Proximidade (padrao)", "Global": "Global"}),
    "gameSettingsPreset": _enum(
        "Preset de dificuldade",
        "ATENCAO: escolher um preset diferente de Custom faz o jogo IGNORAR os ajustes "
        "individuais abaixo. Se voce personalizou algo, deixe em Custom.",
        {"Default": "Padrao (primeira vez)", "Relaxed": "Relaxado (construcao)",
         "Hard": "Dificil (combate)", "Survival": "Sobrevivencia (punitivo)",
         "Custom": "Custom (usa os ajustes abaixo)"}),

    # --- jogador
    "playerHealthFactor": _factor("Vida do jogador", "Multiplica a vida maxima. 2 = o dobro de vida."),
    "playerManaFactor": _factor("Mana do jogador", "Multiplica a mana maxima."),
    "playerStaminaFactor": _factor("Stamina do jogador", "Multiplica a stamina maxima."),
    "playerBodyHeatFactor": _factor("Calor corporal",
                                   "Multiplica a resistencia ao frio. Maior = aguenta mais tempo "
                                   "em regiao gelada."),
    "playerDivingTimeFactor": _factor("Folego", "Multiplica o tempo que da para ficar submerso."),
    "enableDurability": _bool("Durabilidade",
                              "Desligado, equipamento nunca quebra e nao precisa de reparo."),
    "enableStarvingDebuff": _bool("Penalidade de fome",
                                  "Ligado, ficar sem comer aplica penalidade (nao so remove os buffs)."),
    "foodBuffDurationFactor": _factor("Duracao do buff de comida",
                                     "Multiplica quanto tempo o efeito da comida dura."),
    "fromHungerToStarving": _duration(
        "Da fome ate passar fome",
        "Tempo entre ficar com fome e comecar a sofrer a penalidade.", 5, 20),
    "shroudTimeFactor": _factor("Tempo dentro da Bruma",
                               "Multiplica quanto tempo da para ficar na Bruma antes de morrer."),
    "tombstoneMode": _enum(
        "Ao morrer",
        "O que fica na lapide. 'Perde tudo' inclui o que estava equipado.",
        {"AddBackpackMaterials": "Perde os materiais da mochila (padrao)",
         "Everything": "Perde tudo",
         "NoTombstone": "Mantem tudo (sem lapide)"}),
    "enableGliderTurbulences": _bool("Turbulencia no planador",
                                     "Desligado, o planador voa estavel, sem correntes de ar."),

    # --- mundo
    "dayTimeDuration": _duration(
        "Duracao do dia",
        "Quanto tempo REAL dura o dia no jogo. O arquivo guarda em nanossegundos; "
        "aqui voce edita em minutos.", 2, 60),
    "nightTimeDuration": _duration(
        "Duracao da noite",
        "Quanto tempo REAL dura a noite. Minimo de 2 minutos - valor menor que isso o "
        "jogo descarta.", 2, 60),
    "weatherFrequency": _enum("Frequencia do clima",
                              "Com que frequencia o tempo muda (chuva, tempestade).",
                              {"Disabled": "Desligado", "Rare": "Raro",
                               "Normal": "Normal", "Often": "Frequente"}),
    "fishingDifficulty": _enum("Dificuldade da pesca",
                               "Quao dificil e o minigame de fisgar o peixe.",
                               {"VeryEasy": "Muito facil", "Easy": "Facil", "Normal": "Normal",
                                "Hard": "Dificil", "VeryHard": "Muito dificil"}),
    "curseModifier": _enum("Maldicao",
                           "Chance de receber maldicao. 'Facil' desliga o sistema.",
                           {"Easy": "Facil (desligado)", "Normal": "Normal",
                            "Hard": "Dificil (chance dobrada)"}),
    "randomSpawnerAmount": _enum("Inimigos pelo mundo",
                                 "Quantos inimigos aparecem fora das bases inimigas.",
                                 {"Few": "Poucos", "Normal": "Normal",
                                  "Many": "Muitos", "Extreme": "Extremo"}),
    "aggroPoolAmount": _enum("Inimigos que atacam juntos",
                             "Quantos inimigos podem perseguir o jogador ao mesmo tempo.",
                             {"Few": "Poucos", "Normal": "Normal",
                              "Many": "Muitos", "Extreme": "Extremo"}),

    # --- coleta e producao
    "miningDamageFactor": _factor("Dano de mineracao",
                                 "Multiplica o quanto a picareta quebra por golpe. Maior = mina mais rapido.",
                                 0.25, 2.0),
    "plantGrowthSpeedFactor": _factor("Velocidade das plantacoes",
                                     "Multiplica a velocidade de crescimento das plantas.", 0.25, 2.0),
    "resourceDropStackAmountFactor": _factor("Recursos por coleta",
                                            "Multiplica a quantidade que cai ao coletar.", 0.25, 2.0),
    "factoryProductionSpeedFactor": _factor("Velocidade de producao",
                                           "Multiplica a velocidade das bancadas e fornalhas.", 0.25, 2.0),
    "perkUpgradeRecyclingFactor": FieldSpec(
        "Retorno ao reciclar perk", "Fracao do material devolvida ao desfazer um upgrade de arma. "
                                    "0,5 = devolve metade; 1 = devolve tudo.",
        kind="factor", minimum=0, maximum=1.0, step=0.05, unit="x"),
    "perkCostFactor": _factor("Custo dos perks", "Multiplica o material necessario para melhorar armas.",
                             0.25, 2.0),

    # --- progressao
    "experienceCombatFactor": _factor("XP de combate", "Multiplica a experiencia ganha lutando."),
    "experienceMiningFactor": _factor("XP de mineracao", "Multiplica a experiencia ganha minerando."),
    "experienceExplorationQuestsFactor": _factor(
        "XP de exploracao e missoes", "Multiplica a experiencia de explorar e completar missoes."),

    # --- inimigos
    "enemyDamageFactor": _factor("Dano dos inimigos", "Multiplica o dano que os inimigos causam.", 0.25, 5.0),
    "enemyHealthFactor": _factor("Vida dos inimigos", "Multiplica a vida dos inimigos.", 0.25, 5.0),
    "enemyStaminaFactor": _factor("Stamina dos inimigos",
                                 "Multiplica a stamina deles (quanto conseguem atacar seguido).", 0.25, 5.0),
    "enemyPerceptionRangeFactor": _factor("Alcance de percepcao",
                                         "Multiplica a distancia em que os inimigos notam voce.", 0.25, 5.0),
    "bossDamageFactor": _factor("Dano dos chefes", "Multiplica o dano dos chefes.", 0.2, 5.0),
    "bossHealthFactor": _factor("Vida dos chefes", "Multiplica a vida dos chefes.", 0.2, 5.0),
    "threatBonus": _factor("Agressividade", "Multiplica a facilidade com que os inimigos se irritam.", 0.25, 5.0),
    "pacifyAllEnemies": _bool("Inimigos pacificos",
                              "Ligado, nenhum inimigo ataca - modo construcao/exploracao."),
    "tamingStartleRepercussion": _enum(
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
    "canKickBan": _bool("Pode expulsar/banir", "Permite remover jogadores do servidor."),
    "canAccessInventories": _bool("Pode abrir inventarios", "Permite mexer em bau de outros jogadores."),
    "canEditBase": _bool("Pode editar base", "Permite construir e destruir dentro da base."),
    "canExtendBase": _bool("Pode ampliar base", "Permite aumentar a area da base."),
    "canEditWorld": _bool("Pode editar o mundo", "Permite alterar terreno fora das bases."),
    "reservedSlots": FieldSpec("Vagas reservadas",
                               "Vagas garantidas para este grupo, mesmo com o servidor cheio.",
                               kind="number", minimum=0, maximum=16, step=1),
}


# ------------------------------------------- Palworld (le PalWorldSettings.ini, tudo
# dentro de OptionSettings=(...))
PALWORLD = {
    "ServerName": FieldSpec(LABEL_NAME, "Como ele aparece na lista da comunidade."),
    "ServerPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "Usada nos comandos administrativos e na API REST.", kind="password"),
    "ServerPlayerMaxNum": FieldSpec("Vagas", "Maximo de jogadores simultaneos (limite de 32).",
                                    kind="number", minimum=1, maximum=32, step=1),
    "PublicPort": FieldSpec("Porta publica", "Precisa bater com a porta redirecionada no roteador.",
                            kind="number", minimum=1024, maximum=65535, step=1),
    "RESTAPIEnabled": _bool("API REST",
                            "Liga a API que o painel usa para mostrar os NOMES dos jogadores."),
    "RESTAPIPort": FieldSpec("Porta da API REST", "Nunca redirecione esta porta no roteador.",
                             kind="number", minimum=1024, maximum=65535, step=1),
    "RCONEnabled": _bool("RCON", "Console remoto. Depreciado pela Pocketpair em favor da API REST."),
    "DeathPenalty": _enum("Penalidade de morte", "O que voce perde ao morrer.",
                          {"None": "Nada", "Item": "Itens (sem equipamento)",
                           "ItemAndEquipment": "Itens e equipamento",
                           "All": "Tudo (inclui Pals)"}),
    "DayTimeSpeedRate": _factor("Velocidade do dia", "Maior = dia passa mais rapido.", 0.1, 5.0),
    "NightTimeSpeedRate": _factor("Velocidade da noite", "Maior = noite passa mais rapido.", 0.1, 5.0),
    "ExpRate": _factor("Ganho de XP", "Multiplica toda a experiencia recebida.", 0.1, 20.0),
    "PalCaptureRate": _factor("Taxa de captura", "Multiplica a chance de capturar Pals.", 0.5, 2.0),
    "PalSpawnNumRate": _factor("Quantidade de Pals", "Multiplica quantos Pals aparecem no mundo.", 0.5, 3.0),
    "PalDamageRateAttack": _factor("Dano dos Pals", "Multiplica o dano causado pelos Pals.", 0.1, 5.0),
    "PalDamageRateDefense": _factor("Defesa dos Pals", "Multiplica a resistencia dos Pals.", 0.1, 5.0),
    "PlayerDamageRateAttack": _factor("Dano do jogador", "Multiplica o dano que voce causa.", 0.1, 5.0),
    "PlayerDamageRateDefense": _factor("Defesa do jogador", "Multiplica sua resistencia.", 0.1, 5.0),
    "CollectionDropRate": _factor("Recursos coletados", "Multiplica o que cai ao coletar.", 0.5, 3.0),
    "EnablePlayerToPlayerDamage": _bool("PvP", "Permite jogadores se atacarem."),
    "bEnableDefenseOtherGuild": _bool("Defesa de outras guildas",
                                      "Permite que sua base seja atacada por outras guildas."),
}


# ----------------------------------------------- Icarus (le ServerSettings.ini)
ICARUS = {
    "SessionName": FieldSpec(LABEL_NAME, "Como ele aparece no navegador de servidores."),
    "JoinPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.", kind="password"),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD, "Da acesso aos comandos de administrador no jogo.",
                               kind="password"),
    "MaxPlayers": FieldSpec("Vagas", "Maximo de jogadores simultaneos.",
                            kind="number", minimum=1, maximum=64, step=1),
    "AllowNonAdminsToLaunchProspects": _bool(
        "Jogador comum pode iniciar prospect",
        "Desligado, so admin escolhe qual missao (prospect) roda no servidor."),
    "AllowNonAdminsToDeleteProspects": _bool(
        "Jogador comum pode apagar prospect", "Cuidado: apagar prospect apaga o progresso dele."),
    "ShutdownIfNotJoinedFor": FieldSpec(
        "Desliga se ninguem entrar", "Segundos sem NENHUMA conexao ate o servidor se encerrar. "
                                     "O systemd reinicia logo depois; aumente para manter de pe.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ShutdownIfEmptyFor": FieldSpec(
        "Desliga ao ficar vazio", "Segundos com o servidor vazio ate ele se encerrar.",
        kind="number", minimum=0, maximum=86400, step=60, unit="s"),
    "ResumeProspect": _bool("Retomar prospect",
                            "Ligado, o servidor volta sozinho para a missao que estava rodando."),
    "LoadProspect": FieldSpec("Prospect a carregar", "Nome do prospect salvo que deve ser aberto."),
    "CreateProspect": FieldSpec("Prospect a criar", "Cria uma missao nova com este nome ao subir."),
    "LastProspectName": FieldSpec("Ultimo prospect",
                                  "Preenchido pelo proprio jogo. Nao edite a mao."),
}


# --------------------------------------------------- DayZ (le serverDZ.cfg)
DAYZ = {
    "hostname": FieldSpec(LABEL_NAME, "Como aparece no navegador de servidores."),
    "password": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = servidor aberto.", kind="password"),
    "passwordAdmin": FieldSpec(LABEL_ADMIN_PASSWORD, "Acesso ao console remoto. TROQUE antes de expor.",
                               kind="password"),
    "maxPlayers": FieldSpec("Vagas", "Maximo de jogadores simultaneos.",
                            kind="number", minimum=1, maximum=127, step=1),
    "steamQueryPort": FieldSpec("Porta de consulta",
                                "Sem ela o servidor nao aparece no navegador do cliente. "
                                "Precisa bater com o que esta liberado no roteador.",
                                kind="number", minimum=1024, maximum=65535, step=1),
    "verifySignatures": FieldSpec("Verificar assinaturas",
                                  "2 = so aceita mods assinados. Deixe em 2.",
                                  kind="number", minimum=0, maximum=2, step=1),
    "forceSameBuild": FieldSpec("Mesma versao", "1 = cliente precisa estar na mesma versao do servidor.",
                                kind="number", minimum=0, maximum=1, step=1),
    "disable3rdPerson": FieldSpec("Somente 1a pessoa", "1 = servidor apenas em primeira pessoa.",
                                  kind="number", minimum=0, maximum=1, step=1),
    "disableVoN": FieldSpec("Desligar voz", "0 = voz habilitada.",
                            kind="number", minimum=0, maximum=1, step=1),
    "serverTimeAcceleration": FieldSpec(
        "Aceleracao do tempo", "12 = um dia do jogo a cada 2 horas reais.",
        kind="number", minimum=0, maximum=64, step=1, unit="x"),
    "instanceId": FieldSpec("ID da instancia", "Define a pasta storage_<id> da persistencia."),
}


# ------------------------------ RuneScape: Dragonwilds (le DedicatedServer.ini)
# O .ini so cuida de identidade e acesso do servidor. As regras do MUNDO (capacidade de
# carga, estabilidade e custo de construcao, PvP, dificuldade...) NAO estao aqui: moram
# no save do mundo (.sav), e mods como o "No Carry Capacity" so as expoem no menu
# "Edit Settings" do jogo. Nao inventar chave dessas neste catalogo: o jogo ignora.
DRAGONWILDS = {
    "OwnerId": FieldSpec("ID do dono",
                         "Seu Player ID, no rodape do menu de Configuracoes do jogo (nao e "
                         "o Steam ID de 17 digitos). Sem ele o servidor NAO sobe."),
    "ServerName": FieldSpec(LABEL_NAME, "Como ele aparece para quem entra."),
    "DefaultWorldName": FieldSpec("Nome do mundo padrao",
                                  "Nome do mundo criado no primeiro start. "
                                  "Trocar depois nao renomeia um mundo que ja existe."),
    "AdminPassword": FieldSpec(LABEL_ADMIN_PASSWORD,
                               "Quem souber esta senha abre a aba Server Management no menu "
                               "do jogo e vira admin. TROQUE antes de expor o servidor.",
                               kind="password"),
    "WorldPassword": FieldSpec(LABEL_JOIN_PASSWORD, "Vazio = qualquer um entra.",
                               kind="password"),
    "ServerGuid": FieldSpec("GUID do servidor", "Gerado pelo proprio jogo. Nao edite a mao."),
    "KnownPlayerList": FieldSpec("Jogadores conhecidos",
                                 "Preenchido pelo proprio jogo (quem ja entrou, privilegios "
                                 "e banimentos). Nao edite a mao."),
}


# Qual catalogo vale para qual arquivo. A comparacao e pelo NOME do arquivo, que e o
# que o painel ja usa para escolher o parser.
CATALOGS = (
    (re.compile(r"^DedicatedServer\.ini$", re.I), DRAGONWILDS),
    (re.compile(r"^enshrouded_server\.json$", re.I), ENSHROUDED),
    (re.compile(r"^PalWorldSettings\.ini$", re.I), PALWORLD),
    (re.compile(r"^ServerSettings\.ini$", re.I), ICARUS),
    (re.compile(r"^serverDZ\.cfg$", re.I), DAYZ),
)


def catalog_for(filename: str) -> dict[str, FieldSpec]:
    """Catalogo do arquivo, ou vazio quando o jogo ainda nao foi mapeado."""
    name = (filename or "").strip().rsplit("/", 1)[-1]
    for pattern, catalog in CATALOGS:
        if pattern.match(name):
            return catalog
    return {}


def describe(filename: str, key: str) -> FieldSpec | None:
    """Descricao de um campo, ou None quando ele nao esta mapeado.

    A busca e so pelo nome da chave: o mesmo campo aparece em secoes diferentes
    (userGroups[0].password e userGroups[1].password, por exemplo) e a descricao vale
    para os dois.
    """
    catalog = catalog_for(filename)
    if not catalog:
        return None
    return catalog.get((key or "").strip())
