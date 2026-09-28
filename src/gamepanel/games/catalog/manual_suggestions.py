"""Sugestoes de jogo mantidas A MAO, para o que o LinuxGSM nao cobre.

O LinuxGSM (suggestions.py, gerado) so conhece servidor com build Linux, entao todo jogo
cujo servidor e so de Windows ficava de fora da busca, e a pessoa ficava sem App ID, sem
portas e sem nada para comecar. Esta lista fecha esse buraco com o mesmo formato, mais o
que so jogo de Windows precisa (`platform` e `recipes`).

Diferente do suggestions.py, este arquivo SE EDITA: cada entrada foi escrita a partir da
documentacao do proprio jogo ou das imagens Docker da comunidade, e o motivo de cada escolha
vai nos `warnings`, que a tela mostra ao escolher. Jogo que ja virou curado (games/*.env,
como V Rising, Enshrouded e Icarus) NAO entra aqui: a busca ja o acha no catalogo, e uma
sugestao com a mesma chave viraria uma sobreposicao por cima do curado.

Regras (tests/gamebroker/unit/test_suggestions.py cobra as mesmas do gerado):
- tem de passar no `validate_dynamic` do broker;
- servidor so de Windows usa `proton`; `wine` so quando o Proton comprovadamente falha;
- sem segredo e sem encadeamento de shell no `start_args`.
"""
SOURCE = "curadoria do painel"

_PROTON_NOTE = ("Servidor so de Windows: roda pelo Proton (receita proton). Se nao subir, "
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
                  'O ASA nao publica query da Steam (a lista e pela Epic): a contagem vem do log.',
                  'O mapa e o primeiro argumento (TheIsland_WP). Nome e senha do servidor ficam no '
                  'GameUserSettings.ini, nao no comando.',
                  'Precisa de ~13 GB de RAM so para subir o mapa padrao.']},
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
                  'As regras do mundo ficam no SandboxSettings.ini de cada mundo, que so nasce no '
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
                  'A 7778/UDP e a porta do jogo + 1, aberta sozinha pelo servidor: por isso ele nao '
                  'anda de porta (o broker nao tem como avisa-la).',
                  'O save inteiro e o game.db em ConanSandbox/Saved.']},
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
                  'servidor cria em /opt/game/userdata no primeiro start: nao ha como passa-las pelo '
                  'comando, entao ele fica nas portas padrao.',
                  'O servidor cria janela na largada: por isso a receita xvfb.']},
)
