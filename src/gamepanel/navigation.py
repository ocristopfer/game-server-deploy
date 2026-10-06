#!/usr/bin/env python3
"""Interface map: what there is to click in the panel, and where.

This module is *pure* on purpose: it does not import Flask, does not open the database, does not
talk SSH. It only describes navigation and actions. What ties it to the current request (role of
whoever is signed in, features enabled in the deploy) is `app.py`, passing the values as
arguments.

Why it exists:

- Before, a server's list of screens was written by hand in SIX different
  templates, each with an arbitrary subset and its own order. Adding
  a screen meant remembering to edit all six; nobody remembered, and that is why one
  place offered "Console" and another did not, one offered "Charts" and another did not.
- Now the list is here. The template asks which sections exist and draws whatever
  comes. New screen = one line in this tuple; no template changes.

The same goes for the actions (start, stop, update): the label, the icon, the group and
the visual weight of each one are data, not markup scattered around.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- features
# A "feature" is a deploy switch (GAMEPANEL_ALLOW_FILES, ALLOW_SHELL).
# A section that depends on a disabled feature does not appear anywhere.
FEATURE_FILES = "files.index"
FEATURE_SHELL = "shell"
FEATURE_BROKER = "broker"


@dataclass(frozen=True)
class Item:
    """A navigation destination.

    `endpoint` is the Flask route name; the template is what resolves the URL, because only it
    knows which server it is talking about.
    """

    key: str
    label: str
    icon: str
    endpoint: str
    admin: bool = False
    feature: str = ""
    # Short description for the dropdown menu, where the label alone is not enough to
    # tell two similar screens apart (the case of Configuration vs Files).
    help: str = ""
    # Label for the wide bar, where seven destinations share a single line.
    short: str = ""


# ------------------------------------------------------- main navigation
# These are the destinations of the bottom bar on the phone. Four is the practical ceiling of a tab
# bar; that is why "Add server", "Users" and "SSH access" live in the menu of the
# top bar: they are things done once, not every day.
NAV_MAIN = (
    Item("servidores", "nav.servers", "🎮", "dashboard.index"),
    Item("historico", "nav.history", "🕘", "history.index"),
    Item("alertas", "nav.alerts", "🔔", "alerts.index", admin=True),
    Item("conta", "nav.account", "👤", "account.index"),
)

# Menu in the corner of the top bar: the rest.
NAV_SECONDARY = (
    # The character is the HEAVY plus sign (U+2795), which is the button icon, not the
    # `+` operator. The linter asks because the two look alike; here the likeness is the point.
    Item("novo", "nav.add_server", "➕", "servers.new", admin=True),  # noqa: RUF001
    # The two broker items only exist in a deploy that turned on GAMEPANEL_ALLOW_BROKER.
    Item("instancias", "nav.instances.help", "🧩", "broker.instances", admin=True,
         feature=FEATURE_BROKER, short="nav.instances"),
    Item("catalogo", "nav.catalog.help", "📚", "broker.catalog", admin=True,
         feature=FEATURE_BROKER, short="nav.catalog"),
    Item("usuarios", "nav.users", "👥", "users.index", admin=True),
    # Every save copy stored on the panel, including those of games that no longer have a
    # server: without this screen, the copy of a removed server had nowhere to show up.
    Item("backups", "nav.backups.help", "💾", "backups.archive", admin=True, short="nav.backups"),
    Item("ssh", "nav.ssh_key", "🔑", "account.ssh_key"),
    Item("atualizacoes", "nav.updates", "⬆️", "updates.index", admin=True),
)


# Which tab of the main bar lights up on each route. A server screen (log,
# backups, terminal) is still "Servers": whoever is there came through the panel and
# expects the bar to say so.
_ACTIVE_EXTRA = {
    "servidores": (
        "dashboard.index", "servers.detail", "servers.new", "servers.edit", "servers.action",
        "config_quick.index", "config_quick.register_file", "config_quick.save", "files.index",
        "files.save", "files.delete", "files.upload", "files.download",
        "terminal.index", "console.index", "charts.index", "backups.index", "backups.create", "backups.restore",
        "backups.delete", "backups.download", "backups.send_to_panel", "backups.panel_restore",
        "backups.panel_delete", "backups.panel_download", "schedules.index", "schedules.new",
        "schedules.toggle", "schedules.delete", "schedules.run",
        "players.setup", "players.use", "players.action", "jobs.detail",
        "broker.instances", "broker.instance_new", "broker.instance_deactivate", "broker.instance_remove",
        "broker.instance_cancel", "broker.catalog", "broker.catalog_new", "broker.catalog_edit",
        "broker.catalog_update",
        "broker.catalog_remove", "backups.archive", "backups.archive_download", "backups.archive_delete",
    ),
    "alertas": ("alerts.index", "alerts.save", "alerts.hook_new", "alerts.hook_save",
                "alerts.hook_delete", "alerts.hook_test"),
    "conta": ("account.index", "account.two_factor", "account.two_factor_off",
              "account.two_factor_codes", "account.ssh_key",
              "users.index", "users.new", "users.role", "users.password", "users.delete",
              "users.two_factor_off", "updates.index"),
    "historico": ("history.index",),
}

_BY_ENDPOINT = {
    endpoint: key
    for key, endpoints in _ACTIVE_EXTRA.items()
    for endpoint in endpoints
}


def active_nav_for(endpoint: str | None) -> str:
    """Which main navigation item is active, given the current route.

    Computed here, once, instead of each template declaring its own: the old way
    of doing this is a variable that twenty screens need to remember to pass, and three
    of them forget.
    """
    return _BY_ENDPOINT.get(endpoint or "", "")


# ------------------------------------------------------- desktop navigation
# From 900px everything fits in a single bar, so nothing needs to hide behind the
# "more" menu: the everyday destinations stay on the bar and the person's own (account, SSH key)
# go in the menu under their name. These are KEYS of the items above, not copies of them: the label, the
# icon, the admin rule and the feature stay defined in one place.
NAV_DESKTOP_BAR = ("servidores", "instancias", "catalogo", "historico", "backups", "alertas", "usuarios")
NAV_DESKTOP_ACCOUNT = ("conta", "ssh", "atualizacoes")

_ALL_ITEMS = {i.key: i for i in NAV_MAIN + NAV_SECONDARY}

# On the phone "Instances" and "Users" light up the tab above them ("Servers",
# "Account"), because there are only four tabs. On the wide bar each destination is its own
# item, so the route lights up itself; otherwise "Instances" would show up as "Servers".
_ACTIVE_ON_DESKTOP = {
    "instancias": ("broker.instances", "broker.instance_new", "broker.instance_deactivate",
                   "broker.instance_remove", "broker.instance_cancel"),
    "catalogo": ("broker.catalog", "broker.catalog_new", "broker.catalog_edit", "broker.catalog_update",
                 "broker.catalog_remove"),
    "usuarios": ("users.index", "users.new", "users.role", "users.password", "users.delete",
                 "users.two_factor_off"),
    "backups": ("backups.archive", "backups.archive_download", "backups.archive_delete"),
    "ssh": ("account.ssh_key",),
    "conta": ("account.index", "account.two_factor", "account.two_factor_off", "account.two_factor_codes"),
    "atualizacoes": ("updates.index",),
}
_BY_ENDPOINT_ON_DESKTOP = {
    endpoint: key
    for key, endpoints in _ACTIVE_ON_DESKTOP.items()
    for endpoint in endpoints
}


def nav_desktop(*, admin: bool, broker: bool) -> tuple[tuple[Item, ...], tuple[Item, ...]]:
    """(bar items, account menu items) that this person can open on desktop."""
    def resolve(keys: tuple[str, ...]) -> tuple[Item, ...]:
        return visible_items(tuple(_ALL_ITEMS[c] for c in keys), admin=admin, broker=broker)

    return resolve(NAV_DESKTOP_BAR), resolve(NAV_DESKTOP_ACCOUNT)


def active_desktop_nav_for(endpoint: str | None) -> str:
    """Item lit on the wide bar: the destination itself when it exists, otherwise the phone one."""
    return _BY_ENDPOINT_ON_DESKTOP.get(endpoint or "") or active_nav_for(endpoint)


# ------------------------------------------------------- screens of a server
# The order here is the order on screen, and it follows real usage frequency: what one
# looks at every day first, what one touches once a month at the end.
SERVER_SECTIONS = (
    Item("visao", "server.overview", "📊", "servers.detail",
         help="server.overview.help"),
    Item("config", "server.config", "⚙️", "config_quick.index", feature=FEATURE_FILES,
         help="server.config.help"),
    Item("charts.index", "server.charts", "📈", "charts.index",
         help="server.charts.help"),
    Item("backups.index", "server.backups", "💾", "backups.index",
         help="server.backups.help"),
    Item("schedules.index", "server.schedules", "⏰", "schedules.index",
         help="server.schedules.help"),
    # Mods: what the server loads and the mod upload. Admin-only like "Files", because the
    # upload writes inside the container.
    Item("mods.index", "server.mods", "🧩", "mods.index", admin=True, feature=FEATURE_FILES,
         help="server.mods.help"),
    # "Files" is the raw sibling of "Configuration": same folder, no form.
    # The two only appear together for whoever may browse the container.
    Item("files.index", "server.files", "📁", "files.index", admin=True, feature=FEATURE_FILES,
         help="server.files.help"),
    # ONE command-line destination, not two. Which of the two screens it opens is an
    # implementation detail (see `terminal_endpoint`): for the user, "Terminal"
    # is a single place, and inside it one picks between an interactive session and a single command.
    Item("terminal.index", "server.terminal", "⌨️", "terminal.index", admin=True, feature=FEATURE_SHELL,
         help="server.terminal.help"),
    Item("editar", "server.edit", "✏️", "servers.edit", admin=True,
         help="server.edit.help"),
)


def visible_items(items: tuple[Item, ...], *, admin: bool, broker: bool) -> tuple[Item, ...]:
    """Navigation items that this person, in this deploy, can open.

    An item whose `feature` is off disappears from the menu: no link that leads to a 403.
    """
    allowed = {FEATURE_BROKER: broker, "": True}
    return tuple(
        i for i in items
        if (not i.admin or admin) and allowed.get(i.feature, True)
    )


def visible_sections(*, admin: bool, arquivos: bool, shell: bool) -> tuple[Item, ...]:
    """The sections that this person, in this deploy, can actually open.

    The route decorator is what really blocks; this exists so as not to draw a button
    that leads to a 403: a menu that lies is worse than a short menu.
    """
    allowed = {FEATURE_FILES: arquivos, FEATURE_SHELL: shell, "": True}
    return tuple(
        s for s in SERVER_SECTIONS
        if (not s.admin or admin) and allowed[s.feature]
    )


def terminal_endpoint(*, tem_pty: bool) -> str:
    """Where the "Terminal" destination points.

    With a PTY (any Linux) it is the interactive session. Without a PTY the panel still runs (on
    Windows, for example), and then the same destination opens the single-command box, which
    does not need a real terminal. In neither case do two menu
    entries for "run a command" appear.
    """
    return "terminal.index" if tem_pty else "console.index"


def section_endpoint(section: Item, *, tem_pty: bool) -> str:
    if section.key == "terminal.index":
        return terminal_endpoint(tem_pty=tem_pty)
    return section.endpoint


# --------------------------------------------------------------- actions
GROUP_POWER = "energia"
GROUP_MAINTENANCE = "manutencao"


@dataclass(frozen=True)
class Action:
    """An action on the game service.

    The remote command does NOT live here: it depends on `shlex` and on the service format, and
    is `app.py`'s responsibility. This module answers for how the action is presented.
    """

    key: str
    label: str      # full name, used in the history and in the confirmation
    short: str       # what fits on a phone button
    icon: str
    group: str
    variant: str = ""     # "primary", "danger" or empty
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


# These functions return a LIST, not a tuple, on purpose: the size varies with the
# server state. A variable-length tuple is a promise the type does not
# keep - whoever reads `tuple[Action, ...]` expects a fixed shape, and static analysis
# rightly complains.
def card_power(service: str) -> list[Action]:
    """The power buttons that make sense on the panel card, given the state.

    The card shows TWO controls, not four. A running server does not need a
    "Start" button, and a stopped one does not need "Stop": offering all four always is
    what turned five cards into a wall of forty touch targets on the
    phone. The rest stays one tap away, in the card menu.
    """
    if service == "active":
        return [BY_KEY["restart"], BY_KEY["stop"]]
    return [BY_KEY["start"]]


def remaining_power(service: str) -> list[Action]:
    """The power actions the card did not show: they go into its menu.

    Nothing disappears: what leaves the button row reappears one tap away. What must not
    happen is the SAME action showing up in both places, and this function guarantees
    that from `card_power`, instead of a second hand-written list.
    """
    ahead = {a.key for a in card_power(service)}
    return [a for a in actions_in_group(GROUP_POWER) if a.key not in ahead]
