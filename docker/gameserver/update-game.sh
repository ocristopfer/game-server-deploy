#!/usr/bin/env bash
# Updates the game through SteamCMD and restarts the server. Same shortcut as the LXC, so
# the panel can call "Atualizar jogo" without knowing where the server is running.
set -Eeuo pipefail

# shellcheck disable=SC1091
. /etc/game/service.env

systemctl stop "$GAME_UNIT" || true

# </dev/null: the timer/panel has no one to answer if SteamCMD decides to ask something.
${STEAM_TIMEOUT_UPDATE:-}setpriv --reuid=steam --regid=steam --init-groups \
  /usr/bin/env HOME=/home/steam \
  /opt/steamcmd/steamcmd.sh ${STEAMCMD_PLATFORM_ARG:-}+force_install_dir "$GAME_DIR" \
    ${STEAMCMD_LOGIN_CACHED} +app_update "$STEAM_APP_ID" validate +quit </dev/null

systemctl start "$GAME_UNIT"
echo "Atualizacao concluida."
