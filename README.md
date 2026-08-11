# Game Server Deploy (Proxmox LXC + SteamCMD)

Deploy simplificado de servidores dedicados de jogos em containers LXC no Proxmox,
inspirado no [LinuxGSM](https://github.com/GameServerManagers/LinuxGSM) porem muito mais simples:
um comando cria o container, instala o SteamCMD, baixa o jogo, cria o servico systemd
e no final mostra **quais portas redirecionar no roteador**.

Segue o mesmo padrao do deploy do Frigate: o `.ps1` roda no Windows, envia o bundle
via SSH para o host Proxmox e executa o `provision-game-lxc.sh` la (que usa `pct`).

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

Se `PANEL_PUBKEY` estiver no `.env`, o passo 2 tambem instala o `sshd` e autoriza a
chave do [painel administrativo](#painel-administrativo-web) — o CT ja nasce gerenciavel pela tela.

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
| 219 | fallback / `-AppId` | 192.168.2.29 |

## Jogos definidos

| Jogo | Comando | Portas |
|------|---------|--------|
| RuneScape: Dragonwilds | `.\deploy-game.ps1 -Game dragonwilds` | 7777/udp |
| Palworld | `.\deploy-game.ps1 -Game palworld` | 8211/udp, 27015/udp |
| Satisfactory | `.\deploy-game.ps1 -Game satisfactory` | 7777/udp, 7777/tcp |
| Enshrouded | `.\deploy-game.ps1 -Game enshrouded` | 15636/udp, 15637/udp |

### RuneScape: Dragonwilds — notas

- App do servidor dedicado: `4019830` (build Linux nativo, `RSDragonwildsServer.sh`)
- Porta padrao **7777/UDP**; cada mundo adicional usa a seguinte (7778, 7779...)
- Config criada no primeiro start (localize com `find /opt/game -name DedicatedServer.ini`):
  nome do servidor, senha do mundo, senha de admin, OwnerID. Pare o servidor antes de editar!
- Limite de jogadores: fixo em 6 (travado pela Jagex, nao configuravel)
- Saves: `/opt/game/RSDragonwilds/Saved/SaveGames/`

### Palworld — notas

- App do servidor dedicado: `2394010` (build Linux nativo, `PalServer.sh`)
- Portas: **8211/UDP** (jogo) e **27015/UDP** (query da Steam, necessaria para aparecer
  na lista da comunidade). RCON (25575/TCP) so se habilitado no `.ini` — nao redirecione
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
- Portas: uma so, **7777/UDP** (jogo) e **7777/TCP** (API HTTPS de gerenciamento que o
  cliente usa para adotar e configurar o servidor). Abra as duas. As portas antigas
  15000/15777 sairam na 1.0
- O deploy cria o symlink `~steam/.steam/sdk64/steamclient.so` (sem ele o servidor sobe
  mas nao registra na Steam)
- Config: nao ha `.ini` para preencher antes — no cliente, **Servidores > Adicionar servidor**
  com `IP:7777`, defina a senha de admin e reivindique o servidor. Ajustes finos depois em
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

## Painel administrativo (web)

Um container separado sobe um painel web para gerenciar todos os servidores: cadastrar,
ver status, **jogadores conectados** e **uso de CPU/memoria/disco/rede**,
start/stop/restart, atualizar pelo SteamCMD, ler logs (com modo ao vivo), **abrir um
terminal interativo** e **editar ou baixar os arquivos dos jogos** — tudo direto dentro
de cada container.

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
`PROXMOX_PASSWORD` no `.env` (ou passe `-ProxmoxPassword`) e o deploy entra por senha:

```powershell
.\deploy-admin.ps1 -Full -InstallKey   # entra por senha e autoriza sua chave no Proxmox
```

- O deploy tenta a chave primeiro e so cai para a senha se ela nao for aceita.
- A senha nunca vai para disco: ela e passada ao `ssh` pelo mecanismo `SSH_ASKPASS`
  atraves de uma variavel de ambiente deste processo, e some do ambiente no fim (mesmo
  se o deploy falhar no meio).
- `-InstallKey` autoriza sua chave publica no Proxmox uma unica vez; dai em diante nao
  precisa mais da senha no `.env`.

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
| CT de jogo novo | preencha `PANEL_PUBKEY` no `.env` — o `deploy-game.ps1` ja deixa pronto |
| CTs de jogo existentes | preencha `ADMIN_AUTHORIZE_CTIDS=210,211,212,213` e rode o `deploy-admin.ps1` |
| Caso a caso | copie o comando pronto da tela **Acesso SSH** do painel |

A chave publica aparece no resumo do deploy do painel e na tela "Acesso SSH".

### Cadastrando um servidor

Em **Adicionar**, informe:

- **Host** — IP do container do jogo (ex.: `192.168.2.20`)
- **Servico** — a unit systemd (ex.: `dragonwilds.service`)
- **Usuario/porta SSH** — normalmente `root` e `22`
- **Pasta de configuracao** (opcional) — onde a tela **Arquivos** abre por padrao
  (ex.: `/opt/game/Pal/Saved/Config/LinuxServer`)
- **Porta de consulta** (opcional) — porta de query Steam/A2S para contar os jogadores
  online (Palworld: `27015`)

Start, stop, restart, update, terminal e editor rodam a partir dai. Acoes demoradas
(update) viram um job com a saida atualizando ao vivo na tela.

### Jogadores conectados

Ha duas formas, e a tela **Configurar contagem** (botao no card "Jogadores") descobre
qual serve para cada jogo.

**1. Consulta direta (A2S da Steam)** — a mesma consulta que o navegador de servidores
do jogo faz: UDP do painel para a porta de query. Nao passa por SSH, nao precisa de
senha nem RCON, e nao exige nada instalado no container. Palworld responde na
`27015/udp`.

O assistente **pergunta ao container quais portas UDP o jogo abriu** (le `/proc/net/udp`
pelo SSH) e dispara um `A2S_INFO` em cada uma, somando as portas usuais da Steam. Se
alguma responder, um clique em "Usar esta" ja liga a contagem.

**2. Pelo log do servidor** — para jogo que nao publica consulta na rede. O
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

### Editor de configuracoes

A aba **Arquivos** navega pelo sistema de arquivos do container e edita os `.ini`/`.cfg`
do jogo direto no navegador.

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
cadastrados no painel, entao da para testar start/stop/update, o terminal e o editor de
ponta a ponta. O codigo entra por bind mount com `--reload`: editar `admin/app.py` ou os
templates e recarregar a pagina basta.

```bash
docker compose logs -f panel
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
