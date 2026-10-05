#!/bin/bash
# Plays the role of systemd for ONE service: runs the game as 'steam' and brings it back up
# if it crashes (the same Restart=on-failure/RestartSec as the LXC unit).
#
# Called by the container's 'systemctl'; all output (stdout+stderr) is already redirected
# to /var/log/game/<unit>.log, which is what the 'journalctl' here reads.
set -u

unit="${1:?uso: game-supervisor <unidade>}"
STATE_DIR=/run/game
mkdir -p "$STATE_DIR"

# shellcheck disable=SC1091
. /etc/game/service.env

GAME_DIR="${GAME_DIR:-/opt/game}"
GAME_USER="${GAME_USER:-steam}"
RESTART_SEC="${RESTART_SEC:-10}"
carimbo() { date '+%b %d %H:%M:%S'; }
diga() { echo "$(carimbo) $(hostname) ${unit}: $*"; }

while true; do
  diga "iniciando: ${GAME_EXEC}"
  # The recorded pid has to be the GAME's (the panel measures its CPU/RAM). That is why
  # the chain only uses 'exec': subshell -> setpriv -> env -> sh -> game binary, all
  # in the same pid.
  (
    cd "$GAME_DIR" || exit 1
    exec setpriv --reuid="$GAME_USER" --regid="$GAME_USER" --init-groups \
      /usr/bin/env "HOME=/home/${GAME_USER}" "USER=${GAME_USER}" \
        "LD_LIBRARY_PATH=${GAME_DIR}:${GAME_DIR}/linux64:${LD_LIBRARY_PATH:-}" \
      /bin/sh -c "exec ${GAME_EXEC}"
  ) &
  filho=$!
  echo "$filho" >"$STATE_DIR/${unit}.main"
  wait "$filho"
  codigo=$?
  rm -f "$STATE_DIR/${unit}.main"

  if [ -f "$STATE_DIR/${unit}.stop" ]; then
    diga "parado a pedido (codigo ${codigo})"
    break
  fi
  if [ "$codigo" -eq 0 ]; then
    diga "o servidor saiu normalmente (codigo 0) - nao vou reiniciar"
    break
  fi
  diga "o servidor saiu com codigo ${codigo}; reiniciando em ${RESTART_SEC}s"
  sleep "$RESTART_SEC"
done
