#!/bin/bash
# systemctl de mentira: liga/desliga um processo que escreve num log, so para o painel
# ter o que iniciar, parar e monitorar no ambiente local.
set -u

STATE_DIR=/run/fakesystemd
LOG_DIR=/var/log/fakegame
mkdir -p "$STATE_DIR" "$LOG_DIR"

quiet=0
value_only=0
propriedade=""
args=()
for a in "$@"; do
  case "$a" in
    --quiet|-q) quiet=1 ;;
    --value) value_only=1 ;;
    -p) propriedade="PROXIMO" ;;
    --no-pager|--now|--system|--user|-l) ;;
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
unit="${unit%.service}"
pidfile="$STATE_DIR/${unit}.pid"
log="$LOG_DIR/${unit}.log"

running() {
  [ -n "$unit" ] && [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null
}

start_unit() {
  running && return 0
  # setsid: o processo precisa sobreviver ao fim da sessao ssh que o iniciou.
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

case "$cmd" in
  show)
    # O painel usa 'systemctl show -p MainPID --value <unit>' para medir o processo
    # do jogo (RAM e CPU dele, nao do container inteiro).
    valor=0
    if [ "$propriedade" = "MainPID" ] && running; then valor="$(cat "$pidfile")"; fi
    # O painel usa o ActiveEnterTimestamp para so contar eventos do log desta execucao.
    if [ "$propriedade" = "ActiveEnterTimestamp" ]; then
      if running; then valor="$(date -r "$pidfile" '+%a %Y-%m-%d %H:%M:%S %Z')"; else valor=""; fi
    fi
    if [ "$value_only" -eq 1 ]; then echo "$valor"; else echo "${propriedade}=${valor}"; fi
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
