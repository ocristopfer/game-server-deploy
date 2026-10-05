#!/usr/bin/env python3
"""Templates for the catalog's "Add game" form.

A template is NOT a game: it is a set of values the form fills in at once, so the person
only completes what changes (name, app id, project folder name). The one that really
validates is still the broker - the template grants no power at all, it only saves typing
and the mistake of forgetting a placeholder.

It is the path for someone looking for a game that is in no source: the search finds
nothing, but the game ENGINE is almost always known (Unreal, Unity, Source), and each engine
has its own way of receiving a port, writing a log and keeping a save.

Pure on purpose (no Flask, no database), like `navigation.py`: it is data, and
`tests/gamebroker/unit/test_templates.py` loads this file and checks that each template
passes the broker validator.

The key names in `values` are the `name=` of the form fields. `recipes` is the list of
checked boxes, separated by spaces. Label and description are i18n catalog KEYS: text
written here would come out in Portuguese on the English screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The Unreal project is the folder that shows up inside /opt/game after installation
# (Pal, RSDragonwilds, FactoryGame). There is no way to know without installing; that is why
# the template carries a very visible fake name instead of a silent guess.
PROJECT = "NomeDoProjeto"
# The same for the executable of a Unity game (VRisingServer.exe, CoreKeeperServer).
EXECUTABLE = "NomeDoExecutavel"
# And for the mod folder of a Source game (-game cstrike, -game tf).
MOD = "pasta_do_jogo"


@dataclass(frozen=True)
class Template:
    key: str
    label_key: str
    description_key: str
    values: dict[str, str] = field(default_factory=dict)


# Every template lists ALL the fields it knows, including the empty ones: switching templates
# has to clear what the previous one left (one's Windows platform and Proton, on the other's
# Linux game, would turn into a Wine install nobody asked for).
_BLANK = {
    "start_script": "", "start_args": "", "ports": "", "game_port": "", "query_port": "",
    "extra_port": "", "memory_mb": "", "cores": "", "disk_gb": "", "config_path": "",
    "config_files": "", "backup_paths": "", "player_source": "log", "join_re": "",
    "leave_re": "", "platform": "", "recipes": "", "shiftable": "",
}

# Both lines come from the real Satisfactory log. The leave line does not carry the name of
# who left, so the player list is approximate (the count is right).
_UNREAL_JOIN = "LogNet: Join succeeded: (?P<name>.+)"
_UNREAL_LEAVE = "LogNet: UNetConnection::Close:"


UNREAL_LINUX = Template(
    key="unreal-linux",
    label_key="catalog.template.unreal_linux",
    description_key="catalog.template.unreal_linux_help",
    values={
        **_BLANK,
        # `-log` sends the log to stdout (journald keeps it and the panel reads it); `-Port` is
        # the Unreal default for the game port (UDP).
        "start_args": "-log -Port={PORT}",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "30",
        # Every Unreal server keeps config and save under <Project>/Saved.
        "config_path": f"/opt/game/{PROJECT}/Saved/Config/LinuxServer",
        "config_files": (
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/Game.ini\n"
            f"/opt/game/{PROJECT}/Saved/Config/LinuxServer/GameUserSettings.ini"
        ),
        "backup_paths": f"/opt/game/{PROJECT}/Saved/SaveGames",
        "join_re": _UNREAL_JOIN,
        "leave_re": _UNREAL_LEAVE,
        # The arguments above receive {PORT}: the broker may pick the port.
        "shiftable": "1",
    },
)

UNREAL_WINDOWS = Template(
    key="unreal-windows",
    label_key="catalog.template.unreal_windows",
    description_key="catalog.template.unreal_windows_help",
    values={
        **_BLANK,
        # The .exe at the root of an Unreal server is only the bootstrap: without a UI it stays
        # up without ever spawning the server (that was the case with Icarus). Shipping is what opens the port.
        "start_script": f"{PROJECT}/Binaries/Win64/{PROJECT}Server-Win64-Shipping.exe",
        # -log would open a console WINDOW, stuck in an X display nobody sees; the pair -stdout
        # -FullStdOutLogOutput is what makes the log reach the journal (see games/icarus.env).
        "start_args": "-stdout -FullStdOutLogOutput -Port={PORT} -QueryPort={QUERY_PORT}",
        "ports": "7777/udp 27015/udp",
        "game_port": "7777",
        "query_port": "27015",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "30",
        "config_path": f"/opt/game/{PROJECT}/Saved/Config/WindowsServer",
        "config_files": (
            f"/opt/game/{PROJECT}/Saved/Config/WindowsServer/Game.ini\n"
            f"/opt/game/{PROJECT}/Saved/Config/WindowsServer/GameUserSettings.ini"
        ),
        "backup_paths": f"/opt/game/{PROJECT}/Saved/SaveGames",
        # The Steam query is already open for the server list; it is more reliable than the
        # log, which changes from game to game.
        "player_source": "a2s",
        # Proton, not wine: fsync/ntsync, which the distro wine does not have. Wine only if
        # Proton has been proven not to work with the game.
        "platform": "windows",
        "recipes": "proton",
        "shiftable": "1",
    },
)

UNITY_LINUX = Template(
    key="unity-linux",
    label_key="catalog.template.unity_linux",
    description_key="catalog.template.unity_linux_help",
    values={
        **_BLANK,
        "start_script": f"{EXECUTABLE}.x86_64",
        # -batchmode -nographics: without it Unity tries to open a video card. `-logFile -`
        # sends the log to stdout (journal), and not to ~/.config/unity3d/.../Player.log.
        "start_args": "-batchmode -nographics -logFile -",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "4096",
        "cores": "2",
        "disk_gb": "20",
        "config_path": "/opt/game",
    },
)

UNITY_WINDOWS = Template(
    key="unity-windows",
    label_key="catalog.template.unity_windows",
    description_key="catalog.template.unity_windows_help",
    values={
        **_BLANK,
        "start_script": f"{EXECUTABLE}.exe",
        "start_args": "-batchmode -nographics -logFile -",
        "ports": "7777/udp",
        "game_port": "7777",
        "memory_mb": "8192",
        "cores": "4",
        "disk_gb": "20",
        "config_path": "/opt/game",
        "platform": "windows",
        # The virtual X costs little and avoids the most common failure of a Unity server under
        # Proton: creating a window at startup and dying without a display (V Rising does that).
        "recipes": "proton xvfb",
    },
)

SOURCE = Template(
    key="source",
    label_key="catalog.template.source",
    description_key="catalog.template.source_help",
    values={
        **_BLANK,
        "start_script": "srcds_run",
        # -strictportbind: without it srcds silently jumps to the next free port, and the
        # firewall stays open on a port where the game is not.
        "start_args": f"-game {MOD} -console -strictportbind -port {{PORT}} +map MAPA +maxplayers 16",
        "ports": "27015/udp 27015/tcp",
        "game_port": "27015",
        "memory_mb": "2048",
        "cores": "2",
        "disk_gb": "20",
        # No config_files: Source's server.cfg is a list of console commands, not an .ini,
        # and the field-by-field form would read it wrong. The folder opens in the file editor.
        "config_path": f"/opt/game/{MOD}/cfg",
        # What the srcds console writes on join and on leave, with the name on both.
        "join_re": 'Client "(?P<name>.+?)" connected',
        "leave_re": "Dropped (?P<name>.+?) from server",
        "recipes": "steamclient-sdk64",
        "shiftable": "1",
    },
)

TEMPLATES = (UNREAL_LINUX, UNREAL_WINDOWS, UNITY_LINUX, UNITY_WINDOWS, SOURCE)
