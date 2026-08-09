#!/bin/sh
# update-game de mentira: demora alguns segundos e vai imprimindo, para dar para ver o
# job em execucao acompanhando a saida no painel.
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
