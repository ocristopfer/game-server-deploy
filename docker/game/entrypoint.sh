#!/bin/bash
# Prepares the fake game container: authorizes the panel key, creates the config files
# the game would have, starts the "server" and brings up sshd.
set -Eeuo pipefail

GAME_KIND="${GAME_KIND:-palworld}"
GAME_SERVICE="${GAME_SERVICE:-game.service}"
# root = legacy mode (the panel logs in as root); gamepanel = helper mode (docs/security-hardening-
# contract.md). docker-compose.yml runs one container of each, so both paths are exercised daily.
GAME_SSH_USER="${GAME_SSH_USER:-root}"
PANEL_ACCESS=/usr/local/lib/gamepanel/ct-panel-access.sh

authorize_panel_key() {
  install -d -m 700 /root/.ssh
  echo "==> esperando a chave publica do painel em /keys/panel.pub"
  for _ in $(seq 1 90); do
    [ -f /keys/panel.pub ] && break
    sleep 1
  done
  if [ ! -f /keys/panel.pub ]; then
    echo "[aviso] a chave do painel nao apareceu; o painel nao vai conseguir entrar" >&2
    return 0
  fi
  case "$GAME_SSH_USER" in
    root)
      cat /keys/panel.pub >/root/.ssh/authorized_keys
      chmod 600 /root/.ssh/authorized_keys
      echo "==> chave do painel autorizada (root, modo legado)"
      ;;
    gamepanel)
      # The same piece a real CT gets: gamepanel user, sudo rules, gp-service (which here calls
      # the fake systemctl) and the key. Root gets no key at all; lock_root, further down, refuses
      # root over SSH once sshd has its host keys.
      bash "$PANEL_ACCESS" install "$GAME_SERVICE" "$(cat /keys/panel.pub)"
      rm -f /root/.ssh/authorized_keys
      echo "==> chave do painel autorizada (gamepanel, modo helper)"
      ;;
    *) echo "[erro] GAME_SSH_USER invalido: $GAME_SSH_USER (use root ou gamepanel)" >&2; exit 1 ;;
  esac
}

# Helper mode only. After `ssh-keygen -A` because the piece runs `sshd -t`, which needs the host
# keys. It verifies first that gamepanel reaches steam and gp-service; if not, the container
# fails to start instead of coming up with a panel that cannot get in.
lock_root() {
  [ "$GAME_SSH_USER" = gamepanel ] || return 0
  [ -f /keys/panel.pub ] || return 0
  bash "$PANEL_ACCESS" lock
}

seed_palworld() {
  local cfg=/opt/game/Pal/Saved/Config/LinuxServer
  # Binaries/Linux: where the Mods screen installs UE4SS (the profile loader_dir).
  install -d -o steam -g steam "$cfg" /opt/game/Pal/Saved/SaveGames/0 /opt/game/Pal/Binaries/Linux
  [ -s "$cfg/PalWorldSettings.ini" ] && return 0
  cat >"$cfg/PalWorldSettings.ini" <<'INI'
[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,NightTimeSpeedRate=1.000000,ExpRate=1.000000,PalCaptureRate=1.000000,PalSpawnNumRate=1.000000,PalDamageRateAttack=1.000000,PalDamageRateDefense=1.000000,PlayerDamageRateAttack=1.000000,PlayerDamageRateDefense=1.000000,PlayerStomachDecreaceRate=1.000000,PlayerStaminaDecreaceRate=1.000000,PlayerAutoHPRegeneRate=1.000000,DeathPenalty=All,bEnablePlayerToPlayerDamage=False,bEnableFriendlyFire=False,bEnableInvaderEnemy=True,bActiveUNKO=False,bEnableAimAssistPad=True,bEnableAimAssistKeyboard=False,DropItemMaxNum=3000,BaseCampMaxNum=128,BaseCampWorkerMaxNum=15,DropItemAliveMaxHours=1.000000,bAutoResetGuildNoOnlinePlayers=False,AutoResetGuildTimeNoOnlinePlayers=72.000000,GuildPlayerMaxNum=20,PalEggDefaultHatchingTime=72.000000,WorkSpeedRate=1.000000,bIsMultiplay=False,bIsPvP=False,bCanPickupOtherGuildDeathPenaltyDrop=False,bEnableNonLoginPenalty=True,bEnableFastTravel=True,bIsStartLocationSelectByMap=True,bExistPlayerAfterLogout=False,bEnableDefenseOtherGuildPlayer=False,CoopPlayerMaxNum=4,ServerPlayerMaxNum=32,ServerName="Servidor de teste do painel",ServerDescription="Container falso do docker compose",AdminPassword="troque-me",ServerPassword="",PublicPort=8211,PublicIP="",RCONEnabled=False,RCONPort=25575,Region="",bUseAuth=True,BanListURL="https://api.palworldgame.com/api/banlist.txt")
INI
  cat >/opt/game/DefaultPalWorldSettings.ini <<'INI'
; Copia intacta que o jogo usa como base - nao editar.
[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,ServerName="Default Palworld Server",ServerPlayerMaxNum=32,PublicPort=8211)
INI
  printf '#!/bin/sh\necho "PalServer (simulado)"\n' >/opt/game/PalServer.sh
  chmod 0755 /opt/game/PalServer.sh
}

seed_dragonwilds() {
  local cfg=/opt/game/RSDragonwilds/Saved/Config/LinuxServer
  install -d -o steam -g steam "$cfg" /opt/game/RSDragonwilds/Saved/SaveGames
  [ -s "$cfg/DedicatedServer.ini" ] && return 0
  cat >"$cfg/DedicatedServer.ini" <<'INI'
[/Script/Dragonwilds.DedicatedServerSettings]
ServerName=Servidor de teste do painel
ServerPassword=
AdminPassword=troque-me
MaxPlayers=8
OwnerID=
WorldName=Gielinor
INI
  cat >"$cfg/GameUserSettings.ini" <<'INI'
[/Script/Engine.GameUserSettings]
bUseVSync=False
FrameRateLimit=30.000000
INI
  printf '#!/bin/sh\necho "RSDragonwildsServer (simulado)"\n' >/opt/game/RSDragonwildsServer.sh
  chmod 0755 /opt/game/RSDragonwildsServer.sh
}

# A binary save and a big log: they are what lets us test the download and the editor's
# read-only mode without installing any game.
seed_arquivos_grandes() {
  local saves="$1" log="$2"
  install -d -o steam -g steam "$(dirname "$saves")" "$(dirname "$log")"
  [ -s "$saves" ] || dd if=/dev/urandom of="$saves" bs=1M count=6 status=none
  if [ ! -s "$log" ]; then
    awk 'BEGIN { for (i = 1; i <= 60000; i++)
      printf "2026-01-01 00:00:00 [Info] linha de log numero %d - mundo salvo, jogadores: %d\n", i, i % 8 }' >"$log"
  fi
}

seed_game_files() {
  install -d -o steam -g steam /opt/game
  case "$GAME_KIND" in
    palworld)
      seed_palworld
      seed_arquivos_grandes /opt/game/Pal/Saved/SaveGames/0/Level.sav /opt/game/Pal/Saved/Logs/Pal.log
      ;;
    dragonwilds)
      seed_dragonwilds
      seed_arquivos_grandes /opt/game/RSDragonwilds/Saved/SaveGames/world.sav \
        /opt/game/RSDragonwilds/Saved/Logs/RSDragonwilds.log
      ;;
    *) echo "[aviso] GAME_KIND desconhecido: $GAME_KIND" >&2 ;;
  esac
  # Same owner as the real game: that is how we can check that the panel editor keeps
  # the owner when saving (it writes as root).
  chown -R steam:steam /opt/game
}

main() {
  authorize_panel_key
  seed_game_files
  # 0755: in helper mode the panel reads the fake journal (these logs) as gamepanel, without sudo.
  install -d -m 0755 /run/sshd /run/fakesystemd /var/log/fakegame
  ssh-keygen -A >/dev/null
  # Legacy mode's setting. In helper mode the drop-in written by lock_root wins: Debian's
  # sshd_config includes sshd_config.d/*.conf at the TOP, and sshd keeps the first value it reads.
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
  lock_root
  echo "==> iniciando ${GAME_SERVICE} (simulado)"
  systemctl start "$GAME_SERVICE" || true

  # Steam query port. GAME_QUERY_A2S=0 mimics a game that does NOT publish a query
  # (RuneScape Dragonwilds is like that): then counting by the log is all that is left.
  if [ "${GAME_QUERY_A2S:-1}" = "1" ]; then
    echo "==> subindo o query A2S falso na porta ${GAME_QUERY_PORT:-27015}/udp"
    setsid nohup python3 /usr/local/bin/fake-a2s >/var/log/fake-a2s.log 2>&1 &
  else
    # A game without an A2S query is NOT without a port: it opens the game port and simply
    # does not answer the query (RuneScape Dragonwilds is like that). Opening a mute UDP
    # socket here reproduces that, and it is what makes the panel assistant conclude "the
    # game process opened the port and did not answer" instead of "found no port at all".
    echo "==> sem query A2S: abrindo ${GAME_UDP_PORT:-7777}/udp mudo (como o jogo real)"
    setsid nohup python3 -c "
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', ${GAME_UDP_PORT:-7777}))
while True:
    time.sleep(3600)
" >/var/log/fake-udp-mudo.log 2>&1 &
  fi

  # Admin REST API, in the Palworld format. GAME_API=0 mimics a game that has no API at
  # all (RuneScape Dragonwilds is like that). It listens only on 127.0.0.1: the panel
  # reaches it over SSH, from inside the container.
  if [ "${GAME_API:-0}" = "1" ]; then
    echo "==> subindo a API REST falsa em 127.0.0.1:${GAME_API_PORT:-8212}/tcp"
    setsid nohup python3 /usr/local/bin/fake-restapi >/var/log/fake-restapi.log 2>&1 &
  else
    echo "==> sem API REST (jogo que nao publica API de administracao)"
  fi
  echo "==> sshd pronto em $(hostname)"
  exec /usr/sbin/sshd -D -e
}

main "$@"
