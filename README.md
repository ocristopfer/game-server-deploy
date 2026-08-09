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

## Jogos definidos

| Jogo | Comando | Portas |
|------|---------|--------|
| RuneScape: Dragonwilds | `.\deploy-game.ps1 -Game dragonwilds` | 7777/udp |
| Palworld | `.\deploy-game.ps1 -Game palworld` | 8211/udp, 27015/udp |

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
ver status, start/stop/restart, atualizar pelo SteamCMD, ler logs, **abrir um terminal
interativo** e **editar os arquivos de configuracao dos jogos** — tudo direto dentro de
cada container.

```powershell
.\deploy-admin.ps1                # usa as chaves ADMIN_* do .env
.\deploy-admin.ps1 -Interactive   # pergunta cada valor
```

No fim o deploy mostra a URL (`http://<ip-do-ct>:8080`), o usuario e a senha.

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
| CTs de jogo existentes | preencha `ADMIN_AUTHORIZE_CTIDS=210 211` e rode o `deploy-admin.ps1` |
| Caso a caso | copie o comando pronto da tela **Acesso SSH** do painel |

A chave publica aparece no resumo do deploy do painel e na tela "Acesso SSH".

### Cadastrando um servidor

Em **Adicionar**, informe:

- **Host** — IP do container do jogo (ex.: `192.168.2.20`)
- **Servico** — a unit systemd (ex.: `dragonwilds.service`)
- **Usuario/porta SSH** — normalmente `root` e `22`
- **Pasta de configuracao** (opcional) — onde a tela **Arquivos** abre por padrao
  (ex.: `/opt/game/Pal/Saved/Config/LinuxServer`)

Start, stop, restart, update, terminal e editor rodam a partir dai. Acoes demoradas
(update) viram um job com a saida atualizando ao vivo na tela.

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
- Arquivos binarios sao recusados; o limite e `ADMIN_FILE_MAX_KB` (padrao 1024 KB).
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
| `/opt/gamepanel/` | aplicacao (Flask + `static/terminal.js`) |
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
