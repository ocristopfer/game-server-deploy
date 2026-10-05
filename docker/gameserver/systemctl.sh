#!/bin/bash
# The container's 'systemctl': there is no systemd inside a Docker container, so the one
# that starts/stops the game is this script -- with the same interface the panel uses.
#
# Commands handled: start | stop | restart | status | is-active [--quiet] |
#                   show [-p P]... [--value] (MainPID, ActiveEnterTimestamp, ActiveState,
#                   SubState, NRestarts, Result) |
#                   enable | disable | daemon-reload (no effect, they just do not fail)
#
# State in /run/game/<unit>.*:
#   .pid      pid of the supervisor (game-supervisor), which restarts the game if it crashes
#   .main     pid of the game process (the panel measures ITS CPU/RAM, not the container's)
#   .started  when the service came up (equivalent to ActiveEnterTimestamp)
#   .stop     marks that a stop was requested (the supervisor must not restart)
#   .offset   log byte where this start began (used by journalctl --since)
#   .restarts how many times the supervisor brought the game back since the last start (NRestarts)
#   .result   how the game last exited: success | exit-code (Result)
#
# The panel calls this as `gamepanel` (status, logs) and through `sudo gp-service` (start/stop/
# restart, as root). Everything a read needs is therefore world-readable; only root writes.
set -u

STATE_DIR=/run/game
LOG_DIR=/var/log/game
STOP_TIMEOUT="${GAME_STOP_TIMEOUT:-90}"
# 0755 even when created by gamepanel's first `show`: a later root start writes into it.
mkdir -p -m 0755 "$STATE_DIR" "$LOG_DIR" 2>/dev/null || true

quiet=0
value_only=0
# Several -p are allowed, like the real one: the panel asks ActiveState, SubState, NRestarts
# and Result in ONE `show` (status_service). Keeping only the last -p answered just `Result=`,
# and every Docker server showed as stopped.
properties=()
next_is_property=0
args=()
for a in "$@"; do
  if [ "$next_is_property" -eq 1 ]; then
    IFS=, read -r -a more <<<"$a"
    properties+=("${more[@]}")
    next_is_property=0
    continue
  fi
  case "$a" in
    --quiet|-q) quiet=1 ;;
    --value) value_only=1 ;;
    -p|--property) next_is_property=1 ;;
    --property=*) IFS=, read -r -a more <<<"${a#--property=}"; properties+=("${more[@]}") ;;
    --no-pager|--now|--system|--user|-l|--full) ;;
    *) args+=("$a") ;;
  esac
done

cmd="${args[0]:-}"
unit="${args[1]:-}"

# Commands that take no unit answer before the unit is looked up: the mod installers call
# `systemctl daemon-reload` AS STEAM after writing the env overlay, and steam cannot read the
# root-only service.env below - the call would print "Permission denied" and fail for nothing.
# There is nothing to reload here: the supervisor reads the drop-ins at every start.
case "$cmd" in
  daemon-reload|reset-failed) exit 0 ;;
esac

if [ -z "$unit" ] && [ -r /etc/game/service.env ]; then
  # shellcheck disable=SC1091
  . /etc/game/service.env
  unit="${GAME_UNIT:-}"
fi
unit="${unit%.service}"
[ -n "$unit" ] || { echo "systemctl: informe a unidade" >&2; exit 1; }

pidfile="$STATE_DIR/${unit}.pid"
mainfile="$STATE_DIR/${unit}.main"
startedfile="$STATE_DIR/${unit}.started"
stopfile="$STATE_DIR/${unit}.stop"
offsetfile="$STATE_DIR/${unit}.offset"
restartsfile="$STATE_DIR/${unit}.restarts"
resultfile="$STATE_DIR/${unit}.result"
log="$LOG_DIR/${unit}.log"

# /proc and not `kill -0`: the panel asks for status as gamepanel, and `kill -0` on the
# supervisor (owned by root) fails with EPERM - the server would always show as stopped.
vivo() {
  local pid
  [ -f "$pidfile" ] || return 1
  pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] && [ -d "/proc/$pid" ]
}

# The game itself (not the supervisor) is up. Between a crash and the restart the supervisor
# is alive and the game is not: systemd calls that SubState=auto-restart.
main_alive() {
  local pid
  [ -f "$mainfile" ] || return 1
  pid="$(cat "$mainfile" 2>/dev/null)"
  [ -n "$pid" ] && [ -d "/proc/$pid" ]
}

start_unit() {
  vivo && return 0
  rm -f "$stopfile"
  touch "$log"
  # Readable by gamepanel: the panel reads it through journalctl without any right. Under sudo
  # the umask is whatever the caller had, so the mode is set here instead of trusted.
  chmod 0644 "$log"
  # journalctl uses this offset so the panel only counts players from this run.
  wc -c <"$log" | tr -d ' ' >"$offsetfile"
  # A manual start is a new baseline, like systemd: the panel reads a DROP as "someone
  # restarted it by hand", never as a crash loop.
  echo 0 >"$restartsfile"
  echo success >"$resultfile"
  # setsid: the supervisor has to outlive the end of the ssh session that started it, and
  # get its own process group (the stop kills the whole group).
  setsid nohup /usr/local/bin/game-supervisor "$unit" >>"$log" 2>&1 &
  echo $! >"$pidfile"
  date '+%a %Y-%m-%d %H:%M:%S %Z' >"$startedfile"
  sleep 1
  vivo
}

stop_unit() {
  touch "$stopfile"
  if vivo; then
    local grupo esperou
    grupo="$(cat "$pidfile")"
    # Kill the group: the game has to receive the TERM to save the world before exiting.
    kill -TERM -- "-$grupo" 2>/dev/null || kill -TERM "$grupo" 2>/dev/null || true
    esperou=0
    while vivo && [ "$esperou" -lt "$STOP_TIMEOUT" ]; do
      sleep 1
      esperou=$((esperou + 1))
    done
    if vivo; then
      echo "servico nao parou em ${STOP_TIMEOUT}s, mandando KILL" >&2
      kill -KILL -- "-$grupo" 2>/dev/null || kill -KILL "$grupo" 2>/dev/null || true
      sleep 1
    fi
  fi
  rm -f "$pidfile" "$mainfile" "$startedfile"
}

property_value() {
  case "$1" in
    MainPID) if vivo && main_alive; then cat "$mainfile"; else echo 0; fi ;;
    ActiveEnterTimestamp) if vivo; then cat "$startedfile" 2>/dev/null || true; fi ;;
    ActiveState) if vivo; then echo active; else echo inactive; fi ;;
    SubState)
      if ! vivo; then echo dead
      elif main_alive; then echo running
      else echo auto-restart
      fi ;;
    # NRestarts is what gives a crash loop away (alert_service.restart_alert): ActiveState stays
    # 'active' the whole time the supervisor keeps bringing the game back.
    NRestarts) cat "$restartsfile" 2>/dev/null || echo 0 ;;
    Result) cat "$resultfile" 2>/dev/null || echo success ;;
    *) echo "" ;;
  esac
}

case "$cmd" in
  start)
    start_unit || { echo "o servico ${unit} nao subiu; ultimas linhas:" >&2
                    tail -n 20 "$log" >&2; exit 1; }
    ;;
  stop) stop_unit ;;
  restart)
    stop_unit
    start_unit || { echo "o servico ${unit} nao voltou; ultimas linhas:" >&2
                    tail -n 20 "$log" >&2; exit 1; }
    ;;
  show)
    for property in "${properties[@]}"; do
      valor="$(property_value "$property")"
      if [ "$value_only" -eq 1 ]; then echo "$valor"; else echo "${property}=${valor}"; fi
    done
    ;;
  is-active)
    if vivo; then
      [ "$quiet" -eq 1 ] || echo active
      exit 0
    fi
    [ "$quiet" -eq 1 ] || echo inactive
    exit 3
    ;;
  status)
    if vivo; then
      echo "* ${unit}.service - servidor de jogo (container)"
      echo "     Active: active (running) desde $(cat "$startedfile" 2>/dev/null)"
      echo "   Main PID: $(cat "$mainfile" 2>/dev/null || echo '?')"
    else
      echo "* ${unit}.service - servidor de jogo (container)"
      echo "     Active: inactive (dead)"
    fi
    echo
    tail -n 10 "$log" 2>/dev/null || true
    vivo || exit 3
    ;;
  # Without systemd there is nothing to enable: the entrypoint starts the game on every
  # container start, which is the equivalent of 'enable' here.
  enable|disable|mask|unmask) : ;;
  list-units) ls -1 "$STATE_DIR"/*.pid 2>/dev/null | sed 's|.*/||; s|\.pid$|.service|' ;;
  *) echo "systemctl (container): comando nao suportado: $cmd" >&2; exit 1 ;;
esac
