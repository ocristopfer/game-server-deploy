#!/bin/sh
# journalctl de mentira: le o log do processo criado pelo fake-systemctl.
# Suporta o que o painel usa: -u <unit> --no-pager -n <N> [-f] [--show-cursor]
# [--after-cursor <cursor>]. O cursor aqui e so a contagem de linhas ja entregues
# ("n=123") - suficiente para exercitar o "seguir log" da tela.
set -u

unit=""
lines=50
follow=0
show_cursor=0
after=""

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--unit) unit="${2:-}"; shift ;;
    -n|--lines) lines="${2:-50}"; shift ;;
    -f|--follow) follow=1 ;;
    --show-cursor) show_cursor=1 ;;
    --after-cursor) after="${2:-}"; shift ;;
    --no-pager|-e|-x) ;;
    *) ;;
  esac
  shift
done

unit="${unit%.service}"
log="/var/log/fakegame/${unit}.log"

if [ ! -f "$log" ]; then
  echo "-- No entries --"
  [ "$show_cursor" -eq 1 ] && echo "-- cursor: n=0"
  exit 0
fi

total=$(wc -l <"$log" | tr -d ' ')

if [ "$follow" -eq 1 ]; then
  exec tail -n "$lines" -f "$log"
fi

if [ -n "$after" ]; then
  ja="${after#n=}"
  case "$ja" in
    ''|*[!0-9]*) ja=0 ;;
  esac
  if [ "$total" -gt "$ja" ]; then
    tail -n +"$((ja + 1))" "$log"
  else
    echo "-- No entries --"
  fi
else
  tail -n "$lines" "$log"
fi

[ "$show_cursor" -eq 1 ] && echo "-- cursor: n=${total}"
exit 0
