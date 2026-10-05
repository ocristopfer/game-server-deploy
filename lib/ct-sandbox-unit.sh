#!/usr/bin/env bash
# shellcheck shell=bash
# Opt-in systemd sandbox for the GAME unit (phase 9 of docs/security-hardening.md).
#
# A drop-in, <unit>.d/gamepanel-sandbox.conf, that takes from the game process what no game here
# needs: new privileges (setuid), its own view of /tmp, write access to /usr and /etc, the kernel
# tunables, modules and cgroup tree, the clock and the execution domain. What it leaves alone is
# as deliberate as what it takes:
#
#   - NO MemoryDenyWriteExecute: Wine, Proton, Mono (BepInEx, Unity) and UE4SS all generate code
#     at runtime; with it they die at the first JIT page.
#   - NO ProtectHome: the Wine/Proton prefixes, ~/.steam/sdk64 and ETS2's home live in /home/steam.
#   - ProtectSystem=full, not strict: the game writes in /opt/game (saves, logs, ue4ss/), the
#     Proton prefix in /home/steam and its own /tmp (win-run's XDG_RUNTIME_DIR, xvfb-run's X
#     socket, wineserver) - all of which `full` keeps writable. /etc/gamepanel/game-env and
#     /etc/game-runtime.env are only READ by the unit; the panel writes them over SSH, outside it.
#
# It is OPT-IN, per CT, because nothing proves it for a game except running that game with it:
# one game that needs one of these things fails only at start, or worse, minutes later. That is
# why `on` never leaves a broken server behind: it restarts the game with the drop-in, watches it
# (still active, no automatic restart, same main process, the same ports bound), and if anything
# fails it removes the drop-in and restarts the game the way it was.
#
# Namespacing in an UNPRIVILEGED LXC: PrivateTmp/ProtectSystem/ProtectKernel* need a mount
# namespace. Proxmox's AppArmor profile only allows it with `features: nesting=1` (every CT this
# project creates has it); without it the unit dies with status=226/NAMESPACE - which the watch
# above catches and rolls back like any other failure.
#
# Usage (as root, inside the container):
#   ct-sandbox-unit.sh on <unit> [--settle S] [--port N/udp|N/tcp]... [--port-timeout S]
#                                [--no-baseline-ports] [--without Directive]...
#   ct-sandbox-unit.sh off <unit>        remove the drop-in and restart the game (if it was running)
#   ct-sandbox-unit.sh status <unit>     what is installed, and whether the RUNNING process has it
#   ct-sandbox-unit.sh render [--without Directive]...   print the drop-in (tests, docs)
#
# Exit codes of `on`: 0 applied; 1 refused or rolled back (the game runs as before);
# 2 rolled back but the game did NOT come back - look at it now.
#
# ONE place for the drop-in text and the apply/rollback logic: deploy/game/sandbox-ct.sh pushes
# this file into an existing CT through `pct exec` (root SSH is locked on migrated CTs), and
# lib/ct-phases.sh (setup_unit_sandbox) runs it on a new CT when the deploy asks for it.

SB_VERSION=1
SB_DROPIN_NAME=gamepanel-sandbox.conf
SB_SYSTEMD_DIR=/etc/systemd/system
# The order is the order in the file. ProtectSystem is the only one whose value is not "yes".
SB_DIRECTIVES=(NoNewPrivileges PrivateTmp ProtectSystem ProtectKernelTunables ProtectKernelModules
  ProtectControlGroups RestrictSUIDSGID LockPersonality ProtectClock)
# A restart that takes longer than this to reach "active" is a failure: Type=simple units are
# active as soon as the process is forked, so "activating" past this is a start-up loop.
SB_ACTIVATING_LIMIT=30
SB_POLL=2
SB_SETTLE_DEFAULT=60
SB_PORT_TIMEOUT_DEFAULT=300
# How long the restore after a failure watches the game. Shorter than `on`: it only has to
# prove the server is back where it was, not that it survives a new constraint.
SB_RESTORE_SETTLE=30

sb_msg() { printf 'ct-sandbox-unit: %s\n' "$*"; }
sb_die() { printf 'ct-sandbox-unit: ERROR: %s\n' "$*" >&2; exit 1; }

# Same rule as ct-panel-access.sh: a unit name and nothing that could become an option.
sb_valid_unit() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9@._-]*\.service$ ]]; }
sb_valid_port() { [[ "$1" =~ ^[0-9]{1,5}/(udp|tcp)$ ]] && (( ${1%/*} >= 1 && ${1%/*} <= 65535 )); }
sb_valid_seconds() { [[ "$1" =~ ^[0-9]{1,4}$ ]] && (( $1 >= 1 )); }
sb_known_directive() {
  local d
  for d in "${SB_DIRECTIVES[@]}"; do [[ "$d" == "$1" ]] && return 0; done
  return 1
}

sb_dropin_path() { printf '%s/%s.d/%s' "$SB_SYSTEMD_DIR" "$1" "$SB_DROPIN_NAME"; }

# --- the drop-in ---------------------------------------------------------------------------------

# Prints the drop-in. The arguments are the directives to leave OUT (a game that is proven to
# need one of them); they are recorded in the header so `status` says what the CT runs without.
sb_render() {
  local d without=" $* "
  printf '# gamepanel-sandbox %s (lib/ct-sandbox-unit.sh). Remove with: ct-sandbox-unit.sh off <unit>\n' "$SB_VERSION"
  printf '# without:%s\n' "${*:+ $*}"
  printf '[Service]\n'
  for d in "${SB_DIRECTIVES[@]}"; do
    if [[ "$without" == *" $d "* ]]; then continue; fi
    if [[ "$d" == ProtectSystem ]]; then printf '%s=full\n' "$d"; else printf '%s=yes\n' "$d"; fi
  done
}

# Writes through a temp file in the same folder and a `mv`: systemd must never read half a file.
sb_write_dropin() {
  local unit="$1" dir tmp
  shift
  dir="$SB_SYSTEMD_DIR/${unit}.d"
  install -d -m 0755 -o root -g root "$dir"
  tmp="$(mktemp "$dir/.sb-tmp.XXXXXX")"
  sb_render "$@" >"$tmp"
  chown root:root "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$dir/$SB_DROPIN_NAME"
}

# The folder stays: it is shared with gamepanel-env.conf and the loaders' drop-ins.
sb_remove_dropin() { rm -f -- "$(sb_dropin_path "$1")"; }

# --- what systemd and the kernel say about the unit ----------------------------------------------

sb_prop() { systemctl show -p "$2" --value -- "$1" 2>/dev/null || true; }

# The PIDs of the unit's processes, from its cgroup (v2, or v1's name=systemd hierarchy). Child
# cgroups too: a game whose launcher moved itself into a sub-cgroup still counts.
sb_unit_pids() {
  local cg base f
  cg="$(sb_prop "$1" ControlGroup)"
  [[ -n "$cg" ]] || return 0
  for base in /sys/fs/cgroup /sys/fs/cgroup/systemd /sys/fs/cgroup/unified; do
    [[ -d "$base$cg" ]] || continue
    while IFS= read -r f; do cat -- "$f" 2>/dev/null || true; done \
      < <(find "$base$cg" -name cgroup.procs 2>/dev/null)
    return 0
  done
}

# Sockets of the given PIDs, as "port/proto" lines (see sb_proc_net_ports).
sb_ports_of_pids() {
  local pid fd link inodes=""
  for pid in "$@"; do
    for fd in /proc/"$pid"/fd/*; do
      link="$(readlink "$fd" 2>/dev/null || true)"
      [[ "$link" == socket:\[*\] ]] || continue
      link="${link#socket:[}"
      inodes+="${link%]} "
    done
  done
  [[ -n "$inodes" ]] || return 0
  sb_proc_net_ports "$inodes"
}

# "port/proto" of every socket in /proc/net whose inode is in the list (empty list = all of them):
# TCP only when listening (state 0A), UDP any bound socket. Read from /proc/net, not ss or lsof:
# the Debian template is not guaranteed to have either.
sb_proc_net_ports() {
  local want="$1" proto file
  for proto in tcp udp; do
    for file in /proc/net/"$proto" /proc/net/"${proto}6"; do
      [[ -r "$file" ]] || continue
      # The hex is converted by hand: Debian's awk is mawk, which has no strtonum().
      awk -v proto="$proto" -v want=" $want " '
        function hex(s,   i, n) {
          n = 0
          for (i = 1; i <= length(s); i++) n = n * 16 + index("0123456789ABCDEF", toupper(substr(s, i, 1))) - 1
          return n
        }
        NR > 1 {
          if (proto == "tcp" && $4 != "0A") next
          if (want != "  " && index(want, " " $10 " ") == 0) next
          split($2, local_addr, ":")
          printf "%d/%s\n", hex(local_addr[2]), proto
        }' "$file"
    done
  done | sort -u
}

# The lowest ephemeral port: a socket above it was picked by the kernel (an outbound UDP to Steam,
# Dragonwilds' EOS port) and changes at every start, so it cannot be required after the restart.
sb_ephemeral_floor() {
  local low
  low="$(awk '{print $1}' /proc/sys/net/ipv4/ip_local_port_range 2>/dev/null || true)"
  if [[ "$low" =~ ^[0-9]+$ ]]; then printf '%s' "$low"; else printf '32768'; fi
}

# The ports the game has bound RIGHT NOW, below the ephemeral range. What it listened on before
# the drop-in, it must listen on after: that is the check that needs no per-game configuration.
sb_baseline_ports() {
  local floor line
  local -a pids=()
  floor="$(sb_ephemeral_floor)"
  mapfile -t pids < <(sb_unit_pids "$1")
  ((${#pids[@]})) || return 0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if (( ${line%/*} < floor )); then printf '%s\n' "$line"; fi
  done < <(sb_ports_of_pids "${pids[@]}")
}

sb_port_bound() { sb_proc_net_ports "" | grep -qx -- "$1"; }

# Watches the unit after a restart. Healthy = active for `settle` seconds without an automatic
# restart and with the same main process, AND every port in the list bound within
# `port_timeout` seconds (counted from the restart). Prints the reason and returns 1 otherwise.
sb_watch() {
  local unit="$1" settle="$2" port_timeout="$3" start now state sub restarts0 restarts pid pid0="" p
  shift 3
  local -a pending=("$@") still=()
  start="$(date +%s)"
  restarts0="$(sb_prop "$unit" NRestarts)"
  while :; do
    now="$(date +%s)"
    state="$(sb_prop "$unit" ActiveState)"
    sub="$(sb_prop "$unit" SubState)"
    case "$state" in
      active) ;;
      activating)
        if [[ "$sub" == auto-restart ]]; then sb_msg "FAILED: the service died and systemd is restarting it"; return 1; fi
        if (( now - start > SB_ACTIVATING_LIMIT )); then sb_msg "FAILED: the service never left activating"; return 1; fi ;;
      *) sb_msg "FAILED: the service is ${state}/${sub} ($(sb_prop "$unit" Result))"; return 1 ;;
    esac
    restarts="$(sb_prop "$unit" NRestarts)"
    if [[ "$restarts" != "$restarts0" ]]; then sb_msg "FAILED: systemd restarted the service on its own"; return 1; fi
    if [[ "$state" == active ]]; then
      pid="$(sb_prop "$unit" MainPID)"
      if [[ -z "$pid0" ]]; then pid0="$pid"
      elif [[ "$pid" != "$pid0" ]]; then sb_msg "FAILED: the main process changed (${pid0} -> ${pid})"; return 1
      fi
    fi
    still=()
    for p in "${pending[@]}"; do sb_port_bound "$p" || still+=("$p"); done
    pending=("${still[@]}")
    if (( now - start >= settle )) && ((${#pending[@]} == 0)); then return 0; fi
    if (( now - start >= port_timeout )) && ((${#pending[@]})); then
      sb_msg "FAILED: port(s) the game had open did not come back within ${port_timeout}s: ${pending[*]}"
      return 1
    fi
    sleep "$SB_POLL"
  done
}

# --- on / off / status ---------------------------------------------------------------------------

sb_on() {
  local unit="$1" settle="$SB_SETTLE_DEFAULT" port_timeout="$SB_PORT_TIMEOUT_DEFAULT" baseline=1 since
  local -a ports=() without=() base=()
  shift
  while (($#)); do
    case "$1" in
      --settle) sb_valid_seconds "${2:-}" || sb_die "--settle needs seconds"; settle="$2"; shift 2 ;;
      --port-timeout) sb_valid_seconds "${2:-}" || sb_die "--port-timeout needs seconds"; port_timeout="$2"; shift 2 ;;
      --port) sb_valid_port "${2:-}" || sb_die "invalid port: '${2:-}' (use 7777/udp)"; ports+=("$2"); shift 2 ;;
      --no-baseline-ports) baseline=0; shift ;;
      --without) sb_known_directive "${2:-}" || sb_die "unknown directive: '${2:-}' (${SB_DIRECTIVES[*]})"; without+=("$2"); shift 2 ;;
      *) sb_die "unknown option: '$1'" ;;
    esac
  done
  (( ${#without[@]} < ${#SB_DIRECTIVES[@]} )) || sb_die "without any directive there is no sandbox"

  [[ "$(sb_prop "$unit" LoadState)" == loaded ]] || sb_die "unit ${unit} does not exist in this CT"
  # The baseline must be a RUNNING server: a game that already fails without the sandbox would
  # make every failure look like the sandbox's fault, and the rollback would "restore" a dead server.
  [[ "$(sb_prop "$unit" ActiveState)" == active ]] \
    || sb_die "${unit} is not active: start the game without the sandbox first (nothing changed)"

  if ((baseline)); then
    mapfile -t base < <(sb_baseline_ports "$unit")
    ports+=("${base[@]}")
  fi
  if ((${#ports[@]})); then
    mapfile -t ports < <(printf '%s\n' "${ports[@]}" | sort -u)
    sb_msg "ports that must come back: ${ports[*]}"
  else
    sb_msg "no port to check (only that the service stays up)"
  fi

  # The restore only demands what was really open BEFORE: an explicit --port the game never opened
  # (a typo, a port only a later start opens) would turn a clean rollback into "did not come back".
  local -a restore_ports=()
  local p
  for p in "${ports[@]}"; do
    if sb_port_bound "$p"; then restore_ports+=("$p"); fi
  done

  since="$(date '+%Y-%m-%d %H:%M:%S')"
  sb_write_dropin "$unit" "${without[@]}"
  systemctl daemon-reload
  sb_msg "restarting ${unit} with the sandbox (the game goes down now; watching it for ${settle}s)"
  systemctl restart -- "$unit" || sb_msg "systemctl restart returned an error"
  if sb_watch "$unit" "$settle" "$port_timeout" "${ports[@]}"; then
    sb_msg "sandbox ON for ${unit}"
    sb_status "$unit"
    return 0
  fi

  sb_msg "last journal lines with the sandbox:"
  journalctl -u "$unit" --since "$since" --no-pager -n 40 2>/dev/null | sed 's/^/  | /' || true
  sb_msg "ROLLING BACK: removing the drop-in and starting the game as it was"
  sb_remove_dropin "$unit"
  systemctl daemon-reload
  systemctl reset-failed -- "$unit" 2>/dev/null || true
  systemctl restart -- "$unit" || true
  if sb_watch "$unit" "$SB_RESTORE_SETTLE" "$port_timeout" "${restore_ports[@]}"; then
    sb_msg "rolled back: ${unit} runs again WITHOUT the sandbox"
    return 1
  fi
  sb_msg "WARNING: ${unit} did NOT come back even without the sandbox - check the game now (journalctl -u ${unit})"
  return 2
}

sb_off() {
  local unit="$1" was_active=0
  [[ "$(sb_prop "$unit" LoadState)" == loaded ]] || sb_die "unit ${unit} does not exist in this CT"
  if [[ ! -e "$(sb_dropin_path "$unit")" ]]; then
    sb_msg "${unit} has no sandbox (nothing to do)"
    return 0
  fi
  if [[ "$(sb_prop "$unit" ActiveState)" == active ]]; then was_active=1; fi
  sb_remove_dropin "$unit"
  systemctl daemon-reload
  sb_msg "drop-in removed"
  # A running process keeps the namespaces it was born with: only a restart drops them.
  if ((was_active)); then
    systemctl reset-failed -- "$unit" 2>/dev/null || true
    systemctl restart -- "$unit"
    if ! sb_watch "$unit" "$SB_RESTORE_SETTLE" "$SB_PORT_TIMEOUT_DEFAULT"; then
      sb_msg "WARNING: ${unit} did not stay active after the sandbox was removed"
      return 2
    fi
    sb_msg "${unit} restarted without the sandbox"
  fi
}

# What is installed, and what the RUNNING process actually has: a drop-in written after the start
# (or a systemd that skipped the namespace) is not protection yet.
sb_status() {
  local unit="$1" f header without state pid nnp seccomp ns_self ns_init mounts="the system's"
  f="$(sb_dropin_path "$unit")"
  if [[ -f "$f" ]]; then
    header="$(head -n 1 "$f")"
    without="$(sed -n 's/^# without://p' "$f" | head -n 1)"
    printf 'drop-in:   %s (version %s; without:%s)\n' "$f" "$(awk '{print $3}' <<<"$header")" "${without:- nothing}"
    if [[ "$header" != "# gamepanel-sandbox ${SB_VERSION} "* ]]; then
      printf 'warning:   written by another version of this script (this one is %s): run on again\n' "$SB_VERSION"
    fi
  else
    printf 'drop-in:   absent\n'
  fi
  state="$(sb_prop "$unit" ActiveState)/$(sb_prop "$unit" SubState)"
  pid="$(sb_prop "$unit" MainPID)"
  printf 'service:   %s %s (pid %s)\n' "$unit" "$state" "${pid:-?}"
  if [[ "$pid" =~ ^[1-9][0-9]*$ && -r "/proc/$pid/status" ]]; then
    nnp="$(awk '/^NoNewPrivs:/ {print $2}' "/proc/$pid/status")"
    seccomp="$(awk '/^Seccomp:/ {print $2}' "/proc/$pid/status")"
    ns_self="$(readlink "/proc/$pid/ns/mnt" 2>/dev/null || true)"
    ns_init="$(readlink /proc/1/ns/mnt 2>/dev/null || true)"
    if [[ -n "$ns_self" && "$ns_self" != "$ns_init" ]]; then mounts=private; fi
    printf 'process:   NoNewPrivs=%s Seccomp=%s mounts=%s\n' "${nnp:-?}" "${seccomp:-?}" "$mounts"
  fi
}

sb_main() {
  [[ "$(id -u)" == 0 ]] || sb_die "run as root"
  local verb="${1:-}" unit="${2:-}"
  case "$verb" in
    render)
      shift
      local -a without=()
      while (($#)); do
        if [[ "$1" != --without ]] || ! sb_known_directive "${2:-}"; then sb_die "usage: render [--without Directive]..."; fi
        without+=("$2"); shift 2
      done
      sb_render "${without[@]}"
      return 0 ;;
    on|off|status) ;;
    *) sb_die "usage: ct-sandbox-unit.sh on|off|status <unit> [options] | render [--without Directive]..." ;;
  esac
  sb_valid_unit "$unit" || sb_die "invalid unit: '${unit}'"
  shift 2
  case "$verb" in
    on) sb_on "$unit" "$@" ;;
    off) (($# == 0)) || sb_die "off takes no options"; sb_off "$unit" ;;
    status) (($# == 0)) || sb_die "status takes no options"; sb_status "$unit" ;;
  esac
}

# Executed, not sourced: sourcing only brings the functions (for the sandbox test).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -Eeuo pipefail
  sb_main "$@"
fi
