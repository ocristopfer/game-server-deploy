#!/usr/bin/env bash
# Applies the in-CT firewall (lib/ct-firewall.sh) to the containers that ALREADY EXIST:
# panel, broker and the games. New CTs are already born with it (provision-*-lxc.sh and the
# broker's installer); this script is for the ones that came before.
#
# Runs on the Proxmox HOST, called by apply-firewall.ps1. Everything goes through `pct`, not the
# network: a wrong rule never locks this script out of the CT it just touched. Each CT
# is TESTED after applying (the connection that matters for it) and, if the test fails, that
# CT's firewall is turned off right away - what remains is a warning, not an unreachable server.
#
# Reads fw.env (next to it): PANEL_CTID BROKER_CTID ADMIN_FIREWALL_SOURCES PANEL_PORT BROKER_PORT
# BROKER_IP_PREFIX BROKER_IP_INICIO BROKER_IP_FIM EXTRA_GAME_CTS ONLY_CTS DRY_RUN
set -Eeuo pipefail
trap 'printf "\n[ERROR] line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIREWALL="$SCRIPT_DIR/ct-firewall.sh"
GAMES_DIR="$SCRIPT_DIR/games"

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "$SCRIPT_DIR/fw.env" ]] || die "fw.env not found next to the script"
[[ -f "$FIREWALL" ]] || die "ct-firewall.sh not found next to the script"
set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/fw.env"
set +a

PANEL_CTID="${PANEL_CTID:-}"
BROKER_CTID="${BROKER_CTID:-}"
PANEL_PORT="${PANEL_PORT:-8080}"
BROKER_PORT="${BROKER_PORT:-8443}"
ADMIN_FIREWALL_SOURCES="${ADMIN_FIREWALL_SOURCES:-192.168.0.0/16}"
DRY_RUN="${DRY_RUN:-0}"
ok_count=0
failed=()
skipped=()

selected() {  # ctid -> 0 if the CT is part of this run
  [[ -z "${ONLY_CTS:-}" ]] && return 0
  [[ " ${ONLY_CTS//,/ } " == *" $1 "* ]]
}

running() { pct status "$1" 2>/dev/null | grep -q running; }

ct_ip() { pct exec "$1" -- hostname -I 2>/dev/null | awk '{print $1}'; }

# From inside `from`, opens TCP to ip:port. It is the proof that the rule lets through whoever it should.
reaches() {  # from ip port
  pct exec "$1" -- timeout 5 bash -c "</dev/tcp/$2/$3" >/dev/null 2>&1
}

# "https://10.20.1.1:8443/" -> "10.20.1.1:8443"
endpoint_of() {
  local url="$1" rest host port
  rest="${url#*://}"
  rest="${rest%%/*}"
  host="${rest%%:*}"
  if [[ "$rest" == *:* ]]; then port="${rest##*:}"
  elif [[ "$url" == https://* ]]; then port=443
  else port=80
  fi
  printf '%s:%s' "$host" "$port"
}

# Applies to one CT and runs `verify` (a host command). Test failed: turn it off and warn.
apply_to() {  # ctid description conf verify...
  local ctid="$1" label="$2" conf="$3"
  shift 3
  if ! running "$ctid"; then
    skipped+=("$ctid ($label): CT stopped")
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    # Show only: files in the CT's /tmp, nothing that is live gets touched.
    pct push "$ctid" "$FIREWALL" /tmp/ct-firewall --perms 0755
    pct push "$ctid" "$conf" /tmp/ct-firewall.env --perms 0600
    msg "CT $ctid ($label) - rules that would be applied:"
    pct exec "$ctid" -- env CT_FIREWALL_CONF=/tmp/ct-firewall.env bash /tmp/ct-firewall render \
      || failed+=("$ctid ($label): configuration refused")
    pct exec "$ctid" -- rm -f /tmp/ct-firewall /tmp/ct-firewall.env
    return 0
  fi
  msg "CT $ctid ($label)"
  pct push "$ctid" "$FIREWALL" /usr/local/sbin/ct-firewall --perms 0755
  pct push "$ctid" "$conf" /etc/ct-firewall.env --perms 0644
  if ! pct exec "$ctid" -- /usr/local/sbin/ct-firewall apply; then
    failed+=("$ctid ($label): the rules did not load (the CT was left as it was)")
    return 0
  fi
  if "$@"; then
    printf '  test ok\n'
    ok_count=$((ok_count + 1))
  else
    pct exec "$ctid" -- /usr/local/sbin/ct-firewall off || true
    failed+=("$ctid ($label): the connection test failed - firewall OFF in this CT")
  fi
}

write_conf() {  # file lines...
  local file="$1"
  shift
  printf '%s\n' "$@" > "$file"
}

# ----------------------------------------------------------------------------------- start
modprobe nf_tables 2>/dev/null || warn "could not load the nf_tables module on the host"
{ mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
  || warn "could not make nf_tables load at host boot"

[[ -n "$PANEL_CTID" ]] && running "$PANEL_CTID" || die "the panel CT (${PANEL_CTID:-?}) must be running: the tests start from it"
PANEL_IP="$(ct_ip "$PANEL_CTID")"
[[ -n "$PANEL_IP" ]] || die "could not find the panel IP (CT $PANEL_CTID)"
BROKER_IP=""
if [[ -n "$BROKER_CTID" ]] && running "$BROKER_CTID"; then
  BROKER_IP="$(ct_ip "$BROKER_CTID")"
fi
MGMT="$PANEL_IP${BROKER_IP:+ $BROKER_IP}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- broker ---------------------------------------------------------------------------------
if [[ -n "$BROKER_IP" ]] && selected "$BROKER_CTID"; then
  urls="$(pct exec "$BROKER_CTID" -- sh -c '. /etc/gamebroker/broker.env; echo "$PROXMOX_URL $OPNSENSE_URL"')"
  read -r px_url op_url <<<"$urls"
  px="$(endpoint_of "$px_url")"
  op="$(endpoint_of "$op_url")"
  write_conf "$tmp/broker.env" "FW_ROLE=broker" "FW_PANEL_SOURCES=\"$PANEL_IP\"" \
    "FW_BROKER_PORT=\"$BROKER_PORT\"" "FW_API_ENDPOINTS=\"$px $op\"" \
    "FW_GAME_NET=\"${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_PREFIX}.${BROKER_IP_FIM:-199}\""
  verify_broker() {
    reaches "$PANEL_CTID" "$BROKER_IP" "$BROKER_PORT" \
      && reaches "$BROKER_CTID" "${px%:*}" "${px##*:}" \
      && reaches "$BROKER_CTID" "${op%:*}" "${op##*:}"
  }
  apply_to "$BROKER_CTID" "broker" "$tmp/broker.env" verify_broker
fi

# --- broker games -----------------------------------------------------------------------------
# The list and the ports come from the broker's database: that is where what each instance got
# lives (a game that moves ports is not on the ports of games/*.env).
game_lines=""
if [[ -n "$BROKER_IP" ]]; then
  game_lines="$(pct exec "$BROKER_CTID" -- python3 -c '
import sqlite3
c = sqlite3.connect("file:/var/lib/gamebroker/broker.db?mode=ro", uri=True)
for iid, handle, ip in c.execute("SELECT id, handle, ip FROM instances").fetchall():
    ports = c.execute("SELECT number, proto, role FROM ports WHERE instance_id = ?", (iid,)).fetchall()
    game = [str(n) for n, p, r in ports if r == "jogo" and p == "udp"]
    print(handle, ip, ",".join(game) or "-", " ".join(f"{n}/{p}" for n, p, _ in ports))
')"
fi

# Presence (FW_PRESENCE_PORTS) is the GAME's UDP port, through which the panel counts who is
# talking to it; "-" = none. See ct-firewall.sh.
apply_game() {  # ctid ip ports description presence
  local ctid="$1" ip="$2" ports="$3" label="$4" presence="${5:--}"
  [[ "$presence" != "-" ]] || presence=""
  if [[ -z "$ports" ]]; then
    skipped+=("$ctid ($label): the game ports are unknown")
    return 0
  fi
  write_conf "$tmp/game-$ctid.env" "FW_ROLE=game" "FW_MGMT_SOURCES=\"$MGMT\"" "FW_GAME_PORTS=\"$ports\""     "FW_PRESENCE_PORTS=\"$presence\""
  # shellcheck disable=SC2317
  verify_game() { reaches "$PANEL_CTID" "$ip" 22; }
  apply_to "$ctid" "$label" "$tmp/game-$ctid.env" verify_game
}

while read -r handle ip presence ports; do
  [[ -n "${handle:-}" ]] || continue
  selected "$handle" || continue
  apply_game "$handle" "$ip" "$ports" "broker game, $ip" "$presence"
done <<<"$game_lines"

# --- legacy games (made by deploy-game.ps1) ---------------------------------------------------
# Ports from games/<game>.env; the game is recognized by the <game>.service unit inside the CT.
for ctid in ${EXTRA_GAME_CTS//,/ }; do
  selected "$ctid" || continue
  if ! running "$ctid"; then
    skipped+=("$ctid (legacy): CT stopped")
    continue
  fi
  key=""
  for env_file in "$GAMES_DIR"/*.env; do
    k="$(basename "$env_file" .env)"
    if pct exec "$ctid" -- test -f "/etc/systemd/system/${k}.service"; then key="$k"; break; fi
  done
  if [[ -z "$key" ]]; then
    skipped+=("$ctid (legacy): game not recognized (no known <game>.service unit)")
    continue
  fi
  ports="$(bash -c 'set -a; source "$1"; echo "${GAME_PORTS:-}"' _ "$GAMES_DIR/$key.env")"
  # Same rule as ct-phases.sh: no presence when the query shares the game port.
  presence="$(bash -c 'set -a; source "$1"; [[ "${GAME_PORT:-}" != "${QUERY_PORT:-0}" ]] && echo "${GAME_PORT:-}"' _ "$GAMES_DIR/$key.env" || true)"
  apply_game "$ctid" "$(ct_ip "$ctid")" "$ports" "legacy, $key" "${presence:--}"
done

# --- panel (last: the other tests start from it) --------------------------------------------
if selected "$PANEL_CTID"; then
  write_conf "$tmp/panel.env" "FW_ROLE=panel" "FW_ADMIN_SOURCES=\"$ADMIN_FIREWALL_SOURCES\"" \
    "FW_PANEL_PORT=\"$PANEL_PORT\""
  # From the host: it is on the administration network. If it cannot reach, the list is wrong.
  verify_panel() { timeout 5 bash -c "</dev/tcp/$PANEL_IP/$PANEL_PORT" 2>/dev/null; }
  apply_to "$PANEL_CTID" "panel" "$tmp/panel.env" verify_panel
fi

# ----------------------------------------------------------------------------------- summary
printf '\n==================== CT FIREWALL ====================\n'
[[ "$DRY_RUN" == "1" ]] && printf 'Show-only mode: NOTHING was applied.\n'
printf 'Applied and tested: %s CT(s)\n' "$ok_count"
for line in "${skipped[@]}"; do printf 'SKIPPED %s\n' "$line"; done
for line in "${failed[@]}"; do printf 'FAILED  %s\n' "$line"; done
printf '\nTurn it off on a CT (emergency): pct exec <CT> -- ct-firewall off\n'
printf 'See the rules of a CT:           pct exec <CT> -- ct-firewall status\n'
(( ${#failed[@]} == 0 ))
