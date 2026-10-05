#!/usr/bin/env bash
# Shortcuts game-start / game-stop / game-restart / game-status / game-logs.
# Each one calls this script with the action as the first argument; the unit comes from
# service.env, so there is no need to remember the service name.
set -u

# shellcheck disable=SC1091
. /etc/game/service.env 2>/dev/null || true
unit="${GAME_UNIT:-game.service}"

acao="${1:-status}"
shift || true

case "$acao" in
  start|stop|restart|status) exec systemctl "$acao" "$unit" "$@" ;;
  logs)
    if [ "$#" -eq 0 ]; then
      exec journalctl -u "$unit" -f
    fi
    exec journalctl -u "$unit" "$@"
    ;;
  *) echo "uso: game-{start|stop|restart|status|logs}" >&2; exit 1 ;;
esac
