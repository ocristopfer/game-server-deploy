#!/bin/sh
# The "game server": it only dumps lines into the log so the panel has something to show.
#
# With GAME_LOG_PLAYERS=1 it also simulates joins and leaves in the Unreal Engine format
# (which is what is left for counting players in a game without an A2S query). The files
# /run/fake-join and /run/fake-leave let you force an event right away, for testing:
#   echo Alex > /run/fake-join
set -u
unit="${1:-game}"

agora() { date '+%b %d %H:%M:%S'; }
iso() { date '+%Y-%m-%dT%H:%M:%S%z'; }

evento_forcado() {
  arquivo="$1" formato="$2"
  [ -s "$arquivo" ] || return 0
  nome=$(cat "$arquivo")
  : >"$arquivo"
  # shellcheck disable=SC2059
  printf "$formato\n" "$(iso)" "$(hostname)" "$unit" "$nome"
}

echo "$(agora) $(hostname) ${unit}[1]: servidor iniciado (simulado)"
echo "$(agora) $(hostname) ${unit}[1]: config carregada de /opt/game"

tick=0
while true; do
  tick=$((tick + 1))
  echo "$(agora) $(hostname) ${unit}[1]: tick ${tick} - jogadores online: $((tick % 4))"
  if [ "${GAME_LOG_PLAYERS:-0}" = "1" ]; then
    evento_forcado /run/fake-join '%s %s %s[1]: LogNet: Join succeeded: %s'
    evento_forcado /run/fake-leave '%s %s %s[1]: LogNet: UNetConnection::Close: Player left: %s'
  fi
  sleep 5
done
