"""Game suggestions maintained BY HAND, for what LinuxGSM does not cover.

LinuxGSM (suggestions.py, generated) only knows servers with a Linux build, so every game
whose server is Windows-only was left out of the search, and the person ended up with no App
ID, no ports and nothing to start from. This list closes that gap with the same format, plus
what only a Windows game needs (`platform` and `recipes`).

Unlike suggestions.py, this file IS EDITED: each entry was written from the game's own
documentation or from the community Docker images, and the reason for each choice goes into
the `warnings`, which the screen shows when it is picked. A game that has already become
curated (games/*.env, like V Rising, Enshrouded and Icarus) does NOT go here: the search
already finds it in the catalog, and a suggestion with the same key would become an override
on top of the curated one.

Rules (tests/gamebroker/unit/test_suggestions.py checks the same ones as for the generated file):
- it has to pass the broker's `validate_dynamic`;
- a Windows-only server uses `proton`; `wine` only when Proton has been proven to fail;
- no secrets and no shell chaining in `start_args`.
"""
SOURCE = "curadoria do painel"

_PROTON_NOTE = ("Servidor só de Windows: roda pelo Proton (receita proton). Se não subir, "
                "troque para wine e anote o motivo.")

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
     'recipes': ['proton'],
     'config_path': '/opt/game/ShooterGame/Saved/Config/WindowsServer',
     'config_files': ['/opt/game/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini',
                      '/opt/game/ShooterGame/Saved/Config/WindowsServer/Game.ini'],
     'backup_paths': ['/opt/game/ShooterGame/Saved/SavedArks'],
     'player_source': 'log',
     'memory_mb': 16384, 'cores': 4, 'disk_gb': 50,
     'warnings': [_PROTON_NOTE,
                  'O ASA não publica query da Steam (a lista é pela Epic): a contagem vem do log.',
                  'O mapa é o primeiro argumento (TheIsland_WP). Nome e senha do servidor ficam no '
                  'GameUserSettings.ini, não no comando.',
                  'Precisa de ~13 GB de RAM só para subir o mapa padrão.']},
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
                  'As regras do mundo ficam no SandboxSettings.ini de cada mundo, que só nasce no '
                  'primeiro start (Saved/SaveGames/Server/Worlds/<mundo>/).']},
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
     'recipes': ['proton'],
     'config_path': '/opt/game/ConanSandbox/Saved/Config/WindowsServer',
     'config_files': ['/opt/game/ConanSandbox/Saved/Config/WindowsServer/ServerSettings.ini',
                      '/opt/game/ConanSandbox/Saved/Config/WindowsServer/Engine.ini'],
     'backup_paths': ['/opt/game/ConanSandbox/Saved'],
     'player_source': 'a2s',
     'memory_mb': 8192, 'cores': 4, 'disk_gb': 40,
     'warnings': [_PROTON_NOTE,
                  'A 7778/UDP é a porta do jogo + 1, aberta sozinha pelo servidor: por isso ele não '
                  'anda de porta (o broker não tem como avisá-la).',
                  'O save inteiro é o game.db em ConanSandbox/Saved.']},
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
                  'As portas (GamePort, QueryPort, BlobSyncPort) moram no dedicatedserver.cfg, que o '
                  'servidor cria em /opt/game/userdata no primeiro start: não há como passá-las pelo '
                  'comando, então ele fica nas portas padrão.',
                  'O servidor cria janela na largada: por isso a receita xvfb.']},
)
