"""English catalog.

Same keys as `pt.py`; see the package docstring. A key missing here falls back to Portuguese
instead of disappearing - and `test_i18n.py` enforces parity, so that a gap is a decision
and not an oversight.
"""
from __future__ import annotations

MESSAGES: dict[str, str] = {
    # -------------------------------------------------------- navigation
    "nav.servers": "Servers",
    "nav.history": "History",
    "nav.alerts": "Alerts",
    "nav.account": "Account",
    "nav.users": "Users",
    "nav.backups": "Backups",
    "nav.backups.help": "Save copies kept in the panel",
    "archive.title": "Backups in the panel",
    "archive.intro":
        "Every save copy the panel has kept, by game — including a game whose server has already "
        "been removed. They live in <code>{dir}</code>.",
    "archive.keep": "The {n} newest copies of each game are kept.",
    "archive.keep_all": "No copy is deleted automatically.",
    "archive.none":
        "The panel has not kept any copy yet. Every new backup comes here; the older ones, which are "
        "only in the container, can be sent from the server's Backups tab.",
    "archive.restore_on": "Restore on",
    "archive.no_server":
        "No server of this game in the panel. Create the instance (or register the server) again: "
        "the copy shows up in its Backups tab, with the restore button.",
    "archive.game": "Game",
    "nav.instances": "Instances",
    "nav.instances.help": "Game instances",
    "nav.catalog": "Catalog",
    "nav.catalog.help": "Game catalog",
    "nav.add_server": "Add server",
    "nav.ssh_key": "SSH access",
    "nav.logout": "Sign out",
    "nav.more": "More",
    "prefs.theme": "Toggle light/dark theme",
    "prefs.language": "Change the interface language",
    "nav.account_of": "{name}'s account",
    "nav.main": "Main navigation",

    # ------------------------------------------------------------ roles
    "role.admin": "Administrator",
    "role.operator": "Operator",

    # ------------------------------------------------ server sections
    "server.overview": "Overview",
    "server.overview.help": "Status, players, resources and log",
    "server.config": "Configuration",
    "server.config.help": "The game settings, field by field",
    "server.mods": "Mods",
    "server.mods.help": "What mods the server loads, and send mods to it",
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

    # ------------------------------------------------------------ actions
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

    # ------------------------------------------------- base and version notice
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

    # ------------------------------------------------------------ language
    "account.language": "Language",
    "account.language.title": "Interface language",
    "account.language.changed": "Language changed.",

    # -------------------------------------------------------- dashboard
    "dashboard.no_servers": "No servers registered yet.",
    "dashboard.ssh_access": "SSH access",
    "dashboard.ask_an_admin": "Ask a panel administrator to register the server.",

    # ----------------------------------------------------- history
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

    # ----------------------------------------------------- ssh key
    "ssh_key.public_key": "Panel public key",
    "ssh_key.not_found": "Key not found. Run the panel deploy again.",
    "ssh_key.containers": "Game containers",
    "ssh_key.host_keys": "Host keys",

    # ------------------------------------------------------ charts
    "charts.no_samples": "No samples for this period yet.",
    "charts.cpu_memory": "CPU and memory",
    "charts.no_readings": "No meter readings for this period.",
    "charts.players": "Players",
    "charts.as_table": "See the numbers as a table",
    "charts.when": "When",
    "charts.cpu": "CPU",
    "charts.memory": "Memory",
    "charts.period": "Period",

    # ------------------------------------------------------- backups
    "backups.what_is_saved": "What goes into the copy",
    "backups.stored_copies": "Copies in the container",
    "backups.file": "File",
    "backups.when": "When",
    "backups.size": "Size",
    "backups.before_restore": "before restoring",
    "backups.admin_only": "download, restore and delete are admin-only",
    "backups.none_yet": "No copies yet.",
    "backups.pre_restore_copy": "Taken by the panel right before a restore",

    # -------------------------------------------------- schedules
    "schedules.tasks_here": "Tasks for this server",
    "schedules.task": "Task",
    "schedules.when": "When",
    "schedules.next_run": "Next",
    "schedules.last_run": "Last run",
    "schedules.off": "off",
    "schedules.admin_only": "only an administrator can change it",
    "schedules.none_here": "Nothing scheduled for this server.",
    "schedules.new_task": "Schedule a task",
    "schedules.what_to_do": "What to do",
    "schedules.daily": "Every day, at a fixed time",
    "schedules.weekly": "Once a week",
    "schedules.every_n_hours": "Every N hours",
    "schedules.hour": "Hour",
    "schedules.minute": "Minute",
    "schedules.weekday": "Day of the week",
    "schedules.every": "Every",
    "schedules.hours_from_now": "hours, counted from now",
    # ---------------------------------------------------- instances
    "instances.new": "New instance",
    "instances.game": "Game",
    "instances.only_installable": "Only games the broker can install on its own are listed.",
    "instances.name": "Name",
    "instances.none_creatable": "No creatable game in the catalog (or the broker did not answer).",
    "instances.game_not_listed": "Game not here? Add it to the catalog.",
    "instances.name_hint":
        "How the instance shows up in the panel. Letters, digits, space, dot, "
        "hyphen and underscore.",
    "instances.how_it_works":
        "The broker picks a free IP and ports, creates the container, installs the game and only "
        "then opens the firewall. You follow the progress on the job screen.",
    "instances.instance": "Instance",
    "instances.remove": "Remove",
    "instances.type_name_to_confirm": "Type the name to confirm",
    "instances.forget_record_only": "Forget the record only (the container no longer exists in Proxmox)",
    "instances.none_yet": "No instance created by the broker yet.",

    # ------------------------------------------------------- console
    "console.interactive": "Interactive session",
    "console.single_command": "Single command",
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

    # ------------------------------------------------------ files
    "files.download": "download",
    "files.delete": "delete",
    "files.empty_folder": "empty folder",
    "files.listing_truncated": "Listing cut at the first items of this folder.",
    "files.configuration": "Configuration",
    "files.editor": "Editor",
    "files.edit_server": "Edit server",
    "files.path_lower": "path",
    "files.file_to_upload": "file to upload",
    "files.path": "Path",

    # ------------------------------------------------- second factor
    "login_2fa.title": "Verification",
    "login_2fa.hint": "Enter the 6-digit code from your authenticator app.",
    "login_2fa.code": "Code",
    "account_2fa.copy_key": "Copy key",
    "account_2fa.six_digit_code": "6-digit code",
    "account_2fa_codes.copy_codes": "Copy codes",

    # ------------------------------------------------------ users
    "users.user": "User",
    "users.role": "Role",
    "users.created_at": "Created",
    "users.you": "you",
    "users.reset_password": "Reset password",
    "users.new_user": "New user",
    "users.initial_password": "Initial password",
    "users.confirm_password": "Confirm password",
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

    # ------------------------------------------ game configuration
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

    # --------------------------------------------------------- account
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

    # ---------------------------------------------- server screen
    "server_detail.host": "Host",
    "server_detail.access": "Access",
    "server_detail.access_helper": "unprivileged ({user})",
    "server_detail.access_legacy": "root (legacy, needs migration)",
    "server_detail.ssh_port": "SSH port",
    "server_detail.service": "Service",
    "server_detail.game_ports": "Game ports",
    "server_detail.config_folder": "Config folder",
    "server_detail.server": "Server",
    "server_detail.maintenance": "Maintenance",
    "server_detail.published_name": "Published name",
    "server_detail.world": "World",
    "server_detail.online": "Online",
    "server_detail.player": "Player",
    "server_detail.connected_for": "Connected for",
    "server_detail.score": "Score",
    "server_detail.no_identifier": "no identifier",
    "server_form.max_players": "Slots",
    "server_form.max_players_hint": (
        "The server's player limit, so the screen shows 2/6. Only used when the "
        "count does not report it (log, active connections)."),
    "form.bad_max_players": "Slots: a number from 0 to 1000.",
    "player_source.net": "active connections",
    "server_form.count_net": "Active connections on the game port (CT firewall)",
    "flash.count_on_by_net": "Player count now uses the active connections on the game port.",
    "presence.missing": (
        "This CT's firewall does not count connections yet: re-apply the firewall "
        "(deploy/firewall/apply-firewall.ps1)."),
    "presence.unreadable": "Could not read the active connections from the CT firewall.",
    "players_setup.presence_title": "Active connections on the game port",
    "players_setup.presence_help": (
        "Who is exchanging packets with the server right now, counted by the CT firewall. Meant for "
        "games with no query (Dragonwilds uses EOS): the number does not depend on the log, and the "
        "names still come from it."),
    "server_detail.names_from": "Counted by: {source}. Names by: {names_from}.",
    "server_detail.names_partial": "The names do not match the count: the list shows the most recent to join.",
    "server_detail.fallback": "The chosen source did not answer ({error}). Counting by: {source}.",
    "player_source.a2s": "A2S query",
    "player_source.http": "game API",
    "player_source.log": "server log",
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

    # --------------------------------------------- alerts - destinations
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

    # ----------------------------------------- alerts - preferences
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

    # ----------------------------------------------- alerts - daily log
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

    # ---------------------------------------- alerts - how it works
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

    # --------------------------------------------- mod manager
    "mods.no_profile":
        "This game has no mod manager yet. Mod files can go through the Files screen.",
    "mods.help_ets2":
        "In Euro Truck Simulator 2 the server <strong>loads no mod files</strong>: map, DLCs and "
        "mods come inside the <code>server_packages</code>, exported from the GAME with the mods "
        "active in the profile (console, with the map loaded: <code>export_server_packages</code>). "
        "Every player needs the SAME mods. Changed the list? Export and upload the packages again.",
    "mods.help_unreal_linux":
        "The server's <code>.pak</code> mods live in <code>{folder}</code>. Visual-only mods are "
        "client-side; gameplay mods must be here AND, usually, on the players too. Script mods "
        "(UE4SS) run through the official UE4SS built for Linux, below: Lua mods live in the "
        "<code>ue4ss/Mods</code> folder next to the game's executable. Installing generates this "
        "server's files (every game's engine carries the studio's changes); after a game update, "
        "install again.",
    "mods.help_palworld":
        "The server's <code>.pak</code> mods live in <code>{folder}</code>. Visual-only mods are "
        "client-side; gameplay mods must be here AND, usually, on the players too. Script mods "
        "(UE4SS) run through the official UE4SS built for Linux, below: Lua mods live in the "
        "<code>ue4ss/Mods</code> folder next to the game's executable.",
    "mods.packages_title": "What the server loads",
    "mods.no_packages":
        "No packages in <code>{folder}</code> yet: export them from the game and upload "
        "<code>server_packages.sii</code> and <code>server_packages.dat</code> below.",
    "mods.packages_unreadable": "The server's server_packages.sii could not be read as text.",
    "mods.summary": "Map {map} - {dlcs} DLCs - {n} mods",
    "mods.col_mod": "Mod",
    "mods.col_origin": "Source",
    "mods.workshop": "Workshop",
    "mods.manual": "installed by hand (outside the Workshop)",
    "mods.optional": "optional",
    "mods.players_list_title": "Links for the players",
    "mods.players_list_help":
        "Copy and send to whoever is going to play: these are the Workshop mods the server uses. "
        "Mods installed by hand (like a map downloaded from a website) are not here.",
    "mods.expected_title": "Mods the server should have",
    "mods.missing": "{n} mods from the list are missing from the server packages:",
    "mods.missing_help":
        "They were not active in the profile of whoever exported. Enable them in the game, export "
        "again and upload the packages.",
    "mods.all_present": "Every mod on the list is in the server packages.",
    "mods.extra": "On the server but not on the list: {names}",
    "mods.expected_label": "Workshop links or IDs, one per line",
    "mods.expected_help":
        "You can paste the chat as it came (with time and name in front): the panel finds the id= "
        "on each line.",
    "mods.expected_save": "Save list",
    "mods.expected_saved": "List saved: {n} mods.",
    "mods.files_title": "Mods on the server",
    "mods.no_files": "No mods in the folder yet.",
    "mods.delete": "Remove",
    "mods.delete_confirm": "Remove {name} from the server?",
    "mods.upload_title": "Upload to the server",
    "mods.files_to_send": "Files",
    "mods.upload_accepts":
        "Accepts {allowed}. Goes to {folder}; a file with the same name is replaced (a .bak copy "
        "is kept).",
    "mods.restart_after": "Restart the server afterwards (mods only load when it starts again)",
    "mods.upload_button": "Upload",
    "mods.help_vrising":
        "V Rising mods come from <strong>Thunderstore</strong> and run on <strong>BepInEx</strong>, "
        "which must be installed and enabled on the server. The panel downloads everything FROM "
        "INSIDE the container. A server mod only needs to be here; if a mod touches the client, "
        "each player installs their own.",
    "mods.status_failed": "Could not read the server mods: {reason}",
    "mods.not_thunderstore": "This server does not use Thunderstore mods.",
    "mods.overlay_problem":
        "The loader setting would not reach the game on this server (accessed without root): {reason}",
    "mods.bad_package":
        "Package not recognised. Paste the link to its Thunderstore page, or author/package.",
    "mods.loader_title": "BepInEx (mod loader)",
    "mods.loader_on": "on",
    "mods.loader_off": "off",
    "mods.loader_missing": "BepInEx is not installed on this server yet.",
    "mods.loader_install": "Install BepInEx",
    "mods.loader_update": "Reinstall / update",
    "mods.loader_enable": "Enable",
    "mods.loader_disable": "Disable (the server starts without mods)",
    "mods.loader_uninstall": "Uninstall",
    "mods.loader_uninstall_confirm":
        "Uninstall {name}? It leaves the server together with the mods that depend on it, and the "
        "game goes back to the original. The .pak files in the game folder stay. Install again to undo.",
    "mods.overrides_bad":
        "The Wine setting BepInEx needs was undone (a game redeploy rewrites that file). Install "
        "BepInEx again to reapply it.",
    "mods.low_memory":
        "This server has {have} MB of memory, and the first start with BepInEx needs about "
        "{need} MB (measured: 9.4 GB). With less, the server keeps dying out of memory. Raise the "
        "container memory before installing.",
    "mods.loader_first_run":
        "The first start after installing BepInEx takes several minutes: it generates the game "
        "code before opening the server. The following ones are normal.",
    "mods.plugins_title": "Mods (plugins)",
    "mods.col_version": "Version",
    "mods.plugin_add_label": "Install a Thunderstore mod",
    "mods.plugin_add_help":
        "Link to the mod page, or author/package (e.g. deca/VampireCommandFramework). "
        "Dependencies come along. Without a version you get the newest; with one (in the field "
        "below or in the pasted name, deca-VampireCommandFramework-0.11.0) you get that one, "
        "with dependencies at the versions it asks for.",
    "mods.version_label": "Version (optional)",
    "mods.version_help": "Empty = the newest. E.g. 1.2.3",
    "mods.bad_version": "Invalid version. Use numbers like 1.2.3, or leave it empty for the newest.",
    "mods.pinned": "pinned version",
    "mods.change_version_title": "Change the version of an installed mod",
    "mods.change_version_help":
        "The chosen version fully replaces the installed one, along with the dependencies it "
        "asks for (a dependency shared with another mod may go back to an older version). The "
        "mod's config is kept. Empty updates to the newest.",
    "mods.change_version_button": "Change version",
    "mods.antivirus_note":
        "Every mod goes through the <strong>antivirus (ClamAV)</strong> inside the container "
        "before it reaches the game; if it finds something, or cannot scan, the mod is NOT "
        "installed and the server does not restart. The first time, the container installs "
        "ClamAV (a few extra minutes). It catches what is already known: keep downloading "
        "only from sources you trust.",
    "mods.audit_button": "Scan installed mods",
    "mods.audit_help":
        "Runs the antivirus over what is already installed on this server, including what came "
        "in before scanning existed. Read-only: nothing is deleted, and the result is in the "
        "task log. Uses about 1 GB of memory for a few seconds, next to the game.",
    "mods.plugin_install": "Install",
    "mods.where_to_find": "Where to find mods",
    "mods.source_workshop": "Steam Workshop",
    "mods.source_nexus": "Nexus Mods",
    "mods.source_thunderstore": "Thunderstore",
    "mods.source_shroudtopia": "Shroudtopia (loader)",
    "mods.help_dragonwilds":
        "Server mods are <strong>.pak</strong> files (with the same-named <code>.utoc</code> and "
        "<code>.ucas</code> that Unreal 5 requires - send all three together) and live in "
        "<code>{folder}</code>. Script mods (UE4SS) run through the official UE4SS built for Linux, "
        "below; the game flags the session as modded while it is on. Nexus Mods does not allow "
        "automated downloads without a Premium account: download "
        "there and upload here. Each mod page says whether players need it too.",
    "mods.help_enshrouded":
        "Enshrouded mods need a <strong>loader</strong> on the server: Shroudtopia, which the panel "
        "downloads from GitHub and places next to <code>enshrouded_server.exe</code>. Mods are DLLs "
        "(Nexus Mods) that go into <code>{folder}</code>. Proven on a real server under Proton. "
        "Each mod page says whether it is server-only or for the players too.",
    "mods.shroudtopia_title": "Shroudtopia (mod loader)",
    "mods.shroudtopia_missing": "Shroudtopia is not installed on this server yet.",
    "mods.shroudtopia_install": "Install Shroudtopia",
    "mods.shroudtopia_log": "End of the loader log",
    "mods.shroudtopia_log_help":
        "A mod built for another game version does not bring the server down, but "
        "silently loses its feature: it shows up here as \"not found\".",
    "mods.shroudtopia_config_help":
        "The example mods in the official package are NOT installed: they come with "
        "cheats turned on. Each mod's options live in <code>shroudtopia.json</code>, "
        "on the <a href=\"{url}\">Files screen</a>.",
    "mods.help_icarus":
        "Icarus script mods run on <strong>UE4SS</strong>, which the panel downloads from GitHub and places "
        "next to <code>IcarusServer-Win64-Shipping.exe</code>. Mods live in <code>{folder}</code>, "
        "one folder per mod.",
    "mods.ue4ss_title": "UE4SS (mod loader)",
    "mods.ue4ss_missing": "UE4SS is not installed on this server yet.",
    "mods.ue4ss_install": "Install UE4SS",
    "mods.ue4ss_log": "End of the UE4SS log",
    "mods.ue4ss_config_help":
        "Installed with no console and without its bundled cheat mods: only the blueprint mod "
        "loaders stay on. Each mod is a folder in <code>{folder}</code>, switched on in the "
        "<code>mods.txt</code> of that folder, on the <a href=\"{url}\">Files screen</a>.",
    "mods.source_ue4ss": "UE4SS (loader)",
    "mods.not_proven":
        "This installer has NOT been tested on a real server yet. Back up the world first (Backups "
        "screen) and check the server after installing.",
    "mods.help_satisfactory":
        "Satisfactory mods run on <strong>SML</strong> (Satisfactory Mod Loader). The panel "
        "downloads the Linux server package of each mod and its dependencies from ficsit.app, "
        "checks the sha256 and the antivirus, and puts each one in a folder in <code>{folder}</code>. "
        "Every player needs the SAME mods in the game (through the Satisfactory Mod Manager).",
    "mods.help_valheim":
        "Valheim mods run on <strong>BepInEx</strong>, installed from Thunderstore. On a Linux "
        "server it is loaded by systemd variables (a drop-in), without changing the start script.",
    "mods.help_rust":
        "Rust plugins run on <strong>Oxide</strong> (uMod). It OVERWRITES game files, and the panel "
        "keeps the originals so it can be switched off. <strong>Every Rust update wipes "
        "Oxide</strong>: reinstall after updating. Plugins are <code>.cs</code> files in "
        "<code>{folder}</code>, and load without a restart.",
    "mods.sml_title": "SML (Satisfactory Mod Loader)",
    "mods.sml_missing": "SML is not installed yet. It also comes on its own with the first mod.",
    "mods.sml_install": "Install SML",
    "mods.sml_mod_label": "Install a mod from ficsit.app",
    "mods.sml_mod_help": (
        "The mod reference (RefinedPower) or the link to its ficsit.app page. Dependencies come "
        "along."),
    "mods.sml_bad_ref": "Could not recognise the mod: use the reference (RefinedPower) or a ficsit.app/mod/... link",
    "mods.oxide_title": "Oxide (plugin loader)",
    "mods.oxide_missing": "Oxide is not installed on this server yet.",
    "mods.oxide_install": "Install Oxide",
    "mods.oxide_wiped": "Some Oxide files were replaced (was Rust updated?): reinstall.",
    "mods.oxide_log": "End of the Oxide log",
    "mods.source_ficsit": "ficsit.app",
    "mods.source_reforger_workshop": "Arma Reforger Workshop",
    "mods.help_workshop_dst":
        "In Don't Starve Together the <strong>server itself</strong> downloads the mods from the Steam "
        "Workshop when it starts. The panel writes the list to <code>dedicated_server_mods_setup.lua</code> "
        "(what to download) and to each shard's <code>modoverrides.lua</code> (what to enable); the "
        "options you already gave a mod are kept. Players get the mods automatically when they join.",
    "mods.help_workshop_zomboid":
        "In Project Zomboid the <strong>server itself</strong> downloads the mods from the Steam "
        "Workshop when it starts. There are two lists in the server <code>.ini</code>: Workshop IDs "
        "(what to download) and mod IDs (what to enable). One Workshop item can carry several mods: "
        "once downloaded, the screen shows which ones it brought.",
    "mods.help_workshop_unturned":
        "In Unturned the <strong>server itself</strong> downloads the mods from the Steam Workshop "
        "when it starts, through the server folder's <code>WorkshopDownloadConfig.json</code>. Maps "
        "and mods come with their dependencies. The game command needs "
        "<code>+InternetServer/&lt;name&gt;</code>.",
    "mods.help_workshop_reforger":
        "In Arma Reforger the <strong>server itself</strong> downloads the mods from the Bohemia "
        "workshop when it starts, through the <code>game.mods</code> list of the JSON passed with "
        "<code>-config</code>. The ID is the 16-character GUID on the mod page. A version pinned by "
        "hand in the config is kept.",
    "mods.workshop_antivirus_note":
        "Here the antivirus does NOT check first: the game server does the download when it starts. "
        "Use <strong>Scan installed mods</strong> afterwards, which runs ClamAV on the folder where "
        "the game keeps what it downloaded.",
    "mods.workshop_title": "Workshop mods",
    "mods.workshop_config": "Config: <code>{path}</code>",
    "mods.workshop_problem_no_cluster":
        "No cluster with a server.ini: start the server once so it creates its configuration.",
    "mods.workshop_problem_no_config":
        "The server config does not exist yet: start the server once so it creates it.",
    "mods.workshop_problem_no_server_name":
        "No server name: add +InternetServer/<name> to the game command (Edit screen) and start it once.",
    "mods.workshop_problem_no_config_arg":
        "The server does not get -config in its command: create config.json and pass -config in the "
        "game command (Edit screen).",
    "mods.workshop_problem_bad_json": "The server config is not valid JSON: fix it on the Files screen.",
    "mods.workshop_dst_setup_missing":
        "These mods are missing from dedicated_server_mods_setup.lua (a game update rewrites it) and "
        "will not be downloaded: save the list again. {ids}",
    "mods.workshop_zomboid_found": "Mods in this item: {mods}",
    "mods.workshop_downloaded": "downloaded",
    "mods.workshop_pending": "downloads on next start",
    "mods.workshop_ids_label": "Mods (one per line)",
    "mods.workshop_ids_help":
        "The mod page link on the Steam Workshop, or just the number. Removing a line removes the mod.",
    "mods.workshop_reforger_help":
        "The mod page link on the Reforger workshop, or the GUID followed by the name. Removing a line "
        "removes the mod.",
    "mods.zomboid_mods_label": "Enabled mods (Mods=)",
    "mods.zomboid_mods_help":
        "Mod IDs separated by semicolons, as listed on this screen after the download.",
    "mods.workshop_save": "Save the list",
    "mods.help_workshop_ark":
        "In ARK: Survival Ascended the <strong>server itself</strong> downloads the mods from "
        "CurseForge when it starts. The list goes into the server command (<code>-mods=</code>), "
        "through a systemd override the panel writes; the game ignores <code>ActiveMods</code> in "
        "GameUserSettings.ini. Every player needs the same mods.",
    "mods.help_workshop_conan":
        "Conan Exiles' server <strong>does not download any mod</strong>: the container downloads "
        "each item from the Steam Workshop, the antivirus checks it, and only then do the files go "
        "into <code>ConanSandbox/Mods</code>, in list order (the <code>modlist.txt</code>). Use the "
        "items marked Enhanced: the old (Legacy) ones are ignored, and a mod outdated for the game "
        "version keeps the server from starting.",
    "mods.source_curseforge": "CurseForge",
    "mods.workshop_ark_help":
        "The mod's CurseForge Project ID (the number on the side of the mod page), one per line. "
        "Removing a line removes the mod.",
    "mods.workshop_ark_base_changed":
        "The server command changed after the mod list was saved (a redeploy?): the server still "
        "starts with the old command. Save the list again to use the new one.",
    "mods.workshop_conan_modlist_off":
        "ServerModList is off in ServerSettings.ini: the mods do not load. Save the list again to "
        "turn it back on.",
    "mods.workshop_rejected": "The server refused this mod: {reason}",
    "mods.workshop_rejected_badge": "refused",
    "mods.workshop_refresh":
        "Download every mod again (to pick up their updates after a game update)",
    "mods.workshop_problem_root_dropin":
        "The mod list was written as root before this server was migrated, and it cannot be changed "
        "without root. Run deploy/game/migrate-ct.ps1 again on this CT: it converts the list.",
    "mods.workshop_problem_no_win_run":
        "The server command does not go through win-run, which is how the list reaches the game without root.",
    "mods.workshop_problem_no_overlay":
        "This CT was not prepared for mods without root yet: run deploy/game/migrate-ct.ps1 again on it.",
    "mods.workshop_problem_no_unit":
        "The server command was not found in systemd: check the service name on the Edit screen.",
    "mods.workshop_bad_ids": "No mod ID found in what was pasted: nothing was changed.",
    "mods.zomboid_bad_mods": "The Mods= list only takes letters, digits, _ . - and semicolons.",
    "mods.source_umod": "uMod (plugins)",
    "mods.ue4ss_linux_config_help":
        "Linux port of UE4SS, loaded by LD_PRELOAD on the service, with no "
        "console or window. Each mod is a folder in <code>{folder}</code>, switched on in the "
        "<code>mods.txt</code> there, on the <a href=\"{url}\">Files screen</a>. Lua or Linux "
        "<code>.so</code> mods only: Windows <code>.dll</code> mods do not load.",
    "mods.source_ue4ss_linux": "UE4SS for Linux (tested games)",
    "mods.ue4ss_release":
        "Pinned UE4SS for Linux version: {tag}. If the server ships a .sym, the game's layout is "
        "generated from it on every install - after a game update, install again.",
    "mods.ue4ss_old_layout":
        "The old UE4SS install (the previous fork) is still next to the executable: install again "
        "to move the Lua mods into the ue4ss/ folder and remove its files.",
    "mods.bad_name": "{name} is not accepted here. Expected: {allowed}.",
    "mods.folder_mod": "folder (whole mod)",
    "mods.remove_selected": "Remove the ticked ones",
    "mods.remove_selected_confirm":
        "Remove the ticked mods from the server? This cannot be undone: to bring one back, upload it "
        "again.",
    "mods.remove_none_selected": "Tick at least one mod to remove.",
    "mods.remove_too_many": "At most {n} mods at a time.",
    "mods.bad_lua_name": "{name} is not the name of a Lua mod that can be removed here.",
    "mods.lua_title": "Lua mods (UE4SS)",
    "mods.lua_remove_help":
        "Removing deletes the mod's folder and its line in mods.txt; the rest of mods.txt stays as it "
        "is.",
    "mods.iostore_remove_help":
        "An Unreal 5 mod comes in three files with the same name (.pak, .utoc and .ucas): ticking one "
        "of them removes all three.",
    "mods.help_custom":
        "Manual setup: the panel downloads the loader from the link you gave, unpacks it where you "
        "said and receives mods in <code>{folder}</code>.",
    "mods.custom_warning":
        "Manual setup: the panel has no way of knowing whether this loader works with this game. It "
        "only downloads, runs the antivirus, unpacks and removes what it installed - if the server "
        "does not start, uninstall the loader.",
    "mods.custom_setup_title": "Manual mod setup",
    "mods.custom_setup_help":
        "For a game the panel does not know: the link to the loader (mod manager), the folder it goes "
        "in and the folder mods live in. Folders are relative to the game folder (/opt/game).",
    "mods.custom_url_label": "Loader link (optional)",
    "mods.custom_url_help":
        "https only. A .zip, a .tar.gz or a single file (a DLL). Empty = the game needs no loader, "
        "just the mods folder.",
    "mods.custom_loader_dir_label": "Loader folder",
    "mods.custom_loader_dir_help":
        "Where the package is unpacked, relative to the game folder (usually the executable's). Empty "
        "= the game folder itself.",
    "mods.custom_mods_dir_label": "Mods folder",
    "mods.custom_mods_dir_help": "Where uploaded mods go, relative to the game folder. E.g. BepInEx/plugins",
    "mods.custom_ext_label": "Accepted extensions",
    "mods.custom_ext_help":
        "Separated by spaces. Scripts and executables (.sh, .so, .exe...) never get in. Empty goes "
        "back to the default.",
    "mods.custom_env_title": "Game environment (optional)",
    "mods.custom_wine_label": "Wine overrides",
    "mods.custom_wine_help":
        "For Windows loaders (Proton/Wine): entries like winhttp=n,b, separated by spaces. They are "
        "added when the loader is installed and taken out when it is uninstalled.",
    "mods.custom_preload_label": "LD_PRELOAD",
    "mods.custom_preload_help":
        "For Linux loaders: the loader's .so library, relative to the game folder. Added when the "
        "loader is installed and taken out when it is uninstalled.",
    "mods.custom_save": "Save the setup",
    "mods.custom_saved": "Mod setup saved.",
    "mods.custom_clear": "Delete the setup",
    "mods.custom_clear_confirm":
        "Delete the manual setup? Nothing is deleted on the server: uninstall the loader first if you "
        "want it gone.",
    "mods.custom_cleared": "Mod setup deleted.",
    "mods.custom_bad_url": "The loader link must be a valid https:// address (up to 500 characters).",
    "mods.custom_bad_loader_dir":
        "Invalid loader folder: use a path relative to the game folder, with no .. and no leading /.",
    "mods.custom_bad_mods_dir":
        "Invalid mods folder: it is required, relative to the game folder, with no .. and no leading "
        "/.",
    "mods.custom_bad_ext": "Invalid extensions: use up to 16, like .pak .dll .lua.",
    "mods.custom_blocked_ext": "{ext} is not accepted as a mod (these never get in: {blocked}).",
    "mods.custom_bad_wine": "Invalid Wine overrides: use up to 8 entries like winhttp=n,b, one per DLL.",
    "mods.custom_bad_preload":
        "Invalid LD_PRELOAD: a .so file relative to the game folder, with letters, digits, _ . + - "
        "only",
    "mods.custom_overlay_needs_helper":
        "Wine overrides and LD_PRELOAD only work with the server in rootless mode (gamepanel login): "
        "migrate the CT or leave those fields empty.",
    "mods.custom_overlay_needs_loader":
        "Wine overrides and LD_PRELOAD come in with the loader: fill in its link.",
    "mods.custom_builtin_wins":
        "This game already has its own mod manager in the panel: the manual setup does not apply.",
    "mods.custom_loader_title": "Loader (manual setup)",
    "mods.custom_loader_missing": "The loader is not installed on this server yet.",
    "mods.custom_no_loader": "No loader: mods go straight into the mods folder.",
    "mods.custom_loader_install": "Install the loader",
    "mods.custom_installed": "installed",
    "mods.custom_installed_files": "{n} file(s) installed by the panel - sha256 {sha}...",
    "mods.custom_incomplete":
        "The last install stopped halfway: what got in is recorded. Reinstall or uninstall.",
    "mods.custom_uninstall_confirm":
        "Uninstall the loader? Only what the panel installed goes (and the folders it created, with "
        "whatever is in them), plus the environment settings.",
    "mods.custom_mods_folder": "Mods folder: <code>{folder}</code>",
    "mods.source_custom_loader": "Loader (configured link)",

    # --------------------------------------------- game catalog
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
        "or its own installer is still created by <code>deploy-game.ps1</code>.",
    "catalog.add_game": "Add game",
    "catalog.data_only":
        "Data only: the broker <strong>accepts no commands</strong>. Anything needing a special "
        "install (Wine, Proton, a Steam symlink) goes in through the recipes below.",
    "catalog.search_game": "Search for a game",
    "catalog.by_name_or_app_id": "(name or App ID)",
    "catalog.search_hint":
        "Fills in App ID, ports and start command from LinuxGSM, the Pterodactyl eggs and a "
        "panel list. It is only a suggestion: check it before submitting.",
    "catalog.start_from_template": "Start from a template",
    "catalog.blank": "Blank",
    "catalog.template_hint":
        "Search can't find the game? Pick its engine: the template fills in ports, paths, "
        "arguments and the log pattern in one go.",
    "catalog.search_filled": "fields filled in. Check them before submitting.",
    "catalog.search_in_catalog": "already in the catalog",
    "catalog.search_none":
        "No suggestion for that name. Start from a template below (by the game's engine) and "
        "look up the dedicated server App ID and the ports:",
    "catalog.search_steamdb": "App ID on SteamDB",
    "catalog.search_web_ports": "Ports on the web",
    "catalog.search_failed": "Could not search:",
    "catalog.recipes_hint":
        "Windows-only server: tick <strong>proton</strong> (preferred; <strong>wine</strong> only "
        "if Proton does not work), <strong>xvfb</strong> if it opens a window on start and "
        "<strong>vulkan</strong> if it crashes in Direct3D 12 without a graphics card.",
    "catalog.template.unreal_linux": "Unreal Engine (native Linux server)",
    "catalog.template.unreal_linux_help":
        "Palworld, Satisfactory, Dragonwilds and most Unreal games with a Linux build. Replace "
        "{project} with the project folder (the one under /opt/game after installing) and enter "
        "the dedicated server App ID.",
    "catalog.template.unreal_windows": "Unreal Engine (Windows only, via Proton)",
    "catalog.template.unreal_windows_help":
        "Unreal server without a Linux build (Icarus, Abiotic Factor, Conan). Replace {project} "
        "with the project folder in the paths and in the Shipping executable, which is the one "
        "that opens the port.",
    "catalog.template.unity_linux": "Unity (native Linux server)",
    "catalog.template.unity_linux_help":
        "Replace {executable} with the .x86_64 executable at the game root. Check the game's "
        "guide for how it takes the port: Unity has no standard argument for it.",
    "catalog.template.unity_windows": "Unity (Windows only, via Proton)",
    "catalog.template.unity_windows_help":
        "Unity server without a Linux build (V Rising, Sons of the Forest). Replace {executable} "
        "with the .exe at the root. Comes with a virtual X (xvfb): Unity servers often open a "
        "window on start.",
    "catalog.template.source": "Source / srcds (Valve)",
    "catalog.template.source_help":
        "Valve games and mods (srcds_run). Replace {mod} with the game folder (cstrike, tf, "
        "garrysmod) and MAPA with a map that exists.",
    "catalog.key": "Key",
    "catalog.key_example": "mygame",
    "catalog.key_hint": "Lowercase, digits and hyphen. It becomes the container and service name.",
    "catalog.name": "Name",
    "catalog.name_example": "My Game",
    "catalog.app_id": "Dedicated server App ID (Steam)",
    "catalog.client_app_id": "Game App ID (client)",
    "catalog.client_app_id_hint":
        "Only for a Windows server without a <code>steam_appid.txt</code> next to the executable "
        "(Conan Exiles: 440900). Without it the server answers Steam with appid 0 and does not "
        "show up in the game's server list. Blank for most games.",
    "catalog.suggestion.ark_ascended.vulkan":
        "Even headless, the server creates a Direct3D 12 device: without the virtual X (xvfb) and"
        " the software Vulkan driver (vulkan) it crashes on start.",
    "catalog.suggestion.conan_exiles.xvfb_appid":
        "Without the virtual X (xvfb) the server hangs right after mounting the game files. The "
        "client App ID (440900) is what makes it show up in the server list.",
    "catalog.app_id_hint": "The <strong>dedicated server</strong> one, not the game's. Check SteamDB.",
    "catalog.ports_hint": "Port/protocol, separated by a space. Below 1024 is not allowed.",
    "catalog.game_port": "Game port",
    "catalog.query_port": "Query port",
    "catalog.extra_port": "Extra port",
    "catalog.example": "e.g. {value}",
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
    "catalog.windows_needs_wine": "Windows (needs Proton or Wine)",
    "catalog.log_join_line": "Log: join line",
    "catalog.log_leave_line": "Log: leave line",
    "catalog.install_recipes": "Install recipes",
    "catalog.broker_picks_ports": "The broker assigns the ports (several instances of the same game)",
    "catalog.broker_picks_ports_hint":
        "Only check this if the game takes its ports from the arguments: the start arguments must "
        "contain {PORT} (plus {QUERY_PORT} and {EXTRA_PORT}, if there is a query port and an extra "
        "port) and the game may have only those three ports.",
    "catalog.key_fixed_hint":
        "The key cannot change: it is the game's name in the broker. To change it, delete and add "
        "again.",
    "catalog.edited": "edited",
    "catalog.edited_help": "The data was edited in the panel and overrides the games/*.env file from the repository.",
    "catalog.edit": "Edit",
    "catalog.delete": "Delete",
    "catalog.delete_confirm": "Delete {name} from the catalog? Instances already created stay.",
    "catalog.undo_edit": "Undo edit",
    "catalog.undo_edit_confirm": "Discard the edit of {name} and go back to the repository file?",
    "catalog.edit_title": "Edit {name}",
    "catalog.curated_edit_note": (
        "<strong>Curated</strong> game: the edit is stored in the broker, on top of "
        "<code>games/{game}.env</code>. The install commands are still the file's; "
        "to go back to it, use <strong>Undo edit</strong> in the catalog."),
    "catalog.edit_instances_note": "Applies to the next instances. The ones already created do not change.",
    "catalog.save": "Save",
    "catalog.add_to_catalog": "Add to the catalog",

    # ------------------------------------------ server registration
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

    # ------------------------------------------ titles and components
    # ------------------------- error page and permission barrier
    "error.csrf_invalid": "Invalid or expired CSRF token — reload the page.",
    "error.terminal_session_gone": "Terminal session expired or closed.",
    "error.terminal_bad_input": "Invalid input.",
    "error.terminal_bad_size": "Invalid size.",
    "error.download_too_large":
        "File of {size} bytes is over the download limit ({limit} bytes) — use scp for this one.",
    "error.not_found": "Page not found.",
    "error.admin_only": "This screen is for panel administrators only.",
    "error.job_admin_only": "This record belongs to an action restricted to panel administrators.",
    "error.terminal_disabled": "The terminal is turned off (GAMEPANEL_ALLOW_SHELL=0).",
    "error.terminal_no_pty": "Terminal unavailable: this system has no PTY.",
    "error.console_disabled": "The console is turned off (GAMEPANEL_ALLOW_SHELL=0).",
    "error.files_disabled": "The file editor is turned off (GAMEPANEL_ALLOW_FILES=0).",
    "error.broker_disabled": "The broker is turned off on this panel (GAMEPANEL_ALLOW_BROKER=0).",
    "error.operator_reads_registered_only":
        "An operator can only open the config files already registered on this server.",
    "error.operator_saves_registered_only":
        "An operator can only save the config files already registered on this server.",
    "error.upload_too_large":
        "File too large to upload (limit of {limit}). To send a bigger one, raise the panel's "
        "GAMEPANEL_UPLOAD_MAX — after checking there is that much free space in the panel "
        "container.",
    "error.content_too_large": "Content too large (the editor takes up to {kb} KB per file).",

    # ------------------------------------- form validation
    "flash.server_duplicate": "There is already a server registered at {host}.",
    "flash.username_invalid":
        "Invalid username: use 1 to 32 characters among lowercase letters, digits, '-' and '_', "
        "starting with a letter or '_'.",
    "flash.role_invalid": "Invalid role.",
    "flash.schedule_pick_action": "Pick what the task should do.",
    "flash.schedule_pick_kind": "Pick when the task should run.",
    "flash.schedule_bad_time": "Invalid time (use hour 0-23 and minute 0-59).",
    "flash.schedule_bad_interval": "Invalid interval (from 1 to {max} hours).",
    "account_2fa.qr_label": "Two-step verification QR code",

    "error.title": "Error {code}",
    "job.title": "Action #{id}",
    "account_2fa_codes.title": "Recovery codes",
    "players_setup.title": "Player count",
    "server.sections_of_this_server": "Sections of this server",
    "server.measuring": "measuring resources...",
    "server.server": "Server",

    # -------------------------------- button labels and confirmation
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
    "instances.deactivate_confirm":
        "Turn off {name}? The save is copied to the panel first; then "
        "the server will be STOPPED and the ports close on the firewall.",
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

    # ---------------------------------------- player count
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

    # --------------------------------------------- alert events
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

    # ----------------------------------- action names in the history
    "job.shell": "Command in the container",
    "job.terminal": "Interactive terminal",
    "job.file_saved": "File saved",
    "job.file_deleted": "File deleted",
    "job.config_changed": "Configuration changed",
    "job.file_downloaded": "File downloaded",
    "job.mod_loader": "Mod loader",
    "job.mod_installed": "Mod installed",
    "job.mod_workshop": "Workshop mod list changed",
    "job.mod_audited": "Mods scanned (antivirus)",
    "job.mod_removed_plugin": "Mod uninstalled",
    "job.mod_uploaded": "Mod uploaded",
    "job.mod_deleted": "Mod removed",
    "job.mod_setup": "Manual mod setup changed",
    "job.file_uploaded": "File uploaded",
    "job.backup": "Backup",
    "job.backup_restored": "Backup restored",
    "job.backup_deleted": "Backup deleted",
    "backups.stored_both_html":
        "Stored as <code>.tar.gz</code> in <code>{dir}</code>, inside the container itself, "
        "and a second copy goes to the panel.",
    "backups.panel_copies": "Copies in the panel",
    "backups.panel_copies_help":
        "They stay in the panel even if the server or the instance is removed. A new server of the "
        "same game sees these copies and can restore from them.",
    "backups.panel_keep": "The {n} newest stay; older ones go away on their own.",
    "backups.panel_keep_all": "No copy is deleted automatically.",
    "backups.panel_none":
        "No copy in the panel yet. The next backups come here on their own; the older ones in the "
        "container can be sent with the \"send to panel\" button.",
    "backups.in_panel": "in panel",
    "backups.in_panel_title": "This file already has a copy in the panel",
    "backups.send_to_panel": "send to panel",
    "backups.panel_restore_confirm":
        "Restore {file} (panel copy) on {server}? The server will be STOPPED, the copy goes back to "
        "the container and replaces the current save. A safety copy is taken first.",
    "backups.panel_delete_confirm":
        "Delete {file} from the panel? If the "
        "container is gone, this may be the only copy.",
    "instances.installing": "Installation in progress",
    "instances.installing_help":
        "The creation goes on even if you leave "
        "this screen; the log shows which step it is on.",
    "instances.view_log": "View log",
    "instances.cancel_install": "Cancel installation",
    "instances.cancel_confirm":
        "Cancel the installation of {name}? The container created so far will be DELETED and the IP, "
        "the CT and the ports become free again.",
    "instances.confirm_title": "Confirm the new instance",
    "instances.confirm_intro":
        "Checked just now on Proxmox and OPNsense. Nothing is reserved yet: if another creation "
        "happens before you confirm, the numbers may change.",
    "instances.confirm_game": "Game",
    "instances.confirm_name": "Name",
    "instances.confirm_ct": "Container (CT)",
    "instances.confirm_ip": "IP",
    "instances.confirm_ports": "Ports",
    "instances.confirm_create": "Create now",
    "instances.back": "Back",
    "flash.install_cancelling":
        "Cancellation requested: the installation stops "
        "and the container is deleted. Follow it in the log.",
    "flash.install_already_finished": "This installation has already finished; there is nothing to cancel.",
    "instances.deactivate_no_backup": "Turn off without backup",
    "instances.deactivate_no_backup_confirm": "Turn off {name} WITHOUT copying the save to the panel?",
    "instances.panel_copies": "Save copies in the panel: {n} (newest on {when}).",
    "instances.panel_copies_none": "No save copy in the panel: removing deletes the game for good.",
    "flash.panel_backup_deleted": "Copy {file} deleted from the panel.",
    "flash.deactivate_without_backup":
        "This instance has no panel server with backup paths: it was turned off WITHOUT a save copy.",
    "job.backup_sent_to_panel": "Backup sent to the panel",
    "job.player_action": "Action on a player",
    "job.instance_created": "Instance created (broker)",
    "job.instance_deactivated": "Instance turned off (broker)",
    "job.instance_removed": "Instance removed (broker)",
    "job.game_edited": "Catalog game edited",
    "job.game_removed": "Catalog game deleted (or edit undone)",
    "job.game_added": "Game added to the catalog",
    "player_action.announce": "Announce to everyone",
    "player_action.kick": "Kick",
    "player_action.ban": "Ban",

    # ---------------------------------------- flash messages
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
    "flash.game_updated": "Game {name} updated.",
    "flash.game_restored": "Edit of {name} undone: the repository file applies again.",
    "flash.game_removed": "Game {name} deleted from the catalog.",
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

    # --------------------------------- server registration errors
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

    # -------------------------------------------------- A2S query
    "a2s.truncated": "the server's answer ended sooner than expected",
    "a2s.unterminated_text": "unterminated text in the answer",
    "a2s.split_incomplete": "the split answer arrived incomplete",
    "a2s.split_unknown": "split answer in an unknown format (compressed?)",
    "a2s.unexpected_reply": "unexpected answer from the server (type {kind})",
    "a2s.no_reply": "no answer within {seconds}s on port {port}/udp",
    "a2s.query_failed": "could not query {host}:{port} - {reason}",

    # -------------------------------- path and file in the container
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

    # ---------------------------------------------- game http api
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

    # ---------------------------------------- log pattern and broker
    "pattern.too_long": "the {label} pattern is too long (the limit is {n} characters)",
    "pattern.invalid": "invalid {label} pattern: {reason}",
    "broker.bad_host_or_service": "the broker returned a host or service in an invalid format",
    "broker.server_not_saved": "the server was not saved",

    # -------------------------- alert text (goes to the channel)
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

    # ---------------------------------------- scheduling and weekdays
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
    "passkey.sign_in": "Sign in with biometrics",
    "passkey.title": "Device biometrics",
    "passkey.hint": (
        "Sign in with your phone's fingerprint, face or PIN, without typing the password. It "
        "counts as password and code together: register only devices that are yours."),
    "passkey.created": "added on {when}",
    "passkey.last_used": "used on {when}",
    "passkey.remove": "Remove",
    "passkey.remove_confirm": "Remove \"{name}\"? This device will no longer sign in with biometrics.",
    "passkey.add": "Register this device",
    "passkey.label": "Device name",
    "passkey.label_example": "e.g. phone",
    "passkey.disabled": "Biometric sign-in is off on this panel (it needs an https address).",
    "passkey.cancelled": "Cancelled or timed out. Try again.",
    "passkey.login_failed": "Could not confirm the biometrics. Sign in with your password.",
    "passkey.register_failed": "The device was not registered. Try again.",
    "passkey.already_registered": "This device is already registered.",
    "passkey.default_label": "Device",
    "passkey.registered": "Device registered: next time, sign in with biometrics.",
    "passkey.removed": "Device removed.",
    "passkey.not_found": "Device not found.",
    "nav.updates": "Updates",
    "updates.intro":
        "The panel updates itself from the releases published on GitHub ({repo}). A separate "
        "service installs them, as root, once a day: it checks the package sha256, restarts the "
        "panel and goes back to the previous version if the new one does not answer.",
    "updates.status": "Status",
    "updates.running": "Running version",
    "updates.latest": "Latest release",
    "updates.checked_at": "Last check",
    "updates.installed_at": "Last automatic install",
    "updates.not_installed":
        "The automatic updater has not run on this panel yet. It is installed by the full "
        "deploy (deploy-admin.ps1 -Full); the development environment does not have it.",
    "updates.result.error": "the last attempt failed",
    "updates.result.available": "version {version} available",
    "updates.result.installed": "updated by the last check",
    "updates.result.off": "checking is off",
    "updates.result.up_to_date": "up to date",
    "updates.install_log": "Installer output",
    "updates.check_now": "Check now",
    "updates.install_now": "Update to {version}",
    "updates.install_confirm":
        "Install version {version} now? The panel will be RESTARTED and whoever is using it "
        "loses the screen for a few seconds (open terminals drop).",
    "updates.mode": "Automatic update",
    "updates.mode.auto": "Automatic",
    "updates.mode.auto.help":
        "Installs every new release on its own. A new MAJOR version is only announced: it may "
        "need a manual step.",
    "updates.mode.notify": "Notify only",
    "updates.mode.notify.help": "Checks every day and shows the notice; you decide when to update.",
    "updates.mode.off": "Off",
    "updates.mode.off.help": "Does not contact GitHub. The Check now button still works.",
    "updates.bad_mode": "Unknown update mode.",
    "updates.write_failed": "Could not leave the request for the updater (see the panel log).",
    "updates.mode_saved": "Update mode saved.",
    "updates.check_requested": "Check requested: reload the page in a few seconds.",
    "updates.install_requested":
        "Update requested: the panel will restart shortly. Reload the page in a minute.",
    "updates.footer_available": "update {version} available",
    "push.title": "Notifications on this device",
    "push.hint":
        "Get the panel's alerts (server down, high CPU, memory or disk, a failed task...) as "
        "notifications on your phone or browser. Each device picks its own events.",
    "push.enable": "Turn on notifications on this device",
    "push.disable_here": "Turn off on this device",
    "push.denied": "The browser blocked notifications. Allow them in the site settings and try again.",
    "push.unsupported":
        "This browser cannot receive the panel's notifications. The panel must be opened over "
        "https; on an iPhone, add the panel to the home screen and turn them on from there.",
    "push.default_label": "Device",
    "push.label": "Device name",
    "push.created": "added on {when}",
    "push.last_ok": "last delivery {when}",
    "push.failing": "failing",
    "push.remove_confirm": "Stop sending notifications to \"{name}\"?",
    "push.limit": "Limit of {n} devices per person reached: remove one to add another.",
    "push.subscribed": "Notifications turned on for this device.",
    "push.unsubscribed": "Notifications turned off for this device.",
    "push.saved": "Device saved.",
    "push.removed": "Device removed: it no longer receives notifications.",
    "push.not_found": "Device not found.",
    "push.bad_subscription": "The browser sent a subscription the panel does not accept.",
    "push.bad_endpoint": "push address outside the known services",
    "push.bad_keys": "invalid device encryption keys",
    "push.http_status": "the push service answered HTTP {status}",
    "push.http_status_reason": "the push service answered HTTP {status}: {reason}",
    "push.call_failed": "could not reach the push service: {reason}",
    "push.test_title": "Game panel test",
    "push.test_body": "If you are reading this, notifications work on this device.",
    "push.test_sent": "Test notification sent to \"{name}\".",
    "push.test_failed": "The test notification did not reach \"{name}\": {reason}",
    # ------------------------------ screen text moved out of templates and scripts
    "account.operator_scope":
        "As an operator you start, stop, update and edit the configuration of servers already "
        "registered. Server registration, terminal, files and users belong to the "
        "administrator.",
    "account.recovery_codes_left_one": "{n} recovery code left",
    "account.recovery_codes_left_many": "{n} recovery codes left",
    "account.two_factor_off_hint":
        "With it, knowing the password is not enough to sign in: the panel also asks for a "
        "6-digit code from your phone.",
    "account.two_factor_root_hint":
        "This panel has root power over the game containers: turn it on.",
    "account_2fa.step_register": "1. Add the panel to the app",
    "account_2fa.step_register_hint":
        "Use an authenticator app (Google Authenticator, Authy, Microsoft Authenticator, "
        "1Password, Bitwarden...). On the phone, choose <strong>add account</strong> and "
        "<strong>scan QR code</strong> — or, without a camera, <strong>enter key "
        "manually</strong> with the text below the code.",
    "account_2fa.key_details":
        "Type <strong>time based</strong>, 6 digits, 30 seconds. Keep this key and this code "
        "only until you confirm below: after enabling they are not shown again.",
    "account_2fa.step_confirm": "2. Confirm with a code",
    "account_2fa.clock_hint":
        "Also check that the phone's clock is set to automatic: that is what makes the code "
        "match.",
    "account_2fa_codes.save_them_now_html":
        "<strong>Save these codes now.</strong> They are shown only this once. Each one "
        "replaces the app code a single time — it is the way out if you lose your phone. Keep "
        "them in a password manager or on paper, never on the same phone as the app.",
    "backups.keep_newest":
        "The <strong>{n}</strong> newest copies stay; older ones are removed on their own.",
    "backups.keep_all": "No copy is deleted automatically.",
    "backups.change_paths":
        "To change what goes in, edit the <a href=\"{url}\">backup paths</a> in the server "
        "settings.",
    "backups.live_copy_hint":
        "You can take the copy with the server running, that is the usual way. Just know that a "
        "save written in the middle of the copy may go in half done &mdash; for a perfect copy, "
        "stop the server first.",
    "backups.nothing_to_save_admin":
        "This server has nothing to save. Fill in the <strong>configuration folder</strong> or "
        "the <strong>backup paths</strong> <a href=\"{url}\">in the server settings</a>.",
    "backups.nothing_to_save_operator":
        "This server has nothing to save. Fill in the <strong>configuration folder</strong> or "
        "the <strong>backup paths</strong> (ask an administrator).",
    "history.removed": "(removed)",
    "history.error": "error",
    "history.keep_days":
        "The panel keeps the last <strong>{n} days</strong> "
        "(<code>GAMEPANEL_JOBS_KEEP_DAYS</code>) &mdash; each record carries the full output of "
        "what ran, and without cleanup the database only grows.",
    "history.cleanup_off":
        "Automatic cleanup is off (<code>GAMEPANEL_JOBS_KEEP_DAYS=0</code>): the history grows "
        "without limit.",
    "history.admin_actions_hidden":
        "Terminal, console and files do not show up here &mdash; they are administrator "
        "actions.",
    "catalog.source_curated": "curated",
    "catalog.source_dynamic": "dynamic",
    "config.no_files": "No configuration file registered for this server yet.",
    "config.ask_admin_to_register": "Ask a panel administrator to register the file.",
    "config.format": "format {name}",
    "config.pin_hint":
        "&quot;Pin here&quot; keeps the file in the bar above (up to {n} per server); the link "
        "opens it without pinning.",
    "config.nothing_found":
        "Nothing found in <code>{folder}</code>. Adjust the &quot;Config folder&quot; under <a "
        "href=\"{url}\">Edit server</a> or enter the file's full path in the bar above.",
    "config.settings_count": "Settings ({n})",
    "config.on": "On",
    "config.off": "Off",
    "config.outside_catalog": "{value} (not in the catalog)",
    "config.range": "{low} to {high}",
    "config.add_setting_hint":
        "For a key that does not exist in the file yet. It goes at the end of the chosen block, "
        "without touching the rest.",
    "config.save_hint":
        "Writes only the changed keys, keeping comments and the rest of the file. A "
        "<code>.bak</code> copy is kept next to it before any write. Most games only read their "
        "configuration at startup &mdash; without a restart, the change does not take effect.",
    "config.cannot_open_as_form": "Could not open <code>{path}</code> as a form.",
    "config.ask_admin_text_edit":
        "Let a panel administrator know &mdash; editing as text is restricted to them.",
    "service_state.unknown": "unknown",
    "service_state.unreachable": "unreachable",
    "server.more_actions_on": "More actions on {name}",
    "dashboard.register_hint":
        "Register the IP of a game container to control start, stop, update and run commands "
        "from here.",
    "dashboard.authorize_key_hint":
        "The panel reaches each container over SSH &mdash; first authorize its key in the "
        "container under <a href=\"{url}\">SSH access</a>.",
    "players.badge_online": "{count} online",
    "players.badge_players": "{count} players",
    "players.no_reading": "no reading",
    "players.names_unpublished": "This game does not publish the list of names — only the count.",
    "players.nobody_online": "Nobody connected right now.",
    "server_detail.count_off_admin":
        "Counting is off. Use the <a href=\"{url}\">wizard</a>: it tests the UDP and TCP ports "
        "the game opened, builds the HTTP API call when there is one and, if nothing answers, "
        "helps you count from the log.",
    "server_detail.count_off_operator":
        "Counting is off. A panel administrator turns it on in the counting wizard.",
    "server_detail.query_failed": "Could not query: {error}",
    "server_detail.query_failed_admin":
        "Check in the <a href=\"{url}\">wizard</a> that the port/URL is right and that the "
        "server is up.",
    "server_detail.query_failed_operator":
        "Check that the server is up; if it is, let a panel administrator know.",
    "server_detail.log_only_games":
        "A game that publishes nothing on the network (like RuneScape Dragonwilds) needs "
        "counting from the log.",
    "server_detail.online_of": "{n} of {total}",
    "server_detail.player_action_confirm": "{action} {player} from {server}?",
    "server_detail.approx_admin":
        "The <strong>count</strong> is right, but the <strong>names</strong> are a guess: this "
        "game's log says someone left without saying who, so the panel shows the last ones to "
        "join. If your server's leave line has the name, put <code>(?P&lt;name&gt;...)</code> "
        "in it in the <a href=\"{url}\">wizard</a> and the list becomes exact.",
    "server_detail.approx_operator":
        "The <strong>count</strong> is right, but the <strong>names</strong> are a guess: this "
        "game's log says someone left without saying who, so the panel shows the last ones to "
        "join. If your server's leave line has the name, put <code>(?P&lt;name&gt;...)</code> "
        "in it and the list becomes exact.",
    "server_detail.player_actions_note":
        "Kick, ban and announce go through the game's own API &mdash; the same one that counts "
        "players. Each one is recorded in the <a href=\"{url}\">history</a>.",
    "server_detail.no_log_lines": "(no log lines)",
    "server_detail.stop_following": "Stop following",
    "server_detail.no_connection": "no connection",
    "metrics.unavailable": "unavailable",
    "metrics.refresh_every": "refreshes every {n}s",
    "metrics.no_reading_now": "no reading right now",
    "metrics.read_failed": "Could not read the gauges: {error}",
    "metrics.meters_unavailable": "gauges unavailable",
    "metrics.cores_load": "{cores} core(s) · load {load}",
    "metrics.used_of_total": "{used} of {total}",
    "metrics.disk_mount": "Disk {mount}",
    "metrics.disk": "Disk",
    "metrics.stopped": "stopped",
    "files.upload_hint":
        "The file is uploaded in chunks, straight to the container &mdash; mods or saves of "
        "several GB are fine. If one with the same name already exists, it is replaced and a "
        "<code>.bak</code> copy is kept next to it.",
    "files.parent": ".. (up)",
    "files.download_name": "Download {name}",
    "files.delete_name": "Delete {name}",
    "files.delete_dir_name": "Delete {name} (only if empty)",
    "files.delete_entry_confirm": "Delete {path}?\n\nThis cannot be undone.",
    "files.binary_notice":
        "<strong>Binary file.</strong> The panel does not edit it so as not to corrupt the game "
        "&mdash; but you can download the whole file.",
    "files.download_size": "Download ({size})",
    "files.truncated_notice":
        "<strong>Read only:</strong> the file is {size} and exceeds the editing limit ({max_kb} "
        "KB). Below are the last {shown} &mdash; download the file to work on all of it.",
    "files.save_hint":
        "Ctrl+S saves. Before writing, the panel keeps a <code>{name}.&lt;date&gt;.bak</code> "
        "copy in the same folder, and keeps the original file's owner and permissions.",
    "files.crlf_note": "This file uses CRLF line endings &mdash; it will be saved that way.",
    "files.opens_as_form_html":
        "opens this file as a form and pins it on the <strong>Configuration</strong> screen",
    "files.delete_no_undo":
        "removes <code>{name}</code> from the container right away &mdash; there is no "
        "<code>.bak</code> copy here and no undo",
    "files.editor_intro":
        "Pick a file from the list to edit it &mdash; up to {max_kb} KB. Above that the panel "
        "shows the last {preview_kb} KB, read only.",
    "files.any_file_downloadable_html":
        "Any file can be downloaded through the <em>download</em> link in the list, including "
        "binaries (saves, .so, .pak) and files too large for the editor.",
    "files.config_search_hint":
        "Looking for the game's configuration file? The search for candidates is under <a "
        "href=\"{url}\">Configuration</a> &mdash; that is where its result is useful (pinning "
        "the file and editing it field by field).",
    "files.config_folder_is": "This server's config folder: <code>{path}</code>",
    "files.config_folder_hint_html":
        "Tip: fill in the \"Config folder\" under <a href=\"{url}\">Edit server</a> so this "
        "screen opens in the right place.",
    "files.stop_before_editing":
        "Stop the server before touching files it rewrites on exit &mdash; several games "
        "overwrite the .ini on shutdown.",
    "terminal.session_intro":
        "Interactive SSH session as <strong>{user}</strong> on <code>{host}</code>. It has a "
        "real TTY: <code>htop</code>, <code>nano</code>, <code>vim</code> and confirmation "
        "prompts work. The session drops on its own after {minutes} min idle.",
    "terminal.input": "terminal input",
    "terminal.keyboard_help":
        "The keyboard goes straight to the shell: <code>Tab</code> completes, "
        "<code>&uarr;</code> walks the bash history and <code>Ctrl+C</code> interrupts. To "
        "copy, select with the mouse (with text selected <code>Ctrl+C</code> copies instead of "
        "interrupting); <code>Ctrl+V</code> pastes.",
    "terminal.exit_fullscreen": "Exit full screen",
    "terminal.expired": "session expired",
    "terminal.closed": "session closed",
    "terminal.ended": "ended",
    "terminal.ended_exit": "ended (exit {code})",
    "terminal.reconnecting": "reconnecting...",
    "terminal.connecting": "connecting...",
    "terminal.connected": "connected",
    "terminal.http_error": "http error {status}",
    "terminal.open_failed": "failed to open: {error}",
    "terminal.output_lost": "[panel: old output discarded]",
    "copy.done": "Copied!",
    "copy.failed": "Could not copy",
    "config.unsaved_changes": "there are unsaved changes",
    "files.cursor_position": "line {line}, column {column}",
    "files.changed_suffix": " - changed",
    "http.no_connection": "no connection",
    "app.short_name": "Games",
    "app.description": "Starts, stops, updates and watches the game servers.",
    "offline.no_answer": "The panel did not answer.",
    "offline.no_answer_hint":
        "The panel did not answer. It only works with access to the network where the "
        "containers are &mdash; starting and stopping servers cannot happen offline.",
    "console.run_as_intro":
        "Commands run as <strong>{user}</strong> inside the container <code>{host}</code>, over "
        "SSH. Each run is limited to {timeout}s and is recorded in the history below.",
    "console.interactive_hint":
        "For something interactive (nano, htop, confirmation prompts) use the <a "
        "href=\"{url}\">interactive session</a>.",
    "console.non_interactive_hint":
        "Non-interactive: no TTY, no <code>vim</code>/<code>top</code>/<code>htop</code>. Use "
        "<code>journalctl -n 50</code>, <code>ls</code>, <code>df -h</code>, <code>cat</code>, "
        "<code>sed -i</code> etc. Ctrl+Enter runs it.",
    "console.running_placeholder": "(running...)",
    "console.running": "Running...",
    "job.waiting_output": "(waiting for output...)",
    "job.finished_exit": "Finished with exit code {code}.",
    "job.running_hint":
        "Running — the output below updates on its own. A game update can take several minutes.",
    "login_2fa.recovery_hint":
        "No phone? Use one of the recovery codes (<code class=\"nowrap\">abcde-12345</code>); "
        "each one works once.",
    "ssh_key.intro":
        "The panel controls each server over SSH, using the key below. It logs in as the "
        "unprivileged <code>gamepanel</code> user, never as <code>root</code>, and the game "
        "itself runs as <code>steam</code>.",
    "ssh_key.new_cts":
        "Containers created by <code>deploy-game.ps1</code> or by the broker already come with "
        "the <code>gamepanel</code> user and this key: there is nothing to do.",
    "ssh_key.existing_cts":
        "A container that still lets the panel in as <code>root</code> is converted from the "
        "repository, on your machine, replacing <code>&lt;CTID&gt;</code> with the container id:",
    "ssh_key.migrate_note":
        "It installs the user, proves the access from the panel, switches the server to "
        "<code>gamepanel</code> and only then locks root over SSH.",
    "ssh_key.manual":
        "Or by hand, inside the container as <code>root</code>, with "
        "<code>lib/ct-panel-access.sh</code> copied from the repository:",
    "ssh_key.manual_lock":
        "Then set the SSH user to <code>gamepanel</code> on the server's edit screen, check that "
        "it shows up as reachable, and only then lock root:",
    "ssh_key.unit_placeholder": "game.service",
    "ssh_key.host_key_changed":
        "On the first connection the panel learns and pins the container's host key "
        "(<code>accept-new</code>). If the container is recreated, the key changes and the "
        "connection starts failing with <code>REMOTE HOST IDENTIFICATION HAS CHANGED</code> "
        "&mdash; in that case remove the old entry:",
    "ssh_key.container_ip": "container-ip",
    "ssh_key.run_as": "Run it inside the panel container, as the <code>gamepanel</code> user.",
    "schedules.clock_note":
        "The clock is the <strong>panel</strong>'s &mdash; it is now <strong>{now}</strong> "
        "({zone}). If that does not match your time, adjust the panel container's "
        "<code>TZ</code>. A task that came due while the panel was down <strong>does not fire "
        "late</strong>: it waits for the next occurrence.",
    "schedules.no_timezone": "no time zone set",
    "schedules.what_to_do_hint":
        "<strong>Backup</strong> uses the paths from the server settings, with the same "
        "retention as the Backups screen. <strong>Update</strong> runs SteamCMD &mdash; the "
        "server is down during the update.",
    "schedules.daily_and_weekly": "(daily and weekly)",
    "schedules.weekly_only": "(weekly)",
    "schedules.interval_only": "(interval)",
    "schedules.runs_note":
        "Every run shows up in the <a href=\"{url}\">history</a> like any other action, with "
        "<code>agendador</code> in place of the user.",
    "users.role_of": "Role of {name}",
    "users.username_hint":
        "Lowercase letters, digits, <code>-</code> and <code>_</code>. E.g. <code>john</code>",
    "users.roles_hint":
        "<strong>{operator}</strong>: starts, stops, updates, edits the already registered "
        "configuration, sees log and players. <strong>{admin}</strong>: all of that plus "
        "registering servers, terminal, file browser and this screen.",
    "users.password_handoff_html":
        "You set the password and hand it to the person; they change it later under <a "
        "href=\"{url}\">Account</a>. The panel does not send email.",
    "users.cut_note":
        "The split follows what gives root access to the container: terminal, file editor and "
        "the server settings (which point the panel's SSH) stay with the administrator.",
    "charts.over_time": "{title} over time",
    "charts.samples_note":
        "{n} sample(s) &middot; one every {every} min &middot; kept for {days} days",
    "charts.no_samples_hint":
        "The panel stores a reading every {every} minutes while it is up &mdash; come back in a "
        "little while, or pick a longer period.",
    "charts.peak_in_period": "peak of <strong>{n}</strong> in the period",
    "charts.no_player_count":
        "No player count in this period (counting must be turned on in the server settings).",
    "charts.table_hint":
        "The same values as the chart, without relying on color or hovering. Newest to oldest.",
    "charts.range_6h": "6 hours",
    "charts.range_24h": "24 hours",
    "charts.range_7d": "7 days",

    # ---- errors that reach the screen from runtime/, integrations/, app.py and blueprints/
    # Raised as `i18n.Message` far from any request; the display point translates them.
    "ssh.timeout": "timed out ({seconds}s) running on host {host}",
    "ssh.command_failed": "command failed (exit {code})",
    "terminal.session_open_failed": "could not open the session: {reason}",
    "terminal.session_ended": "session ended: {reason}",
    "terminal.too_many_sessions": "limit of {n} simultaneous terminals reached",
    "file.list_failed": "could not list the folder",
    "file.search_failed": "the search failed",
    "file.read_failed": "could not read the file",
    "file.write_failed": "could not save",
    "file.delete_failed": "could not delete",
    "file.upload_failed": "upload failed (exit {code})",
    "backup.list_failed": "could not list the backups",
    "backup.delete_failed": "could not delete the backup",
    "http.path_missing": "'{path}' does not exist in the response",
    "http.not_a_list": "'{path}' does not point to a list",
    "http.not_a_count": "'{path}' is neither a number nor a list",
    "http.no_players_found": "found no players in the response - fill in the list or count path",
    "log.bad_path":
        "invalid log path - use an absolute path, with no spaces (the '*' is allowed, e.g. "
        "/opt/game/profiles/*.ADM)",
    "ports.list_failed": "could not list the container's open ports: {reason}",
    "ports.tcp_probe_failed": "could not probe the TCP ports: {reason}",
    "error.timed_out": "timed out",
    "broker.cert_mismatch": "the broker's certificate does not match the pinned fingerprint",
    "broker.not_configured": "the broker is not configured on this panel",
    "broker.unreachable": "could not reach the broker ({kind})",
    "broker.reply_too_big": "the broker's response is too large",
    "broker.unexpected_reply": "unexpected response from the broker",
    "broker.http_status": "the broker answered HTTP {status}",
    "webhook.bad_url": "invalid URL (use http:// or https://)",
    "webhook.http_status": "the webhook answered HTTP {status}",
    "webhook.http_status_reason": "the webhook answered HTTP {status}: {reason}",
    "webhook.call_failed": "could not call the webhook: {reason}",
    "players.need_join_pattern": "enter the join line pattern",
    "players.everyone": "everyone",
    "api.two_factor_required": "enable two-step verification in Account",
    "api.broker_needs_two_factor": "enable two-step verification in Account to use the broker",
    "account.wrong_password": "Wrong password.",
    "account.too_many_tries": "Too many attempts. Wait a few minutes.",
    "account.code_invalid_or_used": "Invalid or already used code.",
    "alerts.bad_webhook_url": "Invalid URL (start with http:// or https://).",
    "alerts.needs_query_count": "player count by query (A2S) or HTTP API",
    "alerts.needs_player_count": "player count (A2S, HTTP API or log)",
    "alerts.needs_error_pattern": "an error expression in the server registration",
    "alerts.limit_disk": "full disk",
    "alerts.limit_memory": "full memory",
    "alerts.limit_cpu": "high CPU",
    "alerts.destination_fallback": "destination",
    "flash.backup_deleted": "Backup {file} deleted.",
    "alerts.unnamed": "No name",
    # ---- the "Add game" form (services/broker_service.py) and the console end-of-job line
    "broker_form.app_id": "App ID",
    "broker_form.memory": "Memory",
    "broker_form.must_be_number": "{label} must be a number.",
    "console.exit_code": "exit code {code}",
    # ---- "Add game" search suggestions: source and warnings of the hand-written list
    # (games/catalog/manual_suggestions.py) and the Pterodactyl complement note (search.py)
    "catalog.source.manual": "panel curation",
    "catalog.suggestion.from_pterodactyl": "Came from the Pterodactyl egg (LinuxGSM did not have it): {fields}.",
    "catalog.suggestion.field.config_path": "config folder",
    "catalog.suggestion.field.config_files": "config files",
    "catalog.suggestion.field.ports": "ports",
    "catalog.suggestion.proton_note":
        "Windows-only server: it runs through Proton (proton recipe). If it does not start, "
        "switch to wine and write down why.",
    "catalog.suggestion.ark_ascended.no_steam_query":
        "ASA does not publish a Steam query (its server list is Epic's): the player count comes from the log.",
    "catalog.suggestion.ark_ascended.map_argument":
        "The map is the first argument (TheIsland_WP). The server name and password live in "
        "GameUserSettings.ini, not in the command.",
    "catalog.suggestion.ark_ascended.memory": "Needs ~13 GB of RAM just to load the default map.",
    "catalog.suggestion.abiotic_factor.sandbox_settings":
        "The world rules live in each world's SandboxSettings.ini, which is only created on the "
        "first start (Saved/SaveGames/Server/Worlds/<world>/).",
    "catalog.suggestion.conan_exiles.port_plus_one":
        "7778/UDP is the game port + 1, opened by the server on its own: that is why it does not "
        "move to other ports (the broker has no way to tell it).",
    "catalog.suggestion.conan_exiles.save": "The whole save is game.db in ConanSandbox/Saved.",
    "catalog.suggestion.sons_of_the_forest.ports":
        "The ports (GamePort, QueryPort, BlobSyncPort) live in dedicatedserver.cfg, which the "
        "server creates in /opt/game/userdata on the first start: there is no way to pass them "
        "on the command line, so it stays on the default ports.",
    "catalog.suggestion.sons_of_the_forest.xvfb": "The server creates a window at startup: hence the xvfb recipe.",

    # ---- game config fields (games/adapters/*.py)
    # The Config screen's labels, help texts and option labels, one block per adapter:
    # `game.<adapter>.<field>.label` / `.help` / `.opt.<value>`, with the field and the value
    # LOWERCASED (the key convention test). A game with its own screen brings its keys here
    # and in the other catalog; `test_game_texts.py` fails while one is missing.
    # The section names and the format name that `config_format` produces (an unnamed block).
    "config.no_section": "(no section)",
    "config.root": "(root)",
    "config.format_text": "Text",
    # Errors of the config readers (`games/config_format.py`, `load_config_doc`).
    "config.error.invalid_name": "invalid setting name: {name}",
    "config.error.value_newline": "the value cannot contain a line break",
    "config.error.value_too_long": "value too long (limit of {n} characters)",
    "config.error.invalid_bool": "invalid boolean value: {value} (use True or False)",
    "config.error.value_double_quote": 'the value cannot contain double quotes (")',
    "config.error.invalid_json": "invalid JSON: {reason}",
    "config.error.json_not_container": "the JSON must be an object or a list to become a form",
    "config.error.json_missing_path": "path not found in the JSON: {path}",
    "config.error.not_an_integer": "{value} is not an integer",
    "config.error.not_a_number": "{value} is not a number",
    "config.error.json_dot_in_key": "a dot (.) is not accepted in a JSON key name",
    "config.error.json_add_to_list": "cannot add {name} to a JSON list",
    "config.error.json_not_object": "{section} is not a JSON object",
    "config.error.sii_value_quote": 'the value cannot contain quotes (") or a backslash (\\)',
    "config.error.sii_needs_block": "in a .sii file the new setting must go inside a block",
    "config.error.sii_invalid_name": "invalid setting name in the .sii: {name}",
    "config.error.binary_file": "this file is binary — field-by-field editing does not apply to it",
    "config.error.file_too_big":
        "the file is {kb} KB and exceeds the editing limit ({limit} KB) — a configuration file rarely gets this "
        "big, check that it is the right file",
    "config.error.too_many_keys":
        "the file has {n} keys (the form stops at {limit}) — it does not look like a configuration file",
    # Units and the validation message of a mapped field (`games/base.py`).
    "game.unit.factor": "x",
    "game.unit.minutes": "min",
    "game.unit.seconds": "s",
    "game.validation.invalid_choice": "invalid value; use one of: {choices}",
    "game.validation.not_a_number": "must be a number",
    "game.validation.minimum": "minimum {limit}",
    "game.validation.maximum": "maximum {limit}",
    "game.validation.with_unit": "{value} {unit}",
    # Labels shared by several games, then one block per adapter.
    "game.common.name": "Server name",
    "game.common.join_password": "Join password",
    "game.common.admin_password": "Admin password",
    "game.dayz.hostname.help": "How it shows up in the server browser.",
    "game.dayz.password.help": "Empty = open server.",
    "game.dayz.passwordadmin.help": "Remote console access. CHANGE it before exposing the server.",
    "game.dayz.maxplayers.label": "Max players",
    "game.dayz.maxplayers.help": "Maximum players at the same time.",
    "game.dayz.steamqueryport.label": "Steam query port",
    "game.dayz.steamqueryport.help":
        "Without it the server does not show up in the client's browser. It must match what is forwarded on the "
        "router.",
    "game.dayz.verifysignatures.label": "Verify signatures",
    "game.dayz.verifysignatures.help": "2 = only signed mods are accepted. Leave it at 2.",
    "game.dayz.forcesamebuild.label": "Force same build",
    "game.dayz.forcesamebuild.help": "1 = the client must be on the same build as the server.",
    "game.dayz.disable3rdperson.label": "First person only",
    "game.dayz.disable3rdperson.help": "1 = first-person-only server.",
    "game.dayz.disablevon.label": "Disable voice (VoN)",
    "game.dayz.disablevon.help": "0 = voice enabled.",
    "game.dayz.servertimeacceleration.label": "Time acceleration",
    "game.dayz.servertimeacceleration.help": "12 = one in-game day every 2 real hours.",
    "game.dayz.instanceid.label": "Instance ID",
    "game.dayz.instanceid.help": "Sets the storage_<id> persistence folder.",
    "game.dragonwilds.ownerid.label": "Owner ID",
    "game.dragonwilds.ownerid.help":
        "Your Player ID, at the bottom of the game's Settings menu (not the 17-digit Steam ID). Without it the "
        "server does NOT start.",
    "game.dragonwilds.servername.help": "How it shows up to whoever joins.",
    "game.dragonwilds.defaultworldname.label": "Default world name",
    "game.dragonwilds.defaultworldname.help":
        "Name of the world created on the first start. Changing it later does not rename an existing world.",
    "game.dragonwilds.adminpassword.help":
        "Whoever knows this password opens the Server Management tab in the game menu and becomes admin. CHANGE it "
        "before exposing the server.",
    "game.dragonwilds.worldpassword.help": "Empty = anyone can join.",
    "game.dragonwilds.serverguid.label": "Server GUID",
    "game.dragonwilds.serverguid.help": "Generated by the game itself. Do not edit by hand.",
    "game.dragonwilds.knownplayerlist.label": "Known players",
    "game.dragonwilds.knownplayerlist.help":
        "Filled in by the game itself (who has joined, privileges and bans). Do not edit by hand.",
    "game.enshrouded.name.help": "How it shows up in the game's server list.",
    "game.enshrouded.slotcount.label": "Slots",
    "game.enshrouded.slotcount.help": "How many players can be connected at the same time.",
    "game.enshrouded.queryport.label": "Port",
    "game.enshrouded.queryport.help":
        "Port the player types to join. Changing it here also requires changing the forwarding on the router.",
    "game.enshrouded.ip.label": "Listen IP",
    "game.enshrouded.ip.help": "0.0.0.0 accepts connections on any interface. Only change it if you know exactly why.",
    "game.enshrouded.enablevoicechat.label": "Voice chat",
    "game.enshrouded.enablevoicechat.help": "Turns on voice chat on the server.",
    "game.enshrouded.enabletextchat.label": "Text chat",
    "game.enshrouded.enabletextchat.help": "Turns on text chat on the server.",
    "game.enshrouded.voicechatmode.label": "Voice chat mode",
    "game.enshrouded.voicechatmode.help": "Proximity: you only hear who is nearby. Global: everyone hears everyone.",
    "game.enshrouded.voicechatmode.opt.proximity": "Proximity (default)",
    "game.enshrouded.voicechatmode.opt.global": "Global",
    "game.enshrouded.gamesettingspreset.label": "Game settings preset",
    "game.enshrouded.gamesettingspreset.help":
        "WARNING: picking any preset other than Custom makes the game IGNORE the individual settings below. If you "
        "customized anything, leave it on Custom.",
    "game.enshrouded.gamesettingspreset.opt.default": "Default (first time)",
    "game.enshrouded.gamesettingspreset.opt.relaxed": "Relaxed (building)",
    "game.enshrouded.gamesettingspreset.opt.hard": "Hard (combat)",
    "game.enshrouded.gamesettingspreset.opt.survival": "Survival (punishing)",
    "game.enshrouded.gamesettingspreset.opt.custom": "Custom (uses the settings below)",
    "game.enshrouded.playerhealthfactor.label": "Player health",
    "game.enshrouded.playerhealthfactor.help": "Multiplies max health. 2 = double the health.",
    "game.enshrouded.playermanafactor.label": "Player mana",
    "game.enshrouded.playermanafactor.help": "Multiplies max mana.",
    "game.enshrouded.playerstaminafactor.label": "Player stamina",
    "game.enshrouded.playerstaminafactor.help": "Multiplies max stamina.",
    "game.enshrouded.playerbodyheatfactor.label": "Body heat",
    "game.enshrouded.playerbodyheatfactor.help":
        "Multiplies cold resistance. Higher = lasts longer in freezing regions.",
    "game.enshrouded.playerdivingtimefactor.label": "Diving time",
    "game.enshrouded.playerdivingtimefactor.help": "Multiplies how long you can stay underwater.",
    "game.enshrouded.enabledurability.label": "Durability",
    "game.enshrouded.enabledurability.help": "Off, equipment never breaks and never needs repair.",
    "game.enshrouded.enablestarvingdebuff.label": "Starving debuff",
    "game.enshrouded.enablestarvingdebuff.help": "On, going without food applies a debuff (not just losing the buffs).",
    "game.enshrouded.foodbuffdurationfactor.label": "Food buff duration",
    "game.enshrouded.foodbuffdurationfactor.help": "Multiplies how long food effects last.",
    "game.enshrouded.fromhungertostarving.label": "From hunger to starving",
    "game.enshrouded.fromhungertostarving.help": "Time between getting hungry and starting to suffer the debuff.",
    "game.enshrouded.shroudtimefactor.label": "Shroud time",
    "game.enshrouded.shroudtimefactor.help": "Multiplies how long you can stay in the Shroud before dying.",
    "game.enshrouded.tombstonemode.label": "Tombstone mode",
    "game.enshrouded.tombstonemode.help": "What stays in the tombstone. 'Everything' includes what was equipped.",
    "game.enshrouded.tombstonemode.opt.addbackpackmaterials": "Lose backpack materials (default)",
    "game.enshrouded.tombstonemode.opt.everything": "Lose everything",
    "game.enshrouded.tombstonemode.opt.notombstone": "Keep everything (no tombstone)",
    "game.enshrouded.enablegliderturbulences.label": "Glider turbulence",
    "game.enshrouded.enablegliderturbulences.help": "Off, the glider flies steady, without air currents.",
    "game.enshrouded.daytimeduration.label": "Day time duration",
    "game.enshrouded.daytimeduration.help":
        "How long an in-game day lasts in REAL time. The file stores nanoseconds; here you edit it in minutes.",
    "game.enshrouded.nighttimeduration.label": "Night time duration",
    "game.enshrouded.nighttimeduration.help":
        "How long the night lasts in REAL time. Minimum of 2 minutes - the game discards anything shorter.",
    "game.enshrouded.weatherfrequency.label": "Weather frequency",
    "game.enshrouded.weatherfrequency.help": "How often the weather changes (rain, storms).",
    "game.enshrouded.weatherfrequency.opt.disabled": "Disabled",
    "game.enshrouded.weatherfrequency.opt.rare": "Rare",
    "game.enshrouded.weatherfrequency.opt.normal": "Normal",
    "game.enshrouded.weatherfrequency.opt.often": "Often",
    "game.enshrouded.fishingdifficulty.label": "Fishing difficulty",
    "game.enshrouded.fishingdifficulty.help": "How hard the fish-hooking minigame is.",
    "game.enshrouded.fishingdifficulty.opt.veryeasy": "Very easy",
    "game.enshrouded.fishingdifficulty.opt.easy": "Easy",
    "game.enshrouded.fishingdifficulty.opt.normal": "Normal",
    "game.enshrouded.fishingdifficulty.opt.hard": "Hard",
    "game.enshrouded.fishingdifficulty.opt.veryhard": "Very hard",
    "game.enshrouded.cursemodifier.label": "Curse modifier",
    "game.enshrouded.cursemodifier.help": "Chance of getting cursed. 'Easy' turns the system off.",
    "game.enshrouded.cursemodifier.opt.easy": "Easy (off)",
    "game.enshrouded.cursemodifier.opt.normal": "Normal",
    "game.enshrouded.cursemodifier.opt.hard": "Hard (double chance)",
    "game.enshrouded.randomspawneramount.label": "Random spawner amount",
    "game.enshrouded.randomspawneramount.help": "How many enemies appear outside enemy camps.",
    "game.enshrouded.randomspawneramount.opt.few": "Few",
    "game.enshrouded.randomspawneramount.opt.normal": "Normal",
    "game.enshrouded.randomspawneramount.opt.many": "Many",
    "game.enshrouded.randomspawneramount.opt.extreme": "Extreme",
    "game.enshrouded.aggropoolamount.label": "Aggro pool amount",
    "game.enshrouded.aggropoolamount.help": "How many enemies can chase a player at the same time.",
    "game.enshrouded.aggropoolamount.opt.few": "Few",
    "game.enshrouded.aggropoolamount.opt.normal": "Normal",
    "game.enshrouded.aggropoolamount.opt.many": "Many",
    "game.enshrouded.aggropoolamount.opt.extreme": "Extreme",
    "game.enshrouded.miningdamagefactor.label": "Mining damage",
    "game.enshrouded.miningdamagefactor.help":
        "Multiplies how much the pickaxe breaks per hit. Higher = faster mining.",
    "game.enshrouded.plantgrowthspeedfactor.label": "Plant growth speed",
    "game.enshrouded.plantgrowthspeedfactor.help": "Multiplies how fast plants grow.",
    "game.enshrouded.resourcedropstackamountfactor.label": "Resource drop amount",
    "game.enshrouded.resourcedropstackamountfactor.help": "Multiplies the amount that drops when gathering.",
    "game.enshrouded.factoryproductionspeedfactor.label": "Production speed",
    "game.enshrouded.factoryproductionspeedfactor.help": "Multiplies the speed of workbenches and furnaces.",
    "game.enshrouded.perkupgraderecyclingfactor.label": "Perk upgrade recycling",
    "game.enshrouded.perkupgraderecyclingfactor.help":
        "Share of the material returned when undoing a weapon upgrade. 0.5 = half back; 1 = everything back.",
    "game.enshrouded.perkcostfactor.label": "Perk cost",
    "game.enshrouded.perkcostfactor.help": "Multiplies the material needed to upgrade weapons.",
    "game.enshrouded.experiencecombatfactor.label": "Combat XP",
    "game.enshrouded.experiencecombatfactor.help": "Multiplies experience gained from combat.",
    "game.enshrouded.experienceminingfactor.label": "Mining XP",
    "game.enshrouded.experienceminingfactor.help": "Multiplies experience gained from mining.",
    "game.enshrouded.experienceexplorationquestsfactor.label": "Exploration and quest XP",
    "game.enshrouded.experienceexplorationquestsfactor.help":
        "Multiplies experience from exploring and completing quests.",
    "game.enshrouded.enemydamagefactor.label": "Enemy damage",
    "game.enshrouded.enemydamagefactor.help": "Multiplies the damage enemies deal.",
    "game.enshrouded.enemyhealthfactor.label": "Enemy health",
    "game.enshrouded.enemyhealthfactor.help": "Multiplies enemy health.",
    "game.enshrouded.enemystaminafactor.label": "Enemy stamina",
    "game.enshrouded.enemystaminafactor.help": "Multiplies their stamina (how long they can keep attacking).",
    "game.enshrouded.enemyperceptionrangefactor.label": "Enemy perception range",
    "game.enshrouded.enemyperceptionrangefactor.help": "Multiplies the distance at which enemies notice you.",
    "game.enshrouded.bossdamagefactor.label": "Boss damage",
    "game.enshrouded.bossdamagefactor.help": "Multiplies boss damage.",
    "game.enshrouded.bosshealthfactor.label": "Boss health",
    "game.enshrouded.bosshealthfactor.help": "Multiplies boss health.",
    "game.enshrouded.threatbonus.label": "Threat bonus",
    "game.enshrouded.threatbonus.help": "Multiplies how easily enemies get aggressive.",
    "game.enshrouded.pacifyallenemies.label": "Pacify all enemies",
    "game.enshrouded.pacifyallenemies.help": "On, no enemy attacks - building/exploration mode.",
    "game.enshrouded.tamingstartlerepercussion.label": "Taming startle repercussion",
    "game.enshrouded.tamingstartlerepercussion.help": "How much taming progress is lost when the animal gets startled.",
    "game.enshrouded.tamingstartlerepercussion.opt.keepprogress": "Keep all progress",
    "game.enshrouded.tamingstartlerepercussion.opt.losesomeprogress": "Lose some progress (default)",
    "game.enshrouded.tamingstartlerepercussion.opt.loseallprogress": "Lose all progress",
    "game.enshrouded.password.label": "Group password",
    "game.enshrouded.password.help":
        "Password the player types to join THIS group. Each group (Admin/Friend/Guest) has its own - there is no "
        "single server password.",
    "game.enshrouded.cankickban.label": "Can kick/ban",
    "game.enshrouded.cankickban.help": "Allows removing players from the server.",
    "game.enshrouded.canaccessinventories.label": "Can access inventories",
    "game.enshrouded.canaccessinventories.help": "Allows using other players' chests.",
    "game.enshrouded.caneditbase.label": "Can edit base",
    "game.enshrouded.caneditbase.help": "Allows building and destroying inside the base.",
    "game.enshrouded.canextendbase.label": "Can extend base",
    "game.enshrouded.canextendbase.help": "Allows enlarging the base area.",
    "game.enshrouded.caneditworld.label": "Can edit world",
    "game.enshrouded.caneditworld.help": "Allows changing terrain outside bases.",
    "game.enshrouded.reservedslots.label": "Reserved slots",
    "game.enshrouded.reservedslots.help": "Slots guaranteed for this group, even when the server is full.",
    "game.ets2.lobby_name.help": "How it shows up in the game's server list.",
    "game.ets2.description.label": "Description",
    "game.ets2.description.help": "Short text shown next to the name in the list.",
    "game.ets2.welcome_message.label": "Welcome message",
    "game.ets2.welcome_message.help": "Shown in chat to whoever joins.",
    "game.ets2.password.help": "Empty = open server.",
    "game.ets2.max_players.label": "Max players",
    "game.ets2.max_players.help":
        "Above 8, EACH player needs g_max_convoy_size 128 in the game's config.cfg, otherwise the server vanishes "
        "from their list.",
    "game.ets2.max_vehicles_total.label": "Max vehicles total",
    "game.ets2.max_vehicles_total.help": "Vehicle limit in the world.",
    "game.ets2.max_ai_vehicles_player.label": "AI traffic per player",
    "game.ets2.max_ai_vehicles_player.help": "AI vehicles around each player.",
    "game.ets2.player_damage.label": "Player damage",
    "game.ets2.player_damage.help": "Collisions between trucks cause damage.",
    "game.ets2.traffic.label": "Traffic",
    "game.ets2.traffic.help": "Turns on AI vehicles.",
    "game.ets2.hide_colliding.label": "Hide colliding vehicles",
    "game.ets2.hide_colliding.help": "A truck stopped on top of another one disappears.",
    "game.ets2.force_speed_limiter.label": "Force speed limiter",
    "game.ets2.force_speed_limiter.help": "Forces the speed limiter on.",
    "game.ets2.friends_only.label": "Friends only",
    "game.ets2.friends_only.help": "Only Steam friends of players already on the server can join.",
    "game.ets2.show_server.label": "Show in server list",
    "game.ets2.show_server.help": "Off = only whoever searches by the ID can join.",
    "game.ets2.name_tags.label": "Name tags",
    "game.ets2.name_tags.help": "Shows each player's name.",
    "game.ets2.server_logon_token.label": "Server logon token",
    "game.ets2.server_logon_token.help": "Keeps the same server identity across restarts.",
    "game.icarus.sessionname.help": "How it shows up in the server browser.",
    "game.icarus.joinpassword.help": "Empty = anyone can join.",
    "game.icarus.adminpassword.help": "Grants access to the in-game admin commands.",
    "game.icarus.maxplayers.label": "Max players",
    "game.icarus.maxplayers.help": "Maximum players at the same time.",
    "game.icarus.allownonadminstolaunchprospects.label": "Non-admins can launch prospects",
    "game.icarus.allownonadminstolaunchprospects.help":
        "Off, only an admin picks which mission (prospect) runs on the server.",
    "game.icarus.allownonadminstodeleteprospects.label": "Non-admins can delete prospects",
    "game.icarus.allownonadminstodeleteprospects.help": "Careful: deleting a prospect deletes its progress.",
    "game.icarus.shutdownifnotjoinedfor.label": "Shut down if nobody joins",
    "game.icarus.shutdownifnotjoinedfor.help":
        "Seconds without ANY connection until the server shuts itself down. systemd restarts it right after; raise "
        "it to keep the server up.",
    "game.icarus.shutdownifemptyfor.label": "Shut down when empty",
    "game.icarus.shutdownifemptyfor.help": "Seconds with the server empty until it shuts itself down.",
    "game.icarus.resumeprospect.label": "Resume prospect",
    "game.icarus.resumeprospect.help": "On, the server goes back by itself to the mission that was running.",
    "game.icarus.loadprospect.label": "Prospect to load",
    "game.icarus.loadprospect.help": "Name of the saved prospect to open.",
    "game.icarus.createprospect.label": "Prospect to create",
    "game.icarus.createprospect.help": "Creates a new mission with this name on start.",
    "game.icarus.lastprospectname.label": "Last prospect",
    "game.icarus.lastprospectname.help": "Filled in by the game itself. Do not edit by hand.",
    "game.palworld.servername.help": "How it shows up in the community server list.",
    "game.palworld.serverpassword.help": "Empty = open server.",
    "game.palworld.adminpassword.help": "Used for admin commands and the REST API.",
    "game.palworld.serverplayermaxnum.label": "Max players",
    "game.palworld.serverplayermaxnum.help": "Maximum players at the same time (limit of 32).",
    "game.palworld.publicport.label": "Public port",
    "game.palworld.publicport.help": "Must match the port forwarded on the router.",
    "game.palworld.restapienabled.label": "REST API",
    "game.palworld.restapienabled.help": "Turns on the API the panel uses to show player NAMES.",
    "game.palworld.restapiport.label": "REST API port",
    "game.palworld.restapiport.help": "Never forward this port on the router.",
    "game.palworld.rconenabled.label": "RCON",
    "game.palworld.rconenabled.help": "Remote console. Deprecated by Pocketpair in favor of the REST API.",
    "game.palworld.deathpenalty.label": "Death penalty",
    "game.palworld.deathpenalty.help": "What you drop when you die.",
    "game.palworld.deathpenalty.opt.none": "Nothing",
    "game.palworld.deathpenalty.opt.item": "Items (no equipment)",
    "game.palworld.deathpenalty.opt.itemandequipment": "Items and equipment",
    "game.palworld.deathpenalty.opt.all": "Everything (Pals included)",
    "game.palworld.daytimespeedrate.label": "Day time speed",
    "game.palworld.daytimespeedrate.help": "Higher = days go by faster.",
    "game.palworld.nighttimespeedrate.label": "Night time speed",
    "game.palworld.nighttimespeedrate.help": "Higher = nights go by faster.",
    "game.palworld.exprate.label": "EXP rate",
    "game.palworld.exprate.help": "Multiplies all experience gained.",
    "game.palworld.palcapturerate.label": "Pal capture rate",
    "game.palworld.palcapturerate.help": "Multiplies the chance to capture Pals.",
    "game.palworld.palspawnnumrate.label": "Pal appearance rate",
    "game.palworld.palspawnnumrate.help": "Multiplies how many Pals appear in the world.",
    "game.palworld.paldamagerateattack.label": "Damage from Pals",
    "game.palworld.paldamagerateattack.help": "Multiplies the damage Pals deal.",
    "game.palworld.paldamageratedefense.label": "Damage to Pals",
    "game.palworld.paldamageratedefense.help": "Multiplies how tough Pals are (higher = they take more damage).",
    "game.palworld.playerdamagerateattack.label": "Damage from players",
    "game.palworld.playerdamagerateattack.help": "Multiplies the damage you deal.",
    "game.palworld.playerdamageratedefense.label": "Damage to players",
    "game.palworld.playerdamageratedefense.help": "Multiplies how tough you are (higher = you take more damage).",
    "game.palworld.collectiondroprate.label": "Gatherable items drop rate",
    "game.palworld.collectiondroprate.help": "Multiplies what drops when gathering.",
    "game.palworld.enableplayertoplayerdamage.label": "PvP",
    "game.palworld.enableplayertoplayerdamage.help": "Lets players attack each other.",
    "game.palworld.benabledefenseotherguild.label": "Raids from other guilds",
    "game.palworld.benabledefenseotherguild.help": "Lets your base be attacked by other guilds.",
}
