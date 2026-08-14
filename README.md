# Game Server Deploy (Proxmox LXC ou Docker + SteamCMD)

Deploy simplificado de servidores dedicados de jogos, inspirado no
[LinuxGSM](https://github.com/GameServerManagers/LinuxGSM) porem muito mais simples: um
comando cria o container, instala o SteamCMD, baixa o jogo, cria o servico e no final
mostra **quais portas redirecionar no roteador**.

Dois destinos, a mesma definicao de jogo (`games/<jogo>.env`) nos dois:

| Destino | Comando | Quando usar |
|---------|---------|-------------|
| **LXC no Proxmox** | `.\deploy-game.ps1 -Game palworld` | voce tem um Proxmox e quer o jogo num container proprio, com systemd de verdade |
| **Docker** | `.\deploy-docker.ps1 -Game palworld` | qualquer maquina com Docker (ate o seu PC), sem Proxmox no caminho |

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
.\deploy-game.ps1 -Game dragonwilds
```

### Modo interativo (pergunta cada valor)

```powershell
.\deploy-game.ps1 -Game dragonwilds -Interactive
```

Os valores do `.env` (se existir) viram os defaults dos prompts — Enter aceita.

### Deploy generico por App ID da Steam

```powershell
.\deploy-game.ps1 -AppId 4019830
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
| RuneScape: Dragonwilds | `.\deploy-game.ps1 -Game dragonwilds` | 7777/udp |
| Palworld | `.\deploy-game.ps1 -Game palworld` | 8211/udp, 27015/udp |
| Satisfactory | `.\deploy-game.ps1 -Game satisfactory` | 7787/udp, 7787/tcp |
| Enshrouded | `.\deploy-game.ps1 -Game enshrouded` | 15636/udp, 15637/udp |
| DayZ | `.\deploy-game.ps1 -Game dayz` | 2302-2304/udp, 27016/udp |
| Icarus | `.\deploy-game.ps1 -Game icarus` | 17777/udp, 27017/udp |

Troque `deploy-game.ps1` por `deploy-docker.ps1` para o mesmo jogo em Docker. Alem da
instalacao, cada `games/<jogo>.env` diz ao painel onde fica a configuracao
(`CONFIG_PATH`/`CONFIG_FILES`) e como contar jogadores (`QUERY_PORT`/`PLAYER_SOURCE`) —
e o que faz o servidor nascer cadastrado e com a tela **Config** pronta.

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
.\deploy-game.ps1 -Game dayz -SteamGuardCode 12345
```

Sem credencial nenhuma, o deploy para antes de enviar qualquer coisa:

```
THROW: O servidor de dayz nao esta disponivel por login anonimo na Steam.
       Preencha STEAM_USER e STEAM_PASS no .env (conta que POSSUA o jogo) ou use -Interactive.
```

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
.\deploy-docker.ps1 -Panel                  # sobe o painel (http://localhost:8080)
.\deploy-docker.ps1 -Game palworld          # sobe o jogo e o cadastra no painel
.\deploy-docker.ps1 -Game dayz -SteamGuardCode 12345
.\deploy-docker.ps1 -Game palworld -Down    # para o servidor (o mundo fica no volume)
.\deploy-docker.ps1 -Game palworld -Recreate
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
.\deploy-admin.ps1                # usa as chaves ADMIN_* do .env
.\deploy-admin.ps1 -Interactive   # pergunta cada valor
```

No fim o deploy mostra a URL (`http://<ip-do-ct>:8080`), o usuario e a senha.

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
- O envio direto troca `app.py`, `templates/` e `static/` (removendo templates que
  sairam do repo) e reinicia o servico, abortando com as ultimas linhas do log se ele
  nao voltar.
- **Config nao vai por ai**: mudar `ADMIN_*` (portas, limites, senha do painel) ou os
  recursos do CT exige o caminho completo:

```powershell
.\deploy-admin.ps1 -Full          # cria/reconfigura o CT pelo Proxmox
```

### Acesso ao Proxmox por senha

O ideal e ter sua chave publica autorizada no Proxmox. Quando nao ha chave, preencha
`PROXMOX_PASSWORD` no `.env` (ou passe `-ProxmoxPassword`) e o deploy entra por senha.
Vale para os **dois** scripts — `deploy-admin.ps1` e `deploy-game.ps1`:

```powershell
.\deploy-admin.ps1 -Full -InstallKey        # painel: entra por senha e autoriza sua chave
.\deploy-game.ps1 -Game icarus -InstallKey  # jogo: idem, no mesmo host Proxmox
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

### Terminal interativo

A aba **Terminal** abre uma sessao SSH de verdade dentro do container, com TTY: `htop`,
`nano`, `vi`, `tail -f` e prompts de confirmacao funcionam como num terminal local.

- Emulador proprio (`admin/static/terminal.js`), sem dependencia externa: cores 16/256/RGB,
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

O motor fica em `admin/gameconf.py`, isolado do resto do painel (nao fala SSH nem HTTP),
com testes proprios:

```bash
docker compose exec panel python3 /opt/gamepanel/test_gameconf.py
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
- `ADMIN_FILE_ROOTS` restringe onde o navegador de arquivos pode entrar (padrao: tudo).
- Pare o servidor antes de editar o que ele reescreve ao sair — varios jogos sobrescrevem
  o `.ini` no shutdown.

### Console de comandos

Cada servidor tem uma aba **Console**: voce digita um comando e ele executa como `root`
**dentro daquele container de jogo**, com a saida na tela e o historico registrado (quem
rodou, o que rodou, exit code). Util para um comando so, sem abrir sessao.

- Sem TTY: para `vim`/`htop` e prompts, use o **Terminal**.
- Ctrl+Enter executa; as setas ↑/↓ percorrem o historico.
- Limite de tempo por comando: 600s (`GAMEPANEL_SHELL_TIMEOUT`).

Console e terminal sao execucao remota de comandos exposta numa pagina web — quem entrar
no painel tem root nos containers de jogo. Se nao quiser essa capacidade, desligue com
`ADMIN_ALLOW_SHELL=0` no `.env` (as duas telas somem e as rotas respondem 403); o editor
de arquivos tem o proprio interruptor, `ADMIN_ALLOW_FILES=0`.

### Testando o painel localmente (docker compose)

Para mexer no painel sem depender do Proxmox:

```bash
docker compose up --build         # http://localhost:8080 - admin / admin12345
```

Sobem tres containers: o painel e dois "servidores de jogo" falsos (Debian com `sshd`, um
`systemctl`/`journalctl` simulados e os `.ini` que o jogo teria). Os dois ja vem
cadastrados no painel — com o `.ini` apontado, entao a tela **Config** tambem da para
testar de ponta a ponta, junto com start/stop/update, terminal e editor. O codigo entra
por bind mount com `--reload`: editar `admin/app.py` ou os templates e recarregar a
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
docker compose exec panel python3 /opt/gamepanel/test_gameconf.py   # testes do parser
docker compose exec panel python3 /opt/gamepanel/test_players.py    # testes da contagem
docker compose exec game-palworld sh -c 'echo 7 > /run/fake-players' # fixa a contagem
docker compose down -v            # zera banco, chaves e arquivos de teste
```

### Seguranca

- Login com usuario unico, senha com hash **scrypt** no SQLite, sessao em cookie assinado
  (HttpOnly, SameSite=Lax) e bloqueio apos 5 tentativas erradas em 5 minutos
- Todos os POSTs exigem token **CSRF**
- O painel serve **HTTP puro** — pensado para LAN. Nao exponha na internet sem um proxy
  reverso com TLS na frente
- Comprometer o painel da acesso root aos **containers de jogo**, nao ao Proxmox

### Arquivos

| Caminho (no CT do painel) | O que e |
|---------------------------|---------|
| `/opt/gamepanel/` | aplicacao (Flask + `static/terminal.js` + `static/metrics.js`) |
| `/var/lib/gamepanel/panel.db` | SQLite: usuarios, servidores, historico |
| `/var/lib/gamepanel/known_hosts` | host keys aprendidas dos containers |
| `/etc/gamepanel/id_ed25519` | chave SSH do painel |
| `/etc/gamepanel/panel.env` | configuracao lida pelo systemd |

```bash
pct exec <ADMIN_CTID> -- systemctl status gamepanel.service --no-pager
pct exec <ADMIN_CTID> -- journalctl -u gamepanel.service -f
```

Esqueceu a senha? Rode o `deploy-admin.ps1` de novo com `ADMIN_PASSWORD` preenchido —
ele redefine a senha do usuario sem tocar nos servidores cadastrados.
