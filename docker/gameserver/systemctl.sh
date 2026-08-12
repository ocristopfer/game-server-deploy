#!/bin/bash
# 'systemctl' do container: nao existe systemd dentro de um container Docker, entao
# quem liga/desliga o jogo e este script — com a mesma interface que o painel usa.
#
# Comandos atendidos: start | stop | restart | status | is-active [--quiet] |
#                     show -p MainPID|ActiveEnterTimestamp [--value] |
#                     enable | disable | daemon-reload (sem efeito, so nao falham)
#
# Estado em /run/game/<unidade>.*:
#   .pid     pid do supervisor (game-supervisor), que reinicia o jogo se ele cair
#   .main    pid do processo do jogo (o painel mede CPU/RAM DELE, nao do container)
#   .started quando o servico entrou no ar (equivale ao ActiveEnterTimestamp)
#   .stop    marca que a parada foi pedida (o supervisor nao deve reiniciar)
#   .offset  byte do log onde este start comecou (usado pelo journalctl --since)
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

vivo() {
  [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null
}

start_unit() {
  vivo && return 0
  rm -f "$stopfile"
  touch "$log"
  # O journalctl usa este offset para o painel so contar jogadores desta execucao.
  wc -c <"$log" | tr -d ' ' >"$offsetfile"
  # setsid: o supervisor precisa sobreviver ao fim da sessao ssh que o iniciou, e
  # ganhar um grupo de processos proprio (a parada mata o grupo inteiro).
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
    # Mata o grupo: o jogo precisa receber o TERM para salvar o mundo antes de sair.
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
  # Sem systemd nao ha o que habilitar: o entrypoint sobe o jogo em todo start do
  # container, que e o equivalente ao 'enable' daqui.
  enable|disable|daemon-reload|reset-failed|mask|unmask) : ;;
  list-units) ls -1 "$STATE_DIR"/*.pid 2>/dev/null | sed 's|.*/||; s|\.pid$|.service|' ;;
  *) echo "systemctl (container): comando nao suportado: $cmd" >&2; exit 1 ;;
esac
