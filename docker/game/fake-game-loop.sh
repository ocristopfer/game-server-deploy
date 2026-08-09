#!/bin/sh
# O "servidor de jogo": so despeja linhas no log para o painel ter o que mostrar.
set -u
unit="${1:-game}"

echo "$(date '+%b %d %H:%M:%S') $(hostname) ${unit}[1]: servidor iniciado (simulado)"
echo "$(date '+%b %d %H:%M:%S') $(hostname) ${unit}[1]: config carregada de /opt/game"

tick=0
while true; do
  tick=$((tick + 1))
  echo "$(date '+%b %d %H:%M:%S') $(hostname) ${unit}[1]: tick ${tick} - jogadores online: $((tick % 4))"
  sleep 5
done
