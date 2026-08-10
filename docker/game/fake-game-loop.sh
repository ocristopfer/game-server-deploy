#!/bin/sh
# O "servidor de jogo": so despeja linhas no log para o painel ter o que mostrar.
#
# Com GAME_LOG_PLAYERS=1 tambem simula entradas e saidas no formato da Unreal Engine
# (que e o que sobra para contar jogadores em jogo sem consulta A2S). O arquivo
# /run/fake-join e /run/fake-leave permitem forcar um evento na hora, para teste:
#   echo Cristopfer > /run/fake-join
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
