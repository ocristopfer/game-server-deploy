# Game Server Deploy (Proxmox LXC + SteamCMD)

Deploy simplificado de servidores dedicados de jogos em containers LXC no Proxmox,
inspirado no [LinuxGSM](https://github.com/GameServerManagers/LinuxGSM) porem muito mais simples:
um comando cria o container, instala o SteamCMD, baixa o jogo, cria o servico systemd
e no final mostra **quais portas redirecionar no roteador**.

Segue o mesmo padrao do deploy do Frigate: o `.ps1` roda no Windows, envia o bundle
via SSH para o host Proxmox e executa o `provision-game-lxc.sh` la (que usa `pct`).

## Pre-requisitos

- Acesso SSH por chave como `root` ao host Proxmox
- `ssh` e `tar` disponiveis no Windows (nativos no Windows 10/11)

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

### RuneScape: Dragonwilds — notas

- App do servidor dedicado: `4019830` (build Linux nativo, `RSDragonwildsServer.sh`)
- Porta padrao **7777/UDP**; cada mundo adicional usa a seguinte (7778, 7779...)
- Config criada no primeiro start (localize com `find /opt/game -name DedicatedServer.ini`):
  nome do servidor, senha do mundo, senha de admin, OwnerID. Pare o servidor antes de editar!
- Limite de jogadores: fixo em 6 (travado pela Jagex, nao configuravel)
- Saves: `/opt/game/RSDragonwilds/Saved/SaveGames/`

## Comandos uteis (no host Proxmox)

```bash
pct exec <CTID> -- systemctl status dragonwilds.service --no-pager
pct exec <CTID> -- journalctl -u dragonwilds.service -f
pct exec <CTID> -- update-game     # atualiza o jogo via SteamCMD (para/atualiza/reinicia)
```

## Update automatico

O deploy instala um timer systemd (`game-update-check.timer`) que roda todo dia as 06:00
(configuravel via `UPDATE_SCHEDULE` no `.env`, formato OnCalendar). Ele compara o buildid
instalado com o mais recente da Steam e **so para/atualiza/reinicia o servidor quando ha
update de verdade** — sem update, nada e tocado. Desative com `AUTO_UPDATE=0`.

```bash
pct exec <CTID> -- systemctl list-timers game-update-check.timer   # proximo horario
pct exec <CTID> -- check-game-update                               # checar agora
pct exec <CTID> -- journalctl -u game-update-check.service -n 20   # log das checagens
```
