# Game Server Deploy (Proxmox LXC ou Docker + SteamCMD)

Deploy simplificado de servidores dedicados de jogos, inspirado no
[LinuxGSM](https://github.com/GameServerManagers/LinuxGSM) porem muito mais simples: um
comando cria o container, instala o SteamCMD, baixa o jogo, cria o servico e no final
mostra **quais portas redirecionar no roteador**.

Dois destinos, a mesma definicao de jogo (`games/<jogo>.env`) nos dois:

| Destino | Comando | Quando usar |
|---------|---------|-------------|
| **LXC no Proxmox** | `.\deploy\game\deploy-game.ps1 -Game palworld` | voce tem um Proxmox e quer o jogo num container proprio, com systemd de verdade |
| **Docker** | `.\deploy\game\deploy-docker.ps1 -Game palworld` | qualquer maquina com Docker (ate o seu PC), sem Proxmox no caminho |

No caminho Proxmox o `.ps1` roda no Windows, envia o bundle via SSH para o host e executa
o `provision-game-lxc.sh` la (que usa `pct`). No caminho Docker o mesmo `.ps1` gera a
stack, constroi a imagem e sobe o container. Nos dois, o servidor termina o deploy **ja
cadastrado no painel**.

## Pre-requisitos

- Acesso SSH como `root` ao host Proxmox (por chave de preferencia — com senha o
  script pede a senha 3x, uma por etapa)
- `ssh` e `scp` disponiveis no Windows (nativos no Windows 10/11)

## Uso

### Modo automatico (tudo via .env)

```powershell
Copy-Item .env.example .env   # edite CTID, storage, rede, memoria, cores, disco...
.\deploy\game\deploy-game.ps1 -Game dragonwilds
```

### Modo interativo (pergunta cada valor)

```powershell
.\deploy\game\deploy-game.ps1 -Game dragonwilds -Interactive
```

Os valores do `.env` (se existir) viram os defaults dos prompts — Enter aceita.

### Deploy generico por App ID da Steam

```powershell
.\deploy\game\deploy-game.ps1 -AppId 4019830
```

Use o App ID do **servidor dedicado** (consulte no [SteamDB](https://steamdb.info)).
O script tenta detectar automaticamente o script de start (`*.sh` na raiz da instalacao).
Se o jogo precisar de argumentos ou tiver portas conhecidas, crie um `games/<nome>.env`
a partir do `games/_template.env`.

## O que o script faz

1. Baixa o template Debian (se necessario) e cria o LXC (`pct create`) com os recursos
   definidos no `.env` — ou os recomendados do jogo, se voce deixar em branco
2. Instala dependencias (`lib32gcc-s1` etc.), cria o usuario `steam` e instala o SteamCMD
   em `/opt/steamcmd` (pula se ja existir)
3. Instala/valida o jogo em `/opt/game` via `app_update <id> validate` (login anonimo)
4. Cria o servico systemd `<jogo>.service` (start no boot, restart em falha) e os
   atalhos `update-game`, `game-restart` etc. dentro do CT
5. Sobe o servidor, valida que ficou ativo e imprime o resumo com **as portas a redirecionar**
6. **Cadastra o servidor no painel** (`--register-server`), com IP do CT, unit systemd,
   portas, forma de contar jogadores e arquivos de configuracao — a tela **Config** ja
   abre pronta. `-NoRegister` pula esta etapa

O passo 2 tambem instala o `sshd` no CT e autoriza a chave do
[painel administrativo](#painel-administrativo-web) — sem ela o servidor apareceria
cadastrado na tela mas sem responder. A chave e lida do proprio painel (`ADMIN_CTID`, ou
`ADMIN_HOST`/`ADMIN_IP_CIDR` quando ele nao mora neste Proxmox); `PANEL_PUBKEY` no `.env`
continua valendo e tem prioridade.

Rodar de novo e idempotente: atualiza config do CT e revalida o jogo. `RECREATE_CT=1` destroi e recria.

## Um container por jogo

Cada jogo mora no proprio CT, com IP proprio. No `.env`, qualquer chave da secao
"Container LXC" pode ser especializada por jogo com o sufixo `_<GAME_KEY em maiusculas>`:

```ini
CTID_DRAGONWILDS=210
IP_CIDR_DRAGONWILDS=192.168.2.20/24

CTID_PALWORLD=211
IP_CIDR_PALWORLD=192.168.2.21/24
MEMORY_PALWORLD=16384        # vale para qualquer chave: CORES_, ROOTFS_SIZE_GB_, SWAP_...
```

O `CTID`/`IP_CIDR` sem sufixo continuam existindo como **fallback**: valem para o deploy
generico (`-AppId`) e para jogos sem bloco proprio. O hostname do CT ja e o nome do jogo,
entao nao precisa de `HOSTNAME_OVERRIDE`.

Como o deploy e idempotente **por CTID**, apontar dois jogos para o mesmo id nao criaria um
container novo — reconfiguraria o que ja existe e trocaria o jogo que roda la dentro. Por
isso o `deploy-game.ps1` para antes de enviar qualquer coisa se o CTID ou o IP resolvido ja
for de outro jogo ou do painel:

```
THROW: CTID 210 ja pertence ao jogo DRAGONWILDS (CTID_DRAGONWILDS no .env).
       Defina CTID_SATISFACTORY com um id livre.
```

No inicio de cada deploy o script imprime o alvo resolvido — confira antes de deixar rodar:

```
Valores especificos de SATISFACTORY: CTID, IP_CIDR
Alvo: CT 212 (satisfactory) em 192.168.2.22/24
```

Layout de referencia (o do `.env.example`):

| CTID | Jogo | IP |
|------|------|-----|
| 209 | gamepanel (painel) | 192.168.2.19 |
| 210 | dragonwilds | 192.168.2.20 |
| 211 | palworld | 192.168.2.21 |
| 212 | satisfactory | 192.168.2.22 |
| 213 | enshrouded | 192.168.2.23 |
| 214 | dayz | 192.168.2.24 |
| 215 | icarus | 192.168.2.25 |
| 219 | fallback / `-AppId` | 192.168.2.29 |

## Jogos definidos

| Jogo | Comando | Portas |
|------|---------|--------|
| RuneScape: Dragonwilds | `.\deploy\game\deploy-game.ps1 -Game dragonwilds` | 7777/udp |
| Palworld | `.\deploy\game\deploy-game.ps1 -Game palworld` | 8211/udp, 27015/udp |
| Satisfactory | `.\deploy\game\deploy-game.ps1 -Game satisfactory` | 7787/udp, 7787/tcp |
| Enshrouded | `.\deploy\game\deploy-game.ps1 -Game enshrouded` | 15636/udp, 15637/udp |
| DayZ | `.\deploy\game\deploy-game.ps1 -Game dayz` | 2302-2304/udp, 27016/udp |
| Icarus | `.\deploy\game\deploy-game.ps1 -Game icarus` | 17777/udp, 27017/udp |
| Valheim | `.\deploy\game\deploy-game.ps1 -Game valheim` | 2456/udp, 2457/udp |
| V Rising | `.\deploy\game\deploy-game.ps1 -Game vrising` | 9876/udp, 9877/udp |

Troque `deploy-game.ps1` por `deploy-docker.ps1` para rodar em Docker. Alem da
instalacao, cada `games/<jogo>.env` diz ao painel onde fica a configuracao
(`CONFIG_PATH`/`CONFIG_FILES`), o que guardar no backup (`BACKUP_PATHS`) e como contar
jogadores (`QUERY_PORT`/`PLAYER_SOURCE`) — e o que faz o servidor nascer cadastrado, com
a tela **Config** pronta e o **Backup** apontado para o save certo.

### Jogos sem build Linux: wine ou Proton

Enshrouded, Icarus e V Rising so publicam servidor para Windows. O deploy baixa o build Windows
(`STEAM_PLATFORM=windows`) e roda o `.exe` dentro do CT com o runtime escolhido em
`games/<jogo>.env`:

| Variavel | Para que serve |
|----------|----------------|
| `WINDOWS_RUNTIME` | `wine` (pacote da distro), `proton` (Proton-GE baixado do GitHub) ou vazio para jogo nativo |
| `PROTON_VERSION` | tag fixa do Proton-GE, ex. `GE-Proton11-5` |
| `WINE_DLL_OVERRIDES` | vai para `WINEDLLOVERRIDES`; padrao `mscoree,mshtml=` |
| `WINDOWS_RUNTIME_XVFB` | `1` quando o `.exe` cria janela mesmo headless |

O `provision-game-lxc.sh` instala o runtime, grava `/etc/game-runtime.env` e cria o comando
**`win-run`** dentro do CT. O script de start do jogo vira uma linha:

```bash
exec win-run /opt/game/servidor.exe "$@"
```

Trocar de runtime e mudar `WINDOWS_RUNTIME` e redeployar - nenhum script de jogo muda.

**Por que Proton e nao o wine da distro.** O wine do Debian nao tem esync nem fsync: cada
mutex/evento/semaforo do Windows vira syscall cara, e em servidor muito multi-thread isso
vira gargalo de CPU. O Proton-GE traz o proprio wine com **fsync** (`futex_waitv`, kernel
>= 5.16) ligado por padrao. Por isso o Enshrouded usa `proton`.

**Regra para jogo novo sem build Linux: Proton primeiro.** Todo `games/*.env`, modelo e
sugestao de servidor so de Windows nasce com `proton`; `wine` direto so quando o Proton ja
foi tentado e nao funciona com aquele jogo, e o motivo fica escrito no `.env`.

**O `UMU_ID` tem que ser o appid REAL do jogo.** Esta e a segunda armadilha do Proton fora
do Steam, e ela e silenciosa: com um `UMU_ID` qualquer (0, por exemplo) o Proton propaga
`SteamAppId=0` e a **API de game server da Steam falha**. O log do jogo mostra
`[AppId: 0] Game Server API initialized 0` em vez de `[AppId: 1149460] ... 1`, a porta de
query nunca abre, e o servidor fica de pe, invisivel no navegador e sem contagem no painel.

O `win-run` resolve sozinho: le o `steam_appid.txt` que acompanha o executavel e exporta
`UMU_ID`/`SteamAppId`/`SteamGameId` com esse valor. Se o jogo nao tiver o arquivo, cai em
`0` - o que e correto para quem nao usa Steam (Enshrouded).

Os dois jogos rodam em `proton`: Enshrouded porque nao depende da Steam, Icarus porque com
o appid certo a Steam inicializa normalmente **e** ele ainda ganha o ntsync.

**O detalhe que faz servidor dedicado funcionar sob Proton.** Por padrao o Proton lanca o
jogo atraves do shim `steam.exe`, que espera um **cliente Steam vivo** para completar um
handshake. Num servidor dedicado nao existe cliente Steam, e o resultado e um deadlock
silencioso: processo de pe, RSS parado em ~34MB, **zero CPU**, nenhuma porta aberta e nem o
log do proprio jogo criado. O `systemd` reporta `active` o tempo todo.

O diagnostico que fecha isso: a thread principal fica em `wchan=pipe_read`, com o processo
segurando as duas pontas do mesmo pipe.

A saida esta no proprio `proton`: com **`UMU_ID` definido** e o executavel passado em
**caminho Windows** (`Z:\opt\game\servidor.exe`), ele segue por
`"Executable is inside wine prefix, launching normally"` e chama o wine direto, sem shim.
O `win-run` faz as duas coisas automaticamente. Depois disso o mesmo servidor carrega em
menos de 20s, com 35 threads e a thread principal em `ntsync_schedule`.

Coisas que **nao** eram o problema, ja testadas e descartadas (para ninguem repetir):
`LimitNOFILE`, diretorio de trabalho, prefixo corrompido, systemd vs execucao manual, e
desligar o `lsteamclient` (ele chega desligado ao processo e o travamento continua).

**Cuidado com os overrides.** Desligar `explorer.exe`/`services.exe`/`wbemprox.dll` parece
economia obvia em servidor headless, mas foi **medido e reprovado**: sob Proton, cada um dos
tres trava o Enshrouded na largada. No Icarus, sem `explorer.exe` o servidor morre com
`nodrv_CreateWindow`. Por isso o padrao e conservador. Lembre que o Proton ja injeta os
proprios overrides por cima do seu (`steam.exe=b`, `winebth.sys=d`, `d3d11=n`...).

A unit systemd ganha `LimitNOFILE=1048576` quando ha runtime de Windows: esync/fsync criam um
descritor por objeto de sincronizacao e o limite padrao (1024) derruba o servidor sob carga.

**Ganho extra opcional - `ntsync`.** O kernel do Proxmox 6.14 traz o modulo `ntsync`
(`/lib/modules/$(uname -r)/kernel/drivers/misc/ntsync.ko`), que implementa as primitivas do
NT dentro do kernel e e mais rapido que fsync. Ele **nao vem carregado**. Para usar, no host:

```bash
modprobe ntsync && echo ntsync > /etc/modules-load.d/ntsync.conf
ls -l /dev/ntsync
pct set <CTID> -dev0 /dev/ntsync,mode=0666   # expoe o device ao container
pct reboot <CTID>
```

Sem `/dev/ntsync` dentro do CT o Proton usa fsync normalmente - nao quebra nada, so nao
aproveita o caminho mais rapido.

### Mapa de portas e NAT

Cada jogo tem CT e IP proprios, entao **na LAN nao existe conflito**: dois servidores
poderiam usar a mesma porta em IPs diferentes sem se atrapalhar. O conflito aparece no
**roteador**, onde existe um IP publico so e cada porta externa aponta para um unico
destino. Por isso as portas abaixo sao unicas entre si — nao por exigencia dos jogos,
mas para que todo redirecionamento seja **1:1** (porta externa = porta interna).

| Jogo | Destino | Redirecionar no roteador | Nunca redirecionar |
|------|---------|--------------------------|--------------------|
| Dragonwilds | 192.168.2.20 | `7777/udp` (+ `7778`, `7779` se criar mundos extras) | — |
| Palworld | 192.168.2.21 | `8211/udp`, `27015/udp` | REST `8212/tcp`, RCON `25575/tcp` |
| Satisfactory | 192.168.2.22 | `7787/udp`, `7787/tcp` | — |
| Enshrouded | 192.168.2.23 | `15636/udp`, `15637/udp` | — |
| DayZ | 192.168.2.24 | `2302/udp`, `2303/udp`, `2304/udp`, `27016/udp` | — |
| Icarus | 192.168.2.25 | `17777/udp`, `27017/udp` | — |
| V Rising | (CT do broker) | `9876/udp`, `9877/udp` | RCON `25575/tcp` |

**O 1:1 nao e preferencia estetica** nos jogos que publicam query A2S — Palworld, DayZ e
Icarus. Esses servidores anunciam a *propria* porta ao master server da Steam; se o NAT
traduzir `27020` externo para `27015` interno, a Steam divulga uma porta que nao existe do
lado de fora e o servidor fica invisivel no navegador, mesmo respondendo. Nos jogos de IP
direto (Dragonwilds, Satisfactory, Enshrouded) uma traducao assimetrica funcionaria, mas
manter tudo 1:1 evita ter uma porta na LAN e outra na internet.

**Regra de desempate: antiguidade.** Quando dois jogos querem a mesma porta, ela fica com
o que foi configurado primeiro (a ordem dos CTIDs conta essa historia: 210 dragonwilds,
211 palworld, 212 satisfactory, 213 enshrouded, 214 dayz, 215 icarus). Quem chega depois
muda. Isso evita mexer em servidor com gente jogando e em bookmark ja salvo no cliente —
o custo cai sempre no jogo mais novo, que ainda nao tem historico.

As duas colisoes resolvidas por essa regra:

- **`7777`** — disputada por Dragonwilds (CT 210) e Satisfactory (CT 212). Ficou com o
  **Dragonwilds**, mais antigo, que ainda reserva 7778/7779 para mundos extras. O
  Satisfactory foi para **7787**, levando junto o TCP da API de gerenciamento
- **`27015`** — query padrao da Steam, disputada por Palworld (CT 211) e Icarus (CT 215).
  Ficou com o **Palworld**; o Icarus foi para **27017** (a 27016 e do DayZ)

Nada de painel, SSH ou API de jogo vai para a internet. O painel (192.168.2.19) e acessado
pela LAN ou por VPN; o SSH dos containers so responde a partir do painel.

#### Como isso vira regra no OPNsense

Existe um alias de porta por jogo (`JOGO_<Nome>`), versionado em
[`aliases.json`](aliases.json), e uma regra de port forward por jogo, em
[`download_rules.csv`](download_rules.csv). O molde da regra e sempre o mesmo:

| Campo | Valor |
|-------|-------|
| Interface | WAN |
| Protocol | UDP (so o Satisfactory usa **TCP/UDP**) |
| Destination | WAN address |
| Destination port range | o alias do jogo |
| Redirect target IP | o IP do CT do jogo |
| Redirect target port | **o mesmo alias** |

O mesmo alias nos dois campos de porta e o que produz o mapeamento 1:1 — sem isso, os
jogos com query A2S somem do navegador da Steam. Alias de porta no OPNsense **nao guarda
protocolo**: ele vem da regra, e por isso o Satisfactory precisa de TCP/UDP explicito
(UDP e o jogo, TCP e a API de gerenciamento, ambos na mesma porta).

O CSV exportado **nao traz as colunas de destination nem de destination port**, entao ele
serve como referencia e backup, nao como fonte de importacao: reimportar pode deixar esses
campos vazios, e uma regra sem porta de destino casa *qualquer* porta para aquele host.

### RuneScape: Dragonwilds — notas

- App do servidor dedicado: `4019830` (build Linux nativo, `RSDragonwildsServer.sh`)
- Porta padrao **7777/UDP**; cada mundo adicional usa a seguinte (7778, 7779...), entao a
  faixa 7777-7779 fica reservada a este jogo — veja [Mapa de portas e NAT](#mapa-de-portas-e-nat)
- Config criada no primeiro start (localize com `find /opt/game -name DedicatedServer.ini`):
  nome do servidor, senha do mundo, senha de admin, OwnerID. Pare o servidor antes de editar!
- Limite de jogadores: fixo em 6 (travado pela Jagex, nao configuravel)
- **Nao publica nada consultavel**: nem query A2S da Steam, nem RCON, nem API HTTP. O
  `DedicatedServer.ini` nao tem chave para isso e o jogo nao tem navegador de servidores
  (entra-se por IP direto). Guias de hosting que mandam abrir `27015` estao copiando
  texto de outros jogos Unreal. A contagem de jogadores no painel so pode vir do log
- Saves: `/opt/game/RSDragonwilds/Saved/SaveGames/`

### Palworld — notas

- App do servidor dedicado: `2394010` (build Linux nativo, `PalServer.sh`)
- Portas: **8211/UDP** (jogo) e **27015/UDP** (query da Steam, necessaria para aparecer
  na lista da comunidade). A **API REST (8212/TCP)** e o RCON (25575/TCP) so existem se
  habilitados no `.ini` — nao redirecione nenhum dos dois no roteador
- Tres formas de contar jogadores, da melhor para a pior: **API REST** (`8212/tcp`, da os
  nomes, o level e o ping), **A2S** (`27015/udp`, so a contagem — o Palworld nao responde
  `A2S_PLAYER`) e o log. Para ligar a REST: `RESTAPIEnabled=True`, `RESTAPIPort=8212` e
  uma `AdminPassword` forte; no painel, **Configurar contagem > API HTTP** com
  `http://127.0.0.1:8212/v1/api/players` e `basic:admin:<a senha>`.
  O RCON foi marcado como *deprecated* pela Pocketpair em favor da REST
- O deploy cria o symlink `~steam/.steam/sdk64/steamclient.so` (exigido pelo `PalServer.sh`)
  e semeia o `PalWorldSettings.ini` a partir do `DefaultPalWorldSettings.ini`
- Config: `/opt/game/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini` — tudo fica dentro
  de `OptionSettings=(...)`, em uma unica linha: `ServerName`, `ServerPassword`,
  `AdminPassword`, `ServerPlayerMaxNum` (max 32), `PublicPort`, taxas de XP/captura etc.
  Pare o servidor antes de editar (`systemctl stop palworld`)
- Memoria: o servidor cresce com o mundo/jogadores — recomendado 16GB (8GB e o minimo pratico)
- Saves: `/opt/game/Pal/Saved/SaveGames/0/`

### Satisfactory — notas

- App do servidor dedicado: `1690800` (build Linux nativo, `FactoryServer.sh`)
- Portas: uma so, em dois protocolos — **7787/UDP** (jogo) e **7787/TCP** (API HTTPS de
  gerenciamento que o cliente usa para adotar e configurar o servidor). Abra as duas.
  O padrao do jogo e 7777, cedida ao Dragonwilds por antiguidade
  ([Mapa de portas e NAT](#mapa-de-portas-e-nat)). As portas antigas 15000/15777 sairam na 1.0
- O deploy cria o symlink `~steam/.steam/sdk64/steamclient.so` (sem ele o servidor sobe
  mas nao registra na Steam)
- Config: nao ha `.ini` para preencher antes — no cliente, **Servidores > Adicionar servidor**
  com `IP:7787`, defina a senha de admin e reivindique o servidor. Ajustes finos depois em
  `/home/steam/.config/Epic/FactoryGame/Saved/Config/LinuxServer/`
  (`ServerSettings.ini`, `GameUserSettings.ini`), com o servidor parado
- Nao publica query A2S da Steam — a contagem de jogadores no painel vem do log
- Memoria: 12GB e o recomendado oficial; fabricas grandes passam disso, por isso 16GB
- Saves: `/home/steam/.config/Epic/FactoryGame/Saved/SaveGames/server/`

### Enshrouded — notas

- App do servidor dedicado: `2278520` — **sem build Linux**. O deploy baixa o build Windows
  (`STEAM_PLATFORM=windows`) e roda o `enshrouded_server.exe` via **Wine**, igual ao que o
  LinuxGSM e as imagens Docker da comunidade fazem
- Portas: **15637/UDP** e a principal (`queryPort`) — e o que o jogador digita no cliente.
  A `15636/UDP` (`gamePort`) saiu de uso no Content Update #2; abrir as duas nao atrapalha.
  Tudo UDP, nada de TCP
- A porta **nao** vai por linha de comando: o servidor le tudo do `enshrouded_server.json`.
  Se mudar a porta la, ajuste tambem `GAME_PORT`/`GAME_PORTS` em `games/enshrouded.env`
- Config: `/opt/game/enshrouded_server.json` — o deploy cria um modelo no primeiro run.
  **Troque as senhas** de `userGroups` (Admin / Friend / Guest): cada jogador entra com a
  senha do grupo dele, nao existe senha unica de servidor. `slotCount` vai ate 16.
  Pare o servidor antes de editar (`systemctl stop enshrouded`)
- Nao publica query A2S da Steam — a contagem de jogadores no painel vem do log
- Memoria: 16GB (recomendacao oficial para 16 slots, mais a folga do Wine).
  Disco: o build Windows passa de 12GB, por isso 40GB
- O primeiro start demora mais que o normal: o Wine monta o prefixo e o jogo gera o mundo.
  Acompanhe com `game-logs`
- Saves: `/opt/game/savegame/` (prefixo do Wine em `/home/steam/.wine-enshrouded`)

### Icarus — notas

- App do servidor dedicado: `2089300` — **sem build Linux**. Igual ao Enshrouded, o deploy
  baixa o build Windows (`STEAM_PLATFORM=windows`) e roda o `IcarusServer.exe` via **Wine**
- Portas: **17777/UDP** (jogo) e **27017/UDP** (query da Steam, usada pelo navegador de
  servidores do proprio Icarus). As duas vao por linha de comando (`-PORT=` / `-QueryPort=`),
  entao mudar `GAME_PORT` no `.env` basta. Tudo UDP. A query nao fica na 27015 padrao
  porque o Palworld ja a ocupa — veja [Mapa de portas e NAT](#mapa-de-portas-e-nat)
- Publica **A2S** na 27017 — a contagem de jogadores no painel vem da query, nao do log.
  Nao ha RCON nem API HTTP: a administracao e feita dentro do jogo, com o `AdminPassword`
- Config: `/opt/game/Icarus/Saved/Config/WindowsServer/ServerSettings.ini` — o jogo so o
  cria ao gerar o primeiro prospect, entao o deploy semeia um modelo. **Troque o
  `AdminPassword`**; ajuste `SessionName`, `MaxPlayers` e `JoinPassword` (vazio = aberto).
  Pare o servidor antes de editar (`systemctl stop icarus`): o jogo reescreve esse arquivo
  ao sair (`LastProspectName` etc.)
- `ShutdownIfEmptyFor` / `ShutdownIfNotJoinedFor` vem em 300s (o servidor se desliga sozinho
  quando ninguem entra). O systemd reinicia logo depois; se preferir o servidor sempre de pe,
  aumente os dois valores
- O mundo nao nasce com o servidor: quem cria o **prospect** e um jogador conectado, pelo
  menu do jogo (ou preencha `CreateProspect`/`LoadProspect` no `.ini`)
- **`vm.max_map_count`**: a Unreal sob Wine morre com `Freeing X bytes from backup pool` se
  o valor for o padrao. Em CT nao privilegiado o `sysctl` de dentro nao pega — ajuste no
  **host Proxmox**: `sysctl -w vm.max_map_count=262144` e
  `echo "vm.max_map_count=262144" > /etc/sysctl.d/99-icarus.conf`
- **Precisa de X virtual (`xvfb`)**, e essa e a diferenca em relacao ao Enshrouded: o
  build de servidor do Icarus tenta criar uma *janela* na largada, mesmo sem renderizar
  nada. Sem display o Wine morre em ~1s com `nodrv_CreateWindow: Application tried to
  create a window, but no driver could be loaded` e **exit 41**, antes de sequer criar
  `Saved/Logs/`. Por isso o `PRE_INSTALL_CMD` instala o `xvfb` e o wrapper roda o Wine
  sob `xvfb-run -a`. O **`xauth` vai explicito** na mesma linha do `apt-get`: ele e so um
  *Recommends* do `xvfb`, entao com `--no-install-recommends` nao vem junto e o `xvfb-run`
  morre com `error: xauth command not found` (exit 3) antes de chegar no Wine
- **O wrapper chama o binario `Shipping` direto**, nao o `IcarusServer.exe` da raiz. Aquele
  tem so 256KB e e o *bootstrap* da Unreal: headless ele sobe, fica vivo gastando ~1s de CPU
  e **nunca gera o processo do servidor** — sem porta, sem log, e com o systemd reportando
  `active` o tempo todo. O binario real e `Icarus/Binaries/Win64/IcarusServer-Win64-Shipping.exe`
  (~108MB). No `ps`, um servidor sadio mostra ESSE binario, com RSS na casa dos GB;
  se aparecer so o `IcarusServer.exe` com ~17MB, e o bootstrap travado
- No journal aparece `XDG_RUNTIME_DIR is invalid or not set`: e ruido do `libwayland-client`
  em servico systemd ([bug 1093464](https://lists.debian.org/debian-wine/2025/12/msg00004.html)),
  nao e a causa de falha nenhuma. O wrapper define a variavel so para calar a mensagem
- Nao use `WINEDEBUG=-all` no wrapper: ele silencia as linhas `err:` do Wine, que sao a
  unica pista quando o `.exe` morre antes de gerar log proprio. O padrao aqui e `fixme-all`
- `START_ARGS` leva `-stdout -FullStdOutLogOutput` para a Unreal escrever no stdout do
  processo, e nao so no arquivo. Sem isso o `game-logs` fica **mudo com o servidor
  saudavel** (o unico stderr seria o do Wine), o que confunde na hora de diagnosticar.
  Nao use `-log`: ele abre uma janela de console que fica presa dentro do X virtual
- Memoria: 16GB (recomendacao oficial, mais a folga do Wine); o jogo e pesado em
  single-thread, entao core rapido vale mais que muitos cores.
  Disco: a instalacao ocupa ~10,5GB (1,1GB so de `.pdb`), por isso 32GB com folga
- O primeiro start demora mais que o normal: o Wine monta o prefixo. Acompanhe com `game-logs`
- Saves: `/opt/game/Icarus/Saved/PlayerData/` e `/opt/game/Icarus/Saved/Prospects/`
  (prefixo do Wine em `/home/steam/.wine-icarus`)

### V Rising — notas

- App do servidor dedicado: `1829350` — **sem build Linux**, e **fora do LinuxGSM** (por isso a
  busca do painel nao o achava). Roda pelo **Proton** com X virtual (`WINDOWS_RUNTIME_XVFB=1`):
  o servidor e Unity e cria janela na largada
- Portas: **9876/UDP** (jogo, a do Direct Connect) e **9877/UDP** (query da Steam). As duas vao
  por linha de comando (`-gamePort` / `-queryPort`) e vencem o que estiver no `.json`
- **Appid sob Proton**: o wrapper fixa `SteamAppId=1604030` (o do jogo) quando o depot nao traz
  `steam_appid.txt` — com 0 a query nunca abre, como aconteceu com o Icarus
- Config: `/opt/game/save-data/Settings/ServerHostSettings.json` (nome, senha, lista publica em
  `ListOnSteam`/`ListOnEOS`) e `ServerGameSettings.json` (regras do mundo). O deploy semeia os
  dois a partir dos padroes do proprio servidor. Admins: SteamID64 em `adminlist.txt`, na mesma
  pasta. Pare o servidor antes de editar (`systemctl stop vrising`)
- Log: o servidor so escreve em `/opt/game/logs/VRisingServer.log`; o wrapper o repete no
  journal com `tail -F`, e e dali que a tela de logs do painel le
- Saves: `/opt/game/save-data/Saves/` (o Backup do painel guarda Saves e Settings)
- Pelo painel: e curado e criavel, entao sai direto pela tela **Instancias**. **Nao foi testado
  ainda contra um CT de verdade** - se o Proton nao subir, `WINDOWS_RUNTIME=wine` e redeploy

### DayZ — notas

- App do servidor dedicado: `223350` (build **nativo Linux**, binario `DayZServer`)
- **Unico jogo daqui que nao baixa com login anonimo.** O depot do servidor exige uma
  conta Steam que **possua o DayZ** — veja [Jogos que exigem conta Steam](#jogos-que-exigem-conta-steam)
- Portas: **2302/UDP** (jogo), **2303** e **2304/UDP** (engine/Steam) e **27016/UDP**
  (`steamQueryPort`). Sem a 27016 o servidor nao aparece no navegador do cliente.
  Tudo UDP. No painel, cadastre **27016** como porta de consulta — o DayZ publica A2S
- O deploy cria o symlink `~steam/.steam/sdk64/steamclient.so`, as pastas `profiles/` e
  `battleye/`, e semeia o `serverDZ.cfg` (o exemplo que vem no pacote nao tras `steamQueryPort`)
- Config: `/opt/game/serverDZ.cfg` — `hostname`, `password` (entrada), `passwordAdmin`,
  `maxPlayers`, e o `template` da missao (`dayzOffline.chernarusplus` ou `dayzOffline.enoch`
  para Livonia). Pare o servidor antes de editar (`systemctl stop dayz`)
- Persistencia: `/opt/game/mpmissions/dayzOffline.chernarusplus/storage_1/` — o numero segue
  o `instanceId` do `serverDZ.cfg`. Logs e stats em `/opt/game/profiles/`
- Memoria: 8GB (vanilla com ~20 jogadores fica perto de 4GB; mods passam disso)

## Jogos que exigem conta Steam

Quase todo servidor dedicado baixa com `+login anonymous`. O DayZ nao: o depot esta atras
de uma conta que possua o jogo. Esses jogos marcam `STEAM_ANONYMOUS=0` no `games/<jogo>.env`,
e o deploy le as credenciais do `.env` — **nunca do `games/*.env`, que vai para o git**:

```ini
STEAM_USER=conta-dedicada
STEAM_PASS=senha-da-conta
```

Se a conta usa Steam Guard, o codigo vale poucos segundos — passe na hora do deploy em vez
de deixar no `.env`:

```powershell
.\deploy\game\deploy-game.ps1 -Game dayz -SteamGuardCode 12345
```

Sem credencial nenhuma, o deploy para antes de enviar qualquer coisa:

```
THROW: O servidor de dayz nao esta disponivel por login anonimo na Steam.
       Preencha STEAM_USER e STEAM_PASS no .env (conta que POSSUA o jogo) ou use -Interactive.
```

**Pelo painel (broker).** O DayZ tambem sai pela tela **Instancias** quando o broker tem uma
conta: `STEAM_USER`/`STEAM_PASS` no `broker.secrets.env` e `.\deploy\broker\deploy-broker.ps1`.
Ai nao ha como digitar codigo nenhum (o login acontece minutos depois do clique, dentro do CT
novo), entao a conta tem de estar **sem Steam Guard** — por isso uma conta DEDICADA a
servidores, que possua o jogo, e nunca a sua pessoal. Sem a conta o DayZ continua "manual"
no catalogo, com o motivo escrito ali.

**Adicionar ao catalogo um jogo que nao esta em lugar nenhum.** A tela **Catalogo** busca
por nome ou App ID em quatro lugares: os jogos que ja estao no catalogo (com um atalho para
**Criar instancia**), o LinuxGSM, os eggs do Pterodactyl (~40 jogos que o LinuxGSM nao tem,
metade so de Windows: Astroneer, Bannerlord, Space Engineers, Myth of Empires...) e uma lista
mantida a mao no painel (`manual_suggestions.py`: ARK: Survival Ascended, Abiotic Factor,
Conan Exiles, Sons of the Forest). Cada sugestao diz de qual fonte veio; quando o egg completa
um campo que o LinuxGSM deixou vazio (arquivos de config, portas), o aviso diz qual. Para
atualizar as duas listas geradas: `python tools/import-linuxgsm.py` e
`python tools/import-pterodactyl.py` (precisam de internet; o painel nao). Se nada casar, a tela
oferece links para o SteamDB (App ID do servidor dedicado) e uma busca das portas na web.
Quem abre esses links e o seu navegador; o painel continua sem ir a internet. Dai o caminho
e **Comecar de um modelo** pelo motor do jogo: Unreal (Linux ou Windows via Proton), Unity
(Linux ou Windows via Proton) e Source/srcds. Servidor de Windows cadastrado assim roda com
`.exe` direto no "Script de start": o instalador o chama pelo `win-run`. As receitas
`proton`/`wine` escolhem o runtime e `xvfb` liga o X virtual.

Detalhes de como a senha e tratada:

- Ela so aparece na **primeira** instalacao. Depois disso o SteamCMD guarda o token em
  `~steam/Steam/config/config.vdf` dentro do CT, e o `update-game`/`check-game-update`
  usam so `+login <usuario>` — a senha **nao** fica gravada nos scripts do container
- O `deploy.env` enviado ao Proxmox vai para `/root/game-deploy` com `chmod 600`, e a
  copia local em `%TEMP%` e apagada no fim do deploy
- Se o token expirar, o update automatico falha (nao trava: roda com `timeout` e sem stdin).
  Rode o deploy de novo com `-SteamGuardCode` para renovar
- Use uma conta **dedicada** ao servidor, nao a sua principal

> Recomendado: `-Interactive` pergunta a senha sem ecoar na tela, em vez de deixa-la no `.env`.

## Comandos uteis

O deploy instala atalhos no container. Eles funcionam **dos dois jeitos**: logado como root
dentro do CT (`pct enter <CTID>` ou SSH) ou direto do host Proxmox com `pct exec`.

| Atalho | O que faz |
|--------|-----------|
| `game-restart` | reinicia o servidor |
| `game-stop` | para o servidor |
| `game-start` | sobe o servidor |
| `game-status` | status do servico |
| `game-logs` | log ao vivo (aceita args do journalctl, ex.: `game-logs -n 50`) |
| `update-game` | atualiza o jogo via SteamCMD (para/atualiza/reinicia) |
| `check-game-update` | checa se ha update sem aplicar nada desnecessario |

```bash
# dentro do container
game-restart
game-logs

# a partir do host Proxmox
pct exec <CTID> -- game-restart
pct exec <CTID> -- game-status
pct exec <CTID> -- update-game
```

> Os atalhos ficam em `/usr/local/bin` com symlink em `/usr/bin`. O symlink existe porque
> `pct exec` nao usa shell de login e o PATH dele nao inclui `/usr/local/bin` — sem ele,
> `pct exec <CTID> -- update-game` falha com `Failed to exec`.
>
> Em containers criados antes desta versao os symlinks nao existem; recrie-os com
> `pct exec <CTID> -- bash -lc 'for f in update-game check-game-update; do ln -sfn /usr/local/bin/$f /usr/bin/$f; done'`
> ou rode o deploy novamente.

## Update automatico

O deploy instala um timer systemd (`game-update-check.timer`) que roda todo dia as 06:00
(configuravel via `UPDATE_SCHEDULE` no `.env`, formato OnCalendar). Ele compara o buildid
instalado com o mais recente da Steam e **so para/atualiza/reinicia o servidor quando ha
update de verdade** — sem update, nada e tocado. Desative com `AUTO_UPDATE=0`.

```bash
pct exec <CTID> -- systemctl list-timers game-update-check.timer   # proximo horario
pct exec <CTID> -- check-game-update                                # checar agora
pct exec <CTID> -- journalctl -u game-update-check.service -n 20   # log das checagens
```

## Deploy em Docker (sem Proxmox)

Mesmos jogos, mesma definicao em `games/<jogo>.env`, mesmo painel — so que em containers
Docker. Serve para rodar tudo no seu proprio PC, num NUC, num servidor qualquer com
Docker instalado, ou num Docker remoto.

```powershell
.\deploy\game\deploy-docker.ps1 -Panel                  # sobe o painel (http://localhost:8080)
.\deploy\game\deploy-docker.ps1 -Game palworld          # sobe o jogo e o cadastra no painel
.\deploy\game\deploy-docker.ps1 -Game dayz -SteamGuardCode 12345
.\deploy\game\deploy-docker.ps1 -Game palworld -Down    # para o servidor (o mundo fica no volume)
.\deploy\game\deploy-docker.ps1 -Game palworld -Recreate
```

Suba o painel **antes** do primeiro jogo: e dele que sai a chave SSH que o container do
jogo autoriza. Depois disso cada deploy de jogo ja nasce gerenciavel e **cadastrado**,
com o arquivo de configuracao apontado — a tela **Config** abre pronta.

### O que o deploy faz

1. Cria a rede `games` (e por ela que o painel fala com os jogos, por nome de container)
2. Gera a stack em `docker/stacks/<jogo>.yml` — da para ler antes de subir (o arquivo e
   regerado a cada deploy, entao ajuste o `.env`, nao o `.yml`)
3. Constroi a imagem `gamesrv-<jogo>` (Debian + SteamCMD + `sshd` + os atalhos do painel)
4. Sobe o container `game-<jogo>` com as portas do jogo publicadas e limites de
   memoria/CPU vindos de `MEMORY`/`CORES` do `.env` (ou do recomendado do jogo)
5. Cadastra o servidor no painel (`--register-server`), com portas, forma de contar
   jogadores e arquivos de configuracao

O container faz o mesmo que o `provision-game-lxc.sh` faz no LXC: instala o jogo pelo
SteamCMD, roda os `PRE_INSTALL_CMD`/`POST_INSTALL_CMD` do jogo, detecta o script de start
e sobe o servidor. Como nao ha systemd dentro de um container, o papel dele e feito por um
`systemctl`/`journalctl` proprios (em `docker/gameserver/`) com **a mesma interface** que o
painel usa — por isso start/stop/restart, logs ao vivo, medidores e contagem de jogadores
funcionam igual nos dois destinos.

### Dados e atualizacoes

- Dois volumes por jogo: `game-<jogo>-data` (o jogo e os saves, em `/opt/game`) e
  `game-<jogo>-steam` (token da Steam e prefixo do Wine). **Recriar o container nao
  baixa o jogo de novo nem perde o mundo.**
- `restart: unless-stopped` e `stop_grace_period: 120s`: no `docker stop` o servidor
  recebe o TERM e tem tempo de salvar antes de morrer.
- Update automatico diario dentro do container (`UPDATE_TIME`, padrao 06:00), com a mesma
  regra do LXC: so atualiza se o buildid da Steam mudou. `AUTO_UPDATE=0` desliga.
- `UPDATE_ON_START=1` (ou `-UpdateOnStart`) revalida os arquivos do jogo a cada start.

```bash
docker logs -f game-palworld            # acompanhar o download/instalacao
docker exec game-palworld game-status
docker exec game-palworld game-logs -n 50
docker exec game-palworld update-game
docker exec -it game-palworld bash
```

### Docker remoto

`DOCKER_HOST` no `.env` (ou `-DockerHost`) manda o deploy para outra maquina, sem instalar
nada la alem do Docker:

```
DOCKER_HOST=ssh://root@192.168.1.50
```

A imagem e construida no destino (o contexto sobe pela conexao), entao nao ha bind mount
de caminho local — o que roda no seu PC roda igual no servidor.

### Portas e acesso

As portas de `GAME_PORTS` sao publicadas no host (`8211:8211/udp`...) — e o que voce
redireciona no roteador. O SSH do container **nao** e publicado: o painel entra pela rede
interna `games`. Se quiser entrar de fora, defina `SSH_PORT_<JOGO>` no `.env`.

Jogos que exigem conta Steam (DayZ) leem `STEAM_USER`/`STEAM_PASS` do `.env`; o deploy
escreve essas variaveis em `docker/stacks/<jogo>.secret.env` (fora do git) em vez de
deixa-las na stack.

## Painel administrativo (web)

Um container separado sobe um painel web para gerenciar todos os servidores: cadastrar,
ver status, **jogadores conectados** e **uso de CPU/memoria/disco/rede**,
start/stop/restart, atualizar pelo SteamCMD, ler logs (com modo ao vivo), **abrir um
terminal interativo** e **editar, baixar ou apagar os arquivos dos jogos** — tudo direto
dentro de cada container.

```powershell
.\deploy\admin\deploy-admin.ps1                # usa as chaves ADMIN_* do .env
.\deploy\admin\deploy-admin.ps1 -Interactive   # pergunta cada valor
```

No fim o deploy mostra a URL (`http://<ip-do-ct>:8080`), o usuario e a senha.

### No celular: instalar como aplicativo

O painel e um **PWA**: da para instalar na tela inicial do celular e abrir sem barra de
navegador. A interface e desenhada **para o telefone primeiro** &mdash; e dali que se
reinicia um servidor as onze da noite, nao da mesa do escritorio.

- **Instalar**: no Android/Chrome aparece um botao **Instalar** na barra de cima assim
  que o navegador reconhece o painel como instalavel. No iPhone/Safari e
  _Compartilhar &rarr; Adicionar a Tela de Inicio_.
- **Navegacao**: no celular as quatro secoes principais (Servidores, Historico, Alertas,
  Conta) ficam numa **barra de abas embaixo**, ao alcance do polegar; o resto
  (adicionar servidor, usuarios, acesso SSH, sair) esta no menu **⋯** da barra de cima.
  A partir de 900px de largura tudo isso sobe para a barra de cima e a de baixo some.
- **Terminal no telefone**: a tela do terminal ganha uma fileira com as teclas que o
  teclado virtual nao tem &mdash; `Esc`, `Tab`, `^C`, setas, `Home/End`, `PgUp/PgDn`,
  `/`, `|`, `~`. Sem ela, `vim` e `htop` sao inoperaveis no celular.
- **Sem conexao**: o aplicativo guarda so o proprio casco (CSS, JS, icones) e uma tela de
  &quot;sem conexao&quot;. **Nenhuma pagina logada e nenhuma leitura de `/api/` vai para
  o cache**: um painel com poder de root nos containers nao pode reexibir a tela de
  servidores depois do logout, nem mostrar o uso de CPU de uma hora atras como se fosse
  de agora.
- **Versao nova**: quando o deploy troca os arquivos, o painel mostra uma faixa
  _&quot;Ha uma versao nova&quot;_ com um botao. Ele nao se recarrega sozinho de
  proposito &mdash; pode haver uma sessao de terminal aberta no meio de uma edicao.

O que decide &quot;versao nova&quot; e o mtime dos arquivos de `static/`, carimbado no
`/sw.js` na hora de servir. Um deploy que muda o CSS gera um service worker diferente, o
navegador instala e descarta o cache velho.

### Deploy rapido: direto no CT, sem passar pelo Proxmox

Com o container do painel **ja criado e alcancavel por SSH**, o `deploy-admin.ps1` manda
o codigo direto para ele (`scp` + `systemctl restart`) e nem abre conexao com o Proxmox.
E o caminho normal do dia a dia: leva segundos em vez de minutos.

- O endereco vem de `-PanelHost`, de `ADMIN_HOST` no `.env` ou do IP fixo em
  `ADMIN_IP_CIDR`. Com `ADMIN_IP_CIDR=dhcp` e sem `ADMIN_HOST`, nao da para deduzir e o
  deploy segue pelo Proxmox.
- O provisionamento instala `openssh-server` no CT do painel e autoriza a **sua** chave
  publica (`ADMIN_SSH_PUBKEY`, detectada automaticamente do seu `~/.ssh`). E isso que
  habilita o envio direto; sem chave, o painel so aceita deploy pelo Proxmox.
- O envio direto troca os `.py`, `templates/` e `static/` inteiros &mdash; subpastas
  incluidas (`templates/components/`, `static/css`, `static/js`, `static/icons`),
  removendo o que saiu do repo &mdash; e reinicia o servico, abortando com as ultimas
  linhas do log se ele nao voltar. A pasta `static/maps` fica de fora da limpeza: ela e
  criada dentro do container e nao existe aqui para ser reenviada.
- **Config nao vai por ai**: mudar `ADMIN_*` (portas, limites, senha do painel) ou os
  recursos do CT exige o caminho completo:

```powershell
.\deploy\admin\deploy-admin.ps1 -Full          # cria/reconfigura o CT pelo Proxmox
```

### Acesso ao Proxmox por senha

O ideal e ter sua chave publica autorizada no Proxmox. Quando nao ha chave, preencha
`PROXMOX_PASSWORD` no `.env` (ou passe `-ProxmoxPassword`) e o deploy entra por senha.
Vale para os **dois** scripts — `deploy-admin.ps1` e `deploy-game.ps1`:

```powershell
.\deploy\admin\deploy-admin.ps1 -Full -InstallKey        # painel: entra por senha e autoriza sua chave
.\deploy\game\deploy-game.ps1 -Game icarus -InstallKey  # jogo: idem, no mesmo host Proxmox
```

- O deploy tenta a chave primeiro e so cai para a senha se ela nao for aceita.
- A senha nunca vai para disco: ela e passada ao `ssh` pelo mecanismo `SSH_ASKPASS`
  atraves de uma variavel de ambiente deste processo, e some do ambiente no fim (mesmo
  se o deploy falhar no meio).
- `-InstallKey` autoriza sua chave publica no Proxmox uma unica vez; dai em diante nao
  precisa mais da senha no `.env`.
- **Chave com passphrase precisa do `ssh-agent`.** Sem ele, o deploy continua caindo na
  senha mesmo com a chave autorizada: o `ssh` oferece a chave publica, o servidor aceita
  (`Server accepts key` no `ssh -v`) e a autenticacao falha logo depois, porque assinar
  exige a passphrase e um deploy nao tem onde perguntar. O sintoma engana - parece chave
  recusada, e na verdade e chave nao assinada. Habilite o agent uma vez, num PowerShell
  **como administrador**:

  ```powershell
  Set-Service ssh-agent -StartupType Automatic
  Start-Service ssh-agent
  ssh-add $env:USERPROFILE\.ssh\id_ed25519   # janela normal, digite a passphrase
  ```

  Confira com `ssh -o BatchMode=yes root@<proxmox> "echo ok"`: respondeu `ok`, o deploy
  para de usar senha.
- A autenticacao e resolvida **uma vez por deploy**, antes do primeiro `ssh`, e vale para
  todas as chamadas seguintes (envio do bundle, provisionamento, consultas). Um deploy
  chama `ssh`/`scp` meia duzia de vezes; sem isso cada chamada abriria seu proprio prompt.
- O modo senha se aplica **so ao host Proxmox**. O CT do painel e outra maquina, com outra
  senha de root: as consultas a ele continuam exigindo chave (`BatchMode`), para uma senha
  errada falhar na hora em vez de travar o deploy num prompt.

### Contagem de jogadores por servidor (valores testados)

Estes valores ficam no banco do painel, nao no repo - se o painel for recriado, e daqui
que eles voltam. Todos foram validados contra o log/API real de cada servidor.

| Jogo | Fonte | Nomes? |
|------|-------|--------|
| Palworld | API REST `http://127.0.0.1:8212/v1/api/players`, auth `basic:admin:<AdminPassword>`, caminho da lista `players` | **sim** |
| Dragonwilds | log do servico (regex abaixo) | **sim** |
| DayZ | log **em arquivo**: `/opt/game/profiles/*.ADM` (regex abaixo) | **sim** |
| Satisfactory | log do servico (regex abaixo) | **aproximado** |
| Icarus | A2S na porta de query | so contagem |
| Enshrouded | log do servico | so contagem |

As tres formas de contar ja vem preenchidas pelo deploy (`JOIN_RE`, `LEAVE_RE`,
`LOG_PATH` no `games/<jogo>.env`); o assistente do painel serve para ajustar.

**Como o painel decide o que mostrar**, pelos `(?P<name>...)` dos padroes:

| Onde ha o nome | O que sai na tela |
|----------------|-------------------|
| entrada **e** saida | quem esta online, exato |
| so na **entrada** | contagem exata + os ultimos a entrar, marcados como palpite |
| em nenhuma | so a contagem |

**Dragonwilds** - `Configurar contagem > Pelo log`:

```
entrada: PlayerChar entered world \[Account\[[^\]]*\] Character Name\[(?P<name>[^\]]+)\]
saida:   Player Removed from session \[[^\]]*\]-\[(?P<name>[^\]]+)\]
```

**DayZ** - os nomes **nao** saem da consulta A2S (o jogo responde a contagem e devolve os
nomes em branco). Eles estao no log de administracao `.ADM`, que o `-adminlog` do nosso
`START_ARGS` ja liga. Como o jogo abre um `.ADM` por sessao, o caminho leva `*` e o painel
pega sempre o mais novo:

```
arquivo: /opt/game/profiles/*.ADM
entrada: Player "(?P<name>[^"]+)" is connected
saida:   Player "(?P<name>[^"]+)"\(id=[^)]*\) has been disconnected
```

**Satisfactory** - a API so devolve a contagem (`numConnectedPlayers`); nao ha rota de
lista de jogadores. Pelo log da para ter os nomes, mas so **por aproximacao**: a linha de
entrada traz o nome e a de saida **nao**, entao o painel acerta *quantos* estao online e
mostra os *ultimos a entrar* como palpite - avisando na tela que e isso. Se um dia a linha
de saida passar a trazer o nome, basta por o `(?P<name>...)` nela e a lista vira exata.

```
entrada: LogNet: Join succeeded: (?P<name>.+)
saida:   LogNet: UNetConnection::Close:
```

**Icarus e Enshrouded** - por enquanto so a contagem. O Icarus responde `A2S_INFO` mas nao
`A2S_PLAYER` (o painel tenta os dois em toda consulta); o log do Enshrouded anuncia
conexoes sem nomear ninguem. Se o log do seu servidor tiver o nome, o assistente
(`Configurar contagem > Pelo log`) mostra as linhas de verdade do container e da para
montar o padrao ali mesmo - inclusive apontando um arquivo, como no DayZ.

**Palworld** - alternativa por log, caso a REST caia:

```
entrada: \[LOG\] (?P<name>.+?) joined the server\.
saida:   \[LOG\] (?P<name>.+?) left the server\.
```

Notas que economizam tempo depois:

- O token do Satisfactory sai de `PasswordLogin` com a senha de admin do jogo e **nao tem
  validade** (o payload e so `{"pl":"Administrator"}`). Ele e admin pleno na API - trate
  como senha. Se um dia responder 401/`insufficient_scope`, gere outro pelo mesmo caminho.
- A REST do Palworld so sobe com as chaves **dentro** do `OptionSettings=(...)`, numa unica
  linha, sob `[/Script/Pal.PalGameWorldSettings]`. Chave solta no arquivo e silenciosamente
  ignorada, e o servidor roda no padrao sem avisar.
- A contagem por log le do **start do servico** para ca (`journalctl --since ActiveEnterTimestamp`)
  e casa so os primeiros 500 caracteres de cada linha. Reiniciar o servidor zera a contagem
  ate alguem entrar de novo - limitacao inerente da fonte log, nao bug do painel.

### Como ele fala com os servidores

O painel **nao tem acesso ao host Proxmox** — ele nao usa `pct` e nao tem chave para o
hipervisor. Cada servidor cadastrado e um destino SSH, e o painel se conecta direto no
container do jogo:

```
[ CT gamepanel ] --ssh--> [ CT dragonwilds ]  systemctl / journalctl / update-game
                 --ssh--> [ CT palworld    ]
```

Para um container ser gerenciavel ele precisa de `sshd` e da chave publica do painel
autorizada. Ha tres formas de conseguir isso:

| Situacao | O que fazer |
|----------|-------------|
| CT de jogo novo | nada: o `deploy-game.ps1` le a chave do painel e ja deixa o CT pronto (ou preencha `PANEL_PUBKEY` no `.env` para fixar uma) |
| CTs de jogo existentes | preencha `ADMIN_AUTHORIZE_CTIDS=210,211,212,213` e rode o `deploy-admin.ps1` |
| Caso a caso | copie o comando pronto da tela **Acesso SSH** do painel |

A chave publica aparece no resumo do deploy do painel e na tela "Acesso SSH".

### Cadastrando um servidor

Servidor implantado pelo `deploy-game.ps1` ou pelo `deploy-docker.ps1` **ja chega
cadastrado** — a tela abaixo serve para um container que voce criou por fora, ou para
ajustar o que veio do deploy. Um redeploy nao duplica: o painel casa pelo par host+porta
SSH e atualiza o servidor existente, preservando o que voce mudou pela tela (arquivos de
config acrescentados a mao, forma de contar jogadores).

Em **Adicionar**, informe:

- **Host** — IP do container do jogo (ex.: `192.168.2.20`)
- **Servico** — a unit systemd (ex.: `dragonwilds.service`)
- **Usuario/porta SSH** — normalmente `root` e `22`
- **Pasta de configuracao** (opcional) — onde a tela **Arquivos** abre por padrao
  (ex.: `/opt/game/Pal/Saved/Config/LinuxServer`)
- **Arquivos de configuracao** (opcional, um por linha) — o arquivo que voce edita de
  verdade (ex.: `/opt/game/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini`). E ele que
  a tela **Config** abre como formulario, campo a campo
- **Porta de consulta** (opcional) — porta de query Steam/A2S para contar os jogadores
  online (Palworld: `27015`)

Start, stop, restart, update, terminal e editor rodam a partir dai. Acoes demoradas
(update) viram um job com a saida atualizando ao vivo na tela.

### Jogadores conectados

Ha tres formas, e a tela **Configurar contagem** (botao no card "Jogadores") descobre
qual serve para cada jogo.

**1. Consulta direta (A2S da Steam)** — a mesma consulta que o navegador de servidores
do jogo faz: UDP do painel para a porta de query. Nao passa por SSH, nao precisa de
senha nem RCON, e nao exige nada instalado no container. Palworld responde na
`27015/udp`.

O assistente **descobre as portas sozinho, e descobre tambem quem as abriu**. Ele le
`/proc/net/{udp,udp6,tcp,tcp6}` pelo SSH (porta + inode do socket) e cruza com os
descritores abertos de cada processo em `/proc/PID/fd` — o mesmo caminho que o `ss -p`
faz, mas sem depender de `ss`, `netstat` ou `lsof` estarem instalados. Cada porta aparece
na tela com o processo dono, em um de tres estados:

| Estado | O que significa |
|--------|-----------------|
| `PalServer-Linu (pid 40)` | socket aberto e processo dono identificado — e essa que interessa |
| `sshd (pid 1) — infra` | processo que sempre abre porta e nunca e o jogo; vai para o fim da fila |
| `aberta, sem processo dono neste container` | o socket existe mas nenhum processo daqui o abriu (o resolvedor DNS do Docker, por exemplo) |
| `nao estava aberta (chute)` | nao foi detectada: veio do cadastro ou da lista de portas conhecidas |

As portas com dono real sao testadas primeiro. A lista de chutes (`27015`, `8212`,
`7777`...) entra so no fim, como rede de seguranca para quando o servidor esta **parado**
— nessa hora nao ha socket nenhum para detectar. Se alguma responder, um clique em
"Usar esta" ja liga a contagem.

**2. API HTTP do jogo** — a melhor das tres quando existe, porque devolve os **nomes** e
nao so a contagem. Cada vez mais jogo troca a query UDP por uma API de administracao em
TCP: Palworld (REST em `8212/tcp`), Satisfactory (HTTPS em `7787/tcp`), Minecraft com
plugin, Factorio.

Nada aqui e codificado por jogo. Voce aponta uma URL e o painel:

- chama **de dentro do container, pelo mesmo SSH** do resto do painel. Essas APIs sao
  feitas para escutar em `127.0.0.1` (a documentacao do Palworld pede explicitamente
  para nao expor a porta na internet) e assim continuam fechadas para fora — nada de
  abrir porta no roteador;
- aceita `GET` ou `POST` (basta preencher o corpo JSON), com autenticacao
  `basic:usuario:senha`, `bearer:token` ou um cabecalho `Authorization` pronto;
- **acha a lista de jogadores sozinho** na resposta, procurando chaves conhecidas
  (`players`, `onlinePlayers`, `name`, `playerName`, `currentplayernum`, `numPlayers`,
  `maxPlayers`...). Quando ele erra, voce aponta o caminho a mao
  (`data.serverGameState.numConnectedPlayers`) — a resposta crua aparece na tela para
  voce ver o nome certo do campo.

O assistente lista as portas TCP em `LISTEN` dentro do container e bate nelas por HTTP
(e, se nao houver resposta, por HTTPS). Um `401` ja e um bom achado: existe API ali, ela
so quer senha.

No Palworld, ligue a API no `PalWorldSettings.ini` (`RESTAPIEnabled=True`,
`RESTAPIPort=8212`) e use `http://127.0.0.1:8212/v1/api/players` com
`basic:admin:` + a `AdminPassword`.

> A senha da API fica guardada em texto puro no `panel.db` (ela precisa ir no cabecalho
> de cada chamada). O banco ja guarda o caminho da chave SSH que da root nos containers,
> entao trate o arquivo como segredo de qualquer forma.

**3. Pelo log do servidor** — para jogo que nao publica nada na rede. O
**RuneScape Dragonwilds e assim**: a contagem que aparece no navegador do jogo vem do
servico da Steam/Epic, nao do servidor, entao nao ha o que consultar na LAN. Como o
`START_ARGS` dele tem `-log`, a Unreal despeja o log no stdout e o journald guarda —
da para contar reproduzindo as entradas e saidas desde o ultimo start do servico.

Como nenhum jogo escreve o log igual ao outro, os padroes sao configuraveis e o
assistente ajuda a achar: ele mostra as linhas do log que parecem de entrada/saida, deixa
testar dois regex e ver o resultado antes de salvar.

- Com `(?P<name>...)` nos dois padroes, o painel lista **quem** esta online e desde
  quando. Sem o nome na saida (comum na Unreal, que so avisa que a conexao caiu), ele
  soma entradas e subtrai saidas e mostra so a contagem.
- So conta o que aconteceu depois do ultimo start do servico, entao jogador de uma
  execucao anterior nao fica preso na conta.

Nas duas formas:

- **Tela do servidor**: contagem `3/32 online` e a tabela de jogadores. Atualiza a cada 10s.
- **Lista de servidores**: selo com a contagem em cada card.
- Servidor fora do ar ou porta errada nao trava a tela: a consulta desiste em
  `ADMIN_QUERY_TIMEOUT` segundos (padrao 3) e a pagina abre com o aviso. O resultado
  fica em cache por `ADMIN_PLAYERS_TTL` segundos (padrao 5).

### Expulsar, banir e avisar

Quando a contagem de jogadores esta ligada **pela API do jogo**, a lista de quem esta
online ganha os botoes **Expulsar** e **Banir**, e abaixo dela um campo para **avisar todo
mundo**. Sai tudo pela mesma API que ja conta os jogadores — outra rota, mesma senha, e o
mesmo token com prazo (que o painel renova sozinho).

O painel reconhece a API pela URL de contagem ja cadastrada. Dos jogos que este repo
instala, **so o Palworld** publica essas acoes (o Satisfactory nao tem kick na API dele).
Jogo novo entra como mais uma entrada no catalogo `API_ACOES` do `app.py`, sem tocar no
resto. Sem API reconhecida, os botoes simplesmente nao aparecem.

- **Kick e ban precisam do identificador** que a API publica (`userId` no Palworld), nunca
  do nome: nome muda e repete. Jogador que a API listar sem identificador aparece com
  "sem identificador" no lugar dos botoes.
- A mensagem (ate 200 caracteres) e a que o jogo mostra a quem foi expulso, ou a todos no
  caso do aviso.
- Estas rotas respondem **200 com o corpo vazio** — o painel aceita isso como sucesso em
  vez de reclamar que "a resposta nao e JSON".
- Cada acao fica no [Historico](#historico) com quem fez, quem levou e a mensagem.
- **Papel**: e de **operador**. Moderar quem esta jogando nao da acesso ao container, e
  quem ja pode reiniciar o servidor pode tirar alguem de dentro dele.

### Medidores de recursos

Cada servidor mostra quanto do container esta em uso, lido por SSH direto de `/proc` e
dos cgroups &mdash; sem agente, sem instalar nada no container do jogo.

- **Tela do servidor**: barras de CPU, memoria, swap e disco (por ponto de montagem),
  mais taxa de rede (rx/tx), load average, uptime e o **processo do jogo** (PID, RAM
  residente e CPU dele, separado do resto do container). Atualiza a cada 5s.
- **Lista de servidores**: tres barras compactas (CPU, RAM, disco) por card, carregadas
  depois da pagina para nao atrasar a abertura. Atualiza a cada 10s.
- A barra fica amarela em 80% e vermelha em 92%.
- A medicao respeita os limites do container: usa `cpu.max` e `memory.max` do cgroup
  quando existem (o `cpulimit`/`memory` do LXC), entao um CT limitado a 2 nucleos chega
  a 100% com 2 nucleos ocupados &mdash; e nao a 16% dos 12 do host. Sem limite definido,
  cai para `/proc` (com lxcfs, que o Proxmox usa por padrao, os valores ja sao por CT).
- CPU e rede sao medidos por duas amostras espacadas em 0,5s dentro do container, numa
  unica ida de SSH. O resultado fica em cache por `ADMIN_METRICS_TTL` segundos (padrao 4)
  para varias abas abertas nao virarem varias conexoes por segundo.

### Graficos de uso

Os medidores mostram o **agora**; a aba **Graficos** mostra o que aconteceu. O painel
guarda uma amostra de CPU, memoria e jogadores a cada **5 minutos**
(`GAMEPANEL_SAMPLE_EVERY`) enquanto esta no ar, e a tela desenha as ultimas **6h / 24h /
7 dias**. E o que responde "por que travou ontem a noite" depois que a noite passou.

- **Sao dois graficos, nao um.** Porcentagem e quantidade de gente nao dividem eixo:
  sobrepor as duas escalas num plot so inventaria uma relacao que os dados nao tem. CPU e
  memoria ficam juntos (as duas sao %), jogadores vai separado.
- **Buraco continua buraco.** Servidor fora do ar nao vira amostra (zero seria mentira:
  nao foi "usou 0% de CPU"), e a linha **parte** em vez de atravessar reto. Uma leitura
  solta entre dois buracos vira um ponto, para nao sumir.
- **O SVG vem pronto do servidor.** Sem JavaScript a tela continua inteira: cada linha
  tem o valor na ponta e ha a tabela com os mesmos numeros. O JS so acrescenta a mira e
  o balaozinho — e some com o rotulo de ponta quando as duas linhas se encontram no canto
  direito, porque dois rotulos empilhados se desgrudam das linhas e viram ruido.
- **Retencao propria**: as amostras saem depois de **7 dias**
  (`GAMEPANEL_SAMPLES_KEEP_DAYS`), na mesma limpeza de hora em hora do historico.

O custo esta na coleta: cada amostra e uma leitura de medidores, a chamada mais cara do
painel (o script remoto dorme 0,5s para tirar duas amostras de CPU). Por isso o intervalo
e de 5 minutos e nao de um — 288 pontos por dia ja sao mais do que o grafico mostra.

### Terminal interativo

A aba **Terminal** abre uma sessao SSH de verdade dentro do container, com TTY: `htop`,
`nano`, `vi`, `tail -f` e prompts de confirmacao funcionam como num terminal local.

- Emulador proprio (`src/gamepanel/static/js/terminal.js`), sem dependencia externa: cores 16/256/RGB,
  tela alternativa, regiao de rolagem e as teclas especiais (setas, F1-F12, Ctrl+letra).
- Transporte por HTTP (long-poll para a saida, POST para as teclas) — o painel roda em
  gunicorn sync, que nao suporta WebSocket.
- Botoes de Ctrl+C / Ctrl+D / Ctrl+Z, tela cheia e `Ctrl+V` para colar. Com texto
  selecionado, `Ctrl+C` copia em vez de interromper.
- Limites: `ADMIN_TERM_MAX` sessoes simultaneas (padrao 4) e `ADMIN_TERM_IDLE` segundos
  sem uso ate a sessao ser derrubada (padrao 900).
- Cada sessao aberta fica registrada no historico do servidor (quem abriu e quando).

### Edicao rapida de configuracao (tela Config)

Mudar o nome do servidor ou o numero maximo de jogadores nao devia significar procurar o
arquivo, achar a linha certa e nao errar a virgula. **Informe qual e o arquivo de
configuracao do jogo e a tela `Config` o abre como formulario**: um campo por chave, com
o valor atual preenchido.

- O arquivo vem do cadastro do servidor, campo **Arquivos de configuracao** (um caminho
  por linha, ate 8). No deploy em Docker ele ja vem preenchido a partir de
  `CONFIG_FILES` do `games/<jogo>.env`.
- Nao sabe o caminho? A tela chega com **Procurar**: ela varre a pasta do jogo e lista os
  candidatos com um botao *fixar aqui*. Na tela **Arquivos**, o botao *Editar campo a
  campo* fixa o arquivo aberto. Nos dois casos o arquivo passa a abrir direto dali em diante.
- **Adicionar configuracao** cria uma chave que ainda nao existe no arquivo, no bloco
  escolhido — sem precisar saber a sintaxe do formato.
- Campo de filtro no topo: o `PalWorldSettings.ini` tem ~50 chaves numa unica linha.
- Marque **reiniciar o servidor depois de salvar**: quase todo jogo so le a configuracao
  ao iniciar.

Formatos entendidos (detectados pelo nome + conteudo):

| Formato | Exemplo | Detalhe |
|---------|---------|---------|
| `.ini`/`.conf`/`.properties` | Satisfactory, Dragonwilds | secoes `[...]`, comentarios preservados |
| `.ini` da Unreal | Palworld | as ~50 chaves de `OptionSettings=(A=1,B=2,...)` viram campos individuais |
| `.json` | Enshrouded | objetos aninhados viram secoes (`userGroups.0.password`); tipo do valor preservado |
| `serverDZ.cfg` | DayZ | `chave = valor;`, blocos `class X { }` e o comentario `//` da linha vira a ajuda do campo |

O que ele **nao** faz: reescrever o arquivo inteiro. A gravacao aplica **so os campos que
voce alterou**, procurando cada um pela chave (nao pela linha) num arquivo relido na hora
de salvar — comentarios, ordem, formatacao e chaves desconhecidas ficam como estavam. Como
no editor de texto, sai um `.bak` antes de qualquer gravacao e o dono/permissao do arquivo
sao preservados. Se o formato nao for reconhecido, a tela manda voce para o editor de texto.

O motor fica em `src/gamepanel/games/config_format.py`, isolado do resto do painel (nao fala SSH nem HTTP),
com testes proprios:

```bash
docker compose exec -w /workspace panel python3 -m pytest tests/gamepanel/test_config_format.py -q
```

### Editor de configuracoes

A aba **Arquivos** navega pelo sistema de arquivos do container e edita os `.ini`/`.cfg`
do jogo direto no navegador — e a saida para tudo que a tela **Config** nao cobre
(formato exotico, arquivo binario, log grande, download).

- **Procurar arquivos de config** varre a pasta do jogo (ate 5 niveis) atras de `.ini`,
  `.cfg`, `.conf`, `.json`, `.yaml`, `.properties` e `.txt`.
- Ao salvar, o painel guarda `<arquivo>.<data>.bak` na mesma pasta e grava **por cima do
  arquivo existente**, preservando dono e permissao (o jogo roda como `steam`, nao root).
- `Ctrl+S` salva; sair com alteracoes pendentes pede confirmacao. Da para baixar o
  arquivo antes de mexer.
- **Download**: todo arquivo tem um link `baixar` na lista — inclusive binarios (saves,
  `.pak`, `.so`) e arquivos grandes demais para o editor. O download vai em streaming
  (`cat` pelo SSH lido em blocos), entao um save de varios GB desce sem o painel
  guardar nada em memoria. Teto em `ADMIN_FILE_DOWNLOAD_MAX_MB` (padrao 2048; `0` = sem
  limite) e cada download fica no historico do servidor.
- Edicao ate `ADMIN_FILE_MAX_KB` (padrao 4096 KB). Acima disso o arquivo abre em
  **somente leitura** mostrando os ultimos `ADMIN_FILE_PREVIEW_KB` (padrao 256 KB) —
  util para espiar um log grande — com o botao de baixar ao lado. Salvar fica bloqueado
  ai (inclusive no servidor), senao gravar o preview truncaria o arquivo.
- Binarios nao sao editaveis (so baixaveis): o painel detecta pelo byte nulo.
- **Apagar**: cada linha da lista tem um `apagar` (e o arquivo aberto tem o botao
  **Apagar arquivo**, que vale ate para binario e para o modo somente leitura). Pede
  confirmacao com o caminho na tela e **nao tem volta**: aqui nao ha `.bak` nem lixeira —
  seria inutil num save de varios GB. So apaga arquivo, link ou **pasta vazia** (`rmdir`):
  a tela nao faz remocao recursiva, e as raizes de `ADMIN_FILE_ROOTS` sao intocaveis.
  Cada exclusao fica no historico do servidor, e se o arquivo estava fixado na tela
  **Config** ele sai do cadastro junto.
- **Enviar arquivo**: acima da lista ha um campo de upload que grava na pasta aberta no
  momento — e como entra um mod, um `.ini` pronto ou um save vindo de outro servidor. O
  arquivo sobe em pedacos e vai direto para o container, sem passar inteiro pela memoria
  do painel; se ja existir um com o mesmo nome, ele e substituido e uma copia `.bak` fica
  ao lado. O caminho que o navegador manda no nome e descartado (so a ultima parte vale),
  entao `../../etc/cron.d/x` vira `x` na pasta aberta.
  Limite padrao de **512 MB** (`GAMEPANEL_UPLOAD_MAX`). Antes de aumentar, lembre que o
  corpo do envio e guardado num arquivo temporario **do container do painel** antes de a
  aplicacao ver um byte — o teto precisa caber no disco de la, nao no do jogo.
- `ADMIN_FILE_ROOTS` restringe onde o navegador de arquivos pode entrar (padrao: tudo).
- Pare o servidor antes de editar o que ele reescreve ao sair — varios jogos sobrescrevem
  o `.ini` no shutdown.

### Backups

Cada servidor tem uma aba **Backups**: um `.tar.gz` das pastas do save, criado **dentro
do proprio container do jogo** (`/var/backups/gamepanel` por padrao) e, no mesmo job,
**copiado para o painel** (`/var/lib/gamepanel/backups/<jogo>/`). O painel dispara, lista,
baixa, restaura e apaga as duas.

**Por que duas copias.** A do container morre com ele: remover uma instancia pelo broker
apaga o CT com os discos, e o save ia junto. A do painel sobrevive, e e organizada pelo
**jogo** (o nome do servico, `valheim.service` -> `valheim/`), nao pelo servidor. Remover e
criar de novo o mesmo jogo da um servidor com outro id, mas o mesmo servico — e a aba
Backups dele ja mostra as **Copias no painel** do anterior, com o botao **restaurar**: a
copia volta ao container e e extraida como qualquer outra.

- **Todo backup vai para os dois lugares**, manual ou agendado. Se a copia do painel
  falhar (disco cheio, conexao caiu no meio), o job sai com **erro** — a do container
  continua la, mas quem conta com o painel precisa saber agora. Copia que chega truncada
  nao fica com o nome certo: o tamanho e conferido.
- **Desativar uma instancia do broker tira o backup antes**: desativar para o CT, e depois
  disso nao ha SSH para copiar nada — e a ultima hora. Se o backup falhar, a instancia
  continua ativa; o botao **Desativar sem backup** desativa assim mesmo. Na hora de remover, a tela
  mostra quantas copias do save o painel tem (ou avisa que nao tem nenhuma).
- **Copias antigas, de antes desta versao**, so existem no container: cada uma tem o botao
  **enviar ao painel**.
- **Jogo que ja nao tem servidor**: a tela **Backups** do menu (`/backups`, so admin) lista
  tudo o que o painel guardou, por jogo, com baixar e apagar. Para restaurar, crie a
  instancia (ou cadastre o servidor) do mesmo jogo de novo — a copia aparece na aba
  Backups dele. So o servidor do MESMO jogo recebe a copia: o tar guarda caminho absoluto,
  e o save de um jogo extraido no container de outro so espalharia arquivo.

O que entra na copia sai do campo **Caminhos de backup** do cadastro do servidor, e o
deploy ja o preenche: cada `games/<jogo>.env` tem um `BACKUP_PATHS` que o
`deploy-game.ps1` / `deploy-docker.ps1` passa para o painel no cadastro. Nao precisa
mexer em nada para ter backup do save certo — e num redeploy o painel **mantem** o que
voce tiver ajustado pela tela.

| Jogo | `BACKUP_PATHS` |
|------|----------------|
| Palworld | `/opt/game/Pal/Saved/SaveGames` |
| Dragonwilds | `/opt/game/RSDragonwilds/Saved/SaveGames` |
| Enshrouded | `/opt/game/savegame` |
| Icarus | `/opt/game/Icarus/Saved/PlayerData`, `/opt/game/Icarus/Saved/Prospects` |
| DayZ | `/opt/game/mpmissions/dayzOffline.chernarusplus/storage_1`, `/opt/game/profiles` (o numero segue o `instanceId`) |
| Satisfactory | `/home/steam/.config/Epic/FactoryGame/Saved/SaveGames/server` |

Servidor cadastrado a mao (ou antes desta versao) fica com o campo vazio e cai na **pasta
de configuracao** — funciona, mas aponte o save para nao guardar so o `.ini`. E aponte o
*save*, nunca a raiz do jogo: `/opt/game` inteiro leva dezenas de GB de binario que o
SteamCMD rebaixa de graca.

Detalhes que importam:

- **Caminho que ainda nao existe e ignorado com um aviso**, nao e erro: a pasta de save so
  nasce quando alguem entra no servidor pela primeira vez, e as outras continuam entrando
  na copia. O backup so falha se nenhum dos caminhos existir.

- **Retencao**: no container ficam as `GAMEPANEL_BACKUP_KEEP` copias mais novas (padrao
  **5**); no painel, as `GAMEPANEL_PANEL_BACKUP_KEEP` mais novas de cada jogo (padrao
  **10**, `0` = nunca apagar). As antigas saem sozinhas. A copia `-antes-de-restaurar` nao
  aplica a retencao do container: com as copias no limite, ela apagaria a mais antiga —
  que pode ser justo a escolhida para restaurar.
- **Com o servidor ligado funciona** e e o uso normal. O `tar` avisa quando um arquivo
  mudou durante a copia — o backup continua valendo, mas um save gravado bem nessa hora
  pode entrar pela metade. Para uma copia perfeita, pare o servidor antes.
- Antes de gravar, o painel compara o tamanho do alvo com o espaco livre e **recusa** o
  backup se nao couber: encher o disco do container derruba o jogo junto.
- **Restaurar para o servidor, extrai e religa** — e devolve cada arquivo exatamente de
  onde ele saiu (o `tar` guarda os caminhos relativos a `/`). Servidor que ja estava
  parado continua parado. Antes de extrair, o painel tira **sozinho** uma copia do estado
  atual, marcada `-antes-de-restaurar`: e a saida de quem escolheu o backup errado.
- **Papeis**: tirar copia e operacao, e o **operador** pode dispara-la. Baixar, restaurar,
  apagar e enviar ao painel sao de **administrador** — restaurar e apagar destroem dado, e
  baixar tira o save inteiro do container.
- **Espaco no CT do painel**: save costuma ter poucos MB, mas 10 copias de cada jogo somam.
  Um DayZ com mundo grande e o caso de conferir o disco do painel.

Variaveis: `GAMEPANEL_BACKUP_DIR`, `GAMEPANEL_BACKUP_KEEP`, `GAMEPANEL_BACKUP_TIMEOUT`,
`GAMEPANEL_PANEL_BACKUP_DIR` (padrao: `backups/` ao lado do banco),
`GAMEPANEL_PANEL_BACKUP_KEEP`.

### Agendamentos

Cada servidor tem uma aba **Agendamentos**: o painel dispara sozinho **reiniciar, parar,
iniciar, atualizar (SteamCMD)** ou **backup**, em tres formatos —

- **todo dia** numa hora fixa (o classico "reiniciar as 5h");
- **uma vez por semana**, num dia e hora ("backup completo todo domingo as 3h");
- **a cada N horas**, contadas a partir do momento em que a tarefa foi salva.

Cada disparo entra no historico como qualquer outra acao, com `agendador` no lugar do
usuario — da para conferir tudo em [Historico](#historico) filtrando por esse nome. O
botao **rodar agora** dispara na hora, sem esperar o horario: e como se testa uma tarefa
recem-criada sem ficar acordado ate as 5h.

Detalhes que importam:

- **O relogio e o do container do painel.** A propria tela mostra que horas sao para ele e
  qual o fuso; se nao bater com a sua hora, o que esta errado e o `TZ` do container (o
  padrao dos containers e **UTC**).
- **Tarefa atrasada nao dispara.** Se o painel passou a noite fora do ar, o "reiniciar as
  5h" **nao** cai as 14h no meio da partida: ele espera a proxima ocorrencia. A tolerancia
  e de 1h (`GAMEPANEL_SCHEDULE_GRACE`).
- **Nao roda duas vezes.** O horario do ultimo disparo fica gravado e e marcado *antes* de
  a tarefa comecar — um `update` que leva 40 minutos nao e disparado de novo no meio.
- **Um worker so.** O relogio e uma thread dentro do processo do painel, e o `gunicorn`
  aqui roda com `--workers 1` justamente por isso (a sessao do terminal tem o mesmo
  motivo). Com dois processos, cada um teria a sua thread e toda tarefa dispararia em
  dobro.
- Pela linha de comando (`--register-server`, `--create-user`) o relogio **nao sobe**: um
  deploy nao pode disparar tarefa de passagem.
- **Papeis**: qualquer um ve a lista; criar, ligar/desligar, remover e "rodar agora" sao de
  administrador. Remover o servidor do painel leva as tarefas dele junto.

### Alertas

O menu tem **Alertas** (so administrador): **webhooks** e o painel avisa quando algo
acontece sem ninguem estar olhando. Serve para **Discord** (Editar canal &rarr;
Integracoes &rarr; Webhooks &rarr; Copiar URL), **Slack** (Incoming Webhook) ou qualquer
endereco que aceite `POST` de JSON — a chamada leva os campos `content` **e** `text`, e
cada servico le o seu.

Da para cadastrar **varios destinos** (ate 10, `GAMEPANEL_WEBHOOK_MAX`), cada um com a
**sua** lista de eventos e um interruptor de ligado/desligado: o canal da equipe recebe
tudo, o canal geral so as quedas, e o webhook do servidor de testes fica desligado sem
precisar ser apagado. Cada evento sai para todos os destinos que o marcaram, um POST por
destino — se um estiver fora do ar, os outros recebem do mesmo jeito e a falha vai para o
log do painel com o nome do destino. O botao **Testar** de cada linha manda uma mensagem
na hora; se voce digitou uma URL nova, ele testa a nova, antes de salvar.

Na tela a URL aparece **mascarada** (`discord.com/.../1544786528700604457/********`) —
ela e uma credencial, e um screenshot da tela nao deveria entregar o canal. Para trocar,
digite a nova no campo abaixo dela; em branco, mantem a que ja esta la.

O que da para avisar:

| Evento | Padrao | Precisa configurar |
|--------|--------|--------------------|
| Servidor parou de rodar | ligado | — |
| Jogo quebrou (servico em `failed`) | ligado | — |
| Jogo caindo em loop de restart | ligado | — |
| Jogo nao responde (de pe, mas mudo) | ligado | contagem por A2S ou API HTTP |
| Painel perdeu contato (SSH) | ligado | — |
| Tarefa **agendada** falhou | ligado | — |
| Disco quase cheio (limite ajustavel, 50-100%) | ligado | — |
| Servidor voltou a rodar | desligado | — |
| Contato restabelecido | desligado | — |
| Jogo voltou a responder | desligado | contagem por A2S ou API HTTP |
| Erro no log do jogo | desligado | expressao de erro no cadastro |

#### Servico de pe nao e jogo de pe

O alerta de queda so enxerga o systemd: se a unidade responde `active`, para ele esta tudo
bem. Isso deixa passar justamente as falhas mais chatas, em que o painel fica verde e
ninguem consegue jogar. Os quatro eventos abaixo cobrem esse buraco:

- **Jogo quebrou** — o systemd marcou a unidade como `failed` (saiu com erro, estourou o
  limite de restarts, levou OOM). E diferente de "parou": parar pelo painel nao dispara
  este alerta, e este aqui e o unico que **sai mesmo dentro da janela de silencio** — se
  voce mandou reiniciar e o resultado foi `failed`, e exatamente o que voce precisa saber.
- **Loop de restart** — com `Restart=always` o jogo pode morrer a cada 20 segundos que o
  `ActiveState` responde `active` quase sempre: a queda nunca "acontece" e o canal fica
  mudo. Quem denuncia e o `NRestarts` do systemd, que so sobe. Sai **uma vez por
  episodio**; uma volta inteira sem restart novo fecha o episodio. Precisa de systemd
  >= 235; sem isso o painel simplesmente nao avisa desse evento.
- **Jogo nao responde** — o processo esta vivo mas mudo na consulta do proprio jogo, por
  3 verificacoes seguidas (`GAMEPANEL_MUTE_ROUNDS`). Uma consulta A2S e UDP e perder um
  pacote e rotina, por isso a insistencia. Nao conta enquanto o servico esta subindo nem
  dentro da janela de silencio — jogo carregando mapa nao responde e isso e normal. So
  vale para quem conta jogadores por **A2S ou API HTTP**: contagem por log nao pergunta
  nada ao jogo, entao nao tem o que ficar mudo.
- **Erro no log do jogo** — o painel le as ultimas 200 linhas do log (o mesmo da
  contagem: `journalctl` ou o `log_path`) a cada 120s (`GAMEPANEL_LOG_CHECK_EVERY`) e
  procura a **expressao de erro** cadastrada no servidor (campo *Log: linha de erro*).
  Em branco, nem a leitura acontece. A mesma linha nao avisa duas vezes, e ha um teto de
  um alerta destes por servidor a cada 10 min (`GAMEPANEL_LOG_ERR_COOLDOWN`) — a
  expressao vem da tela, e um `.` distraido casa com tudo.

A tela de Alertas avisa quando um evento esta **ligado sem ter onde olhar** (marcou "jogo
nao responde" e nenhum servidor tem consulta configurada, por exemplo). Alerta ligado e
mudo e pior que alerta desligado: o silencio do canal passa a ser lido como "esta tudo
bem".

As regras que evitam o alerta virar ruido — que e o que faz um canal deixar de ser lido:

- **Avisa na mudanca, nunca em repeticao.** O alerta sai quando o servidor cai, e nao a
  cada minuto enquanto ele estiver caido. Vale igual para o disco.
- **Acao pelo painel nao vira susto.** Parar, reiniciar, atualizar ou restaurar derruba o
  servico de proposito; nos 180s seguintes (`GAMEPANEL_ALERT_QUIET`) a queda e esperada e
  nao gera alerta. A excecao e o **jogo quebrou**: terminar em `failed` nunca e esperado.
- **Ao subir, o painel so anota.** Reiniciar o painel nao dispara um alerta por servidor
  que ja estava parado.
- **Sem contato, ele nao opina sobre o servico.** Se o SSH caiu, sai o alerta de contato e
  so — dizer que o jogo parou seria invencao.
- **De tarefa que falha, so a agendada avisa.** Quem clicou o botao ja esta com o erro na
  tela.

O estado do servidor e conferido a cada **60s** (`GAMEPANEL_MONITOR_EVERY`) e o disco a
cada **10 min** (`GAMEPANEL_DISK_CHECK_EVERY`) — o medidor custa uma ida de SSH bem mais
cara que o status. Sem nenhum destino ligado pedindo algum evento, a volta nem acontece.
Os destinos ficam no banco (nao exige redeploy para mudar); `GAMEPANEL_WEBHOOK_URL` serve
so de valor inicial do **primeiro** destino, para o deploy ja deixar pronto.
**Trate a URL como senha**: quem a tiver escreve no seu canal.

> **403 do Discord?** O Cloudflare na frente dele recusa o `User-Agent` padrao do Python
> (`Python-urllib/3.x`) antes do pedido chegar no webhook. O painel manda um proprio
> (`GAMEPANEL_WEBHOOK_UA`), entao isso ja esta resolvido — se voce vir 403 mesmo assim, a
> mensagem de erro na tela agora traz a resposta do destino, que diz o motivo.

### Historico

O menu do topo tem **Historico**: tudo o que aconteceu, em todos os servidores, com filtro
por servidor, acao e quem fez. E onde se responde "quem parou o servidor ontem" e "o
agendador rodou o backup essa semana?". A tela de cada servidor continua mostrando so os
15 ultimos.

O operador nao ve ali (nem em `/jobs/<id>`) o que ele nao pode fazer — terminal, console e
arquivos; veja [Usuarios e papeis](#usuarios-e-papeis).

**Retencao**: cada registro guarda a saida inteira do que rodou (ate 200 KB), e um backup
diario sozinho poe 365 linhas por ano no banco. O painel apaga o que passa de
**60 dias** (`GAMEPANEL_JOBS_KEEP_DAYS`, `0` desliga), numa limpeza que roda de hora em
hora junto com o relogio do agendamento.

### Comando unico (dentro do Terminal)

A tela **Terminal** tem dois modos, e o segundo e o **Comando unico**: voce digita um
comando, ele executa como `root` **dentro daquele container de jogo**, e a saida fica na
tela com o historico registrado (quem rodou, o que rodou, exit code). Util para um
comando so, sem abrir sessao.

Os dois modos ficam na mesma tela de proposito. Eles ja foram dois destinos separados no
menu (&quot;Terminal&quot; e &quot;Console&quot;), com nomes que ninguem conseguia
distinguir de fora &mdash; e cada tela do painel oferecia um subconjunto diferente dos
dois. Hoje a navegacao tem **um** lugar para linha de comando; a escolha entre sessao
interativa e comando avulso e feita la dentro.

- Sem TTY: para `vim`/`htop` e prompts, use a **sessao interativa**.
- Ctrl+Enter executa; as setas ↑/↓ percorrem o historico.
- Limite de tempo por comando: 600s (`GAMEPANEL_SHELL_TIMEOUT`).
- Sem PTY (painel rodando fora de Linux), o destino &quot;Terminal&quot; abre direto
  neste modo &mdash; e continua sendo uma entrada so no menu.

Console e terminal sao execucao remota de comandos exposta numa pagina web — quem entrar
no painel tem root nos containers de jogo. Se nao quiser essa capacidade, desligue com
`ADMIN_ALLOW_SHELL=0` no `.env` (as duas telas somem e as rotas respondem 403); o editor
de arquivos tem o proprio interruptor, `ADMIN_ALLOW_FILES=0`.

### Usuarios e papeis

O painel comeca com um usuario so — o que o `deploy-admin.ps1` cria (`ADMIN_USER`). A
tela **Usuarios** (visivel so para administrador) cria os demais: voce escolhe o nome, o
papel e define a senha inicial, que a pessoa troca depois em **Conta**. Nao ha e-mail nem
link de convite envolvido.

Sao dois papeis:

| Tela | Operador | Administrador |
|------|----------|---------------|
| Servidores, status, jogadores, log | sim | sim |
| Start / stop / restart / update | sim | sim |
| **Config** (arquivos ja registrados) | sim | sim |
| Expulsar, banir e avisar jogadores | sim | sim |
| Cadastrar / editar / remover servidor | nao | sim |
| Registrar um novo arquivo na tela Config | nao | sim |
| Terminal, Console e navegador de **Arquivos** | nao | sim |
| Enviar arquivo para o container | nao | sim |
| Ver a lista de **Backups** e tirar copia | sim | sim |
| Baixar, restaurar, apagar ou enviar ao painel um backup | nao | sim |
| **Historico** global e por servidor | sim | sim |
| **Graficos** de uso | sim | sim |
| Historico de terminal, console e arquivos | nao | sim |
| Ver os **Agendamentos** | sim | sim |
| Criar, ligar/desligar ou remover agendamento | nao | sim |
| **Alertas** (webhook) | nao | sim |
| **Usuarios** | nao | sim |

O corte segue o que da **root no container**: terminal, console e editor de arquivos
ficam com o administrador, e junto com eles o cadastro do servidor (que aponta o SSH do
painel) e o registro de qual arquivo a tela Config abre — sem isso o operador poderia
apontar a tela Config para `/etc/shadow` e contornar a restricao.

O corte vale tambem para o **historico**: um job guarda a saida inteira do que rodou, e a
de um comando no console carrega tudo o que apareceu na tela. Por isso os registros de
`shell`, `terminal`, `edit-file`, `delete-file` e `download-file` somem da lista da tela
do servidor para o operador e respondem **403** em `/jobs/<id>` e `/api/jobs/<id>` — sem
isso, quem leva 403 no console leria o resultado dele pelo id do job. `edit-config` fica
de fora da restricao de proposito: mexer na configuracao do jogo e trabalho de operador.

O papel e lido do banco a cada clique, entao tirar o acesso de alguem vale na hora, e
apagar uma conta derruba a sessao dela. O painel nunca fica sem administrador: nao da
para remover nem rebaixar o ultimo, nem mexer no proprio papel.

Esqueceu a senha de todo mundo, ou perdeu o acesso de administrador? A linha de comando
continua sendo a saida de emergencia (roda dentro do CT do painel):

```bash
cd /opt/gamepanel/current && python3 -m gamepanel.cli --create-user chefe --password nova-senha --role admin
```

O caminho antigo (`python3 /opt/gamepanel/current/gamepanel/app.py --create-user ...`) continua
valendo; os dois chamam o mesmo `gamepanel/cli.py`.

### Idioma da tela

O painel fala **portugues** e **ingles**. Cada pessoa escolhe o seu em **Conta** — a
escolha fica no cadastro dela, entao vale em qualquer aparelho em que ela entrar, e nao
muda o de mais ninguem.

Quem ainda nao escolheu ve o idioma que o **navegador** pede (o `Accept-Language`), o
que vale tambem para a tela de login, onde ainda nao ha ninguem logado. Se o navegador
pedir um idioma que o painel nao fala, vale o padrao do deploy — `ADMIN_LANG` no `.env`
(`GAMEPANEL_LANG` dentro do container), que e `pt` quando nao se diz nada.

Duas coisas seguem **sempre** o padrao do deploy, de proposito:

- **O aviso que vai para o webhook** (Discord, Slack). O canal e um so e e lido por
  varias pessoas; mensagem que trocasse de lingua conforme quem clicou seria pior do que
  uma so.
- **O texto gravado no Historico.** Ele e lido depois, por outra pessoa: se cada linha
  saisse no idioma de quem apertou o botao, a mesma acao apareceria escrita de tres
  jeitos na mesma lista, e o filtro por acao deixaria de fazer sentido.

Traduzir o painel para outra lingua e acrescentar um arquivo em
`src/gamepanel/i18n/` — nao ha passo de compilacao, nem dependencia nova.

### Testando o painel localmente (docker compose)

Para mexer no painel sem depender do Proxmox:

```bash
docker compose up --build         # http://localhost:8080 - admin / admin12345
```

Sobem tres containers: o painel e dois "servidores de jogo" falsos (Debian com `sshd`, um
`systemctl`/`journalctl` simulados e os `.ini` que o jogo teria). Os dois ja vem
cadastrados no painel — com o `.ini` apontado, entao a tela **Config** tambem da para
testar de ponta a ponta, junto com start/stop/update, terminal e editor. O codigo entra
por bind mount com `--reload`: editar `src/gamepanel/app.py` ou os templates e recarregar a
pagina basta.

Nao confunda com o deploy de verdade: aqui os containers se chamam `game-palworld-dev` e
a imagem em `docker/game/` **nao instala jogo nenhum** (a de verdade e a de
`docker/gameserver/`, usada pelo `deploy-docker.ps1`).

Os dois containers falsos sao propositalmente diferentes, para cobrir as tres formas de
contar jogadores: o `game-palworld` tem query A2S (`27015/udp`) **e** uma API REST no
formato da do Palworld (`127.0.0.1:8212`, `admin`/`troque-me`); o `game-dragonwilds` nao
tem nenhuma das duas — so anuncia entradas e saidas no log, como o jogo real. A imagem de
teste tambem nao tem `curl` de proposito: assim o ambiente local exercita o caminho
alternativo da chamada HTTP (o container de jogo de verdade tem `curl`).

```bash
docker compose logs -f panel
docker compose exec -w /opt/gamepanel panel python3 -m pytest -q          # as 7 suites (323 testes)
docker compose exec -w /opt/gamepanel panel python3 -m pytest test_alerts.py -q  # so uma
docker compose exec game-palworld sh -c 'echo 7 > /run/fake-players' # fixa a contagem
docker compose down -v            # zera banco, chaves e arquivos de teste
```

As suites (`test_config_format.py` o parser, `test_gamefields.py` o catalogo,
`test_players.py` a contagem, `test_users.py` papeis/backup/upload, `test_schedules.py`
agendamento e historico, `test_alerts.py` alertas por webhook, `test_charts.py` os
graficos) sao pytest — nao rodam mais como script solto. Veja o
[CLAUDE.md](CLAUDE.md) para rodar fora do Docker, num `.venv` local.

### Seguranca

- Login por usuario, senha com hash **scrypt** no SQLite, sessao em cookie assinado
  (HttpOnly, SameSite=Lax) e bloqueio apos 5 tentativas erradas em 5 minutos
- Dois papeis (**administrador** e **operador**): shell, editor de arquivos, cadastro de
  servidor, gestao de usuarios **e o historico dessas acoes** sao so do administrador —
  veja [Usuarios e papeis](#usuarios-e-papeis)
- Todos os POSTs exigem token **CSRF**
- Respostas levam `X-Frame-Options: DENY` (o painel nao pode ser embutido em iframe),
  `X-Content-Type-Options: nosniff` e `Referrer-Policy: same-origin`
- A volta do `?next=` do login so aceita caminho interno — `//host` e `/\host` sao
  absolutos para o navegador e ficariam de fora do painel
- O assistente de contagem de jogadores envia por **POST**: a senha de admin do jogo
  (`Autenticacao`, `Corpo JSON do login`) nao pode passar pela barra de enderecos, pelo
  `Referer` nem pelo log de um proxy reverso
- O painel serve **HTTP puro** — pensado para LAN. Nao exponha na internet sem um proxy
  reverso com TLS na frente
- As URLs dos webhooks de [Alertas](#alertas) sao segredos (quem as tiver escreve no seu
  canal) e ficam em texto puro no `panel.db`, como a senha da API de contagem. Na tela
  elas aparecem mascaradas, mas quem tem o arquivo do banco tem as URLs inteiras — se uma
  vazar, apague o webhook no Discord/Slack e cadastre outro aqui
- Comprometer o painel da acesso root aos **containers de jogo**, nao ao Proxmox
- Cada container tem **firewall proprio** (nftables), inclusive contra quem esta na mesma
  rede — veja [Firewall dentro dos containers](#firewall-dentro-dos-containers)

### Firewall dentro dos containers

O OPNsense so filtra o que **atravessa** ele. Dentro da mesma sub-rede um CT fala com o
outro direto, e um servidor de jogo invadido alcancaria o SSH do painel, a API do broker, o
Proxmox e a API do OPNsense sem passar por regra nenhuma. Por isso cada CT tem o seu firewall
(`lib/ct-firewall.sh`, instalado como `ct-firewall`), que **nega tudo o que entra** e so abre
o que aquele CT precisa:

| CT | Entrada | Saida |
|----|---------|-------|
| Painel | web (`ADMIN_PORT`) e SSH so de `ADMIN_FIREWALL_SOURCES` (padrao `192.168.0.0/16`) | livre (jogos, broker, webhook) |
| Broker | API `:8443` so do painel; sem SSH (ele nao tem sshd) | so Proxmox e OPNsense (das URLs), SSH e ping na faixa dos jogos, DNS e apt |
| Jogo | portas do jogo de qualquer origem; SSH e ping so do painel e do broker | internet sim; **rede interna nao** (so o DNS) |

Em todos, o loopback passa (as APIs de admin do Palworld e do Satisfactory so escutam em
`127.0.0.1`) e a resposta de conexao ja aberta passa.

- **CT novo ja nasce com ele**: painel (`deploy-admin.ps1 -Full`), broker
  (`deploy-broker.ps1`), jogo pelo broker e jogo pelo `deploy-game.ps1`. O jogo so ganha
  firewall se o deploy sabe o IP do painel (`ADMIN_HOST`/`ADMIN_IP_CIDR`): aplicar sem ele
  trancaria o painel fora do servidor que acabou de nascer.
- **CTs que ja existiam**: `.\deploy\firewall\apply-firewall.ps1`. Ele acha os jogos pelo
  banco do broker (com as portas que cada um recebeu), aplica, **testa** cada CT (o painel
  ainda abre SSH no jogo? o broker ainda fala com o Proxmox?) e **desliga sozinho** o
  firewall do CT cujo teste falhar. `-DryRun` so mostra as regras; `-Only 302` limita a um CT;
  `-ExtraGameCts 210,211` inclui jogos feitos pelo `deploy-game.ps1`.
- **Emergencia** (sempre funciona, porque passa pelo Proxmox e nao pela rede):
  `pct exec <CT> -- ct-firewall off`. Religar: `pct exec <CT> -- ct-firewall apply`.
  Conferir: `pct exec <CT> -- ct-firewall status`.
- **Porta a mais num jogo** (ex.: os mundos extras do Dragonwilds em `7778`/`7779`): edite
  `FW_GAME_PORTS` em `/etc/ct-firewall.env` do CT e rode `ct-firewall apply`.
- O painel so e alcancavel da rede local. Acesso de fora tem de chegar por um tunel ou proxy
  **de dentro** da LAN (ou incluido em `ADMIN_FIREWALL_SOURCES`).
- `CT_FIREWALL=0` no `.env` desliga tudo isso nos proximos deploys.

### Arquivos

| Caminho (no CT do painel) | O que e |
|---------------------------|---------|
| `/opt/gamepanel/` | aplicacao: `app.py`, `ui.py`, `templates/` (com `components/`) e `static/` (`css/`, `js/`, `icons/`) |
| `/var/lib/gamepanel/panel.db` | SQLite: usuarios, servidores, historico |
| `/var/lib/gamepanel/known_hosts` | host keys aprendidas dos containers |
| `/var/lib/gamepanel/backups/<jogo>/` | a segunda copia de cada backup (`GAMEPANEL_PANEL_BACKUP_DIR`) |
| `/etc/gamepanel/id_ed25519` | chave SSH do painel |
| `/etc/gamepanel/panel.env` | configuracao lida pelo systemd |

Cada backup existe em **dois lugares**: no container do jogo, em `/var/backups/gamepanel`
(`GAMEPANEL_BACKUP_DIR`), e aqui, em `/var/lib/gamepanel/backups/` — a copia daqui e a que
sobrevive a remover a instancia. Veja [Backups](#backups).

### Como a interface e montada

Tres decisoes explicam a organizacao do `src/gamepanel/`, e as tres nasceram do mesmo
problema: a mesma coisa escrita em varios lugares acaba virando coisas diferentes.

**`navigation.py` &mdash; o mapa da interface.** Quais telas um servidor tem, em que ordem, com
que icone, e quem pode abrir cada uma. A lista de telas ja esteve escrita a mao em seis
templates, cada um com um subconjunto proprio: era por isso que &quot;Graficos&quot;
aparecia numa tela e nao na outra. Hoje **tela nova = uma linha nessa tupla**, e ela
aparece sozinha na barra do servidor e no menu do cartao do painel. O modulo e puro (nao
importa Flask); quem liga isso ao pedido em curso e o `app.py`.

O mesmo vale para as acoes: `ui.ACOES` diz como cada uma se apresenta (rotulo, icone,
grupo, peso visual) e `app.COMANDOS` diz o que ela roda. Uma `assert` no import garante
que as duas listas nao divirjam &mdash; acao com botao e sem comando da 500 no clique,
acao com comando e sem botao e codigo morto.

**`templates/components/` &mdash; as pecas.** `ui.html` tem o que e generico (botao,
selo, menu, cabecalho, tabela) e `servidor.html` o que conhece o dominio (estado do
servico, barra de navegacao, controles de energia, cartao do painel). Toda acao que muda
alguma coisa monta o proprio campo de CSRF: era uma linha copiada em ~40 formularios, e
basta esquece-la uma vez para ter um botao que da 400 so em producao.

**`static/css/` e `static/js/` &mdash; camadas.** O CSS vai de `tokens` (valores) a
`pages` (o que e de uma tela so), cada camada podendo depender so das anteriores. O JS e
um modulo por comportamento, com o mesmo contrato &mdash; `{ seletor, montar(el) }` — e o
`app.js` so liga cada um aos elementos que a pagina trouxe. **Nenhum template tem
`<script>` com logica dentro**, nem `onsubmit="return confirm(...)"`: a mensagem de
confirmacao viaja em `data-confirmar`, e o nome do arquivo (que vem do container) nunca
mais entra dentro de codigo JavaScript.

```bash
pct exec <ADMIN_CTID> -- systemctl status gamepanel.service --no-pager
pct exec <ADMIN_CTID> -- journalctl -u gamepanel.service -f
```

Esqueceu a senha? Rode o `deploy-admin.ps1` de novo com `ADMIN_PASSWORD` preenchido —
ele redefine a senha do usuario sem tocar nos servidores cadastrados (nem no papel dele).
Para os demais usuarios, um administrador redefine a senha na tela **Usuarios**.
