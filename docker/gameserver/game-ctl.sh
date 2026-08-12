#!/usr/bin/env bash
# Atalhos game-start / game-stop / game-restart / game-status / game-logs.
# Cada um chama este script com a acao no primeiro argumento; a unidade sai do
# service.env, entao nao e preciso lembrar o nome do servico.
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
