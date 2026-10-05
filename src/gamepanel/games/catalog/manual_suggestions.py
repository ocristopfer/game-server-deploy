"""Game suggestions maintained BY HAND, for what LinuxGSM does not cover.

LinuxGSM (suggestions.py, generated) only knows servers with a Linux build, so every game
whose server is Windows-only was left out of the search, and the person ended up with no App
ID, no ports and nothing to start from. This list closes that gap with the same format, plus
what only a Windows game needs (`platform` and `recipes`).

Unlike suggestions.py, this file IS EDITED: each entry was written from the game's own
documentation or from the community Docker images, and the reason for each choice goes into
the `warnings` (as i18n catalog keys), which the screen shows when it is picked. A game that has already become
curated (games/*.env, like V Rising, Enshrouded and Icarus) does NOT go here: the search
already finds it in the catalog, and a suggestion with the same key would become an override
on top of the curated one.

Rules (tests/gamebroker/unit/test_suggestions.py checks the same ones as for the generated file):
- it has to pass the broker's `validate_dynamic`;
- a Windows-only server uses `proton`; `wine` only when Proton has been proven to fail;
- no secrets and no shell chaining in `start_args`.
"""
# The source and the `warnings` are i18n catalog KEYS, not text: the search sends them to the screen
# of whoever is looking, in that person's language (`search.result` translates them on the way out).
# Text written here would come out in Portuguese on the English screen.
SOURCE = "catalog.source.manual"

_PROTON_NOTE = "catalog.suggestion.proton_note"

SUGGESTIONS = (
    {'appid': 2430930,
     'name': 'ARK: Survival Ascended',
     'key': 'ark-ascended',
     'ports': '7777/udp',
     'game_port': 7777,
     'query_port': 0,
     'extra_port': 0,
     'start_script': 'ShooterGame/Binaries/Win64/ArkAscendedServer.exe',
     'start_args': 'TheIsland_WP?listen?Port={PORT} -server -log -NoBattlEye',
     'shiftable': True,
     'platform': 'windows',
     # Measured in Docker (GE-Proton11-5): without the virtual X and a software Vulkan driver the
     # server dies at boot inside d3d12/dxgi (it creates a Direct3D 12 device even headless).
     'recipes': ['proton', 'xvfb', 'vulkan'],
     'config_path': '/opt/game/ShooterGame/Saved/Config/WindowsServer',
     'config_files': ['/opt/game/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini',
                      '/opt/game/ShooterGame/Saved/Config/WindowsServer/Game.ini'],
     'backup_paths': ['/opt/game/ShooterGame/Saved/SavedArks'],
     'player_source': 'log',
     'memory_mb': 16384, 'cores': 4, 'disk_gb': 50,
     'warnings': [_PROTON_NOTE,
                  'catalog.suggestion.ark_ascended.no_steam_query',
                  'catalog.suggestion.ark_ascended.map_argument',
                  'catalog.suggestion.ark_ascended.memory',
                  'catalog.suggestion.ark_ascended.vulkan']},
    {'appid': 2857200,
     'name': 'Abiotic Factor',
     'key': 'abiotic-factor',
     'ports': '7777/udp 27015/udp',
     'game_port': 7777,
     'query_port': 27015,
     'extra_port': 0,
     'start_script': 'AbioticFactor/Binaries/Win64/AbioticFactorServer-Win64-Shipping.exe',
     'start_args': '-stdout -FullStdOutLogOutput -useperfthreads -NoAsyncLoadingThread '
                   '-PORT={PORT} -QueryPort={QUERY_PORT}',
     'shiftable': True,
     'platform': 'windows',
     'recipes': ['proton'],
     'config_path': '/opt/game/AbioticFactor/Saved',
     'config_files': [],
     'backup_paths': ['/opt/game/AbioticFactor/Saved/SaveGames'],
     'player_source': 'a2s',
     'memory_mb': 8192, 'cores': 4, 'disk_gb': 20,
     'warnings': [_PROTON_NOTE,
                  'catalog.suggestion.abiotic_factor.sandbox_settings']},
    {'appid': 443030,
     'name': 'Conan Exiles',
     'key': 'conan-exiles',
     'ports': '7777/udp 7778/udp 27015/udp',
     'game_port': 7777,
     'query_port': 27015,
     'extra_port': 0,
     'start_script': 'ConanSandbox/Binaries/Win64/ConanSandboxServer-Win64-Shipping.exe',
     'start_args': '-stdout -FullStdOutLogOutput -Port={PORT} -QueryPort={QUERY_PORT}',
     'shiftable': False,
     'platform': 'windows',
     # Measured in Docker (GE-Proton11-5): without the virtual X the server hangs forever right
     # after mounting its paks (zero CPU, log stopped). There is no steam_appid.txt next to the
     # .exe, so the client appid goes explicitly: with 0 it answers A2S as appid 0 and the
     # game's server browser never lists it.
     'recipes': ['proton', 'xvfb'],
     'client_app_id': 440900,
     'config_path': '/opt/game/ConanSandbox/Saved/Config/WindowsServer',
     'config_files': ['/opt/game/ConanSandbox/Saved/Config/WindowsServer/ServerSettings.ini',
                      '/opt/game/ConanSandbox/Saved/Config/WindowsServer/Engine.ini'],
     'backup_paths': ['/opt/game/ConanSandbox/Saved'],
     'player_source': 'a2s',
     'memory_mb': 8192, 'cores': 4, 'disk_gb': 40,
     'warnings': [_PROTON_NOTE,
                  'catalog.suggestion.conan_exiles.port_plus_one',
                  'catalog.suggestion.conan_exiles.save',
                  'catalog.suggestion.conan_exiles.xvfb_appid']},
    {'appid': 2465200,
     'name': 'Sons of the Forest',
     'key': 'sons-of-the-forest',
     'ports': '8766/udp 27016/udp 9700/udp',
     'game_port': 8766,
     'query_port': 27016,
     'extra_port': 0,
     'start_script': 'SonsOfTheForestDS.exe',
     'start_args': '-userdatapath /opt/game/userdata',
     'shiftable': False,
     'platform': 'windows',
     'recipes': ['proton', 'xvfb'],
     'config_path': '/opt/game/userdata',
     'config_files': [],
     'backup_paths': ['/opt/game/userdata/Saves'],
     'player_source': 'a2s',
     'memory_mb': 8192, 'cores': 4, 'disk_gb': 20,
     'warnings': [_PROTON_NOTE,
                  'catalog.suggestion.sons_of_the_forest.ports',
                  'catalog.suggestion.sons_of_the_forest.xvfb']},
)
