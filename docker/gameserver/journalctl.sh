#!/bin/bash
# 'journalctl' do container: le o log que o supervisor escreve em
# /var/log/game/<unidade>.log e responde no formato que o painel espera.
#
# Atende: -u <unidade> [--no-pager] [-n N] [-f] [--show-cursor] [--after-cursor C]
#         [--since <data>] [-o <formato>]
#
# O cursor e o deslocamento em bytes ja entregue ("b=12345"): o painel guarda o ultimo e
# pede so o que entrou depois — e o que faz o "seguir log" da tela nao repetir nada.
# --since (o painel passa o horario do start) usa o offset gravado no start, entao a
# contagem de jogadores pelo log so ve eventos DESTA execucao.
set -u

unit=""
lines=50
lines_pedido=0
follow=0
show_cursor=0
after=""
desde=""

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--unit) unit="${2:-}"; shift ;;
    -n|--lines) lines="${2:-50}"; lines_pedido=1; shift ;;
    -f|--follow) follow=1 ;;
    --show-cursor) show_cursor=1 ;;
    --after-cursor) after="${2:-}"; shift ;;
    --since) desde="${2:-}"; shift ;;
    --until|-o|--output) shift ;;
    --no-pager|-e|-x) ;;
    *) ;;
  esac
  shift
done

if [ -z "$unit" ] && [ -f /etc/game/service.env ]; then
  # shellcheck disable=SC1091
  . /etc/game/service.env
  unit="${GAME_UNIT:-}"
fi
unit="${unit%.service}"
log="/var/log/game/${unit}.log"

if [ ! -f "$log" ]; then
  echo "-- No entries --"
  [ "$show_cursor" -eq 1 ] && echo "-- cursor: b=0"
  exit 0
fi

tamanho=$(wc -c <"$log" | tr -d ' ')

if [ "$follow" -eq 1 ]; then
  exec tail -n "$lines" -f "$log"
fi

inicio=0
if [ -n "$after" ]; then
  inicio="${after#b=}"
elif [ -n "$desde" ] && [ -f "/run/game/${unit}.offset" ]; then
  inicio="$(cat "/run/game/${unit}.offset")"
fi
case "$inicio" in
  ''|*[!0-9]*) inicio=0 ;;
esac

if [ "$inicio" -gt 0 ]; then
  if [ "$tamanho" -gt "$inicio" ]; then
    # O log so cresce; se ele encolheu (container recriado) recomecamos do inicio.
    # Sem -n explicito o corte fica com quem pediu (a contagem de jogadores le o
    # bloco inteiro desde o start e faz o proprio tail).
    if [ "$lines_pedido" -eq 1 ]; then
      tail -c "+$((inicio + 1))" "$log" | tail -n "$lines"
    else
      tail -c "+$((inicio + 1))" "$log"
    fi
  else
    echo "-- No entries --"
  fi
else
  tail -n "$lines" "$log"
fi

[ "$show_cursor" -eq 1 ] && echo "-- cursor: b=${tamanho}"
exit 0
