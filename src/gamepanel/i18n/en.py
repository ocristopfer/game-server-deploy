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

    # -------------------------------------------------------- painel
    "dashboard.no_servers": "No servers registered yet.",
    "dashboard.ssh_access": "SSH access",
    "dashboard.ask_an_admin": "Ask a panel administrator to register the server.",

    # ----------------------------------------------------- historico
    "history.server": "Server",
    "history.any_server": "all",
    "history.action": "Action",
    "history.any_action": "all",
    "history.who": "Who",
    "history.anyone": "anyone",
    "history.when": "When",
    "history.result": "Result",
    "history.auto": "auto",
    "history.running": "running",
    "history.empty": "Nothing in the history with these filters.",
    "history.by_scheduler": "Triggered by the panel scheduler",

    # ----------------------------------------------------------- job
    "job.target": "Target",
    "job.started": "Started",
    "job.by": "By",
    "job.result": "Result",

    # ------------------------------------------------------- offline
    "offline.title": "Offline — Game Panel",
    "offline.heading": "Offline",
    "offline.vpn_hint": "If you are away from home, check that the VPN is on.",
    "offline.retry": "Try again",

    # ----------------------------------------------------- chave ssh
    "ssh_key.public_key": "Panel public key",
    "ssh_key.not_found": "Key not found. Run the panel deploy again.",
    "ssh_key.authorize": "Authorize on a game container",
    "ssh_key.host_keys": "Host keys",

    # ------------------------------------------------------ graficos
    "charts.no_samples": "No samples for this period yet.",
    "charts.cpu_memory": "CPU and memory",
    "charts.no_readings": "No meter readings for this period.",
    "charts.players": "Players",
    "charts.peak_of": "peak of",
    "charts.in_period": "in the period",
    "charts.as_table": "See the numbers as a table",
    "charts.when": "When",
    "charts.cpu": "CPU",
    "charts.memory": "Memory",
    "charts.period": "Period",

    # ------------------------------------------------------- backups
    "backups.what_is_saved": "What goes into the copy",
    "backups.backup_paths": "backup paths",
    "backups.nothing_to_save": "This server has nothing to save. Fill in the",
    "backups.config_folder": "configuration folder",
    "backups.or_the": "or the",
    "backups.in_settings": "in the server settings",
    "backups.stored_copies": "Stored copies",
    "backups.file": "File",
    "backups.when": "When",
    "backups.size": "Size",
    "backups.before_restore": "before restoring",
    "backups.admin_only": "download, restore and delete are admin-only",
    "backups.none_yet": "No copies yet.",
    "backups.pre_restore_copy": "Taken by the panel right before a restore",

    # -------------------------------------------------- agendamentos
    "schedules.tasks_here": "Tasks for this server",
    "schedules.task": "Task",
    "schedules.when": "When",
    "schedules.next_run": "Next",
    "schedules.last_run": "Last run",
    "schedules.off": "off",
    "schedules.admin_only": "only an administrator can change it",
    "schedules.none_here": "Nothing scheduled for this server.",
    "schedules.clock_is": "The clock is the one on the",
    "schedules.panel": "panel",
    "schedules.no_late_fire": "does not fire late",
    "schedules.new_task": "Schedule a task",
    "schedules.what_to_do": "What to do",
    "schedules.backup": "Backup",
    "schedules.update": "Update",
    "schedules.daily": "Every day, at a fixed time",
    "schedules.weekly": "Once a week",
    "schedules.every_n_hours": "Every N hours",
    "schedules.hour": "Hour",
    "schedules.minute": "Minute",
    "schedules.weekday": "Day of the week",
    "schedules.every": "Every",
    "schedules.hours_from_now": "hours, counted from now",
    "schedules.runs_show_in": "Every run shows up in the",
    "schedules.history": "history",

    # ---------------------------------------------------- instancias
    "instances.new": "New instance",
    "instances.game": "Game",
    "instances.only_installable": "Only games the broker can install on its own are listed.",
    "instances.name": "Name",
    "instances.none_creatable": "No creatable game in the catalog (or the broker did not answer).",
    "instances.instance": "Instance",
    "instances.remove": "Remove",
    "instances.type_name_to_confirm": "Type the name to confirm",
    "instances.forget_record_only": "Forget the record only (the container no longer exists in Proxmox)",
    "instances.none_yet": "No instance created by the broker yet.",

    # ------------------------------------------------------- console
    "console.interactive": "Interactive session",
    "console.single_command": "Single command",
    "console.commands_run_as": "Commands run as",
    "console.interactive_lower": "interactive session",
    "console.history_hint": "History: &uarr; and &darr; walk through previous commands.",
    "console.output": "Output",
    "console.previous_commands": "Previous commands",
    "console.when": "When",
    "console.command": "Command",
    "console.by": "By",
    "console.result": "Result",
    "console.view": "view",
    "console.none_yet": "No command run on this server yet.",
    "console.terminal_mode": "Terminal mode",

    # ------------------------------------------------------ arquivos
    "files.download": "download",
    "files.delete": "delete",
    "files.empty_folder": "empty folder",
    "files.listing_truncated": "Listing cut at the first items of this folder.",
    "files.binary": "Binary file.",
    "files.read_only": "Read-only:",
    "files.opens_as_form": "opens this file as a form and pins it to the screen",
    "files.configuration": "Configuration",
    "files.editor": "Editor",
    "files.any_file_downloadable": "Any file can be downloaded through the link",
    "files.config_folder_hint": "Tip: fill in the \"Configuration folder\" under",
    "files.edit_server": "Edit server",
    "files.path_lower": "path",
    "files.file_to_upload": "file to upload",
    "files.path": "Path",

    # ------------------------------------------------- segundo fator
    "login_2fa.title": "Verification",
    "login_2fa.hint": "Enter the 6-digit code from your authenticator app.",
    "login_2fa.code": "Code",
    "account_2fa.add_account": "add account",
    "account_2fa.scan_qr": "scan QR code",
    "account_2fa.with_text_below": "with the text below the code.",
    "account_2fa.copy_key": "Copy key",
    "account_2fa.type": "Type",
    "account_2fa.time_based": "time-based",
    "account_2fa.six_digit_code": "6-digit code",
    "account_2fa_codes.save_them_now": "Save these codes now.",
    "account_2fa_codes.copy_codes": "Copy codes",
}
