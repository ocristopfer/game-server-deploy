"""Catalogo em ingles.

Mesmas chaves do `pt.py`; ver o docstring do pacote. Chave que faltar aqui cai no
portugues em vez de sumir — e o teste `test_i18n.py` cobra a paridade, para a falta ser
uma decisao e nao um esquecimento.
"""
from __future__ import annotations

MESSAGES: dict[str, str] = {
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
    "app.version": "Panel version {version}",
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

    # ------------------------------------------------------ usuarios
    "users.user": "User",
    "users.role": "Role",
    "users.created_at": "Created",
    "users.you": "you",
    "users.reset_password": "Reset password",
    "users.new_user": "New user",
    "users.initial_password": "Initial password",
    "users.confirm_password": "Confirm password",
    "users.password_handoff": "You set the password and hand it over; they change it later under",
    "users.what_each_role_opens": "What each role opens",
    "users.screen": "Screen",
    "users.perm_overview": "Servers, status, players, log",
    "users.yes": "yes",
    "users.no": "no",
    "users.perm_actions": "Start / stop / restart / update",
    "users.perm_config": "Configuration (files already registered)",
    "users.perm_charts": "Charts, backups and schedules",
    "users.perm_manage_servers": "Add / edit / remove server",
    "users.perm_register_config": "Register a new config file",
    "users.perm_terminal": "Terminal and file browser",
    "users.two_factor_on": "Two-step verification on",
    "users.new_password_lower": "new password",
    "users.confirm_lower": "confirm",

    # ------------------------------------------ configuracao do jogo
    "config.edit_as_text": "edit as text",
    "config.unpin": "remove from the list",
    "config.found_in_container": "Configuration files found in the container",
    "config.pin_here": "pin here",
    "config.empty_block": "Empty block &mdash; use &quot;add setting&quot; below.",
    "config.no_match": "No setting with that name.",
    "config.add_setting": "Add setting",
    "config.new_setting_block": "block of the new setting",
    "config.restart_after_save": "restart the server after saving",
    "config.edit_as_text_title": "Edit as text",
    "config.file_path": "path of the configuration file",
    "config.filter_placeholder": "filter by name...",
    "config.filter_label": "filter settings",
    "config.name_example": "Name (e.g. ServerPassword)",
    "config.new_setting_name": "name of the new setting",
    "config.value": "Value",
    "config.new_setting_value": "value of the new setting",

    # ------------------------------------------------------ terminal
    "terminal.ssh_session_as": "Interactive SSH session as",
    "terminal.starting": "starting...",
    "terminal.clear": "Clear",
    "terminal.fullscreen": "Full screen",
    "terminal.end_session": "End",
    "terminal.reconnect": "Reconnect",
    "terminal.interrupt_sigint": "Interrupt (SIGINT)",
    "terminal.eof": "End of input (EOF)",
    "terminal.suspend": "Suspend",
    "terminal.special_keys": "Special keys",
    "terminal.open_keyboard": "Open the keyboard",
    "terminal.interrupt": "Interrupt",
    "terminal.arrow_up": "arrow up",
    "terminal.arrow_down": "arrow down",
    "terminal.arrow_left": "arrow left",
    "terminal.arrow_right": "arrow right",

    # --------------------------------------------------------- conta
    "account.role": "Role",
    "account.change_password": "Change password",
    "account.current_password": "Current password",
    "account.new_password": "New password",
    "account.min_length": "At least 8 characters.",
    "account.confirm_new_password": "Confirm new password",
    "account.two_factor": "Two-step verification",
    "account.on": "on",
    "account.off": "off",
    "account.two_factor_on_hint": "Besides the password, signing in asks for the code from your authenticator app.",
    "account.new_recovery_codes": "Generate new recovery codes",
    "account.app_code": "App code",
    "account.old_codes_expire": "The old codes stop working.",
    "account.disable": "Turn off",
    "account.app_or_recovery_code": "App code (or a recovery code)",
    "account.two_factor_required": "This panel requires the second factor: it cannot be turned off.",
    "account.two_factor_broker_hint": "This panel creates and deletes containers through the broker: turn it on.",
    "account.sign_out": "Sign out",
    "account.sign_out_hint": "Ends the session on this device.",

    # ---------------------------------------------- tela do servidor
    "server_detail.host": "Host",
    "server_detail.ssh_port": "SSH port",
    "server_detail.service": "Service",
    "server_detail.game_ports": "Game ports",
    "server_detail.config_folder": "Config folder",
    "server_detail.server": "Server",
    "server_detail.maintenance": "Maintenance",
    "server_detail.count_off": "Counting is off. Use the",
    "server_detail.wizard": "wizard",
    "server_detail.published_name": "Published name",
    "server_detail.world": "World",
    "server_detail.online": "Online",
    "server_detail.player": "Player",
    "server_detail.connected_for": "Connected for",
    "server_detail.score": "Score",
    "server_detail.no_identifier": "no identifier",
    "server_detail.count": "count",
    "server_detail.count_right_names_wrong": "is right, but the",
    "server_detail.names": "names",
    "server_detail.resources": "Resources",
    "server_detail.swap": "Swap",
    "server_detail.network": "Network",
    "server_detail.uptime": "Uptime",
    "server_detail.game_process": "Game process",
    "server_detail.recent_actions": "Recent actions",
    "server_detail.no_actions_yet": "No action run from here yet.",
    "server_detail.service_log": "Service log",
    "server_detail.live": "live",
    "server_detail.follow_log": "Follow log",
    "server_detail.lines": "lines",
    "server_detail.broadcast": "Notice to everyone on the server",
    "server_detail.broadcast_message": "notice message",

    # --------------------------------------------- alertas: destinos
    "alerts.destinations_on_one": "{n} destination on",
    "alerts.destinations_on_many": "{n} destinations on",
    "alerts.no_destination_on": "no destination on",
    "alerts.intro":
        "The panel warns you through a <strong>webhook</strong> when something happens with nobody "
        "watching. Each destination has its own list of events &mdash; you can send everything to "
        "the team channel and only the outages to the general one. It works with "
        "<strong>Discord</strong> (Edit channel &rarr; Integrations &rarr; Webhooks &rarr; Copy "
        "URL), <strong>Slack</strong> (Incoming Webhook) or any address that accepts a JSON "
        "<code>POST</code> &mdash; the call carries both a <code>content</code> and a "
        "<code>text</code> field, so each one reads its own.",
    "alerts.destinations": "Destinations",
    "alerts.no_destination_yet": "No destination registered — alerts are off. Add the first one below.",
    "alerts.pending_intro":
        "<strong>On, but with nowhere to look.</strong> These events will never fire the way the "
        "panel is set up today &mdash; and a silent channel looks like \"all is well\":",
    "alerts.pending_item": "<em>{event}</em>: no server has {missing}.",
    "alerts.pending_fix": "Fix it in <a href=\"{url}\">each server's settings</a>.",
    "alerts.destination_name": "Destination name",
    "alerts.team_channel": "Team channel",
    "alerts.on": "On",
    "alerts.off": "Off",
    "alerts.url_is_a_secret": "The URL stays hidden: it is a credential",
    "alerts.change_url": "Change the URL",
    "alerts.leave_blank_to_keep": "leave blank to keep the current one",
    "alerts.notify_about": "Notify about",
    "alerts.no_event_checked": "With no event checked this destination never receives anything.",
    "alerts.test": "Test",
    "alerts.remove": "Remove",
    "alerts.remove_confirm": "Remove the destination {name}?",
    "alerts.limit_reached": "Limit of {n} destinations reached — remove one to add another.",
    "alerts.add_destination": "Add destination",
    "alerts.name": "Name",
    "alerts.name_hint": "Only so you can find your way around this list.",
    "alerts.webhook_url": "Webhook URL",
    "alerts.webhook_url_hint": "It is a secret: whoever has it writes in your channel.",
    "alerts.add": "Add",
    "alerts.came_from_env":
        "The deploy brought a URL in <code>GAMEPANEL_WEBHOOK_URL</code>; it became the first "
        "destination in this list, and from here on only what is registered counts.",

    # ----------------------------------------- alertas: preferencias
    "alerts.preferences": "Preferences",
    "alerts.warn_disk_over": "Warn when the disk goes over",
    "alerts.disk_hint":
        "On the fullest disk in the container. It warns once, at the crossing: a disk at 95% is "
        "still at 95% next round, and nobody deserves the same alert every minute.",
    "alerts.warn_memory_over": "Warn when memory goes over",
    "alerts.memory_hint":
        "Container memory, against the container's own limit (not the whole machine's). It warns "
        "once, at the crossing, just like the disk.",
    "alerts.warn_cpu_over": "Warn when the CPU goes over",
    "alerts.cpu_hint":
        "Container usage over the cores it has, measured together with the disk (every {n} min). "
        "Since it is a short sample now and then, it catches a CPU stuck at the ceiling, not a "
        "one-second spike.",

    # ----------------------------------------------- alertas: diario
    "alerts.journal": "Alert journal",
    "alerts.journal_empty":
        "Nothing recorded yet. Every alert the panel decides to send shows up here &mdash; "
        "including the ones that did <strong>not</strong> go out.",
    "alerts.when_utc": "When (UTC)",
    "alerts.event": "Event",
    "alerts.what": "What",
    "alerts.destination": "Destination",
    "alerts.outcome": "Outcome",
    "alerts.sent": "sent",
    "alerts.failed": "failed",
    "alerts.no_destination": "no destination",
    "alerts.internal_error": "internal error",
    "alerts.journal_legend":
        "<strong>no destination</strong> means the alert really happened and no active destination "
        "had that event checked &mdash; the channel is quiet by choice, not by defect. "
        "<strong>internal error</strong> is a scheduler task that broke: while it shows up here, "
        "its alerts are not being checked at all.",

    # ---------------------------------------- alertas: como funciona
    "alerts.how_it_works": "How it works",
    "alerts.rule_rhythm":
        "The panel checks each server's state every <strong>{monitor}s</strong>, and disk, memory "
        "and CPU every <strong>{meter} min</strong> (the meter costs far more than the status, "
        "and the three readings come out in one go).",
    "alerts.rule_joining":
        "<strong>A player joining is the exception:</strong> that one the panel checks every "
        "<strong>{n}s</strong>, because whoever gets the notice usually wants to join too, and a "
        "minute later is already late. This short round asks the game directly, without SSH "
        "&mdash; which is why it fits without making the rest more expensive. It applies to "
        "whoever counts by <strong>A2S or HTTP API</strong>.",
    "alerts.streams_now": "<strong>{n}</strong> right now",
    "alerts.streams_none": "none at the moment",
    "alerts.rule_log_listen":
        "Whoever counts by <strong>log</strong> is never asked: the panel keeps a connection open "
        "<em>listening</em> to the log ({listening}) and reacts to the line the second it appears. "
        "Asking every 15 seconds would cost a read of the whole log each time; this way it only "
        "reads when somebody actually joined or left. If the connection drops, the notice goes "
        "back to the {monitor}s round until it comes back.",
    "alerts.rule_on_change":
        "It warns on the <strong>change</strong>, never on repeat: the alert goes out when the "
        "server falls, not on every round while it stays down.",
    "alerts.rule_all_destinations":
        "Each event goes to <strong>every destination</strong> that checked it. One destination "
        "being down does not stop the others from receiving.",
    "alerts.rule_service_up_is_not_game_up":
        "<strong>A service being up does not mean the game is up.</strong> Besides the outage, the "
        "panel watches three things that would otherwise slip by:",
    "alerts.rule_game_failed":
        "<em>Game crashed</em> &mdash; systemd marked the service as <code>failed</code>. This is "
        "different from \"stopped\": somebody stopping it from the panel does not raise this "
        "alert, and this one goes out even inside the quiet window.",
    "alerts.rule_restart_loop":
        "<em>Restart loop</em> &mdash; the game dies and systemd brings it back, over and over. "
        "Between one crash and the next the service answers <code>active</code>, so the outage "
        "alert never fires. This one goes out once per episode.",
    "alerts.rule_game_mute":
        "<em>Game not answering</em> &mdash; the process is alive but silent on the game's own "
        "query, for {n} checks in a row. It only applies to whoever counts players by <strong>A2S "
        "or HTTP API</strong>: counting by log asks the game nothing.",
    "alerts.rule_log_error":
        "<em>Error in the game log</em> reads the end of the log every <strong>{n}s</strong> and "
        "looks for the expression registered on each server. With no expression, not even the read "
        "happens. The same line never warns twice.",
    "alerts.rule_quiet_window":
        "Stopping, restarting, updating or restoring <strong>from the panel</strong> does not "
        "become an alert &mdash; in the {n}s after one of those actions the outage is expected.",
    "alerts.rule_on_boot":
        "On start-up the panel merely <strong>writes down</strong> everyone's state. Restarting "
        "the panel does not fire one alert per server that was already down.",
    "alerts.rule_scheduled_only":
        "Of the tasks that fail, only the <strong>scheduled</strong> one becomes an alert: whoever "
        "clicked the button already has the error on screen.",
    "alerts.rule_editing_resets":
        "Touching this screen resets the monitor's baseline, so the next round does not warn about "
        "what was already that way before the change.",

    # --------------------------------------------- catalogo de jogos
    "catalog.title": "Game catalog",
    "catalog.game": "Game",
    "catalog.creatable": "creatable",
    "catalog.manual": "manual",
    "catalog.ports": "Ports",
    "catalog.shifted_port": "assigned port",
    "catalog.shifted_port_help":
        "The broker assigns ports from a range of its own; the ones listed here are just the "
        "game's defaults",
    "catalog.empty": "Empty catalog (or the broker did not answer).",
    "catalog.curated_vs_dynamic":
        "<strong>curated</strong>: comes from the <code>games/*.env</code> files in the "
        "repository. <strong>dynamic</strong>: added from here. A game that needs a Steam account "
        "or its own installer (TeamSpeak) is still created by <code>deploy-game.ps1</code>.",
    "catalog.add_game": "Add game",
    "catalog.data_only":
        "Data only: the broker <strong>accepts no commands</strong>. Anything needing a special "
        "install (Wine, Proton, a Steam symlink) goes in through the recipes below.",
    "catalog.search_game": "Search for a game",
    "catalog.by_name_or_app_id": "(name or App ID)",
    "catalog.search_hint":
        "Fills in App ID, ports and start command from the LinuxGSM catalog. It is only a "
        "suggestion: check it before submitting.",
    "catalog.start_from_template": "Start from a template",
    "catalog.blank": "Blank",
    "catalog.template_hint": "Fills in ports, paths, arguments and the log pattern in one go.",
    "catalog.key": "Key",
    "catalog.key_example": "mygame",
    "catalog.key_hint": "Lowercase, digits and hyphen. It becomes the container and service name.",
    "catalog.name": "Name",
    "catalog.name_example": "My Game",
    "catalog.app_id": "Dedicated server App ID (Steam)",
    "catalog.app_id_hint": "The <strong>dedicated server</strong> one, not the game's. Check SteamDB.",
    "catalog.ports_hint": "Port/protocol, separated by a space. Below 1024 is not allowed.",
    "catalog.game_port": "Game port",
    "catalog.query_port": "Query port",
    "catalog.extra_port": "Extra port",
    "catalog.optional": "(optional)",
    "catalog.start_script": "Start script",
    "catalog.start_args": "Arguments",
    "catalog.start_args_hint":
        "Use <code>{PORT}</code>, <code>{QUERY_PORT}</code> and <code>{EXTRA_PORT}</code>. No "
        "<code>; | &amp; $</code>.",
    "catalog.memory_mb": "Memory (MB)",
    "catalog.cpus": "CPUs",
    "catalog.disk_gb": "Disk (GB)",
    "catalog.config_folder": "Configuration folder",
    "catalog.config_folder_hint": "Absolute path under <code>/opt/game</code> or <code>/home/steam</code>.",
    "catalog.config_files": "Configuration files",
    "catalog.one_per_line": "(one per line)",
    "catalog.one_per_line_f": "(one per line)",
    "catalog.backup_paths": "Backup folders",
    "catalog.player_count": "Player count",
    "catalog.by_server_log": "From the server log",
    "catalog.by_steam_query": "Steam query (A2S)",
    "catalog.platform": "Platform",
    "catalog.linux_default": "Linux (default)",
    "catalog.windows_needs_wine": "Windows (needs Wine or Proton)",
    "catalog.log_join_line": "Log: join line",
    "catalog.log_leave_line": "Log: leave line",
    "catalog.install_recipes": "Install recipes",
    "catalog.broker_picks_ports": "The broker assigns the ports (several instances of the same game)",
    "catalog.broker_picks_ports_hint":
        "Only check this if the game takes its ports from the arguments: the start arguments must "
        "contain {PORT} (plus {QUERY_PORT} and {EXTRA_PORT}, if there is a query port and an extra "
        "port) and the game may have only those three ports.",
    "catalog.add_to_catalog": "Add to the catalog",

    # ------------------------------------------ cadastro de servidor
    "server_form.title_new": "Add server",
    "server_form.title_edit": "Edit server",
    "server_form.optional": "(optional)",
    "server_form.one_per_line": "(one per line)",
    "server_form.one_per_line_optional": "(one per line, optional)",
    "server_form.name": "Name",
    "server_form.name_hint": "How the server shows up in the panel. E.g.: <code>Dragonwilds</code>",
    "server_form.host": "Host",
    "server_form.host_hint": "IP or hostname of the game container. The panel connects to it over SSH.",
    "server_form.ssh_user": "SSH user",
    "server_form.ssh_port": "SSH port",
    "server_form.systemd_service": "systemd service",
    "server_form.service_hint":
        "Usually <code>&lt;game-name&gt;.service</code>. The <code>.service</code> suffix is added "
        "if missing.",
    "server_form.game_ports": "Game ports",
    "server_form.game_ports_hint": "For reference only, to remember what to forward on the router.",
    "server_form.query_port": "Query port",
    "server_form.query_port_hint": "Steam query port (A2S). Palworld: <code>27015</code>.",
    "server_form.player_count": "Player count",
    "server_form.count_off": "Off",
    "server_form.count_a2s": "Steam query (A2S) on the port above",
    "server_form.count_http": "The game's HTTP API (gives the names)",
    "server_form.count_log": "From the server log",
    "server_form.player_count_hint":
        "A game that publishes nothing on the network (RuneScape Dragonwilds, for instance) can "
        "only be counted from the log.",
    "server_form.player_count_wizard":
        "The <a href=\"{url}\">wizard</a> tests the UDP and TCP ports, builds the API call and "
        "finds the log patterns for you.",
    "server_form.log_join": "Log: join line",
    "server_form.log_leave": "Log: leave line",
    "server_form.log_file": "Log: file",
    "server_form.log_file_hint":
        "Blank reads the service output. Filled in, it reads that file &mdash; which is how you "
        "reach the player's name in games that only write it to a log of their own (DayZ).",
    "server_form.log_error": "Log: error line",
    "server_form.log_error_hint":
        "Turns on the <strong>Error in the game log</strong> alert under <a "
        "href=\"{url}\">Alerts</a>: the panel looks for this expression at the end of the log and "
        "warns when it shows up. Blank, and not even the read happens. Start narrow &mdash; too "
        "wide a pattern turns the channel into a copy of the log.",
    "server_form.api_url": "API: URL",
    "server_form.api_url_hint": "Called from inside the container, over SSH. Palworld: port <code>8212</code>.",
    "server_form.api_auth": "API: authentication",
    "server_form.api_auth_hint":
        "<code>basic:user:password</code>, <code>bearer:token</code> or <code>header:Name: "
        "value</code> (TeamSpeak: <code>header:x-api-key: YOUR-KEY</code>). It is stored in plain "
        "text.",
    "server_form.api_body": "API: JSON body",
    "server_form.api_body_hint": "Filled in it becomes a <code>POST</code>; empty it is a <code>GET</code>.",
    "server_form.api_paths": "API: path to the list / to the count",
    "server_form.api_paths_hint": "Left empty, the panel searches the response on its own.",
    "server_form.config_folder": "Configuration folder",
    "server_form.config_folder_hint":
        "Where the <strong>Files</strong> screen opens by default. E.g.: "
        "<code>/opt/game/Pal/Saved/Config/LinuxServer</code>",
    "server_form.config_files": "Configuration files",
    "server_form.config_files_hint":
        "Put here the file you actually edit: the <strong>Config</strong> screen opens it straight "
        "as a form (one field per key, with a button to add a new one) &mdash; no folder browsing. "
        "Left blank, that screen helps you look for the candidates in the container.",
    "server_form.config_files_hint_link":
        "Put here the file you actually edit: the <a href=\"{url}\"><strong>Config</strong></a> "
        "screen opens it straight as a form (one field per key, with a button to add a new one) "
        "&mdash; no folder browsing. Left blank, that screen helps you look for the candidates in "
        "the container.",
    "server_form.backup_paths": "Backup paths",
    "server_form.backup_paths_hint":
        "What the <strong>Backups</strong> screen puts in the <code>.tar.gz</code>. Left blank, "
        "the <strong>configuration folder</strong> above applies. Point at the "
        "<strong>save</strong> folder, not the game root: all of <code>/opt/game</code> carries "
        "tens of GB of binaries that SteamCMD downloads again for free.",
    "server_form.backup_paths_hint_link":
        "What the <a href=\"{url}\"><strong>Backups</strong></a> screen puts in the "
        "<code>.tar.gz</code>. Left blank, the <strong>configuration folder</strong> above "
        "applies. Point at the <strong>save</strong> folder, not the game root: all of "
        "<code>/opt/game</code> carries tens of GB of binaries that SteamCMD downloads again for "
        "free.",
    "server_form.notes": "Notes",
    "server_form.cancel": "Cancel",
    "server_form.sshd_note":
        "The container needs <code>sshd</code> running and the panel's key authorized — see <a "
        "href=\"{url}\">SSH access</a>.",
    "server_form.remove": "Remove from the panel",
    "server_form.remove_hint": "Deletes only the record. The container and the game files are left untouched.",
    "server_form.remove_confirm": "Remove this server from the panel?",

    # ------------------------------------------ titulos e componente
    "error.title": "Error {code}",
    "job.title": "Action #{id}",
    "account_2fa_codes.title": "Recovery codes",
    "players_setup.title": "Player count",
    "server.sections_of_this_server": "Sections of this server",
    "server.measuring": "measuring resources...",
    "server.server": "Server",

    # -------------------------------- rotulos de botao e confirmacao
    "account.generate": "Generate",
    "account.enable": "Turn on",
    "account.disable_confirm": "Turn off two-step verification? Signing in will ask for the password only.",
    "account.sign_out_of_panel": "Sign out of the panel",
    "account_2fa.open_in_app": "Open in the app",
    "account_2fa_codes.saved_them": "I saved them",
    "backups.back_up_now": "Back up now",
    "backups.restore": "restore",
    "backups.restore_confirm":
        "Restore {file} on {server}?\n\nThe server will be STOPPED, the current files will be "
        "replaced and it comes back up. A copy of the current state is saved first.",
    "backups.delete_confirm": "Delete {file}? There is no undo.",
    "config.use_this_file": "Use this file",
    "config.search_container": "Search the container",
    "config.another_line": "another line",
    "console.run": "Run",
    "dashboard.add_the_first": "Add the first one",
    "error.back_to_panel": "Back to the panel",
    "files.go": "Go",
    "files.upload_here": "Upload to this folder",
    "files.discard": "Discard",
    "files.download_title": "Download",
    "files.edit_field_by_field": "Edit field by field",
    "files.delete_file": "Delete file",
    "files.delete_confirm": "Delete {path}? There is no undo.",
    "history.filter": "Filter",
    "history.clear": "clear",
    "history.newer": "newer",
    "history.older": "older",
    "instances.create": "Create instance",
    "instances.create_confirm":
        "Create the container, install the game and open the ports on the firewall? This can take "
        "several minutes.",
    "instances.deactivate_confirm": "Turn off {name}? The server will be STOPPED and the ports close on the firewall.",
    "instances.remove_confirm": "Remove {name}? The container and the game will be DELETED.",
    "login_2fa.confirm": "Confirm",
    "login_2fa.back": "Back",
    "schedules.run_now": "run now",
    "schedules.run_now_help": "Runs now, without waiting for the set time",
    "schedules.turn_on": "turn on",
    "schedules.turn_off": "turn off",
    "schedules.delete": "remove",
    "schedules.delete_confirm": "Remove: {task}?",
    "schedules.schedule_it": "Schedule",
    "schedules.never": "never",
    "server_detail.configure": "Set up",
    "server_detail.how_counting_works": "How the panel counts the players on this server",
    "server_detail.announce": "Announce",
    "server_detail.reload": "Reload",
    "users.change": "Change",
    "users.two_factor_off": "Turn 2FA off",
    "users.two_factor_off_confirm":
        "Turn off two-step verification for {user}? They sign in with the password alone until "
        "they turn it back on.",
    "users.remove_confirm": "Remove the user {user}?",
    "users.create": "Create",

    # ---------------------------------------- contagem de jogadores
    "players_setup.intro":
        "Three ways to know how many are playing, from the best to the last resort: the "
        "<strong>game's API</strong> (gives the names), the <strong>direct query</strong> the "
        "server browser uses (gives the count) and, when the game publishes nothing on the "
        "network, the <strong>server log</strong>.",
    "players_setup.how_to_count": "How to count",
    "players_setup.tab_udp": "1. Direct query (UDP)",
    "players_setup.tab_http": "2. HTTP API (TCP)",
    "players_setup.tab_log": "3. From the log",
    "players_setup.ports_tested": "Ports tested",
    "players_setup.ports_tested_hint":
        "The panel read from <code>/proc</code> which UDP ports are open inside the container and "
        "<strong>which process opened each one</strong>, then sent an <code>A2S_INFO</code> to all "
        "of them. The detected ones come first; those marked as a <em>guess</em> were not open and "
        "only help while the server is stopped.",
    "players_setup.port": "Port",
    "players_setup.opened_by": "Opened by",
    "players_setup.answer": "Answer",
    "players_setup.server": "Server",
    "players_setup.address": "Address",
    "players_setup.status": "Status",
    "players_setup.kind": "Kind",
    "players_setup.infra_not_the_game": "infrastructure, not the game",
    "players_setup.open_no_owner": "open, with no owning process in this container",
    "players_setup.was_not_open": "was not open (a guess)",
    "players_setup.no_answer": "no answer",
    "players_setup.use_this": "Use this one",
    "players_setup.no_port_to_test": "No port to test.",
    "players_setup.no_udp_query_one":
        "<strong>This game publishes no UDP query.</strong> The server process opened {n} UDP port "
        "and it did not answer the <code>A2S_INFO</code> &mdash; this is not a wrong port nor a "
        "firewall: it is the game's own port, and it does not speak the protocol. The count shown "
        "in the game's browser, when there is one, comes from the Steam/Epic service and not from "
        "the server. Check the <a href=\"{url_http}\">HTTP API</a> tab (several games traded the "
        "UDP query for a TCP API) and, if there is nothing there either, the count can only come "
        "from the <a href=\"{url_log}\">log</a>.",
    "players_setup.no_udp_query_many":
        "<strong>This game publishes no UDP query.</strong> The server process opened {n} UDP "
        "ports and none answered the <code>A2S_INFO</code> &mdash; this is not a wrong port nor a "
        "firewall: they are the game's own ports, and they do not speak the protocol. The count "
        "shown in the game's browser, when there is one, comes from the Steam/Epic service and not "
        "from the server. Check the <a href=\"{url_http}\">HTTP API</a> tab (several games traded "
        "the UDP query for a TCP API) and, if there is nothing there either, the count can only "
        "come from the <a href=\"{url_log}\">log</a>.",
    "players_setup.none_answered":
        "None answered? Check the <a href=\"{url}\">HTTP API</a> tab &mdash; several games traded "
        "the UDP query for a TCP administration API.",
    "players_setup.tcp_answered_http": "TCP ports that answered HTTP",
    "players_setup.tcp_hint":
        "The panel read from <code>/proc</code> the TCP ports in <code>LISTEN</code> inside the "
        "container and <strong>which process opened each one</strong>, then knocked on them over "
        "HTTP <strong>from inside the container itself</strong> &mdash; these APIs usually listen "
        "on <code>127.0.0.1</code> only, and that is how they should stay. A <code>401</code> is a "
        "good sign too: there is an API there, it just wants a password. Check the &quot;Opened "
        "by&quot; column: if it is not the game's process, it is not the game's API.",
    "players_setup.same_on_everything": "{status} on everything",
    "players_setup.asks_for_password": "{status} asks for a password",
    "players_setup.http_but_not_a_game_api": "speaks HTTP, but is not a game API",
    "players_setup.use_this_url": "Use this URL",
    "players_setup.no_tcp_answered_http": "No TCP port answered HTTP.",
    "players_setup.no_http_answer_on": "No HTTP answer on:",
    "players_setup.no_game_api":
        "<strong>No game API answered.</strong> Almost always this is because it ships "
        "<em>off</em> and has to be turned on in the server configuration &mdash; the port only "
        "comes into being after that. On <strong>Palworld</strong>, in "
        "<code>PalWorldSettings.ini</code> (inside <code>OptionSettings=(...)</code>): "
        "<code>RESTAPIEnabled=True</code>, <code>RESTAPIPort=8212</code> and a strong "
        "<code>AdminPassword</code>. Stop the server, edit, bring it back up and reload this page. "
        "If the game simply has no API (RuneScape Dragonwilds has none), use the <a "
        "href=\"{url}\">From the log</a> tab.",
    "players_setup.test_the_call": "Test the call",
    "players_setup.url": "URL",
    "players_setup.url_hint":
        "Always <code>127.0.0.1</code>: the call goes out from inside the container, over the same "
        "SSH as the rest of the panel. Nothing needs opening on the router.",
    "players_setup.auth": "Authentication",
    "players_setup.auth_hint":
        "<code>basic:user:password</code>, <code>bearer:token</code> or a ready-made "
        "<code>Authorization</code> header. Palworld: <code>basic:admin:</code> + the "
        "<code>AdminPassword</code> from <code>PalWorldSettings.ini</code>. For an API that "
        "authenticates through another header, use <code>header:Name: value</code> &mdash; "
        "TeamSpeak wants <code>header:x-api-key: YOUR-KEY</code>.",
    "players_setup.json_body": "JSON body",
    "players_setup.json_body_hint": "Filled in, the call becomes a <code>POST</code>. Empty, it is a <code>GET</code>.",
    "players_setup.list_path": "Path to the list",
    "players_setup.count_path": "Path to the count",
    "players_setup.auto_login": "Automatic login",
    "players_setup.auto_login_hint":
        "For APIs whose token <strong>expires</strong> — Satisfactory's is like that. Fill in "
        "these three fields and the panel trades the password for a token on its own, keeps it, "
        "and when the API answers <code>401</code> it logs in again and repeats the query. Leave "
        "<em>Authentication</em> above empty: the header is then sent with the token obtained "
        "here.",
    "players_setup.login_url": "Login URL",
    "players_setup.token_path": "Path to the token",
    "players_setup.login_json_body": "Login JSON body",
    "players_setup.login_json_body_hint":
        "Satisfactory: the password is the <strong>admin</strong> one set in the client when "
        "claiming the server. The body goes to the same API, with no authentication header.",
    "players_setup.leave_paths_empty":
        "Leave both paths empty first: the panel looks for a player list on its own and, failing "
        "that, for a number under known keys (<code>currentplayernum</code>, "
        "<code>numPlayers</code>, ...). Only fill them in if it gets it wrong &mdash; the raw "
        "answer shows up below so you can see the right field name.",
    "players_setup.test": "Test",
    "players_setup.result": "Result:",
    "players_setup.players_count": "player(s)",
    "players_setup.players_online_now": "player(s) online right now",
    "players_setup.raw_api_answer": "Raw API answer",
    "players_setup.use_this_api": "Use this API",
    "players_setup.password_in_plain_text":
        "The API password is kept in the panel's database in plain text (it has to go in the "
        "header of every call). Treat <code>panel.db</code> as a secret.",
    "players_setup.log_lines_that_look_like": "Log lines that look like joins and leaves",
    "players_setup.find_the_lines":
        "Find the line that shows up when somebody joins and the one that shows up when somebody "
        "leaves, and write the patterns below. Use <code>(?P&lt;name&gt;.+)</code> where the "
        "player's name is &mdash; with the name in both patterns the panel lists who is online; "
        "without it, it only shows the count.",
    "players_setup.no_join_leave_lines": "No line with join or leave words in the log of this run.",
    "players_setup.test_the_pattern": "Test the pattern",
    "players_setup.log_file": "Log file",
    "players_setup.log_file_hint":
        "Blank, the panel reads the service output (<code>journalctl</code>) &mdash; which is "
        "where most games announce. Some only write the <strong>name</strong> of whoever joins to "
        "a file of their own: <strong>DayZ</strong> is like that "
        "(<code>/opt/game/profiles/*.ADM</code>, already turned on by the <code>-adminlog</code> "
        "in our deploy). The <code>*</code> works, and the panel always picks the newest file.",
    "players_setup.join_line": "Join line",
    "players_setup.leave_line": "Leave line",
    "players_setup.last_matching_lines": "Last lines that matched the patterns:",
    "players_setup.no_line_matched": "No line matched the patterns — check the spelling.",
    "players_setup.use_these_patterns": "Use these patterns",

    # --------------------------------------------- eventos de alerta
    "event.server_stopped": "Server stopped running",
    "event.server_back": "Server is running again",
    "event.game_failed": "Game crashed (service in 'failed')",
    "event.restart_loop": "Game caught in a restart loop",
    "event.game_mute": "Game not answering (up, but silent)",
    "event.game_answering": "Game is answering again",
    "event.player_joined": "A player connected",
    "event.player_left": "A player disconnected",
    "event.log_error": "Error in the game log",
    "event.lost_contact": "Panel lost contact (SSH)",
    "event.contact_back": "Contact restored",
    "event.scheduled_task_failed": "A scheduled task failed",
    "event.disk_almost_full": "Disk almost full",
    "event.memory_almost_full": "Memory almost full",
    "event.cpu_high": "High CPU usage",

    # ----------------------------------- nome das acoes no historico
    "job.shell": "Command in the container",
    "job.terminal": "Interactive terminal",
    "job.file_saved": "File saved",
    "job.file_deleted": "File deleted",
    "job.config_changed": "Configuration changed",
    "job.file_downloaded": "File downloaded",
    "job.file_uploaded": "File uploaded",
    "job.backup": "Backup",
    "job.backup_restored": "Backup restored",
    "job.backup_deleted": "Backup deleted",
    "job.player_action": "Action on a player",
    "job.instance_created": "Instance created (broker)",
    "job.instance_deactivated": "Instance turned off (broker)",
    "job.instance_removed": "Instance removed (broker)",
    "job.game_added": "Game added to the catalog",
    "player_action.announce": "Announce to everyone",
    "player_action.kick": "Kick",
    "player_action.ban": "Ban",

    # ---------------------------------------- mensagens de flash
    "flash.two_factor_required_here": "This panel requires two-step verification: turn it on to continue.",
    "flash.too_many_tries": "Too many attempts. Try again in {n}s.",
    "flash.bad_credentials": "Wrong username or password.",
    "flash.verification_expired": "The verification expired. Sign in again.",
    "flash.code_invalid_or_used": "Invalid code, or one that was already used.",
    "flash.bad_port": "Invalid port.",
    "flash.count_on_by_query": "Player count turned on through the query on port {port}/udp.",
    "flash.need_api_url": "Enter the API URL.",
    "flash.count_on_by_api_login": "Count turned on through the API, with automatic login (the token renews itself).",
    "flash.count_on_by_api": "Player count turned on through the server's HTTP API.",
    "flash.need_join_pattern": "Enter the pattern of the join line.",
    "flash.count_on_by_log": "Player count turned on through the server log.",
    "flash.bad_choice": "Invalid choice.",
    "flash.could_not": "I could not do it: {reason}",
    "flash.player_action_done": "{label}: {who}.",
    "flash.notice_sent": "Notice sent: {message}",
    "flash.server_added": "Server {name} registered.",
    "flash.server_updated": "Server updated.",
    "flash.server_removed": "Server removed from the panel (the container was left untouched).",
    "flash.type_a_command": "Type a command.",
    "flash.command_too_long": "Command too long (the limit is {n} characters).",
    "flash.file_too_big": "File too big to save (the limit is {kb} KB).",
    "flash.file_over_edit_limit":
        "{path} is {size} KB and went over the editing limit ({kb} KB). Nothing was written — "
        "download the file to work on it.",
    "flash.file_saved": "{path} saved ({bytes} bytes). A .bak copy was kept next to it.",
    "flash.is_a_root_folder": "{path} is a root folder of the editor — it cannot be deleted from here.",
    "flash.deleted_no_bak": "{output} (no .bak copy — deleting has no undo).",
    "flash.also_left_config": "{path} also left the files of the Config screen.",
    "flash.could_not_delete": "I could not delete it: {reason}",
    "flash.pick_a_file": "Pick a file to upload.",
    "flash.bad_file_name": "Invalid file name.",
    "flash.could_not_upload": "I could not upload it: {reason}",
    "flash.uploaded": "{output}. If the file already existed, a .bak copy was left next to it.",
    "flash.nothing_to_back_up":
        "This server has nothing to save: fill in the configuration folder or the backup paths in "
        "its settings.",
    "flash.left_config_screen": "{path} left the configuration screen (the file was left untouched).",
    "flash.config_files_limit": "Limit of {n} files per server.",
    "flash.now_opens_in_config": "{path} now opens straight in the Config screen.",
    "flash.value_out_of_range": "I saved nothing because a value is out of range - {errors}",
    "flash.no_field_changed": "No field was changed.",
    "flash.could_not_save": "I could not save: {reason}",
    "flash.settings_saved": "{n} setting(s) saved in {path}: {keys}. A .bak copy was kept next to it.",
    "flash.broker_needs_two_factor":
        "The broker can only be used by someone with two-step verification on: turn it on under "
        "Account.",
    "flash.broker_error": "Broker: {reason}",
    "flash.game_added": "Game {name} added to the catalog.",
    "flash.broker_no_operation_id": "Broker: answer with no operation identifier.",
    "flash.instance_deactivated": "Instance turned off: ports closed and container stopped.",
    "flash.instance_removed": "Instance removed.",
    "flash.task_scheduled": "{task} scheduled.",
    "flash.task_off": "Task turned off.",
    "flash.task_on": "Task turned on.",
    "flash.task_removed": "Task removed.",
    "flash.could_not_trigger": "I could not trigger it (a server with no backup paths?).",
    "flash.wrong_current_password": "Wrong current password.",
    "flash.password_changed": "Password changed.",
    "flash.password_too_short": "The password needs at least {n} characters.",
    "flash.password_mismatch": "The confirmation does not match.",
    "flash.wrong_code": "Wrong code. Check the clock on your phone and try again.",
    "flash.two_factor_on": "Two-step verification turned on.",
    "flash.two_factor_off": "Two-step verification turned off.",
    "flash.new_codes": "New codes generated: the old ones stopped working.",
    "flash.threshold_range": "The {name} warning goes from 50% to 100%.",
    "flash.preferences_saved": "Preferences saved.",
    "flash.destination_limit": "Limit of {n} destinations reached.",
    "flash.need_webhook_url": "Enter the webhook URL.",
    "flash.destination_added": "Destination added.",
    "flash.destination_not_found": "Destination not found.",
    "flash.destination_saved": "Destination saved.",
    "flash.destination_removed": "Destination removed.",
    "flash.bad_url": "Invalid URL (start with http:// or https://).",
    "flash.destination_test_failed": "{name}: {reason}",
    "flash.destination_test_sent": "Message sent to {name} - check the channel.",
    "flash.user_exists": "There is already a user called '{user}'.",
    "flash.user_created":
        "User '{user}' created as {role}. Hand them the password and ask them to change it "
        "under Account.",
    "flash.cannot_change_own_role": "You cannot change your own role — ask another administrator.",
    "flash.user_already_is": "'{user}' is already {role}.",
    "flash.only_admin_demote": "This is the only administrator: promote somebody else before demoting them.",
    "flash.user_now_is": "'{user}' is now {role}.",
    "flash.password_reset": "Password for '{user}' reset.",
    "flash.own_two_factor_in_account": "To turn off your own 2FA use the Account screen.",
    "flash.user_two_factor_off": "Two-step verification for '{user}' turned off.",
    "flash.cannot_remove_self": "You cannot remove your own account.",
    "flash.cannot_remove_only_admin": "The panel's only administrator cannot be removed.",
    "flash.user_removed": "User '{user}' removed.",

    # --------------------------------- erros do cadastro de servidor
    "form.need_name": "Enter a name.",
    "form.bad_host": "Invalid host (use the container's IP or hostname).",
    "form.bad_ssh_user": "Invalid SSH user.",
    "form.bad_ssh_port": "Invalid SSH port.",
    "form.bad_query_port": "Invalid query port (use 0 to turn it off).",
    "form.bad_service": "Invalid service (e.g. dragonwilds.service).",
    "form.bad_player_source": "Invalid way of counting players.",
    "form.bad_config_folder": "Invalid configuration folder: {reason}",
    "form.bad_config_file": "Invalid configuration file ({path}): {reason}",
    "form.too_many_config_files": "At most {n} configuration files per server.",
    "form.bad_backup_path": "Invalid backup path ({path}): {reason}",
    "form.no_root_backup": "Not the root: point at the save folder or the configuration one.",
    "form.too_many_backup_paths": "At most {n} backup paths per server.",
    "form.bad_api_url": "Invalid API URL (e.g. http://127.0.0.1:8212/v1/api/players).",
    "form.bad_login_url": "Invalid login URL (e.g. https://127.0.0.1:7787/api/v1).",
    "form.bad_json": "{label} is not valid JSON: {reason}.",
    "form.request_body": "Request body",
    "form.login_body": "Login body",
    "form.path_list": "list",
    "form.path_count": "count",
    "form.path_token": "token",
    "form.bad_json_path": "Invalid path to the {label} (use something like 'data.players').",
    "form.login_needs_token_path":
        "For the automatic login, enter the path to the token as well (e.g. "
        "data.authenticationToken).",
    "pattern.join": "join",
    "pattern.leave": "leave",
    "pattern.error": "error",

    # -------------------------------------------------- consulta A2S
    "a2s.truncated": "the server's answer ended sooner than expected",
    "a2s.unterminated_text": "unterminated text in the answer",
    "a2s.split_incomplete": "the split answer arrived incomplete",
    "a2s.split_unknown": "split answer in an unknown format (compressed?)",
    "a2s.unexpected_reply": "unexpected answer from the server (type {kind})",
    "a2s.no_reply": "no answer within {seconds}s on port {port}/udp",
    "a2s.query_failed": "could not query {host}:{port} - {reason}",

    # -------------------------------- caminho e arquivo no container
    "path.outside_roots": "outside the allowed folders ({folders})",
    "path.not_absolute": "use an absolute path (starting with /)",
    "path.bad_character": "invalid character in the path",
    "path.too_long": "path too long",
    "file.unexpected_reply": "unexpected answer from the container while reading the file",
    "file.corrupted": "the file's contents arrived corrupted",
    "backup.bad_name": "invalid backup name",

    # ----------------------------------------------------------- ssh
    "ssh.failed_to_run": "could not run ssh: {reason}",
    "ssh.no_stdin": "I could not open ssh's input",
    "ssh.no_stdout": "I could not open ssh's output",
    "ssh.upload_timeout": "timed out ({seconds}s) uploading to {host}",

    # ---------------------------------------------- api http do jogo
    "http.bad_url": "invalid URL (e.g. http://127.0.0.1:8212/v1/api/players)",
    "http.auth_failed": "the API answered {status} - check the admin user and password",
    "http.bad_status": "the API answered HTTP {status}",
    "http.reply_too_big": "the API's answer is too big to be read here",
    "http.not_json": "the answer is not JSON: {sample}",
    "api.login_incomplete": "incomplete automatic login (the login URL or the token path is missing)",
    "api.no_token_at": "the login answered, but I found no token at '{path}'",
    "api.need_url": "enter the game's API URL",
    "api.need_join_pattern": "enter the pattern of the player join line",
    "api.need_query_port": "enter the server's query port (Steam query)",
    "api.action_not_published": "this server does not publish that action",
    "api.write_the_notice": "write the notice",
    "api.no_player_id": "I do not know whom to kick: the API published no identifier for this player",

    # ---------------------------------------- padrao de log e broker
    "pattern.too_long": "the {label} pattern is too long (the limit is {n} characters)",
    "pattern.invalid": "invalid {label} pattern: {reason}",
    "broker.bad_host_or_service": "the broker returned a host or service in an invalid format",
    "broker.server_not_saved": "the server was not saved",

    # -------------------------- texto dos alertas (vai para o canal)
    "alert.contact_back": "{name}: contact restored",
    "alert.lost_contact": "{name}: the panel lost contact",
    "alert.no_detail": "no detail",
    "alert.server_back": "{name}: server is running again",
    "alert.server_stopped": "{name}: server stopped running",
    "alert.game_failed": "{name}: the game crashed",
    "alert.service_is_failed": "service {service} is 'failed'",
    "alert.service_is": "service {service} is '{state}'",
    "alert.restart_loop": "{name}: the game is caught in a loop",
    "alert.systemd_restarted": "systemd restarted {service} {times}x since the last look",
    "alert.game_answering": "{name}: the game is answering again",
    "alert.game_mute": "{name}: the game is not answering",
    "alert.service_up_game_mute": "service {service} is running, but the game has not answered for",
    "alert.log_error": "{name}: error in the game log",
    "alert.disk_almost_full": "{name}: disk almost full",
    "alert.disk_detail": "{mount} at {pct}% ({used} of {total})",
    "alert.memory_almost_full": "{name}: memory almost full",
    "alert.memory_detail": "{pct}% ({used} of {total})",
    "alert.cpu_high": "{name}: high CPU usage",
    "alert.cpu_detail_one": "{pct}% on {cores} core",
    "alert.cpu_detail_many": "{pct}% on {cores} cores",
    "alert.cpu_game_part": " (game: {pct}%)",
    "alert.nobody_online": "nobody online",
    "alert.players_online_one": "{n} player online",
    "alert.players_online_many": "{n} players online",
    "alert.players_online_rough": "{n} player(s) online",
    "alert.player_joined": "{name}: {player} joined the game",
    "alert.player_left": "{name}: {player} left the game",
    "alert.joined_one": "{name}: a player connected",
    "alert.joined_many": "{name}: {n} players connected",
    "alert.left_one": "{name}: a player left",
    "alert.left_many": "{name}: {n} players left",
    "alert.restarts_total": " ({n} in total this boot)",
    "alert.mute_rounds": " {n} checks",

    # ---------------------------------------- agendamento e dias da semana
    "schedule.daily": "every day at {time}",
    "schedule.weekly": "{weekday} at {time}",
    "schedule.every_hour": "every hour",
    "schedule.every_n_hours": "every {n}h",
    "weekday.monday": "Monday",
    "weekday.tuesday": "Tuesday",
    "weekday.wednesday": "Wednesday",
    "weekday.thursday": "Thursday",
    "weekday.friday": "Friday",
    "weekday.saturday": "Saturday",
    "weekday.sunday": "Sunday",
    "weekday.on_monday": "every Monday",
    "weekday.on_tuesday": "every Tuesday",
    "weekday.on_wednesday": "every Wednesday",
    "weekday.on_thursday": "every Thursday",
    "weekday.on_friday": "every Friday",
    "weekday.on_saturday": "every Saturday",
    "weekday.on_sunday": "every Sunday",
}
