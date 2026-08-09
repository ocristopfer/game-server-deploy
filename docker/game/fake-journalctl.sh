#!/bin/sh
# journalctl de mentira: le o log do processo criado pelo fake-systemctl.
# Suporta o que o painel usa: -u <unit> --no-pager -n <N> [-f].
set -u

unit=""
lines=50
follow=0

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--unit) unit="${2:-}"; shift ;;
    -n|--lines) lines="${2:-50}"; shift ;;
    -f|--follow) follow=1 ;;
    --no-pager|-e|-x) ;;
    *) ;;
  esac
  shift
done

unit="${unit%.service}"
log="/var/log/fakegame/${unit}.log"

if [ ! -f "$log" ]; then
  echo "-- No entries --"
  exit 0
fi

if [ "$follow" -eq 1 ]; then
  exec tail -n "$lines" -f "$log"
fi
tail -n "$lines" "$log"
