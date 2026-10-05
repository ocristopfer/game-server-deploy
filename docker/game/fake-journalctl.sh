#!/bin/sh
# Fake journalctl: reads the log of the process created by fake-systemctl.
# Supports what the panel uses: -u <unit> --no-pager -n <N> [-f] [--show-cursor]
# [--after-cursor <cursor>]. The cursor here is just the count of lines already delivered
# ("n=123") - enough to exercise the screen's "follow log".
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
    # The fake log is short and vanishes on every start, so --since changes nothing here;
    # -o only picks a format, and the lines already come out ready from fake-game-loop.
    --since|--until|-o|--output) shift ;;
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
