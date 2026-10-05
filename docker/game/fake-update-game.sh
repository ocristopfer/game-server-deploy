#!/bin/sh
# Fake update-game: takes a few seconds and keeps printing, so you can watch the running
# job follow the output in the panel.
set -u
echo "Simulando SteamCMD: validando arquivos do jogo..."
i=0
while [ "$i" -lt 5 ]; do
  i=$((i + 1))
  echo " Update state (0x61) downloading, progress: $((i * 20)).00"
  sleep 2
done
echo "Success! App fully installed."
echo "Update concluido (simulado)."
