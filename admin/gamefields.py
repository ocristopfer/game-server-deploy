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
ROTULO_NOME = "Nome do servidor"
ROTULO_SENHA_ENTRADA = "Senha de entrada"
ROTULO_SENHA_ADMIN = "Senha de admin"


@dataclass
class FieldSpec:
    """Como um campo deve aparecer na tela e o que vale nele."""

    label: str = ""
    help: str = ""
    kind: str = "text"          # text | bool | number | factor | duration | enum | password
    options: dict = field(default_factory=dict)   # valor gravado -> rotulo na tela
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""              # sufixo mostrado ao lado do campo
    # Para kind="duration": o arquivo guarda nanossegundos, a tela mostra minutos.
    escala: int = 1

    def to_display(self, bruto: str) -> str:
        """Valor do arquivo -> valor mostrado na tela."""
        texto = (bruto or "").strip()
        if self.kind != "duration" or not texto:
            return texto
        try:
            minutos = float(texto) / self.escala
        except ValueError:
            return texto
        return f"{minutos:g}"

    def from_display(self, texto: str) -> str:
        """Valor digitado na tela -> valor gravado no arquivo."""
        texto = (texto or "").strip()
        if self.kind != "duration" or not texto:
            return texto
        return str(int(round(float(texto) * self.escala)))

    def validate(self, texto: str) -> str:
        """Devolve mensagem de erro, ou string vazia quando o valor serve.

        A conferencia e feita na unidade da TELA (minutos, multiplicador), que e onde
        a pessoa erra - reportar limite em nanossegundos nao ajudaria ninguem.

        Campo vazio nunca e erro: o jogo tem um padrao para a chave ausente, e apagar
        o valor e uma forma legitima de voltar para ele.
        """
        texto = (texto or "").strip()
        if not texto:
            return ""
        if self.kind == "enum" and self.options:
            return self._valida_enum(texto)
        if self.kind in ("number", "factor", "duration"):
            return self._valida_numero(texto)
        return ""

    def _valida_enum(self, texto: str) -> str:
        if texto in self.options:
            return ""
        return f"valor invalido; use um de: {', '.join(sorted(self.options))}"

    def _valida_numero(self, texto: str) -> str:
        try:
            valor = float(texto)
        except ValueError:
            return "precisa ser um numero"
        if self.minimum is not None and valor < self.minimum:
            return f"minimo {self._com_unidade(self.minimum)}"
        if self.maximum is not None and valor > self.maximum:
            return f"maximo {self._com_unidade(self.maximum)}"
        return ""

    def _com_unidade(self, valor: float) -> str:
        """"2 min", "0.25 x", ou so "16" quando o campo nao tem unidade."""
        return f"{valor:g}{self.unit and ' ' + self.unit}"


def _fator(label: str, ajuda: str, minimo=0.25, maximo=4.0) -> FieldSpec:
    """Multiplicador: 1 = padrao do jogo, 0,5 = metade, 2 = dobro."""
    return FieldSpec(label=label, help=ajuda, kind="factor", minimum=minimo,
                     maximum=maximo, step=0.05, unit="x")


def _duracao(label: str, ajuda: str, min_min: float, max_min: float) -> FieldSpec:
    """Duracao gravada em nanossegundos, editada em minutos."""
    return FieldSpec(label=label, help=ajuda, kind="duration", escala=60 * NS,
                     minimum=min_min, maximum=max_min, step=1, unit="min")


def _enum(label: str, ajuda: str, opcoes: dict) -> FieldSpec:
    return FieldSpec(label=label, help=ajuda, kind="enum", options=opcoes)


def _bool(label: str, ajuda: str) -> FieldSpec:
    return FieldSpec(label=label, help=ajuda, kind="bool")


# ------------------------------------------- Enshrouded (le enshrouded_server.json)
ENSHROUDED = {
    "name": FieldSpec(ROTULO_NOME, "Como ele aparece na lista de servidores do jogo."),
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
    "playerHealthFactor": _fator("Vida do jogador", "Multiplica a vida maxima. 2 = o dobro de vida."),
    "playerManaFactor": _fator("Mana do jogador", "Multiplica a mana maxima."),
    "playerStaminaFactor": _fator("Stamina do jogador", "Multiplica a stamina maxima."),
    "playerBodyHeatFactor": _fator("Calor corporal",
                                   "Multiplica a resistencia ao frio. Maior = aguenta mais tempo "
                                   "em regiao gelada."),
    "playerDivingTimeFactor": _fator("Folego", "Multiplica o tempo que da para ficar submerso."),
    "enableDurability": _bool("Durabilidade",
                              "Desligado, equipamento nunca quebra e nao precisa de reparo."),
    "enableStarvingDebuff": _bool("Penalidade de fome",
                                  "Ligado, ficar sem comer aplica penalidade (nao so remove os buffs)."),
    "foodBuffDurationFactor": _fator("Duracao do buff de comida",
                                     "Multiplica quanto tempo o efeito da comida dura."),
    "fromHungerToStarving": _duracao(
        "Da fome ate passar fome",
        "Tempo entre ficar com fome e comecar a sofrer a penalidade.", 5, 20),
    "shroudTimeFactor": _fator("Tempo dentro da Bruma",
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
    "dayTimeDuration": _duracao(
        "Duracao do dia",
        "Quanto tempo REAL dura o dia no jogo. O arquivo guarda em nanossegundos; "
        "aqui voce edita em minutos.", 2, 60),
    "nightTimeDuration": _duracao(
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
    "miningDamageFactor": _fator("Dano de mineracao",
                                 "Multiplica o quanto a picareta quebra por golpe. Maior = mina mais rapido.",
                                 0.25, 2.0),
    "plantGrowthSpeedFactor": _fator("Velocidade das plantacoes",
                                     "Multiplica a velocidade de crescimento das plantas.", 0.25, 2.0),
    "resourceDropStackAmountFactor": _fator("Recursos por coleta",
                                            "Multiplica a quantidade que cai ao coletar.", 0.25, 2.0),
    "factoryProductionSpeedFactor": _fator("Velocidade de producao",
                                           "Multiplica a velocidade das bancadas e fornalhas.", 0.25, 2.0),
    "perkUpgradeRecyclingFactor": FieldSpec(
        "Retorno ao reciclar perk", "Fracao do material devolvida ao desfazer um upgrade de arma. "
                                    "0,5 = devolve metade; 1 = devolve tudo.",
        kind="factor", minimum=0, maximum=1.0, step=0.05, unit="x"),
    "perkCostFactor": _fator("Custo dos perks", "Multiplica o material necessario para melhorar armas.",
                             0.25, 2.0),

    # --- progressao
    "experienceCombatFactor": _fator("XP de combate", "Multiplica a experiencia ganha lutando."),
    "experienceMiningFactor": _fator("XP de mineracao", "Multiplica a experiencia ganha minerando."),
    "experienceExplorationQuestsFactor": _fator(
        "XP de exploracao e missoes", "Multiplica a experiencia de explorar e completar missoes."),

    # --- inimigos
    "enemyDamageFactor": _fator("Dano dos inimigos", "Multiplica o dano que os inimigos causam.", 0.25, 5.0),
    "enemyHealthFactor": _fator("Vida dos inimigos", "Multiplica a vida dos inimigos.", 0.25, 5.0),
    "enemyStaminaFactor": _fator("Stamina dos inimigos",
                                 "Multiplica a stamina deles (quanto conseguem atacar seguido).", 0.25, 5.0),
    "enemyPerceptionRangeFactor": _fator("Alcance de percepcao",
                                         "Multiplica a distancia em que os inimigos notam voce.", 0.25, 5.0),
    "bossDamageFactor": _fator("Dano dos chefes", "Multiplica o dano dos chefes.", 0.2, 5.0),
    "bossHealthFactor": _fator("Vida dos chefes", "Multiplica a vida dos chefes.", 0.2, 5.0),
    "threatBonus": _fator("Agressividade", "Multiplica a facilidade com que os inimigos se irritam.", 0.25, 5.0),
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
    "ServerName": FieldSpec(ROTULO_NOME, "Como ele aparece na lista da comunidade."),
    "ServerPassword": FieldSpec(ROTULO_SENHA_ENTRADA, "Vazio = servidor aberto.", kind="password"),
    "AdminPassword": FieldSpec(ROTULO_SENHA_ADMIN,
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
    "DayTimeSpeedRate": _fator("Velocidade do dia", "Maior = dia passa mais rapido.", 0.1, 5.0),
    "NightTimeSpeedRate": _fator("Velocidade da noite", "Maior = noite passa mais rapido.", 0.1, 5.0),
    "ExpRate": _fator("Ganho de XP", "Multiplica toda a experiencia recebida.", 0.1, 20.0),
    "PalCaptureRate": _fator("Taxa de captura", "Multiplica a chance de capturar Pals.", 0.5, 2.0),
    "PalSpawnNumRate": _fator("Quantidade de Pals", "Multiplica quantos Pals aparecem no mundo.", 0.5, 3.0),
    "PalDamageRateAttack": _fator("Dano dos Pals", "Multiplica o dano causado pelos Pals.", 0.1, 5.0),
    "PalDamageRateDefense": _fator("Defesa dos Pals", "Multiplica a resistencia dos Pals.", 0.1, 5.0),
    "PlayerDamageRateAttack": _fator("Dano do jogador", "Multiplica o dano que voce causa.", 0.1, 5.0),
    "PlayerDamageRateDefense": _fator("Defesa do jogador", "Multiplica sua resistencia.", 0.1, 5.0),
    "CollectionDropRate": _fator("Recursos coletados", "Multiplica o que cai ao coletar.", 0.5, 3.0),
    "EnablePlayerToPlayerDamage": _bool("PvP", "Permite jogadores se atacarem."),
    "bEnableDefenseOtherGuild": _bool("Defesa de outras guildas",
                                      "Permite que sua base seja atacada por outras guildas."),
}


# ----------------------------------------------- Icarus (le ServerSettings.ini)
ICARUS = {
    "SessionName": FieldSpec(ROTULO_NOME, "Como ele aparece no navegador de servidores."),
    "JoinPassword": FieldSpec(ROTULO_SENHA_ENTRADA, "Vazio = qualquer um entra.", kind="password"),
    "AdminPassword": FieldSpec(ROTULO_SENHA_ADMIN, "Da acesso aos comandos de administrador no jogo.",
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
    "hostname": FieldSpec(ROTULO_NOME, "Como aparece no navegador de servidores."),
    "password": FieldSpec(ROTULO_SENHA_ENTRADA, "Vazio = servidor aberto.", kind="password"),
    "passwordAdmin": FieldSpec(ROTULO_SENHA_ADMIN, "Acesso ao console remoto. TROQUE antes de expor.",
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
                         "Seu Player ID, no rodape do menu de Configuracoes do jogo. "
                         "Sem ele o servidor NAO sobe."),
    "ServerName": FieldSpec(ROTULO_NOME, "Como ele aparece para quem entra."),
    "DefaultWorldName": FieldSpec("Nome do mundo padrao",
                                  "Nome do mundo criado no primeiro start. "
                                  "Trocar depois nao renomeia um mundo que ja existe."),
    "AdminPassword": FieldSpec(ROTULO_SENHA_ADMIN,
                               "Quem souber esta senha abre a aba Server Management no menu "
                               "do jogo e vira admin. TROQUE antes de expor o servidor.",
                               kind="password"),
    "WorldPassword": FieldSpec(ROTULO_SENHA_ENTRADA, "Vazio = qualquer um entra.",
                               kind="password"),
    "ServerGuid": FieldSpec("GUID do servidor", "Gerado pelo proprio jogo. Nao edite a mao."),
}


# Qual catalogo vale para qual arquivo. A comparacao e pelo NOME do arquivo, que e o
# que o painel ja usa para escolher o parser.
CATALOGOS = (
    (re.compile(r"^DedicatedServer\.ini$", re.I), DRAGONWILDS),
    (re.compile(r"^enshrouded_server\.json$", re.I), ENSHROUDED),
    (re.compile(r"^PalWorldSettings\.ini$", re.I), PALWORLD),
    (re.compile(r"^ServerSettings\.ini$", re.I), ICARUS),
    (re.compile(r"^serverDZ\.cfg$", re.I), DAYZ),
)


def catalogo_de(nome_arquivo: str) -> dict:
    """Catalogo do arquivo, ou vazio quando o jogo ainda nao foi mapeado."""
    nome = (nome_arquivo or "").strip().rsplit("/", 1)[-1]
    for padrao, catalogo in CATALOGOS:
        if padrao.match(nome):
            return catalogo
    return {}


def describe(nome_arquivo: str, chave: str) -> FieldSpec | None:
    """Descricao de um campo, ou None quando ele nao esta mapeado.

    A busca e so pelo nome da chave: o mesmo campo aparece em secoes diferentes
    (userGroups[0].password e userGroups[1].password, por exemplo) e a descricao vale
    para os dois.
    """
    catalogo = catalogo_de(nome_arquivo)
    if not catalogo:
        return None
    return catalogo.get((chave or "").strip())
