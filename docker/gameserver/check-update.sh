#!/usr/bin/env bash
# Compares the installed buildid with the one published on Steam and only updates if
# there is a new version -- so the server does not go down for nothing. Same as the LXC's
# check-game-update.
set -Eeuo pipefail

# shellcheck disable=SC1091
. /etc/game/service.env

MANIFEST="${GAME_DIR}/steamapps/appmanifest_${STEAM_APP_ID}.acf"

instalado=$(awk -F'"' '/"buildid"/{print $4; exit}' "$MANIFEST" 2>/dev/null || true)
if [[ -z "$instalado" ]]; then
  echo "Manifesto nao encontrado ($MANIFEST); rodando update completo"
  exec /usr/local/bin/update-game
fi

recente=$(${STEAM_TIMEOUT_INFO:-}setpriv --reuid=steam --regid=steam --init-groups \
  /usr/bin/env HOME=/home/steam \
  /opt/steamcmd/steamcmd.sh ${STEAMCMD_PLATFORM_ARG:-}${STEAMCMD_LOGIN_CACHED} \
    +app_info_update 1 +app_info_print "$STEAM_APP_ID" +quit </dev/null \
  | tr -d '\r' \
  | sed -n '/"branches"/,$p' \
  | sed -n '/"public"/,/}/p' \
  | awk -F'"' '/"buildid"/{print $4; exit}')

if [[ -z "$recente" ]]; then
  echo "Nao foi possivel obter o buildid mais recente da Steam; tentando no proximo ciclo"
  exit 0
fi

if [[ "$instalado" == "$recente" ]]; then
  echo "Jogo ja atualizado (buildid $instalado)"
  exit 0
fi

echo "Update disponivel: $instalado -> $recente. Atualizando..."
exec /usr/local/bin/update-game
