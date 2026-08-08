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
4. Cria o servico systemd `<jogo>.service` (start no boot, restart em falha) e o helper
   `update-game` dentro do CT
5. Sobe o servidor, valida que ficou ativo e imprime o resumo com **as portas a redirecionar**

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
