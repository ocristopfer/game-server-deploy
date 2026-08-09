#!/bin/sh
# check-game-update de mentira: alterna entre "atualizado" e "ha versao nova" para dar
# para testar os dois caminhos na tela.
set -u
STAMP=/run/fakesystemd/check-count
mkdir -p "$(dirname "$STAMP")"
count=$(cat "$STAMP" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" >"$STAMP"

if [ $((count % 2)) -eq 0 ]; then
  echo "Ha uma versao nova disponivel (buildid local 1000, remoto 1001)."
else
  echo "O jogo ja esta na versao mais recente (buildid 1000)."
fi
