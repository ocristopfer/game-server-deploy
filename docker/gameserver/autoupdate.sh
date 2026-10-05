#!/usr/bin/env bash
# The container's automatic update: in the LXC a systemd timer does this; here it is
# this loop. Every day at the configured time it calls check-game-update, which only
# takes the server down if there really is a new version.
set -u

# shellcheck disable=SC1091
. /etc/game/service.env

hora="${UPDATE_TIME:-06:00}"

while true; do
  agora=$(date +%s)
  alvo=$(date -d "today ${hora}" +%s 2>/dev/null || echo 0)
  if [ "$alvo" -le "$agora" ]; then
    alvo=$(date -d "tomorrow ${hora}" +%s 2>/dev/null || echo $((agora + 86400)))
  fi
  # Delay of up to 10 min, like the timer's RandomizedDelaySec: several servers on the
  # same host should not hit Steam in the same second.
  espera=$((alvo - agora + RANDOM % 600))
  echo "$(date '+%F %T') proxima checagem de update em ${espera}s (alvo ${hora})"
  sleep "$espera"
  echo "$(date '+%F %T') checando update..."
  /usr/local/bin/check-game-update || echo "check-game-update falhou (segue no proximo ciclo)"
done
