#!/bin/bash
# The container's 'systemctl': there is no systemd inside a Docker container, so the one
# that starts/stops the game is this script -- with the same interface the panel uses.
#
# Commands handled: start | stop | restart | status | is-active [--quiet] |
#                   show -p MainPID|ActiveEnterTimestamp [--value] |
#                   enable | disable | daemon-reload (no effect, they just do not fail)
#
# State in /run/game/<unit>.*:
#   .pid     pid of the supervisor (game-supervisor), which restarts the game if it crashes
#   .main    pid of the game process (the panel measures ITS CPU/RAM, not the container's)
#   .started when the service came up (equivalent to ActiveEnterTimestamp)
#   .stop    marks that a stop was requested (the supervisor must not restart)
#   .offset  log byte where this start began (used by journalctl --since)
set -u

STATE_DIR=/run/game
LOG_DIR=/var/log/game
STOP_TIMEOUT="${GAME_STOP_TIMEOUT:-90}"
mkdir -p "$STATE_DIR" "$LOG_DIR"

quiet=0
value_only=0
propriedade=""
args=()
for a in "$@"; do
  case "$a" in
    --quiet|-q) quiet=1 ;;
    --value) value_only=1 ;;
    -p|--property) propriedade="PROXIMO" ;;
    --no-pager|--now|--system|--user|-l|--full) ;;
    *)
      if [ "$propriedade" = "PROXIMO" ]; then
        propriedade="$a"
      else
        args+=("$a")
      fi
      ;;
  esac
done

cmd="${args[0]:-}"
unit="${args[1]:-}"
if [ -z "$unit" ] && [ -f /etc/game/service.env ]; then
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
log="$LOG_DIR/${unit}.log"

# /proc and not `kill -0`: the panel asks for status as gamepanel, and `kill -0` on the
# supervisor (owned by root) fails with EPERM - the server would always show as stopped.
vivo() {
  local pid
  [ -f "$pidfile" ] || return 1
  pid="$(cat "$pidfile" 2>/dev/null)"
  [ -n "$pid" ] && [ -d "/proc/$pid" ]
}

start_unit() {
  vivo && return 0
  rm -f "$stopfile"
  touch "$log"
  # journalctl uses this offset so the panel only counts players from this run.
  wc -c <"$log" | tr -d ' ' >"$offsetfile"
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
    valor=""
    case "$propriedade" in
      MainPID) valor=0; vivo && valor="$(cat "$mainfile" 2>/dev/null || echo 0)" ;;
      ActiveEnterTimestamp) vivo && valor="$(cat "$startedfile" 2>/dev/null || true)" ;;
      ActiveState) valor=inactive; vivo && valor=active ;;
    esac
    if [ "$value_only" -eq 1 ]; then echo "$valor"; else echo "${propriedade}=${valor}"; fi
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
  enable|disable|daemon-reload|reset-failed|mask|unmask) : ;;
  list-units) ls -1 "$STATE_DIR"/*.pid 2>/dev/null | sed 's|.*/||; s|\.pid$|.service|' ;;
  *) echo "systemctl (container): comando nao suportado: $cmd" >&2; exit 1 ;;
esac
