#!/usr/bin/env python3
"""Mapa da interface: o que existe para clicar no painel, e onde.

Este modulo e de proposito *puro* — nao importa Flask, nao abre banco, nao fala SSH.
Ele so descreve a navegacao e as acoes. Quem liga isso ao pedido em curso (papel de
quem esta logado, recursos ligados no deploy) e o `app.py`, passando os valores como
argumento.

Por que existir:

- Antes, a lista de telas de um servidor estava escrita a mao em SEIS templates
  diferentes, cada um com um subconjunto arbitrario e uma ordem propria. Acrescentar
  uma tela significava lembrar de editar os seis; ninguem lembrava, e por isso um
  lugar oferecia "Console" e outro nao, um oferecia "Gráficos" e outro nao.
- Agora a lista esta aqui. O template pergunta quais secoes existem e desenha o que
  vier. Tela nova = uma linha nesta tupla; nenhum template muda.

O mesmo vale para as acoes (iniciar, parar, atualizar): o rotulo, o icone, o grupo e
o peso visual de cada uma sao dados, nao marcacao espalhada.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- recursos
# Um "recurso" e um interruptor do deploy (GAMEPANEL_ALLOW_FILES, ALLOW_SHELL).
# A secao que depende de um recurso desligado nao aparece em lugar nenhum.
FEATURE_FILES = "files"
FEATURE_SHELL = "shell"
FEATURE_BROKER = "broker"


@dataclass(frozen=True)
class Item:
    """Um destino de navegacao.

    `endpoint` e o nome da rota Flask; quem resolve a URL e o template, porque so ele
    sabe de qual servidor esta falando.
    """

    key: str
    label: str
    icon: str
    endpoint: str
    admin: bool = False
    feature: str = ""
    # Descricao curta para o menu suspenso — onde o rotulo sozinho nao basta para
    # separar duas telas parecidas (e o caso de Configuracao x Arquivos).
    help: str = ""
    # Rotulo da barra larga, onde seis destinos dividem uma linha so.
    short: str = ""


# ------------------------------------------------------- navegacao principal
# Sao os destinos da barra de baixo no celular. Quatro e o teto pratico de uma barra
# de abas; por isso "Adicionar servidor", "Usuarios" e "Acesso SSH" ficam no menu da
# barra de cima — sao coisas que se faz uma vez, nao todo dia.
NAV_MAIN = (
    Item("servidores", "nav.servers", "🎮", "dashboard"),
    Item("historico", "nav.history", "🕘", "history"),
    Item("alertas", "nav.alerts", "🔔", "alerts", admin=True),
    Item("conta", "nav.account", "👤", "account"),
)

# Menu do canto da barra de cima: o resto.
NAV_SECONDARY = (
    Item("novo", "nav.add_server", "➕", "server_new", admin=True),
    # Os dois do broker so existem no deploy que ligou GAMEPANEL_ALLOW_BROKER.
    Item("instancias", "nav.instances.help", "🧩", "instances_list", admin=True,
         feature=FEATURE_BROKER, short="nav.instances"),
    Item("catalogo", "nav.catalog.help", "📚", "catalog", admin=True,
         feature=FEATURE_BROKER, short="nav.catalog"),
    Item("usuarios", "nav.users", "👥", "users_list", admin=True),
    Item("ssh", "nav.ssh_key", "🔑", "ssh_key"),
)


# Qual aba da barra principal fica acesa em cada rota. Uma tela de servidor (log,
# backups, terminal) continua sendo "Servidores": quem esta la chegou pelo painel e
# espera ver a barra dizendo isso.
_ACTIVE_EXTRA = {
    "servidores": (
        "dashboard", "server_detail", "server_new", "server_edit", "server_action",
        "config_quick", "config_files_edit", "config_save", "files", "files_search",
        "files_save", "files_delete", "files_upload", "files_download",
        "terminal", "console", "charts", "backups", "backup_create", "backup_restore",
        "backup_delete", "backup_download", "schedules", "schedule_new",
        "schedule_toggle", "schedule_delete", "schedule_run",
        "players_setup", "players_use", "player_action", "job_detail",
        "instances_list", "instance_new", "instance_deactivate", "instance_remove",
        "catalog", "catalog_new",
    ),
    "alertas": ("alerts", "alerts_save", "alerts_hook_new", "alerts_hook_save",
                "alerts_hook_del", "alerts_hook_test"),
    "conta": ("account", "account_2fa", "account_2fa_off", "account_2fa_codes", "ssh_key",
              "users_list", "user_new", "user_role", "user_password", "user_delete",
              "user_2fa_off"),
    "historico": ("history",),
}

_BY_ENDPOINT = {
    endpoint: key
    for key, endpoints in _ACTIVE_EXTRA.items()
    for endpoint in endpoints
}


def active_nav_for(endpoint: str | None) -> str:
    """Qual item da navegacao principal esta ativo, dada a rota em curso.

    Calculado aqui, uma vez, em vez de cada template declarar o seu: o jeito antigo
    de fazer isso e uma variavel que vinte telas precisam lembrar de passar, e tres
    delas esquecem.
    """
    return _BY_ENDPOINT.get(endpoint or "", "")


# ------------------------------------------------------- navegacao no desktop
# A partir de 900px cabe tudo numa barra so, entao nada precisa se esconder atras do
# "⋯": os destinos de uso diario ficam na barra e os da pessoa (conta, chave SSH)
# no menu do nome dela. Sao CHAVES dos itens acima, nao copias deles: o rotulo, o
# icone, a regra de admin e o recurso continuam definidos num lugar so.
NAV_DESKTOP_BAR = ("servidores", "instancias", "catalogo", "historico", "alertas", "usuarios")
NAV_DESKTOP_ACCOUNT = ("conta", "ssh")

_ALL_ITEMS = {i.key: i for i in NAV_MAIN + NAV_SECONDARY}

# No celular "Instancias" e "Usuarios" acendem a aba de cima delas ("Servidores",
# "Conta"), porque so ha quatro abas. Na barra larga cada destino e o seu proprio
# item, entao a rota acende ele mesmo — senao "Instancias" apareceria como "Servidores".
_ACTIVE_ON_DESKTOP = {
    "instancias": ("instances_list", "instance_new", "instance_deactivate", "instance_remove"),
    "catalogo": ("catalog", "catalog_new"),
    "usuarios": ("users_list", "user_new", "user_role", "user_password", "user_delete",
                 "user_2fa_off"),
    "ssh": ("ssh_key",),
    "conta": ("account", "account_2fa", "account_2fa_off", "account_2fa_codes"),
}
_BY_ENDPOINT_ON_DESKTOP = {
    endpoint: key
    for key, endpoints in _ACTIVE_ON_DESKTOP.items()
    for endpoint in endpoints
}


def nav_desktop(*, admin: bool, broker: bool) -> tuple[tuple[Item, ...], tuple[Item, ...]]:
    """(itens da barra, itens do menu da conta) que esta pessoa pode abrir no desktop."""
    def resolve(chaves: tuple[str, ...]) -> tuple[Item, ...]:
        return visible_items(tuple(_ALL_ITEMS[c] for c in chaves), admin=admin, broker=broker)

    return resolve(NAV_DESKTOP_BAR), resolve(NAV_DESKTOP_ACCOUNT)


def active_desktop_nav_for(endpoint: str | None) -> str:
    """Item aceso na barra larga: o proprio destino quando ele existe, senao o do celular."""
    return _BY_ENDPOINT_ON_DESKTOP.get(endpoint or "") or active_nav_for(endpoint)


# ------------------------------------------------------- telas de um servidor
# A ordem aqui e a ordem na tela, e ela segue a frequencia de uso real: o que se
# olha todo dia primeiro, o que se mexe uma vez por mes no fim.
SERVER_SECTIONS = (
    Item("visao", "server.overview", "📊", "server_detail",
         help="server.overview.help"),
    Item("config", "server.config", "⚙️", "config_quick", feature=FEATURE_FILES,
         help="server.config.help"),
    Item("charts", "server.charts", "📈", "charts",
         help="server.charts.help"),
    Item("backups", "server.backups", "💾", "backups",
         help="server.backups.help"),
    Item("schedules", "server.schedules", "⏰", "schedules",
         help="server.schedules.help"),
    # "Arquivos" e o irmao bruto de "Configuracao": mesma pasta, sem formulario.
    # Os dois so aparecem juntos para quem pode navegar pelo container.
    Item("files", "server.files", "📁", "files", admin=True, feature=FEATURE_FILES,
         help="server.files.help"),
    # UM destino de linha de comando, nao dois. Qual das duas telas ele abre e
    # detalhe de implementacao (ver `endpoint_do_terminal`): para quem usa, "Terminal"
    # e um lugar so, e la dentro se escolhe entre sessao interativa e comando unico.
    Item("terminal", "server.terminal", "⌨️", "terminal", admin=True, feature=FEATURE_SHELL,
         help="server.terminal.help"),
    Item("editar", "server.edit", "✏️", "server_edit", admin=True,
         help="server.edit.help"),
)


def visible_items(items: tuple[Item, ...], *, admin: bool, broker: bool) -> tuple[Item, ...]:
    """Itens de navegacao que esta pessoa, neste deploy, pode abrir.

    Um item com `recurso` desligado some do menu: nada de link que leva a 403.
    """
    permitidos = {FEATURE_BROKER: broker, "": True}
    return tuple(
        i for i in items
        if (not i.admin or admin) and permitidos.get(i.feature, True)
    )


def visible_sections(*, admin: bool, arquivos: bool, shell: bool) -> tuple[Item, ...]:
    """As secoes que esta pessoa, neste deploy, pode de fato abrir.

    Quem barra de verdade e o decorador da rota; isto existe para nao desenhar botao
    que leva a 403 — um menu que mente e pior que um menu curto.
    """
    permitidos = {FEATURE_FILES: arquivos, FEATURE_SHELL: shell, "": True}
    return tuple(
        s for s in SERVER_SECTIONS
        if (not s.admin or admin) and permitidos[s.feature]
    )


def terminal_endpoint(*, tem_pty: bool) -> str:
    """Para onde o destino "Terminal" aponta.

    Com PTY (todo Linux) e a sessao interativa. Sem PTY o painel ainda roda — em
    Windows, por exemplo — e ai o mesmo destino abre a caixa de comando unico, que
    nao precisa de terminal de verdade. Em nenhum dos dois casos aparecem duas
    entradas de menu para "rodar comando".
    """
    return "terminal" if tem_pty else "console"


def section_endpoint(section: Item, *, tem_pty: bool) -> str:
    if section.key == "terminal":
        return terminal_endpoint(tem_pty=tem_pty)
    return section.endpoint


# --------------------------------------------------------------- acoes
GROUP_POWER = "energia"
GROUP_MAINTENANCE = "manutencao"


@dataclass(frozen=True)
class Action:
    """Uma acao sobre o servico do jogo.

    O comando remoto NAO mora aqui: ele depende de `shlex` e do formato do servico, e
    e responsabilidade do `app.py`. Este modulo responde por como a acao se apresenta.
    """

    key: str
    label: str      # nome completo, usado no historico e na confirmacao
    short: str       # o que cabe num botao de celular
    icon: str
    group: str
    variant: str = ""     # "primary", "danger" ou vazio
    confirm: bool = False


ACTIONS = (
    Action("start", "action.start.confirm", "action.start", "▶", GROUP_POWER, "primary"),
    Action("restart", "action.restart.confirm", "action.restart", "🔄", GROUP_POWER, confirm=True),
    Action("stop", "action.stop.confirm", "action.stop", "⏹", GROUP_POWER, "danger", confirm=True),
    Action("update", "action.update.confirm", "action.update", "⬇", GROUP_MAINTENANCE,
         confirm=True),
    Action("check-update", "action.check_update", "action.check_update", "🔍", GROUP_MAINTENANCE),
)

BY_KEY = {a.key: a for a in ACTIONS}


def actions_in_group(group: str) -> list[Action]:
    return [a for a in ACTIONS if a.group == group]


# Estas funcoes devolvem LISTA, e nao tupla, de proposito: o tamanho varia com o
# estado do servidor. Tupla de comprimento variavel e uma promessa que o tipo nao
# cumpre - quem le `tuple[Acao, ...]` espera uma forma fixa, e a analise estatica
# reclama com razao.
def card_power(service: str) -> list[Action]:
    """Os botoes de energia que fazem sentido no cartao do painel, dado o estado.

    O cartao mostra DOIS controles, nao quatro. Um servidor de pe nao precisa de um
    botao "Iniciar", e um parado nao precisa de "Parar" — oferecer os quatro sempre e
    o que transformava cinco cartoes numa parede de quarenta alvos de toque no
    celular. O que sobra continua a um toque de distancia, no menu do cartao.
    """
    if service == "active":
        return [BY_KEY["restart"], BY_KEY["stop"]]
    return [BY_KEY["start"]]


def remaining_power(service: str) -> list[Action]:
    """As acoes de energia que o cartao nao mostrou — vao para o menu dele.

    Nada some: o que sai da linha de botoes reaparece a um toque. O que nao pode
    acontecer e a MESMA acao aparecer nos dois lugares, e e esta funcao que garante
    isso a partir de `energia_do_cartao`, em vez de uma segunda lista escrita a mao.
    """
    na_frente = {a.key for a in card_power(service)}
    return [a for a in actions_in_group(GROUP_POWER) if a.key not in na_frente]
