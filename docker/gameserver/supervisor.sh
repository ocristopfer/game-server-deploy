#!/bin/bash
# Plays the role of systemd for ONE service: runs the game as 'steam' and brings it back up
# if it crashes (the same Restart=on-failure/RestartSec as the LXC unit).
#
# Called by the container's 'systemctl'; all output (stdout+stderr) is already redirected
# to /var/log/game/<unit>.log, which is what the 'journalctl' here reads.
set -u

unit="${1:?uso: game-supervisor <unidade>}"
STATE_DIR=/run/game
# Where systemd would look for the unit's drop-ins. lib/ct-panel-access.sh writes the mod overlay
# drop-in there (EnvironmentFile=-/etc/gamepanel/game-env/service.env), the same as on a CT.
DROPIN_DIR="/etc/systemd/system/${unit}.service.d"
mkdir -p "$STATE_DIR"

# shellcheck disable=SC1091
. /etc/game/service.env

GAME_DIR="${GAME_DIR:-/opt/game}"
GAME_USER="${GAME_USER:-steam}"
RESTART_SEC="${RESTART_SEC:-10}"
carimbo() { date '+%b %d %H:%M:%S'; }
diga() { echo "$(carimbo) $(hostname) ${unit}: $*"; }

# One KEY=value assignment, the way systemd reads it: the value loses ONE pair of surrounding
# quotes and is never expanded. The key must be a plain name - this ends up as an argument of
# `env`, and anything else (a leading dash, a second '=') would be read as something else.
add_assignment() {
  local kv="$1" key value
  key="${kv%%=*}"
  value="${kv#*=}"
  [[ "$kv" == *=* && "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return 0
  if [[ "$value" =~ ^\'(.*)\'$ || "$value" =~ ^\"(.*)\"$ ]]; then value="${BASH_REMATCH[1]}"; fi
  unit_env+=("${key}=${value}")
  unit_keys+=("$key")
}

# What systemd would hand the unit from its drop-ins: Environment= and EnvironmentFile=, in file
# name order, a later value winning. Read again at every (re)start, as systemd does: the Mods
# screen changes the overlay and restarts the server, and that has to be enough. PARSED, never
# sourced: the overlay is written by steam, and this runs as root - a `source` would run
# whatever line the game managed to put there. The folder that holds it is root's, so steam
# changes the content, never which file is read.
load_unit_environment() {
  local f line file
  unit_env=()
  unit_keys=()
  for f in "$DROPIN_DIR"/*.conf; do
    [ -f "$f" ] || continue
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        Environment=*) add_assignment "${line#Environment=}" ;;
        EnvironmentFile=*)
          file="${line#EnvironmentFile=}"
          # '-' = optional, like systemd. A required file that is missing is reported and the
          # game still starts: here the alternative is a server that never comes back.
          if [ ! -f "${file#-}" ]; then
            [ "${file:0:1}" = - ] || diga "EnvironmentFile missing: ${file}"
            continue
          fi
          while IFS= read -r line || [ -n "$line" ]; do
            case "$line" in ''|'#'*|';'*) continue ;; esac
            add_assignment "$line"
          done <"${file#-}"
          ;;
      esac
    done <"$f"
  done
}

# TERM/INT mean "stop": remembered, not obeyed at once (see the wait below). systemd itself
# would never die before its service does.
term_received=0
trap 'term_received=1' TERM INT

while true; do
  load_unit_environment
  diga "iniciando: ${GAME_EXEC}"
  # Only the NAMES go to the log: the values are the owner's (paths, Wine settings), and the
  # names are enough to see that a loader is (or is not) reaching the game.
  [ "${#unit_keys[@]}" -eq 0 ] || diga "environment from drop-ins: ${unit_keys[*]}"
  # The recorded pid has to be the GAME's (the panel measures its CPU/RAM). That is why
  # the chain only uses 'exec': subshell -> setpriv -> env -> sh -> game binary, all
  # in the same pid. The drop-in variables come LAST so they win, as a drop-in's
  # Environment= wins over the unit's own.
  (
    cd "$GAME_DIR" || exit 1
    exec setpriv --reuid="$GAME_USER" --regid="$GAME_USER" --init-groups \
      /usr/bin/env "HOME=/home/${GAME_USER}" "USER=${GAME_USER}" \
        "LD_LIBRARY_PATH=${GAME_DIR}:${GAME_DIR}/linux64:${LD_LIBRARY_PATH:-}" \
        "${unit_env[@]}" \
      /bin/sh -c "exec ${GAME_EXEC}"
  ) &
  filho=$!
  echo "$filho" >"$STATE_DIR/${unit}.main"
  wait "$filho"
  codigo=$?
  # The stop sends TERM to the whole group, this script included. A trapped signal makes `wait`
  # return at once, with the game still saving: wait again until it really exits. Without this
  # the supervisor died on the TERM, `systemctl stop` saw it gone and returned while the world
  # was still being written - a restart then started a second copy next to it, and `docker stop`
  # took the container down mid-save.
  while kill -0 "$filho" 2>/dev/null; do
    wait "$filho"
    codigo=$?
  done
  rm -f "$STATE_DIR/${unit}.main"

  if [ -f "$STATE_DIR/${unit}.stop" ] || [ "$term_received" -eq 1 ]; then
    diga "parado a pedido (codigo ${codigo})"
    break
  fi
  if [ "$codigo" -eq 0 ]; then
    echo success >"$STATE_DIR/${unit}.result"
    diga "o servidor saiu normalmente (codigo 0) - nao vou reiniciar"
    break
  fi
  echo exit-code >"$STATE_DIR/${unit}.result"
  # NRestarts for the panel: a counter that only goes up while the game keeps dying is how the
  # crash-loop alert sees a server that is "active" most of the time and playable none of it.
  echo $(( $(cat "$STATE_DIR/${unit}.restarts" 2>/dev/null || echo 0) + 1 )) >"$STATE_DIR/${unit}.restarts"
  diga "o servidor saiu com codigo ${codigo}; reiniciando em ${RESTART_SEC}s"
  sleep "$RESTART_SEC"
  # A stop that arrives during the pause must not bring the game back.
  if [ -f "$STATE_DIR/${unit}.stop" ] || [ "$term_received" -eq 1 ]; then break; fi
done
