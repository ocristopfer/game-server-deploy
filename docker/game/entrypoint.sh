#!/bin/bash
# Prepara o container de jogo falso: autoriza a chave do painel, cria os arquivos de
# configuracao que o jogo teria, liga o "servidor" e sobe o sshd.
set -Eeuo pipefail

GAME_KIND="${GAME_KIND:-palworld}"
GAME_SERVICE="${GAME_SERVICE:-game.service}"

authorize_panel_key() {
  install -d -m 700 /root/.ssh
  echo "==> esperando a chave publica do painel em /keys/panel.pub"
  for _ in $(seq 1 90); do
    [ -f /keys/panel.pub ] && break
    sleep 1
  done
  if [ -f /keys/panel.pub ]; then
    cat /keys/panel.pub >/root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    echo "==> chave do painel autorizada"
  else
    echo "[aviso] a chave do painel nao apareceu; o painel nao vai conseguir entrar" >&2
  fi
}

seed_palworld() {
  local cfg=/opt/game/Pal/Saved/Config/LinuxServer
  install -d -o steam -g steam "$cfg" /opt/game/Pal/Saved/SaveGames/0
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

# Um save binario e um log grande: e com eles que da para testar o download e o modo
# somente-leitura do editor sem instalar jogo nenhum.
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
  # Dono igual ao do jogo de verdade: e assim que da para ver se o editor do painel
  # preserva o dono ao salvar (ele grava como root).
  chown -R steam:steam /opt/game
}

main() {
  authorize_panel_key
  seed_game_files
  install -d /run/sshd /run/fakesystemd /var/log/fakegame
  ssh-keygen -A >/dev/null
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
  echo "==> iniciando ${GAME_SERVICE} (simulado)"
  systemctl start "$GAME_SERVICE" || true

  # Porta de query da Steam. GAME_QUERY_A2S=0 imita um jogo que NAO publica consulta
  # (o RuneScape Dragonwilds e assim): ai so sobra contar pelo log.
  if [ "${GAME_QUERY_A2S:-1}" = "1" ]; then
    echo "==> subindo o query A2S falso na porta ${GAME_QUERY_PORT:-27015}/udp"
    setsid nohup python3 /usr/local/bin/fake-a2s >/var/log/fake-a2s.log 2>&1 &
  else
    echo "==> sem query A2S (jogo que nao publica consulta na rede)"
  fi

  # API REST de administracao, no formato da do Palworld. GAME_API=0 imita o jogo que
  # nao tem API nenhuma (o RuneScape Dragonwilds e assim). Escuta so em 127.0.0.1: o
  # painel chega nela por SSH, de dentro do container.
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
