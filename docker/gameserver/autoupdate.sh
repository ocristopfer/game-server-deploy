#!/usr/bin/env bash
# Update automatico do container: no LXC quem faz isso e um timer do systemd; aqui e
# este laco. Todo dia no horario configurado ele chama o check-game-update, que so
# derruba o servidor se houver versao nova de verdade.
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
  # Atraso de ate 10 min, como o RandomizedDelaySec do timer: varios servidores no
  # mesmo host nao devem bater na Steam no mesmo segundo.
  espera=$((alvo - agora + RANDOM % 600))
  echo "$(date '+%F %T') proxima checagem de update em ${espera}s (alvo ${hora})"
  sleep "$espera"
  echo "$(date '+%F %T') checando update..."
  /usr/local/bin/check-game-update || echo "check-game-update falhou (segue no proximo ciclo)"
done
