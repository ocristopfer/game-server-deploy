#!/bin/bash
# Faz o papel do systemd para UM servico: roda o jogo como 'steam' e o levanta de novo
# se ele cair (o mesmo Restart=on-failure/RestartSec do unit do LXC).
#
# Chamado pelo 'systemctl' do container; toda a saida (stdout+stderr) ja vem redirecionada
# para /var/log/game/<unidade>.log, que e o que o 'journalctl' daqui le.
set -u

unit="${1:?uso: game-supervisor <unidade>}"
STATE_DIR=/run/game
mkdir -p "$STATE_DIR"

# shellcheck disable=SC1091
. /etc/game/service.env

GAME_DIR="${GAME_DIR:-/opt/game}"
GAME_USER="${GAME_USER:-steam}"
RESTART_SEC="${RESTART_SEC:-10}"
carimbo() { date '+%b %d %H:%M:%S'; }
diga() { echo "$(carimbo) $(hostname) ${unit}: $*"; }

while true; do
  diga "iniciando: ${GAME_EXEC}"
  # O pid registrado tem de ser o do JOGO (o painel mede CPU/RAM dele). Por isso a
  # cadeia so usa 'exec': subshell -> setpriv -> env -> sh -> binario do jogo, tudo
  # no mesmo pid.
  (
    cd "$GAME_DIR" || exit 1
    exec setpriv --reuid="$GAME_USER" --regid="$GAME_USER" --init-groups \
      /usr/bin/env "HOME=/home/${GAME_USER}" "USER=${GAME_USER}" \
        "LD_LIBRARY_PATH=${GAME_DIR}:${GAME_DIR}/linux64:${LD_LIBRARY_PATH:-}" \
      /bin/sh -c "exec ${GAME_EXEC}"
  ) &
  filho=$!
  echo "$filho" >"$STATE_DIR/${unit}.main"
  wait "$filho"
  codigo=$?
  rm -f "$STATE_DIR/${unit}.main"

  if [ -f "$STATE_DIR/${unit}.stop" ]; then
    diga "parado a pedido (codigo ${codigo})"
    break
  fi
  if [ "$codigo" -eq 0 ]; then
    diga "o servidor saiu normalmente (codigo 0) - nao vou reiniciar"
    break
  fi
  diga "o servidor saiu com codigo ${codigo}; reiniciando em ${RESTART_SEC}s"
  sleep "$RESTART_SEC"
done
