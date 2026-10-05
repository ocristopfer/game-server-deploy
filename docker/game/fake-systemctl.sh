#!/bin/bash
# Fake systemctl: starts/stops a process that writes to a log, just so the panel has
# something to start, stop and monitor in the local environment.
set -u

STATE_DIR=/run/fakesystemd
LOG_DIR=/var/log/fakegame
mkdir -p "$STATE_DIR" "$LOG_DIR"

quiet=0
value_only=0
# Several -p are allowed, like the real one: the panel asks ActiveState, SubState,
# NRestarts and Result in a single `show`, and a fake that only kept the last -p answered
# "inactive" for every server.
properties=()
next_is_property=0
args=()
for a in "$@"; do
  if [ "$next_is_property" -eq 1 ]; then
    properties+=("$a"); next_is_property=0; continue
  fi
  case "$a" in
    --quiet|-q) quiet=1 ;;
    --value) value_only=1 ;;
    -p) next_is_property=1 ;;
    --no-pager|--now|--system|--user|-l) ;;
    *) args+=("$a") ;;
  esac
done

cmd="${args[0]:-}"
unit="${args[1]:-}"
unit="${unit%.service}"
pidfile="$STATE_DIR/${unit}.pid"
log="$LOG_DIR/${unit}.log"

# /proc and not `kill -0`: in helper mode the panel asks for status as gamepanel, and `kill -0`
# on a process owned by root fails with EPERM - every server would show as stopped.
running() {
  local pid
  [ -n "$unit" ] && [ -f "$pidfile" ] || return 1
  pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] && [ -d "/proc/$pid" ]
}

start_unit() {
  running && return 0
  # Readable by everyone: the panel reads it through the fake journalctl as gamepanel.
  touch "$log"
  chmod 0644 "$log"
  # setsid: the process has to outlive the end of the ssh session that started it.
  setsid nohup /usr/local/bin/fake-game-loop "$unit" >>"$log" 2>&1 &
  echo $! >"$pidfile"
  sleep 0.4
}

stop_unit() {
  if running; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$pidfile"
}

property_value() {
  case "$1" in
    # The panel measures the game process (ITS RAM and CPU, not the whole container's).
    MainPID) if running; then cat "$pidfile"; else echo 0; fi ;;
    # The panel uses ActiveEnterTimestamp to count only log events from this run.
    ActiveEnterTimestamp) if running; then date -r "$pidfile" '+%a %Y-%m-%d %H:%M:%S %Z'; fi ;;
    ActiveState) if running; then echo active; else echo inactive; fi ;;
    SubState) if running; then echo running; else echo dead; fi ;;
    NRestarts) echo 0 ;;
    Result) echo success ;;
    *) echo "" ;;
  esac
}

case "$cmd" in
  show)
    for property in "${properties[@]}"; do
      value="$(property_value "$property")"
      if [ "$value_only" -eq 1 ]; then echo "$value"; else echo "${property}=${value}"; fi
    done
    ;;
  start)   start_unit ;;
  stop)    stop_unit ;;
  restart) stop_unit; start_unit ;;
  is-active)
    if running; then
      [ "$quiet" -eq 1 ] || echo active
      exit 0
    fi
    [ "$quiet" -eq 1 ] || echo inactive
    exit 3
    ;;
  status)
    if running; then
      echo "* ${unit}.service - Servidor de jogo (simulado)"
      echo "     Active: active (running); PID $(cat "$pidfile")"
    else
      echo "* ${unit}.service - Servidor de jogo (simulado)"
      echo "     Active: inactive (dead)"
    fi
    echo
    tail -n 10 "$log" 2>/dev/null || true
    running || exit 3
    ;;
  enable|disable|daemon-reload|reset-failed|mask|unmask) : ;;
  list-units) ls -1 "$STATE_DIR" 2>/dev/null | sed 's/\.pid$/.service/' ;;
  *) echo "fake systemctl: comando nao suportado: $cmd" >&2; exit 1 ;;
esac
