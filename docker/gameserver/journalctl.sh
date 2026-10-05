#!/bin/bash
# The container's 'journalctl': reads the log the supervisor writes to
# /var/log/game/<unit>.log and answers in the format the panel expects.
#
# Handles: -u <unit> [--no-pager] [-n N] [-f] [--show-cursor] [--after-cursor C]
#          [--since <date>] [-o <format>]
#
# The cursor is the byte offset already delivered ("b=12345"): the panel keeps the last one
# and asks only for what came in after it -- that is what keeps the screen's "follow log"
# from repeating anything. --since (the panel passes the start time) uses the offset
# recorded at start, so the player count from the log only sees events from THIS run.
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
    # The log only grows; if it shrank (container recreated) we start over from the top.
    # Without an explicit -n the trimming is left to the caller (the player count reads
    # the whole block since the start and does its own tail).
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
