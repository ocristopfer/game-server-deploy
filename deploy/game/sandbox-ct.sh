#!/usr/bin/env bash
# Turns the systemd sandbox of ONE game container's unit on, off, or shows it (phase 9 of
# docs/security-hardening.md). The logic lives in lib/ct-sandbox-unit.sh; this only carries it.
#
# Runs on the Proxmox HOST, called by sandbox-ct.ps1. Everything goes through `pct`, never SSH:
# a migrated CT refuses root over SSH, and the panel's gamepanel user has no sudo rule for this
# on purpose (a sandbox the panel could switch off is no sandbox). `on` restarts the game and
# rolls back on its own if the game does not survive it; the way back by hand is always
#   pct exec <CTID> -- bash /usr/local/lib/gamepanel/ct-sandbox-unit.sh off <unit>
#
# Reads sandbox.env (next to it): CTID ACTION SERVICE SETTLE PORT_TIMEOUT PORTS WITHOUT NO_BASELINE
set -Eeuo pipefail
trap 'printf "\n[ERROR] line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$SCRIPT_DIR/ct-sandbox-unit.sh"
TOOL_IN_CT=/usr/local/lib/gamepanel/ct-sandbox-unit.sh

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "$SCRIPT_DIR/sandbox.env" ]] || die "sandbox.env not found next to the script"
[[ -f "$TOOL" ]] || die "ct-sandbox-unit.sh not found next to the script"
set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/sandbox.env"
set +a

CTID="${CTID:-}"; ACTION="${ACTION:-status}"; SERVICE="${SERVICE:-}"
SETTLE="${SETTLE:-}"; PORT_TIMEOUT="${PORT_TIMEOUT:-}"; PORTS="${PORTS:-}"; WITHOUT="${WITHOUT:-}"
NO_BASELINE="${NO_BASELINE:-0}"
[[ "$CTID" =~ ^[0-9]+$ ]] || die "invalid CTID: '$CTID'"
[[ "$ACTION" =~ ^(on|off|status)$ ]] || die "invalid ACTION: '$ACTION' (on, off or status)"
pct status "$CTID" 2>/dev/null | grep -q running || die "CT $CTID is not running"

in_ct() { pct exec "$CTID" -- bash -c "$1"; }

# The unit: given; or the one gp-service drives (/etc/gamepanel/ct.env, on every migrated CT);
# or the single service in the CT that runs as steam. Never a guess between two.
if [[ -z "$SERVICE" ]]; then
  SERVICE="$(in_ct "sed -n 's/^GAME_UNIT=//p' /etc/gamepanel/ct.env 2>/dev/null | head -n 1" || true)"
fi
if [[ -z "$SERVICE" ]]; then
  SERVICE="$(in_ct "grep -l '^User=steam' /etc/systemd/system/*.service 2>/dev/null | xargs -r -n1 basename" || true)"
  [[ "$(printf '%s\n' "$SERVICE" | grep -c .)" == 1 ]] \
    || die "Could not tell the game service in CT $CTID (found: '${SERVICE//$'\n'/ }'). Use -Service."
fi
[[ "$SERVICE" =~ ^[A-Za-z0-9@._-]+$ ]] || die "invalid SERVICE: '$SERVICE'"
[[ "$SERVICE" == *.service ]] || SERVICE="${SERVICE}.service"

# The CT's own config says whether the namespacing can work at all: without nesting=1 the
# AppArmor profile refuses the mounts and the unit fails with 226/NAMESPACE. `on` would roll back
# on its own, but saying why up front saves a game restart.
features="$(pct config "$CTID" | sed -n 's/^features: //p')"
unprivileged="$(pct config "$CTID" | sed -n 's/^unprivileged: //p')"
msg "CT $CTID, service $SERVICE (unprivileged=${unprivileged:-0}, features=${features:-none})"
if [[ "$ACTION" == on && "$features" != *nesting=1* ]]; then
  printf '  WARNING: CT %s has no nesting=1: the sandbox will most likely fail (226/NAMESPACE) and be rolled back.\n' "$CTID"
fi

# The tool goes in every time: the copy in the CT is always the one from this repository.
in_ct "install -d -m 0755 $(dirname "$TOOL_IN_CT")"
pct push "$CTID" "$TOOL" "$TOOL_IN_CT" --perms 0755

args=("$ACTION" "$SERVICE")
if [[ "$ACTION" == on ]]; then
  [[ -z "$SETTLE" ]] || args+=(--settle "$SETTLE")
  [[ -z "$PORT_TIMEOUT" ]] || args+=(--port-timeout "$PORT_TIMEOUT")
  [[ "$NO_BASELINE" != 1 ]] || args+=(--no-baseline-ports)
  for p in $PORTS; do args+=(--port "$p"); done
  for d in $WITHOUT; do args+=(--without "$d"); done
fi
# Arguments straight to pct exec, never through a shell string: the tool validates every one.
code=0
pct exec "$CTID" -- bash "$TOOL_IN_CT" "${args[@]}" || code=$?
case "$code" in
  0) msg "Done." ;;
  1) die "Not applied: the game runs as before (see the reason above)." ;;
  *) die "The game did NOT come back. Look at it now: pct exec $CTID -- journalctl -u $SERVICE -n 80" ;;
esac
