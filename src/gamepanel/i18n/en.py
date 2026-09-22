"""Catalogo em ingles.

Mesmas chaves do `pt.py`; ver o docstring do pacote. Chave que faltar aqui cai no
portugues em vez de sumir — e o teste `test_i18n.py` cobra a paridade, para a falta ser
uma decisao e nao um esquecimento.
"""
from __future__ import annotations

MENSAGENS: dict[str, str] = {
    # -------------------------------------------------------- navegacao
    "nav.servers": "Servers",
    "nav.history": "History",
    "nav.alerts": "Alerts",
    "nav.account": "Account",
    "nav.users": "Users",
    "nav.instances": "Instances",
    "nav.instances.help": "Game instances",
    "nav.catalog": "Catalog",
    "nav.catalog.help": "Game catalog",
    "nav.add_server": "Add server",
    "nav.ssh_key": "SSH access",
    "nav.logout": "Sign out",
    "nav.more": "More",
    "nav.main": "Main navigation",

    # ------------------------------------------------------------ papeis
    "role.admin": "Administrator",
    "role.operator": "Operator",

    # ------------------------------------------------ secoes do servidor
    "server.overview": "Overview",
    "server.overview.help": "Status, players, resources and log",
    "server.config": "Configuration",
    "server.config.help": "The game settings, field by field",
    "server.files": "Files",
    "server.files.help": "Browse, edit as text, upload and download",
    "server.charts": "Charts",
    "server.charts.help": "CPU, memory and players over time",
    "server.backups": "Backups",
    "server.backups.help": "Save copies, and how to restore",
    "server.schedules": "Schedules",
    "server.schedules.help": "Restart and backup at the set time",
    "server.terminal": "Terminal",
    "server.terminal.help": "Command line inside the container",
    "server.console": "Console",
    "server.edit": "Edit",
    "server.edit.help": "Host, service, ports and paths",

    # ------------------------------------------------------------ acoes
    "action.start": "Start",
    "action.start.confirm": "Start server",
    "action.stop": "Stop",
    "action.stop.confirm": "Stop server",
    "action.restart": "Restart",
    "action.restart.confirm": "Restart server",
    "action.update": "Update",
    "action.update.confirm": "Update game (SteamCMD)",
    "action.check_update": "Check for update",
    "action.save": "Save",

    # ------------------------------------------------- base e aviso de versao
    "app.name": "Game Panel",
    "app.new_version": "There is a new version of the panel.",
    "app.update_now": "Update now",
    "app.install": "Install",

    # ------------------------------------------------------------- login
    "login.title": "Sign in",
    "login.subtitle": "Sign in to manage your servers.",
    "login.username": "Username",
    "login.password": "Password",

    # ------------------------------------------------------------ idioma
    "account.language": "Language",
    "account.language.title": "Interface language",
    "account.language.changed": "Language changed.",
}
