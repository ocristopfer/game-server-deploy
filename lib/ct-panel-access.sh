#!/usr/bin/env bash
# shellcheck shell=bash
# Unprivileged panel access inside a game container (docs/security-hardening-contract.md).
#
# The panel logs in as `gamepanel`, never as root. `gamepanel` may do exactly two things: act as
# `steam` (files, backups, mods, console) and run a handful of fixed root helpers that take no
# free-form argument. `steam` gets no sudo at all, so a compromised game cannot escalate.
#
# ONE piece for every path that builds a container, so the rule is written in one place:
#   lib/ct-phases.sh       pushes this file into the CT and runs it (host via `pct exec`, broker via SSH)
#   docker/game            the dev fake game in helper mode
#   docker/gameserver      the real Docker game image
#   (future) migration     lib/ct-migrate-user.sh, phase 8 of the plan
#
# Usage (as root, inside the container):
#   ct-panel-access.sh install <unit> <panel public key line>
#                     also the mod environment overlay (phase 6): the steam-owned files, the
#                     EnvironmentFile drop-in, the win-run hook, and the conversion of what a ROOT
#                     mod installer left before the CT was migrated (see gp_install_overlay)
#   ct-panel-access.sh verify     gamepanel can reach steam and the helpers through sudo
#   ct-panel-access.sh lock       verify, then refuse root over SSH (only after verify passes)
#
# Every step is idempotent: running `install` twice leaves the same files, and `lock` twice
# leaves the same sshd drop-in. A failed `verify` means NOTHING is locked: locking root while the
# helper path is broken would leave the panel with no way into the server.

GP_USER=gamepanel
GP_HOME=/var/lib/gamepanel-agent
GP_HELPERS_VERSION=1
GP_CONF_DIR=/etc/gamepanel
GP_CT_ENV=/etc/gamepanel/ct.env
GP_SUDOERS=/etc/sudoers.d/gamepanel
GP_SERVICE_HELPER=/usr/local/sbin/gp-service
GP_CLAMAV_HELPER=/usr/local/sbin/gp-clamav-ensure
# Must match the panel default (GAMEPANEL_BACKUP_DIR): the panel writes backups there as steam.
GP_BACKUP_DIR=/var/backups/gamepanel
GP_SSHD_DROPIN=/etc/ssh/sshd_config.d/10-gamepanel.conf
# Options on the panel key: the panel never forwards anything, and a key that cannot open a
# tunnel cannot be turned into a pivot into the internal network if it leaks. No `from=`: the
# address the CT sees may be NATed, and the CT firewall already limits who reaches port 22.
GP_KEY_OPTIONS="no-agent-forwarding,no-port-forwarding,no-X11-forwarding"
# The mod environment overlay (phase 6): two files STEAM owns inside a folder ROOT owns. The panel
# writes them as steam (the Mods screen), and they reach the game through two readers set up here
# once: systemd (EnvironmentFile= in a drop-in of the game unit) and win-run (sourced after
# /etc/game-runtime.env). The folder is root's on purpose: systemd reads the EnvironmentFile AS
# ROOT, and a file steam could replace by a symlink would hand steam the KEY=value lines of any
# root-only file through /proc/self/environ of the game. Here steam changes the content, never
# which file it is.
GP_ENV_DIR=/etc/gamepanel/game-env
GP_SERVICE_ENV=/etc/gamepanel/game-env/service.env
GP_RUNTIME_OVERLAY=/etc/gamepanel/game-env/runtime.env
GP_ENV_DROPIN=gamepanel-env.conf
GP_WIN_RUN=/usr/local/bin/win-run
GP_GAME_RUNTIME_ENV=/etc/game-runtime.env
GP_SYSTEMD_DIR=/etc/systemd/system
# What a value in the overlay may hold: it ends up between single quotes in a file bash sources and
# in an EnvironmentFile. Paths, dll lists (,;=) and arguments - never a quote, $ or backtick.
GP_ENV_VALUE_RE='^[A-Za-z0-9_./:,;=@+ -]*$'

gp_msg() { printf 'ct-panel-access: %s\n' "$*"; }
gp_die() { printf 'ct-panel-access: ERROR: %s\n' "$*" >&2; exit 1; }

# A systemd unit name, and nothing that could become a second word or an option for systemctl.
gp_valid_unit() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9@._-]*\.service$ ]]
}

# An OpenSSH public key line. It is written into authorized_keys, so a newline or a stray option
# here would authorize something else.
gp_valid_pubkey() {
  # No single quote either: ct-phases.sh passes it inside a single-quoted command line.
  [[ "$1" != *$'\n'* && "$1" != *$'\r'* && "$1" != *"'"* ]] || return 1
  [[ "$1" =~ ^(ssh-[a-z0-9-]+|ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9@.-]+)\ [A-Za-z0-9+/=]{20,}(\ .*)?$ ]]
}

# --- rendered files ------------------------------------------------------------------------------

# EXACTLY the contract's text. Exact arguments, no wildcard: `gp-service stop ssh` does not match
# `gp-service stop`, and sudo refuses it before the helper even runs.
gp_render_sudoers() {
  cat <<'EOF'
Defaults:gamepanel !requiretty, !use_pty, env_reset, !log_output
Cmnd_Alias GP_ROOT = /usr/local/sbin/gp-service start, /usr/local/sbin/gp-service stop, \
  /usr/local/sbin/gp-service restart, /usr/local/sbin/gp-service --version, \
  /usr/local/bin/update-game "", /usr/local/bin/check-game-update "", \
  /usr/sbin/nft -j list set inet ct_firewall players, /usr/local/sbin/gp-clamav-ensure ""
gamepanel ALL=(root)  NOPASSWD: GP_ROOT
gamepanel ALL=(steam) NOPASSWD: ALL
EOF
}

gp_render_ct_env() {
  printf 'GAME_UNIT=%s\nGP_HELPERS_VERSION=%s\n' "$1" "$GP_HELPERS_VERSION"
}

gp_render_sshd_dropin() {
  cat <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers gamepanel
EOF
}

gp_render_service_helper() {
  cat <<'EOF'
#!/bin/bash
# gp-service start|stop|restart|--version  (gp-helpers 1, installed by lib/ct-panel-access.sh)
#
# Root helper the panel calls with `sudo -n`. It takes NO unit name: the unit comes from the
# root-owned /etc/gamepanel/ct.env, so `gp-service stop ssh` cannot exist. The file is parsed,
# never sourced (a source would run whatever line someone managed to put there), and the
# environment is ignored (sudo already resets it; this keeps it true when root runs it by hand).
set -u
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CONF=/etc/gamepanel/ct.env

usage() { echo "usage: gp-service start|stop|restart|--version" >&2; exit 2; }

[ "$#" -eq 1 ] || usage
case "$1" in
  --version) echo "gp-helpers 1"; exit 0 ;;
  start|stop|restart) verb="$1" ;;
  *) usage ;;
esac

[ -f "$CONF" ] || { echo "gp-service: $CONF is missing" >&2; exit 3; }
# Root-owned and not writable by anyone else: otherwise whoever can write it picks the unit.
owner="$(stat -c '%u' "$CONF")"
mode="$(stat -c '%a' "$CONF")"
if [ "$owner" != 0 ] || [ $(( 8#$mode & 8#022 )) -ne 0 ]; then
  echo "gp-service: $CONF must be owned by root and not writable by group/others" >&2
  exit 3
fi
unit="$(sed -n 's/^GAME_UNIT=//p' "$CONF" | head -n 1)"
# A unit name and nothing else: no second word, no leading dash systemctl would read as an option.
if ! printf '%s' "$unit" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9@._-]*\.service$'; then
  echo "gp-service: invalid GAME_UNIT in $CONF" >&2
  exit 3
fi
exec systemctl "$verb" "$unit"
EOF
}

# The SAME steps src/gamepanel/games/mods/antivirus.py (_ENSURE) runs as root today, with the
# same messages and exit codes, so the screen reads the same result in both modes. The signature
# folder is fixed: a root helper does not take an override from the caller's environment.
gp_render_clamav_helper() {
  cat <<'EOF'
#!/bin/bash
# gp-clamav-ensure  (gp-helpers 1, installed by lib/ct-panel-access.sh)
#
# Installs ClamAV if missing (apt) and refreshes the signatures. Root helper the panel calls with
# `sudo -n` in helper mode; the scan itself runs as steam. "ClamAV only arrives with the first
# mod" stays true: nothing here runs until someone sends a mod.
set -u
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
FRESH_DAYS=1
MAX_AGE_DAYS=7
refuse() { echo "ANTIVIRUS: $1" >&2; exit "$2"; }

[ "$#" -eq 0 ] || { echo "usage: gp-clamav-ensure (no arguments)" >&2; exit 2; }

if ! command -v clamscan >/dev/null 2>&1; then
  echo "antivirus: installing ClamAV (only the first time on this server)..."
  export DEBIAN_FRONTEND=noninteractive
  { apt-get update -qq && apt-get install -y -qq --no-install-recommends clamav clamav-freshclam; } >/dev/null 2>&1 \
    || refuse "could not install ClamAV (apt)" 2
fi

db=/var/lib/clamav
newest() { find "$db" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) -mtime "-$1" 2>/dev/null | head -n 1; }
if [ -z "$(newest "$FRESH_DAYS")" ]; then
  echo "antivirus: updating the signatures..."
  # The freshclam daemon holds the log lock: running freshclam while it is up fails.
  systemctl stop clamav-freshclam >/dev/null 2>&1 || true
  freshclam --quiet >/dev/null 2>&1 || echo "antivirus: the update failed; using the signatures already here"
  systemctl start clamav-freshclam >/dev/null 2>&1 || true
  [ -n "$(newest "$MAX_AGE_DAYS")" ] || refuse "no signatures from the last ${MAX_AGE_DAYS} days" 2
fi
echo "antivirus: ClamAV ready"
EOF
}

# The drop-in that hands the steam-owned overlay to the game unit. `-`: a missing file is not an
# error (the unit must start even if someone deleted it by hand).
gp_render_env_dropin() {
  printf '[Service]\nEnvironmentFile=-%s\n' "$GP_SERVICE_ENV"
}

# The block win-run runs right after taking the executable off its arguments. lib/ct-phases.sh
# writes the SAME lines into every new win-run (a test compares the two texts), and `install`
# inserts them into the win-run of a CT deployed before this existed. Read only when the file
# belongs to whoever runs win-run: root never sources a file steam can write.
gp_render_win_run_hook() {
  cat <<'EOF'
# gamepanel-overlay: the Mods screen's Wine setting and extra arguments (lib/ct-panel-access.sh).
gp_overlay=/etc/gamepanel/game-env/runtime.env
if [ -f "$gp_overlay" ] && [ "$(stat -c %u "$gp_overlay")" = "$(id -u)" ]; then
  # shellcheck disable=SC1090
  . "$gp_overlay"
  if [ -n "${GAMEPANEL_EXTRA_ARGS:-}" ]; then read -r -a gp_extra <<<"$GAMEPANEL_EXTRA_ARGS"; set -- "$@" "${gp_extra[@]}"; fi
fi
EOF
}

# --- install -------------------------------------------------------------------------------------

# Writes <dest> from stdin only when the content changed, through a temp file on the same
# filesystem and a `mv`: a half-written helper must never be what sudo executes.
gp_write_file() {
  local dest="$1" mode="$2" tmp
  tmp="$(mktemp "$(dirname "$dest")/.gp-tmp.XXXXXX")"
  cat >"$tmp"
  chown root:root "$tmp"
  chmod "$mode" "$tmp"
  if [[ -f "$dest" ]] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
    chown root:root "$dest"
    chmod "$mode" "$dest"
    return 0
  fi
  mv -f "$tmp" "$dest"
}

gp_ensure_sudo() {
  if command -v sudo >/dev/null 2>&1 && command -v visudo >/dev/null 2>&1; then
    return 0
  fi
  gp_msg "installing sudo"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq --no-install-recommends sudo
  command -v visudo >/dev/null 2>&1 || gp_die "sudo is still not available"
}

gp_ensure_user() {
  # The journal group exists wherever systemd is installed; in a Docker image without systemd it
  # does not, and useradd would refuse the whole line because of it.
  getent group systemd-journal >/dev/null || groupadd --system systemd-journal
  if ! id -u "$GP_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$GP_HOME" --create-home --shell /bin/bash \
      --groups systemd-journal "$GP_USER"
  fi
  # On an existing user, bring every attribute back to the contract (a rerun is a repair). Only
  # when something differs: usermod prints "no changes" otherwise, noise in every deploy log.
  if [[ "$(getent passwd "$GP_USER" | cut -d: -f6,7)" != "${GP_HOME}:/bin/bash" ]]; then
    usermod --shell /bin/bash --home "$GP_HOME" "$GP_USER"
  fi
  if ! id -nG "$GP_USER" | tr ' ' '\n' | grep -qx systemd-journal; then
    usermod --append --groups systemd-journal "$GP_USER"
  fi
  # NOT in group steam: group access to the game folders would bypass the "act as steam through
  # sudo" rule, and every file would still end up owned by the wrong user.
  if id -nG "$GP_USER" | tr ' ' '\n' | grep -qx steam; then
    gpasswd --delete "$GP_USER" steam >/dev/null
  fi
  # '*' and not the '!' useradd leaves: sshd treats a '!' password as a LOCKED account when PAM is
  # off, and refuses even the key. '*' means "no password", which is what we want.
  if [[ "$(getent shadow "$GP_USER" | cut -d: -f2)" != "*" ]]; then
    usermod --password '*' "$GP_USER"
  fi
  install -d -m 0700 -o "$GP_USER" -g "$GP_USER" "$GP_HOME"
}

gp_install_key() {
  local pubkey="$1" ssh_dir="$GP_HOME/.ssh" tmp
  install -d -m 0700 -o "$GP_USER" -g "$GP_USER" "$ssh_dir"
  tmp="$(mktemp "$ssh_dir/.gp-tmp.XXXXXX")"
  # The file holds exactly the panel key: a rotated key replaces the old one instead of piling up.
  printf '%s %s\n' "$GP_KEY_OPTIONS" "$pubkey" >"$tmp"
  chown "$GP_USER:$GP_USER" "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$ssh_dir/authorized_keys"
}

gp_install_sudoers() {
  local tmp
  install -d -m 0750 /etc/sudoers.d
  # Outside /etc/sudoers.d while it is checked: a broken file in there breaks sudo for EVERYONE,
  # root included, and that is the one tool left to fix it from inside the CT.
  tmp="$(mktemp /etc/.gp-sudoers.XXXXXX)"
  gp_render_sudoers >"$tmp"
  chown root:root "$tmp"
  chmod 0440 "$tmp"
  if ! visudo -cf "$tmp" >/dev/null; then
    rm -f "$tmp"
    gp_die "the sudoers file failed visudo -cf (nothing was installed)"
  fi
  if [[ -f "$GP_SUDOERS" ]] && cmp -s "$tmp" "$GP_SUDOERS"; then
    rm -f "$tmp"
    return 0
  fi
  mv -f "$tmp" "$GP_SUDOERS"
}

gp_install() {
  local unit="$1" pubkey="$2"
  gp_valid_unit "$unit" || gp_die "invalid unit: '${unit}'"
  gp_valid_pubkey "$pubkey" || gp_die "invalid panel public key"
  id -u steam >/dev/null 2>&1 || gp_die "the steam user must exist first (the sudo rule points at it)"

  gp_ensure_sudo
  gp_ensure_user
  install -d -m 0755 -o root -g root "$GP_CONF_DIR" /usr/local/sbin
  gp_render_ct_env "$unit" | gp_write_file "$GP_CT_ENV" 0644
  gp_render_service_helper | gp_write_file "$GP_SERVICE_HELPER" 0755
  gp_render_clamav_helper | gp_write_file "$GP_CLAMAV_HELPER" 0755
  gp_install_sudoers
  gp_install_key "$pubkey"
  # Backups are written AS STEAM in helper mode, and steam cannot create anything under
  # /var/backups (root's). Without this the first backup of a CT that never had one failed with
  # "mkdir: cannot create directory '/var/backups/gamepanel': Permission denied". Existing
  # archives were root's: they move to steam so retention can delete them.
  install -d -m 0750 -o steam -g steam "$GP_BACKUP_DIR"
  chown -R steam:steam "$GP_BACKUP_DIR"
  gp_install_overlay "$unit"
  gp_msg "panel access ready: user ${GP_USER}, service ${unit}"
}

# --- mod environment overlay (phase 6) -----------------------------------------------------------

gp_valid_env_value() { [[ "$1" =~ $GP_ENV_VALUE_RE ]]; }

# The value of KEY in an env file (first line), without the quotes; status 1 when absent. The same
# reading the Python installers do (`_read_overrides`).
gp_read_kv() {
  local line
  line="$(grep -m1 "^$2=" "$1" 2>/dev/null || true)"
  [[ -n "$line" ]] || return 1
  line="${line#*=}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  while [[ "$line" == [\'\"]* ]]; do line="${line:1}"; done
  while [[ "$line" == *[\'\"] ]]; do line="${line:0:${#line}-1}"; done
  printf '%s' "$line"
}

# Sets KEY='value' in an env file: the line is replaced where it is (or appended). `cat >` and not
# `mv`: the overlay files are steam's, and a new inode would come out root's.
gp_set_kv() {
  local file="$1" key="$2" value="$3" tmp
  gp_valid_env_value "$value" || gp_die "invalid value for ${key} (no quotes, \$ or backticks)"
  tmp="$(mktemp)"
  awk -v k="$key" -v line="${key}='${value}'" '
    index($0, k "=") == 1 { if (!done) print line; done = 1; next }
    { print }
    END { if (!done) print line }' "$file" >"$tmp"
  cat "$tmp" >"$file"
  rm -f "$tmp"
}

# A WINE_DLL_OVERRIDES value without the given groups (exact text), keeping the order of the rest.
gp_without_groups() {
  local value="$1" g drop out="" keep
  shift
  local -a parts=()
  IFS=';' read -r -a parts <<<"$value"
  for g in "${parts[@]}"; do
    g="${g#"${g%%[![:space:]]*}"}"
    g="${g%"${g##*[![:space:]]}"}"
    [[ -n "$g" ]] || continue
    keep=1
    for drop in "$@"; do [[ "$g" == "$drop" ]] && keep=0; done
    ((keep)) && out="${out:+$out;}$g"
  done
  printf '%s' "$out"
}

# The game folder, from the unit's WorkingDirectory (what the deploy writes). Only a real folder
# under /opt: this feeds a recursive chown run by root.
gp_game_dir() {
  local unit_file="$GP_SYSTEMD_DIR/$1" dir
  [[ -f "$unit_file" ]] || return 0
  dir="$(sed -n 's/^WorkingDirectory=//p' "$unit_file" | tail -n 1)"
  if [[ "$dir" =~ ^/opt/[A-Za-z0-9._/-]+$ && "$dir" != *..* && -d "$dir" && ! -L "$dir" ]]; then
    printf '%s' "${dir%/}"
  fi
}

gp_win_run_hooked() { [[ -f "$GP_WIN_RUN" ]] && grep -q 'gamepanel-overlay' "$GP_WIN_RUN"; }

gp_daemon_reload() {
  # Only where systemd is PID 1. In Docker the fake systemctl reads the drop-ins at each start.
  [[ -d /run/systemd/system ]] || return 0
  systemctl daemon-reload
}

# The folder (root's) and the two files (steam's). A file that is not a regular file (a link, a
# folder) can only have been put there by root, and is replaced; content that exists is kept.
gp_ensure_overlay_files() {
  local f
  install -d -m 0755 -o root -g root "$GP_ENV_DIR"
  for f in "$GP_SERVICE_ENV" "$GP_RUNTIME_OVERLAY"; do
    if [[ -L "$f" || ( -e "$f" && ! -f "$f" ) ]]; then rm -rf -- "$f"; fi
    if [[ ! -f "$f" ]]; then
      printf '# Written by the panel as steam (Mods screen). Deleting a line undoes its setting.\n' >"$f"
    fi
    chown steam:steam "$f"
    chmod 0644 "$f"
  done
}

# Variables of the loader drop-ins the ROOT installers wrote before the CT was migrated
# (gamepanel-ue4ss.conf, gamepanel-bepinex.conf) move to service.env, and the drop-in goes: from
# now on the panel, as steam, can turn them off. Only a file with exactly our shape is converted
# ([Service] and Environment=KEY=value); anything else was written by hand, and stays.
gp_convert_loader_dropins() {
  local unit="$1" f line kv
  for f in "$GP_SYSTEMD_DIR/${unit}.d"/gamepanel-*.conf; do
    [[ -f "$f" ]] || continue
    # gamepanel-sandbox.conf is the unit sandbox (lib/ct-sandbox-unit.sh): not a loader, never converted.
    case "${f##*/}" in "$GP_ENV_DROPIN"|gamepanel-mods.conf|gamepanel-sandbox.conf) continue ;; esac
    if grep -qvE '^(\[Service\]|Environment=[A-Z_][A-Z0-9_]*=[A-Za-z0-9_./:,;=@+-]*|)$' "$f"; then
      gp_msg "WARNING: ${f} has more than Environment= lines: left as it was (convert it by hand)"
      continue
    fi
    while IFS= read -r line; do
      [[ "$line" == Environment=* ]] || continue
      kv="${line#Environment=}"
      gp_set_kv "$GP_SERVICE_ENV" "${kv%%=*}" "${kv#*=}"
    done <"$f"
    rm -f -- "$f"
    GP_NEEDS_RELOAD=1
    gp_msg "drop-in ${f##*/} converted to ${GP_SERVICE_ENV}"
  done
}

# The ARK mod list a root install wrote (gamepanel-mods.conf: the unit's ExecStart repeated with
# -mods=). In helper mode the list is GAMEPANEL_EXTRA_ARGS in runtime.env, which win-run appends to
# the game's arguments. Converted only when nothing else changes: the drop-in was built from the
# unit's CURRENT command, and that command goes through win-run.
gp_convert_ark_dropin() {
  local unit="$1" f="$GP_SYSTEMD_DIR/${unit}.d/gamepanel-mods.conf" base current mods
  [[ -f "$f" ]] || return 0
  if ! gp_win_run_hooked; then
    gp_msg "WARNING: ${f} was not converted (win-run does not read the mod environment)"
    return 0
  fi
  base="$(sed -n 's/^# gamepanel-base: //p' "$f" | head -n 1)"
  current="$({ grep -E '^ExecStart=.' "$GP_SYSTEMD_DIR/$unit" 2>/dev/null || true; } | tail -n 1 | cut -d= -f2-)"
  # Word by word, as workshop_remote.ark_base does: the -mods= words are what the drop-in adds.
  current="$(printf '%s' "$current" | tr ' ' '\n' | { grep -v '^-mods=' || true; } | paste -sd ' ' -)"
  mods="$({ grep -oE -- '-mods=[0-9,]+' "$f" || true; } | tail -n 1)"
  if [[ -z "$mods" || -z "$base" || "$base" != "$current" || "$base" != /usr/local/bin/win-run\ * ]]; then
    gp_msg "WARNING: ${f} was not converted (the service command changed or does not go through win-run)"
    return 0
  fi
  gp_set_kv "$GP_RUNTIME_OVERLAY" GAMEPANEL_EXTRA_ARGS "$mods"
  rm -f -- "$f"
  GP_NEEDS_RELOAD=1
  gp_msg "ARK mod list converted to ${GP_RUNTIME_OVERLAY}"
}

# What the Wine loaders (BepInEx, Shroudtopia, UE4SS) changed in /etc/game-runtime.env moves to
# runtime.env, and the base line goes back to what it was before them. The original comes from
# BepInEx's own record (overrides_before) when there is one; Shroudtopia and UE4SS only ever ADD
# their group (winmm=n,b / dwmapi=n,b), so removing it is the original. Done once: an overlay that
# already has the line was converted (or written by the panel) and is never overwritten.
gp_convert_wine_overrides() {
  local game_dir="$1" cur original mark
  [[ -f "$GP_GAME_RUNTIME_ENV" ]] || return 0
  gp_win_run_hooked || return 0
  gp_read_kv "$GP_RUNTIME_OVERLAY" WINE_DLL_OVERRIDES >/dev/null && return 0
  cur="$(gp_read_kv "$GP_GAME_RUNTIME_ENV" WINE_DLL_OVERRIDES || true)"
  [[ -n "$cur" ]] && gp_valid_env_value "$cur" || return 0
  original="$cur"
  mark="${game_dir:-/opt/game}/BepInEx/.gamepanel.json"
  if [[ -f "$mark" ]]; then
    if grep -qE '"overrides_before": *"' "$mark"; then
      original="$(sed -nE 's/.*"overrides_before": *"([^"]*)".*/\1/p' "$mark")"
    else
      original="$(gp_without_groups "$original" 'winhttp=n,b')"
    fi
  fi
  original="$(gp_without_groups "$original" 'winmm=n,b' 'dwmapi=n,b')"
  [[ "$original" != "$cur" ]] && gp_valid_env_value "$original" || return 0
  gp_set_kv "$GP_RUNTIME_OVERLAY" WINE_DLL_OVERRIDES "$cur"
  gp_set_kv "$GP_GAME_RUNTIME_ENV" WINE_DLL_OVERRIDES "$original"
  gp_msg "the loader's WINE_DLL_OVERRIDES moved to ${GP_RUNTIME_OVERLAY} (base: '${original}')"
}

# win-run reads runtime.env. New CTs get it from lib/ct-phases.sh; an older win-run gets the hook
# inserted after the line that takes the executable off the arguments - the rest of the file is
# NOT rewritten (a migration must not change how a live server starts, ntsync and all). Without
# that exact line nothing is touched, and the Wine loaders refuse in helper mode saying why.
gp_patch_win_run() {
  local tmp hook
  [[ -f "$GP_WIN_RUN" ]] || return 0
  gp_win_run_hooked && return 0
  if [[ "$(grep -cxF 'exe="$1"; shift' "$GP_WIN_RUN")" != 1 ]]; then
    gp_msg "WARNING: ${GP_WIN_RUN} lacks the expected line: Wine loaders stay root mode only"
    return 0
  fi
  hook="$(mktemp)"
  gp_render_win_run_hook >"$hook"
  tmp="$(mktemp "$(dirname "$GP_WIN_RUN")/.gp-tmp.XXXXXX")"
  awk -v hookfile="$hook" '
    { print }
    $0 == "exe=\"$1\"; shift" { while ((getline l < hookfile) > 0) print l }' "$GP_WIN_RUN" >"$tmp"
  rm -f "$hook"
  chown root:root "$tmp"
  chmod 0755 "$tmp"
  bash -n "$tmp" || { rm -f "$tmp"; gp_die "win-run with the hook failed bash -n (nothing changed)"; }
  mv -f "$tmp" "$GP_WIN_RUN"
  gp_msg "win-run now reads ${GP_RUNTIME_OVERLAY}"
}

# What the root installers created inside the game folder (BepInEx, ue4ss/, winmm.dll...) was
# root's: steam could not update or remove it from the Mods screen. The deploy already runs this
# same chown on every deploy (render_systemd_unit); -P (the default with -R) changes a link, never
# what it points to. Only runs when something there is not steam's.
gp_chown_game_dir() {
  local dir="$1"
  [[ -n "$dir" ]] || return 0
  [[ -n "$(find "$dir" -xdev ! -user steam -print -quit 2>/dev/null)" ]] || return 0
  chown -R -P steam:steam -- "$dir"
  gp_msg "game files handed back to steam in ${dir}"
}

gp_install_overlay() {
  local unit="$1" dropin_dir="$GP_SYSTEMD_DIR/${1}.d" tmp game_dir
  GP_NEEDS_RELOAD=0
  gp_ensure_overlay_files
  install -d -m 0755 "$dropin_dir"
  tmp="$(mktemp)"
  gp_render_env_dropin >"$tmp"
  if ! cmp -s "$tmp" "$dropin_dir/$GP_ENV_DROPIN"; then GP_NEEDS_RELOAD=1; fi
  gp_write_file "$dropin_dir/$GP_ENV_DROPIN" 0644 <"$tmp"
  rm -f "$tmp"
  game_dir="$(gp_game_dir "$unit")"
  gp_convert_loader_dropins "$unit"
  # win-run first: the two conversions below move values to runtime.env, which only a hooked
  # win-run reads - converting without the hook would turn the loader off at the next restart.
  gp_patch_win_run
  gp_convert_ark_dropin "$unit"
  gp_convert_wine_overrides "$game_dir"
  gp_chown_game_dir "$game_dir"
  if [[ "$GP_NEEDS_RELOAD" == 1 ]]; then gp_daemon_reload; fi
}

# --- verify and lock -----------------------------------------------------------------------------

# What the panel itself checks before switching a server to helper mode. runuser and not su: it
# needs no PAM session and no password, and works in a container without a login shell setup.
gp_verify() {
  id -u "$GP_USER" >/dev/null 2>&1 || { gp_msg "user ${GP_USER} is missing"; return 1; }
  [[ -s "$GP_HOME/.ssh/authorized_keys" ]] || { gp_msg "${GP_USER} has no panel key"; return 1; }
  if ! runuser -u "$GP_USER" -- sudo -n -u steam true </dev/null >/dev/null 2>&1; then
    gp_msg "${GP_USER} cannot act as steam (sudo -n -u steam true)"
    return 1
  fi
  local version
  version="$(runuser -u "$GP_USER" -- sudo -n "$GP_SERVICE_HELPER" --version </dev/null 2>/dev/null || true)"
  if [[ "$version" != "gp-helpers ${GP_HELPERS_VERSION}" ]]; then
    gp_msg "${GP_USER} cannot run ${GP_SERVICE_HELPER} --version through sudo"
    return 1
  fi
  return 0
}

# Removes the panel key(s) - the ones gamepanel holds - from root's authorized_keys, keeping any
# other key (an admin's, or the broker's until its own cleanup removes it right after).
gp_remove_panel_keys_from_root() {
  local root_keys=/root/.ssh/authorized_keys blob tmp
  [[ -f "$root_keys" ]] || return 0
  tmp="$(mktemp /root/.ssh/.gp-tmp.XXXXXX)"
  cp "$root_keys" "$tmp"
  while read -r blob; do
    [[ -n "$blob" ]] || continue
    grep -vF -- "$blob" "$tmp" >"$tmp.next" || true
    mv -f "$tmp.next" "$tmp"
  done < <(grep -oE '(ssh-[a-z0-9-]+|ecdsa-sha2-[a-z0-9-]+|sk-[a-z0-9@.-]+) [A-Za-z0-9+/=]{20,}' \
             "$GP_HOME/.ssh/authorized_keys" | awk '{print $2}')
  # cat > and not mv: keeps the owner, mode and any ACL of the original file.
  cat "$tmp" >"$root_keys"
  rm -f "$tmp"
}

gp_reload_sshd() {
  # Only where systemd is PID 1 (a real CT). In Docker there is no systemd, and the entrypoint
  # starts sshd AFTER this, already reading the drop-in.
  [[ -d /run/systemd/system ]] || return 0
  # try-reload-or-restart: with a socket-activated ssh (no ssh.service running) each connection
  # starts a fresh sshd that already reads the drop-in, and there is nothing to reload. A reload
  # does not drop the session running this (the broker's last root session): only the listener
  # re-reads its configuration.
  systemctl try-reload-or-restart ssh.service 2>/dev/null \
    || systemctl try-reload-or-restart sshd.service
}

gp_lock() {
  if ! gp_verify; then
    gp_die "access as ${GP_USER} does not work: root was NOT locked (the panel would have no way in)"
  fi
  local tmp
  install -d -m 0755 /etc/ssh/sshd_config.d
  tmp="$(mktemp /etc/ssh/sshd_config.d/.gp-tmp.XXXXXX)"
  gp_render_sshd_dropin >"$tmp"
  chmod 0644 "$tmp"
  # sshd -t needs its privilege separation directory, which only exists while sshd runs (or when
  # systemd creates it for the service). Creating it is harmless.
  install -d -m 0755 /run/sshd
  local previous=""
  [[ -f "$GP_SSHD_DROPIN" ]] && previous="$(cat "$GP_SSHD_DROPIN")"
  mv -f "$tmp" "$GP_SSHD_DROPIN"
  if ! sshd -t; then
    # Put back what was there: a config sshd refuses would leave the CT with no SSH at all at
    # the next restart, and that is worse than root still being allowed.
    if [[ -n "$previous" ]]; then printf '%s\n' "$previous" >"$GP_SSHD_DROPIN"; else rm -f "$GP_SSHD_DROPIN"; fi
    gp_die "sshd refused the configuration (sshd -t): root was NOT locked"
  fi
  gp_remove_panel_keys_from_root
  gp_reload_sshd
  gp_msg "root locked: SSH only as ${GP_USER}"
}

gp_main() {
  [[ "$(id -u)" == 0 ]] || gp_die "run as root"
  case "${1:-}" in
    install)
      [[ $# -eq 3 ]] || gp_die "usage: ct-panel-access.sh install <unit> <panel public key>"
      gp_install "$2" "$3" ;;
    verify)
      if gp_verify; then gp_msg "access as ${GP_USER} OK"; else exit 1; fi ;;
    lock) gp_lock ;;
    *) gp_die "usage: ct-panel-access.sh install <unit> <key> | verify | lock" ;;
  esac
}

# Executed, not sourced: sourcing only brings the functions (and the renderers, for the sandbox).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -Eeuo pipefail
  gp_main "$@"
fi
