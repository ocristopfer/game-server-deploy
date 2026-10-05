#!/usr/bin/env bash
# Moves ONE existing game container from root access to the unprivileged `gamepanel` user
# (phase 8 of docs/security-hardening.md; contract in docs/security-hardening-contract.md).
#
# Runs on the Proxmox HOST, called by migrate-ct.ps1. Everything goes through `pct`, never the
# network: if something goes wrong the way back is always `pct enter <CTID>`, and root login is
# only locked AFTER the new path was proven end to end FROM THE PANEL CONTAINER:
#
#   1. install the user, helpers and sudoers in the CT (lib/ct-panel-access.sh install);
#   2. verify sudo inside the CT (ct-panel-access.sh verify);
#   3. real SSH from the panel CT as gamepanel: helper version, steam, service status;
#   4. switch the server record in the panel (cli --set-ssh-user), so the panel uses it now;
#   5. lock root (ct-panel-access.sh lock), then prove root SSH is refused.
#
# Steps 1-3 change nothing the panel uses: if any of them fails, the server stays in legacy
# (root) mode exactly as before. Reads migrate.env (next to it): CTID SERVICE PANEL_CTID LOCK
set -Eeuo pipefail
trap 'printf "\n[ERROR] line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCESS="$SCRIPT_DIR/ct-panel-access.sh"
ACCESS_IN_CT=/usr/local/lib/gamepanel/ct-panel-access.sh
PANEL_KEY=/etc/gamepanel/id_ed25519
PANEL_KNOWN_HOSTS=/var/lib/gamepanel/known_hosts
PANEL_APP=/opt/gamepanel/current

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
ok() { printf '  OK  %s\n' "$*"; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "$SCRIPT_DIR/migrate.env" ]] || die "migrate.env not found next to the script"
[[ -f "$ACCESS" ]] || die "ct-panel-access.sh not found next to the script"
set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/migrate.env"
set +a

CTID="${CTID:-}"; SERVICE="${SERVICE:-}"; PANEL_CTID="${PANEL_CTID:-}"; LOCK="${LOCK:-1}"
[[ "$CTID" =~ ^[0-9]+$ ]] || die "invalid CTID: '$CTID'"
[[ "$PANEL_CTID" =~ ^[0-9]+$ ]] || die "invalid PANEL_CTID (ADMIN_CTID in .env)"
[[ "$CTID" != "$PANEL_CTID" ]] || die "CT $CTID is the panel itself: only game CTs are migrated"
pct status "$CTID" 2>/dev/null | grep -q running || die "CT $CTID is not running"
pct status "$PANEL_CTID" 2>/dev/null | grep -q running || die "the panel CT ($PANEL_CTID) is not running"

in_ct() { pct exec "$CTID" -- bash -c "$1"; }
in_panel() { pct exec "$PANEL_CTID" -- bash -c "$1"; }

# The game unit: given, or the single service in the CT that runs as steam. Guessing between
# two would hand gp-service the wrong unit, and gp-service never takes it from an argument.
if [[ -z "$SERVICE" ]]; then
  SERVICE="$(in_ct "grep -l '^User=steam' /etc/systemd/system/*.service 2>/dev/null | xargs -r -n1 basename" || true)"
  [[ "$(printf '%s\n' "$SERVICE" | grep -c .)" == 1 ]] \
    || die "Could not work out the game service in CT $CTID (found: '${SERVICE//$'\n'/ }'). Use -Service."
fi
[[ "$SERVICE" =~ ^[A-Za-z0-9@._-]+$ ]] || die "invalid SERVICE: '$SERVICE'"
[[ "$SERVICE" == *.service ]] || SERVICE="${SERVICE}.service"

CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
[[ -n "$CT_IP" ]] || die "CT $CTID has no IP"
PANEL_PUBKEY="$(in_panel "cat ${PANEL_KEY}.pub" 2>/dev/null | head -n1 | tr -d '\r\n' || true)"
[[ -n "$PANEL_PUBKEY" ]] || die "Panel public key not found at ${PANEL_KEY}.pub in CT $PANEL_CTID"
in_ct "id steam >/dev/null 2>&1" || die "CT $CTID has no steam user: it is not a game CT of this project"

msg "CT $CTID ($CT_IP), service $SERVICE"

msg "1/5 Installing the gamepanel user, the helpers and the sudoers"
in_ct "install -d -m 0755 $(dirname "$ACCESS_IN_CT")"
pct push "$CTID" "$ACCESS" "$ACCESS_IN_CT" --perms 0755
in_ct "bash $ACCESS_IN_CT install '$SERVICE' '$PANEL_PUBKEY'"
ok "installed"

# `install` also prepared the mod environment overlay (phase 6) and converted what the ROOT mod
# installers had left: loader drop-ins -> service.env, the loader's WINE_DLL_OVERRIDES ->
# runtime.env, root files in the game folder -> steam. The running game is NOT restarted: the
# environment it gets on the next start is the same it had, now from files steam can change.
# What could not be converted (a drop-in written by hand) stays, and is listed here.
leftover="$(in_ct "ls /etc/systemd/system/${SERVICE}.d/ 2>/dev/null | grep '^gamepanel-' | grep -vxE 'gamepanel-(env|sandbox).conf' || true")"
if [[ -n "$leftover" ]]; then
  printf '  WARNING drop-in left as it was (%s): the panel without root cannot change it.\n' "${leftover//$'\n'/ }"
fi
in_ct "grep -v '^#' /etc/gamepanel/game-env/service.env /etc/gamepanel/game-env/runtime.env || true" \
  | sed 's/^/  mod environment: /'

msg "2/5 Checking sudo inside the CT"
in_ct "bash $ACCESS_IN_CT verify" || die "verify failed - the CT stays in root mode, nothing was locked"
ok "sudo checked"

msg "3/5 Testing the new path FROM THE PANEL (real SSH as gamepanel)"
ssh_as_gamepanel() {
  in_panel "ssh -i $PANEL_KEY -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile=$PANEL_KNOWN_HOSTS gamepanel@$CT_IP $(printf '%q' "$1")"
}
version="$(ssh_as_gamepanel 'sudo -n /usr/local/sbin/gp-service --version' || true)"
[[ "$version" == gp-helpers* ]] || die "gp-service over SSH answered '$version' - nothing was locked"
ok "gp-service: $version"
ssh_as_gamepanel 'cd / && sudo -n -u steam -- true' || die "sudo -u steam over SSH failed - nothing was locked"
ok "content as steam"
state="$(ssh_as_gamepanel "systemctl show -p ActiveState --value $SERVICE" || true)"
[[ -n "$state" ]] || die "service status over SSH came back empty - nothing was locked"
ok "service status without sudo: $state"

msg "4/5 Switching the server record in the panel to gamepanel"
in_panel "runuser -u gamepanel -- bash -c 'set -a; . /etc/gamepanel/panel.env; set +a; \
  cd $PANEL_APP && python3 -m gamepanel.cli --set-ssh-user gamepanel --server-host $CT_IP'" \
  || die "the panel refused the switch (is a server registered at $CT_IP? is the panel up to date?). Root was NOT locked."
ok "panel uses gamepanel@$CT_IP"

if [[ "$LOCK" != "1" ]]; then
  msg "5/5 Root NOT locked (-NoLock). The panel already logs in as gamepanel."
  exit 0
fi

msg "5/5 Locking root login"
in_ct "bash $ACCESS_IN_CT lock" || die "lock failed - root is still allowed (the panel already uses gamepanel)"
if in_panel "ssh -i $PANEL_KEY -o BatchMode=yes -o ConnectTimeout=10 -o UserKnownHostsFile=$PANEL_KNOWN_HOSTS \
     root@$CT_IP true" 2>/dev/null; then
  die "root STILL gets in over SSH on CT $CTID - check /etc/ssh/sshd_config.d/10-gamepanel.conf"
fi
ok "root refused over SSH"
version="$(ssh_as_gamepanel 'sudo -n /usr/local/sbin/gp-service --version' || true)"
[[ "$version" == gp-helpers* ]] || die "after the lock gamepanel no longer gets in! Get back in with: pct enter $CTID"
ok "gamepanel still gets in"

msg "Done: CT $CTID migrated. Emergency: pct enter $CTID"
