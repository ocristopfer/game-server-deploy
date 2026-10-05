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

gp_msg() { printf 'ct-panel-access: %s\n' "$*"; }
gp_die() { printf 'ct-panel-access: ERRO: %s\n' "$*" >&2; exit 1; }

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

usage() { echo "uso: gp-service start|stop|restart|--version" >&2; exit 2; }

[ "$#" -eq 1 ] || usage
case "$1" in
  --version) echo "gp-helpers 1"; exit 0 ;;
  start|stop|restart) verb="$1" ;;
  *) usage ;;
esac

[ -f "$CONF" ] || { echo "gp-service: $CONF ausente" >&2; exit 3; }
# Root-owned and not writable by anyone else: otherwise whoever can write it picks the unit.
owner="$(stat -c '%u' "$CONF")"
mode="$(stat -c '%a' "$CONF")"
if [ "$owner" != 0 ] || [ $(( 8#$mode & 8#022 )) -ne 0 ]; then
  echo "gp-service: $CONF precisa ser do root e sem escrita para grupo/outros" >&2
  exit 3
fi
unit="$(sed -n 's/^GAME_UNIT=//p' "$CONF" | head -n 1)"
# A unit name and nothing else: no second word, no leading dash systemctl would read as an option.
if ! printf '%s' "$unit" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9@._-]*\.service$'; then
  echo "gp-service: GAME_UNIT invalido em $CONF" >&2
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

[ "$#" -eq 0 ] || { echo "uso: gp-clamav-ensure (sem argumentos)" >&2; exit 2; }

if ! command -v clamscan >/dev/null 2>&1; then
  echo "antivirus: instalando o ClamAV (so na primeira vez neste servidor)..."
  export DEBIAN_FRONTEND=noninteractive
  { apt-get update -qq && apt-get install -y -qq --no-install-recommends clamav clamav-freshclam; } >/dev/null 2>&1 \
    || refuse "nao consegui instalar o ClamAV (apt)" 2
fi

db=/var/lib/clamav
newest() { find "$db" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) -mtime "-$1" 2>/dev/null | head -n 1; }
if [ -z "$(newest "$FRESH_DAYS")" ]; then
  echo "antivirus: atualizando as assinaturas..."
  # The freshclam daemon holds the log lock: running freshclam while it is up fails.
  systemctl stop clamav-freshclam >/dev/null 2>&1 || true
  freshclam --quiet >/dev/null 2>&1 || echo "antivirus: a atualizacao falhou; usando as assinaturas que ja havia"
  systemctl start clamav-freshclam >/dev/null 2>&1 || true
  [ -n "$(newest "$MAX_AGE_DAYS")" ] || refuse "sem assinaturas dos ultimos ${MAX_AGE_DAYS} dias" 2
fi
echo "antivirus: ClamAV pronto"
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
  gp_msg "instalando o sudo"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq --no-install-recommends sudo
  command -v visudo >/dev/null 2>&1 || gp_die "o sudo nao ficou disponivel"
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
    gp_die "o arquivo do sudoers nao passou no visudo -cf (nada foi instalado)"
  fi
  if [[ -f "$GP_SUDOERS" ]] && cmp -s "$tmp" "$GP_SUDOERS"; then
    rm -f "$tmp"
    return 0
  fi
  mv -f "$tmp" "$GP_SUDOERS"
}

gp_install() {
  local unit="$1" pubkey="$2"
  gp_valid_unit "$unit" || gp_die "unidade invalida: '${unit}'"
  gp_valid_pubkey "$pubkey" || gp_die "chave publica do painel invalida"
  id -u steam >/dev/null 2>&1 || gp_die "o usuario steam precisa existir antes (a regra do sudo aponta para ele)"

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
  gp_msg "acesso do painel pronto: usuario ${GP_USER}, servico ${unit}"
}

# --- verify and lock -----------------------------------------------------------------------------

# What the panel itself checks before switching a server to helper mode. runuser and not su: it
# needs no PAM session and no password, and works in a container without a login shell setup.
gp_verify() {
  id -u "$GP_USER" >/dev/null 2>&1 || { gp_msg "usuario ${GP_USER} ausente"; return 1; }
  [[ -s "$GP_HOME/.ssh/authorized_keys" ]] || { gp_msg "${GP_USER} sem chave do painel"; return 1; }
  if ! runuser -u "$GP_USER" -- sudo -n -u steam true </dev/null >/dev/null 2>&1; then
    gp_msg "${GP_USER} nao consegue agir como steam (sudo -n -u steam true)"
    return 1
  fi
  local version
  version="$(runuser -u "$GP_USER" -- sudo -n "$GP_SERVICE_HELPER" --version </dev/null 2>/dev/null || true)"
  if [[ "$version" != "gp-helpers ${GP_HELPERS_VERSION}" ]]; then
    gp_msg "${GP_USER} nao consegue rodar ${GP_SERVICE_HELPER} --version pelo sudo"
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
    gp_die "o acesso pelo ${GP_USER} nao funcionou: o root NAO foi trancado (o painel ficaria sem entrada)"
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
    gp_die "o sshd recusou a configuracao (sshd -t): o root NAO foi trancado"
  fi
  gp_remove_panel_keys_from_root
  gp_reload_sshd
  gp_msg "root trancado: SSH so como ${GP_USER}"
}

gp_main() {
  [[ "$(id -u)" == 0 ]] || gp_die "rode como root"
  case "${1:-}" in
    install)
      [[ $# -eq 3 ]] || gp_die "uso: ct-panel-access.sh install <unit> <chave publica do painel>"
      gp_install "$2" "$3" ;;
    verify)
      if gp_verify; then gp_msg "acesso do ${GP_USER} OK"; else exit 1; fi ;;
    lock) gp_lock ;;
    *) gp_die "uso: ct-panel-access.sh install <unit> <chave> | verify | lock" ;;
  esac
}

# Executed, not sourced: sourcing only brings the functions (and the renderers, for the sandbox).
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -Eeuo pipefail
  gp_main "$@"
fi
