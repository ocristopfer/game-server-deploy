#!/usr/bin/env bash
# Atualiza o jogo pelo SteamCMD e reinicia o servidor. Mesmo atalho do LXC, para o
# painel poder chamar "Atualizar jogo" sem saber onde o servidor esta rodando.
set -Eeuo pipefail

# shellcheck disable=SC1091
. /etc/game/service.env

systemctl stop "$GAME_UNIT" || true

# </dev/null: o timer/painel nao tem quem responda se o SteamCMD resolver perguntar algo.
${STEAM_TIMEOUT_UPDATE:-}setpriv --reuid=steam --regid=steam --init-groups \
  /usr/bin/env HOME=/home/steam \
  /opt/steamcmd/steamcmd.sh ${STEAMCMD_PLATFORM_ARG:-}+force_install_dir "$GAME_DIR" \
    ${STEAMCMD_LOGIN_CACHED} +app_update "$STEAM_APP_ID" validate +quit </dev/null

systemctl start "$GAME_UNIT"
echo "Atualizacao concluida."
