#!/bin/bash
# Runs INSIDE the sandbox: proves lib/ct-panel-access.sh with the real sudo, visudo and sshd.
# Exits with the number of failures.
#
#   run-panel-access.sh <repo-mounted-at-/repo>
#
# What is at stake: this file decides what the panel can do as root in every game container.
# A rule too wide is root for whoever steals the panel key; a rule too narrow, or a lock that
# runs before the helper path works, locks the panel out of a live server. Neither shows up in
# pytest - only here, or on a real CT.
set -u
REPO="${1:-/repo}"
PIECE="$REPO/lib/ct-panel-access.sh"
failures=0

ok()   { printf 'OK        %s\n' "$*"; }
fail() { printf 'FAILED    %s\n' "$*"; failures=$((failures + 1)); }
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (expected '$2', got '$3')"; fi
}
allowed() { # description, command... (as gamepanel, through sudo -n)
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n "$@" </dev/null >/dev/null 2>&1; then ok "$d"; else fail "$d (sudo refused)"; fi
}
denied() { # description, command... (as gamepanel, through sudo -n)
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n "$@" </dev/null >/dev/null 2>&1; then fail "$d (sudo ALLOWED it)"; else ok "$d"; fi
}
# sudo -l <cmd> checks the rule WITHOUT running the command (nft does not exist here).
listed() {
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n -l "$@" >/dev/null 2>&1; then ok "$d"; else fail "$d (outside the rule)"; fi
}
not_listed() {
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n -l "$@" >/dev/null 2>&1; then fail "$d (inside the rule)"; else ok "$d"; fi
}
key_blob() { cut -d' ' -f2 "$1"; }
# Every file the piece writes, with mode, owner and checksum, plus the user itself.
snapshot() {
  local f
  for f in /etc/sudoers.d/gamepanel /etc/gamepanel/ct.env /usr/local/sbin/gp-service \
           /usr/local/sbin/gp-clamav-ensure /var/lib/gamepanel-agent /var/lib/gamepanel-agent/.ssh \
           /var/lib/gamepanel-agent/.ssh/authorized_keys /etc/ssh/sshd_config.d/10-gamepanel.conf; do
    [ -e "$f" ] && stat -c '%n %a %U:%G' "$f"
    [ -f "$f" ] && sha256sum "$f"
  done
  getent passwd gamepanel
  id -nG gamepanel 2>/dev/null
  ls -A /etc/sudoers.d /etc/gamepanel /usr/local/sbin /etc/ssh/sshd_config.d /etc 2>/dev/null | grep -v '^\(ld.so.cache\|mtab\)$'
}

# ----- the "CT": steam exists (ensure_steam_user runs first), keys for the panel and an admin -----
useradd -m -s /bin/bash steam
work=$(mktemp -d)
ssh-keygen -q -t ed25519 -N '' -C panel@sandbox -f "$work/panel" >/dev/null
ssh-keygen -q -t ed25519 -N '' -C admin@sandbox -f "$work/admin" >/dev/null
panel_key="$(cat "$work/panel.pub")"
# Root has the panel key (the old way) AND an admin key: the lock must remove only the first.
install -d -m 700 /root/.ssh
cat "$work/panel.pub" "$work/admin.pub" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
printf '#!/bin/sh\necho update-game-fake\n' > /usr/local/bin/update-game
printf '#!/bin/sh\necho check-fake\n' > /usr/local/bin/check-game-update
# `sudo -l <cmd>` only answers for a command that exists; the sandbox's fake nft lives in
# /usr/local/sbin, and the rule names the real path.
printf '#!/bin/sh\necho nft-fake\n' > /usr/sbin/nft
chmod 755 /usr/local/bin/update-game /usr/local/bin/check-game-update /usr/sbin/nft
: > /var/log/fake-calls.log
chmod 666 /var/log/fake-calls.log

# ----- input validation: nothing is written on a bad call -----
if bash "$PIECE" install 'ssh.service; rm -rf /' "$panel_key" >/dev/null 2>&1; then
  fail "unit with ; is refused"; else ok "unit with ; is refused"; fi
if bash "$PIECE" install palworld.service "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIx'y" >/dev/null 2>&1; then
  fail "key with a quote is refused"; else ok "key with a quote is refused"; fi
if [ -e /etc/sudoers.d/gamepanel ]; then fail "a refused call wrote the sudoers"; else ok "a refused call writes nothing"; fi
if bash "$PIECE" lock >/dev/null 2>&1; then fail "lock without gamepanel was accepted"; else ok "lock without gamepanel is refused"; fi
if [ -e /etc/ssh/sshd_config.d/10-gamepanel.conf ]; then fail "a refused lock wrote the drop-in"; else ok "a refused lock does not write the drop-in"; fi

# ----- install -----
if bash "$PIECE" install palworld.service "$panel_key" >"$work/install1.log" 2>&1; then
  ok "install runs"; else fail "install failed: $(tail -3 "$work/install1.log")"; fi
if visudo -cf /etc/sudoers.d/gamepanel >/dev/null 2>&1; then ok "visudo -cf passes"; else fail "visudo -cf refused"; fi
check "sudoers 0440 owned by root" "440 root:root" "$(stat -c '%a %U:%G' /etc/sudoers.d/gamepanel)"
expected_sudoers='Defaults:gamepanel !requiretty, !use_pty, env_reset, !log_output
Cmnd_Alias GP_ROOT = /usr/local/sbin/gp-service start, /usr/local/sbin/gp-service stop, \
  /usr/local/sbin/gp-service restart, /usr/local/sbin/gp-service --version, \
  /usr/local/bin/update-game "", /usr/local/bin/check-game-update "", \
  /usr/sbin/nft -j list set inet ct_firewall players, /usr/local/sbin/gp-clamav-ensure ""
gamepanel ALL=(root)  NOPASSWD: GP_ROOT
gamepanel ALL=(steam) NOPASSWD: ALL'
check "sudoers is the contract text" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"
check "ct.env" "$(printf 'GAME_UNIT=palworld.service\nGP_HELPERS_VERSION=1')" "$(cat /etc/gamepanel/ct.env)"
check "ct.env 0644 owned by root" "644 root:root" "$(stat -c '%a %U:%G' /etc/gamepanel/ct.env)"
check "gp-service 0755 owned by root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/sbin/gp-service)"
# Backups are written as steam: the folder must exist and be steam's, or the first backup of a
# CT that never had one dies on mkdir (it happened on a real CT right after migrating).
check "backup folder 0750 owned by steam" "750 steam:steam" "$(stat -c '%a %U:%G' /var/backups/gamepanel)"
check "steam writes in the backup folder" "0" "$(runuser -u steam -- touch /var/backups/gamepanel/x 2>/dev/null; echo $?)"
check "gp-clamav-ensure 0755 owned by root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/sbin/gp-clamav-ensure)"
if bash -n /usr/local/sbin/gp-service && bash -n /usr/local/sbin/gp-clamav-ensure; then
  ok "helpers pass bash -n"; else fail "helper with a syntax error"; fi
check "gamepanel: home and shell" "/var/lib/gamepanel-agent:/bin/bash" "$(getent passwd gamepanel | cut -d: -f6,7)"
check "home 0700 owned by gamepanel" "700 gamepanel" "$(stat -c '%a %U' /var/lib/gamepanel-agent)"
if id -nG gamepanel | tr ' ' '\n' | grep -qx systemd-journal; then ok "gamepanel in the systemd-journal group"; else fail "gamepanel outside systemd-journal"; fi
if id -nG gamepanel | tr ' ' '\n' | grep -qx steam; then fail "gamepanel must NOT be in the steam group"; else ok "gamepanel outside the steam group"; fi
check "panel key on gamepanel, with the options" \
  "no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${panel_key}" \
  "$(cat /var/lib/gamepanel-agent/.ssh/authorized_keys)"
check "authorized_keys 0600 owned by gamepanel" "600 gamepanel" "$(stat -c '%a %U' /var/lib/gamepanel-agent/.ssh/authorized_keys)"

# ----- what gamepanel may do -----
allowed "act as steam (sudo -n -u steam true)" -u steam true
check "the command runs AS steam" steam "$(runuser -u gamepanel -- sudo -n -u steam id -un 2>/dev/null)"
check "gp-service --version" "gp-helpers 1" "$(runuser -u gamepanel -- sudo -n /usr/local/sbin/gp-service --version 2>/dev/null)"
: > /var/log/fake-calls.log
allowed "gp-service restart" /usr/local/sbin/gp-service restart
allowed "gp-service stop" /usr/local/sbin/gp-service stop
allowed "gp-service start" /usr/local/sbin/gp-service start
check "the helper uses the unit from ct.env" \
  "$(printf 'systemctl restart palworld.service\nsystemctl stop palworld.service\nsystemctl start palworld.service')" \
  "$(cat /var/log/fake-calls.log)"
: > /var/log/fake-calls.log
runuser -u gamepanel -- env GAME_UNIT=ssh.service sudo -n /usr/local/sbin/gp-service restart >/dev/null 2>&1
check "GAME_UNIT from the environment does not count" "systemctl restart palworld.service" "$(cat /var/log/fake-calls.log)"
allowed "update-game" /usr/local/bin/update-game
allowed "check-game-update" /usr/local/bin/check-game-update
listed "nft -j list set inet ct_firewall players" /usr/sbin/nft -j list set inet ct_firewall players
listed "gp-clamav-ensure" /usr/local/sbin/gp-clamav-ensure

# ----- what it may NOT do -----
: > /var/log/fake-calls.log
denied "gp-service stop ssh (extra argument)" /usr/local/sbin/gp-service stop ssh
denied "gp-service status (verb not in the list)" /usr/local/sbin/gp-service status
denied "systemctl stop ssh directly" systemctl stop ssh
denied "systemctl restart palworld.service directly" systemctl restart palworld.service
check "nothing reached systemctl" "" "$(cat /var/log/fake-calls.log)"
denied "bash as root" bash -c true
denied "sudo -u root bash" -u root bash -c true
denied "sudo -s" -s true
denied "sudo -i" -i true
not_listed "nft list ruleset" /usr/sbin/nft list ruleset
not_listed "nft flush ruleset" /usr/sbin/nft flush ruleset
# A sudoers command written WITHOUT arguments accepts ANY arguments, so the contract marks the
# helpers that take none with "" - and then it is sudo itself that refuses an extra argument,
# before the program even runs.
denied "gp-clamav-ensure with an argument" /usr/local/sbin/gp-clamav-ensure /etc
denied "update-game with an argument" /usr/local/bin/update-game --force
denied "write to /etc/sudoers.d" tee /etc/sudoers.d/x
denied "become another user (nobody)" -u nobody true

# ----- the helper itself, called by root by hand -----
/usr/local/sbin/gp-service stop ssh >/dev/null 2>&1; check "gp-service stop ssh exits with 2" 2 "$?"
/usr/local/sbin/gp-service >/dev/null 2>&1; check "gp-service without an argument exits with 2" 2 "$?"
/usr/local/sbin/gp-service reload >/dev/null 2>&1; check "gp-service reload exits with 2" 2 "$?"
/usr/local/sbin/gp-clamav-ensure /etc >/dev/null 2>&1; check "gp-clamav-ensure with an argument exits with 2" 2 "$?"
cp /etc/gamepanel/ct.env "$work/ct.env"
printf 'GAME_UNIT=ssh.service -H x\n' > /etc/gamepanel/ct.env
/usr/local/sbin/gp-service restart >/dev/null 2>&1; check "a crooked unit in ct.env exits with 3" 3 "$?"
cp "$work/ct.env" /etc/gamepanel/ct.env
chmod 0666 /etc/gamepanel/ct.env
/usr/local/sbin/gp-service restart >/dev/null 2>&1; check "ct.env writable by others exits with 3" 3 "$?"
chmod 0644 /etc/gamepanel/ct.env

# ----- steam: no sudo at all -----
if runuser -u steam -- sudo -n true >/dev/null 2>&1; then fail "steam has sudo"; else ok "steam has no sudo"; fi
if runuser -u steam -- sudo -n -u gamepanel true >/dev/null 2>&1; then fail "steam becomes gamepanel"; else ok "steam does not become gamepanel"; fi
if sudo -l -U steam 2>&1 | grep -q 'not allowed'; then ok "sudo -l -U steam: nothing"; else fail "sudo -l -U steam lists something"; fi

# ----- idempotence -----
snapshot > "$work/snap1"
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1 || fail "second install failed"
snapshot > "$work/snap2"
if diff "$work/snap1" "$work/snap2" >/dev/null; then ok "running twice changes nothing"
else fail "the second install changed something: $(diff "$work/snap1" "$work/snap2" | head -5)"; fi
# A user someone broke by hand is repaired by a rerun.
usermod -s /bin/sh -a -G steam gamepanel
chmod 0755 /var/lib/gamepanel-agent
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1
snapshot > "$work/snap3"
if diff "$work/snap1" "$work/snap3" >/dev/null; then ok "running again repairs a user changed by hand"
else fail "not repaired: $(diff "$work/snap1" "$work/snap3" | head -5)"; fi
# Key rotation: the new key REPLACES the old one.
ssh-keygen -q -t ed25519 -N '' -C panel2@sandbox -f "$work/panel2" >/dev/null
bash "$PIECE" install palworld.service "$(cat "$work/panel2.pub")" >/dev/null 2>&1
check "the new key replaces the old one" 1 "$(wc -l < /var/lib/gamepanel-agent/.ssh/authorized_keys)"
if grep -qF "$(key_blob "$work/panel2.pub")" /var/lib/gamepanel-agent/.ssh/authorized_keys; then
  ok "the new key is there"; else fail "the new key is not there"; fi
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1

# ----- a broken sudoers never reaches /etc/sudoers.d -----
if (
  # shellcheck source=/dev/null
  source "$PIECE"
  set -Eeuo pipefail
  gp_render_sudoers() { echo 'gamepanel ALL=(root NOPASSWD: ALL'; }
  gp_install_sudoers
) >/dev/null 2>&1; then fail "a broken sudoers was accepted"; else ok "a broken sudoers is refused by visudo"; fi
check "the good sudoers is still there" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"
check "no temporary file left in /etc" "" "$(ls -A /etc | grep '^\.gp-' || true)"
if runuser -u gamepanel -- sudo -n -u steam true >/dev/null 2>&1; then ok "sudo still works"; else fail "sudo broke"; fi

# ----- mod environment overlay (phase 6) -----
# What a loader needs in the game's environment goes to two files STEAM owns in a folder ROOT owns.
# The folder being root's is the point: systemd reads the EnvironmentFile as root, and a file steam
# could swap for a symlink would leak root-only files into the game's environment.
ENV_DIR=/etc/gamepanel/game-env
check "overlay folder 0755 owned by root" "755 root:root" "$(stat -c '%a %U:%G' "$ENV_DIR")"
check "service.env 0644 owned by steam" "644 steam:steam" "$(stat -c '%a %U:%G' "$ENV_DIR/service.env")"
check "runtime.env 0644 owned by steam" "644 steam:steam" "$(stat -c '%a %U:%G' "$ENV_DIR/runtime.env")"
check "drop-in that hands the overlay to the service" \
  "$(printf '[Service]\nEnvironmentFile=-%s' "$ENV_DIR/service.env")" \
  "$(cat /etc/systemd/system/palworld.service.d/gamepanel-env.conf)"
if runuser -u gamepanel -- sudo -n -u steam sh -c "echo 'X_PROBE=1' >> $ENV_DIR/service.env" 2>/dev/null; then
  ok "gamepanel, as steam, writes to the overlay"; else fail "steam does not write to the overlay"; fi
sed -i '/^X_PROBE=/d' "$ENV_DIR/service.env"
if runuser -u steam -- ln -sf /etc/shadow "$ENV_DIR/service.env" 2>/dev/null; then
  fail "steam swapped service.env for a link"; else ok "steam does not swap the file for a link"; fi
if runuser -u steam -- rm -f "$ENV_DIR/runtime.env" 2>/dev/null && [ ! -e "$ENV_DIR/runtime.env" ]; then
  fail "steam deleted runtime.env"; else ok "steam neither deletes nor creates files in the folder"; fi
if runuser -u steam -- touch "$ENV_DIR/other.env" 2>/dev/null; then fail "steam created a file in the folder"; else ok "steam does not create files in the folder"; fi
check "no new rule in the sudoers" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"

# A CT migrated with mods a ROOT installer put in place: drop-ins, /etc/game-runtime.env, root
# files in the game folder, a win-run from before the hook. Rerunning `install` converts it.
win_run_new="$(python3 - "$REPO/lib/ct-phases.sh" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
print(re.search(r"<<'EOF'\n(#!/usr/bin/env bash\n# win-run .*?\n)EOF\n", text, re.S).group(1), end="")
PY
)"
printf '%s' "$win_run_new" | python3 -c '
import re, sys
text = sys.stdin.read()
print(re.sub(r"# gamepanel-overlay:.*?\nfi\n", "", text, count=1, flags=re.S), end="")' > /usr/local/bin/win-run
chmod 0755 /usr/local/bin/win-run
if grep -q gamepanel-overlay /usr/local/bin/win-run; then fail "the old win-run still has the hook"; fi
install -d -o steam -g steam /opt/game /home/steam/pfx
printf '[Unit]\nDescription=x\n[Service]\nUser=steam\nWorkingDirectory=/opt/game\nExecStart=/usr/local/bin/win-run /opt/game/x.exe -log\n' \
  > /etc/systemd/system/palworld.service
dropins=/etc/systemd/system/palworld.service.d
printf '[Service]\nEnvironment=LD_PRELOAD=/opt/game/ue4ss/libUE4SS.so\nEnvironment=UE4SS_TARGET_EXE=TheFrontServer\n' \
  > "$dropins/gamepanel-ue4ss.conf"
printf '[Service]\nExecStartPre=/bin/true\n' > "$dropins/gamepanel-by-hand.conf"
# The unit sandbox (lib/ct-sandbox-unit.sh) is not a loader drop-in: install keeps it, silently.
bash "$REPO/lib/ct-sandbox-unit.sh" render > "$dropins/gamepanel-sandbox.conf"
printf '# Written by the game panel\n# gamepanel-base: /usr/local/bin/win-run /opt/game/x.exe -log\n[Service]\nExecStart=\nExecStart=/usr/local/bin/win-run /opt/game/x.exe -log -mods=928988,929420\n' \
  > "$dropins/gamepanel-mods.conf"
printf "RUNTIME='wine'\nGAME_KEY='probe'\nWINE_PREFIX='/home/steam/pfx'\nWINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'\nUSE_XVFB='0'\n" \
  > /etc/game-runtime.env
install -d /opt/game/BepInEx/core
printf '{"full_name": "BepInEx-BepInExPack", "overrides_before": "mscoree,mshtml=", "files": ["BepInEx"]}' \
  > /opt/game/BepInEx/.gamepanel.json
echo dll > /opt/game/BepInEx/core/BepInEx.dll
: > /opt/game/x.exe
chown -R steam:steam /opt/game/x.exe
ln -sfn /etc/shadow /opt/game/planted-link
chown -h root:root /opt/game/planted-link
shadow_owner="$(stat -c '%U:%G' /etc/shadow)"

if bash "$PIECE" install palworld.service "$panel_key" >"$work/convert.log" 2>&1; then
  ok "install converts the old CT"; else fail "install failed on conversion: $(tail -3 "$work/convert.log")"; fi
check "UE4SS drop-in variables in service.env" \
  "LD_PRELOAD='/opt/game/ue4ss/libUE4SS.so'
UE4SS_TARGET_EXE='TheFrontServer'" "$(grep -v '^#' "$ENV_DIR/service.env")"
if [ -e "$dropins/gamepanel-ue4ss.conf" ]; then fail "the UE4SS drop-in stayed"; else ok "the UE4SS drop-in is gone"; fi
if [ -e "$dropins/gamepanel-by-hand.conf" ]; then ok "a hand-made drop-in stays"; else fail "deleted a hand-made drop-in"; fi
if grep -q 'gamepanel-by-hand.conf' "$work/convert.log"; then ok "the hand-made drop-in was warned about"; else fail "no warning about the hand-made drop-in"; fi
if [ -e "$dropins/gamepanel-sandbox.conf" ]; then ok "the sandbox drop-in stays"; else fail "deleted the sandbox drop-in"; fi
if grep -q 'gamepanel-sandbox.conf' "$work/convert.log"; then fail "warned about the sandbox drop-in as if it were a loader"; else ok "the sandbox drop-in raises no warning"; fi
if [ -e "$dropins/gamepanel-mods.conf" ]; then fail "the ARK drop-in stayed"; else ok "the ARK drop-in is gone"; fi
check "runtime.env with the loader's Wine setting and the ARK list" \
  "GAMEPANEL_EXTRA_ARGS='-mods=928988,929420'
WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'" "$(grep -v '^#' "$ENV_DIR/runtime.env" | sort)"
check "game-runtime.env goes back to the original and keeps the rest" \
  "RUNTIME='wine'
GAME_KEY='probe'
WINE_PREFIX='/home/steam/pfx'
WINE_DLL_OVERRIDES='mscoree,mshtml='
USE_XVFB='0'" "$(cat /etc/game-runtime.env)"
check "the migrated win-run equals a new CT's" "$win_run_new" "$(cat /usr/local/bin/win-run)"
check "win-run 0755 owned by root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/bin/win-run)"
check "loader file handed back to steam" steam "$(stat -c '%U' /opt/game/BepInEx/core/BepInEx.dll)"
check "the planted link changes owner, its target does not" "steam $shadow_owner" \
  "$(stat -c '%U' /opt/game/planted-link) $(stat -c '%U:%G' /etc/shadow)"

# win-run really reads the overlay - as steam, and only as steam.
printf '#!/bin/sh\necho "WINEDLLOVERRIDES=$WINEDLLOVERRIDES ARGS=$*"\n' > /usr/local/sbin/wine
chmod 0755 /usr/local/sbin/wine
check "win-run as steam uses the overlay and appends the list" \
  "WINEDLLOVERRIDES=mshtml=;winhttp=n,b ARGS=/opt/game/x.exe -log -mods=928988,929420" \
  "$(cd /opt/game && runuser -u steam -- env HOME=/home/steam /usr/local/bin/win-run /opt/game/x.exe -log 2>&1)"
check "win-run as root does NOT read steam's file" \
  "WINEDLLOVERRIDES=mscoree,mshtml= ARGS=/opt/game/x.exe -log" \
  "$(cd /opt/game && HOME=/root /usr/local/bin/win-run /opt/game/x.exe -log 2>&1)"

# The installers themselves, as steam, against these real files: what the panel runs in helper mode.
# The workshop installer reads the unit with `systemctl cat`: the fake answers it from the file.
cp /usr/local/sbin/systemctl "$work/systemctl.fake"
cat > /usr/local/sbin/systemctl <<'SH'
#!/bin/bash
if [ "$1" = cat ]; then echo "# /etc/systemd/system/$2"; cat "/etc/systemd/system/$2"; exit; fi
echo "systemctl $*" >> /var/log/fake-calls.log
SH
remote() { # script, args...
  local src="$REPO/src/gamepanel/games/mods/$1"; shift
  runuser -u gamepanel -- sudo -n -u steam -- python3 -c "$(cat "$src")" "$@" 2>&1 | tail -n 1
}
check "UE4SS Linux disabled as steam" '{"enabled": false}' \
  "$(remote ue4ss_linux_remote.py --overlay --unit palworld.service loader-disable /opt/game/Pal/Binaries/Linux)"
check "service.env without the UE4SS variables" "" "$(grep -v '^#' "$ENV_DIR/service.env")"
check "Shroudtopia enabled as steam" '{"enabled": true}' "$(remote shroudtopia_remote.py --overlay loader-enable /opt/game)"
check "runtime.env with winmm" "WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b;winmm=n,b'" \
  "$(grep '^WINE_DLL_OVERRIDES=' "$ENV_DIR/runtime.env")"
check "Shroudtopia disabled as steam" '{"enabled": false}' "$(remote shroudtopia_remote.py --overlay loader-disable /opt/game)"
check "base untouched by steam" "WINE_DLL_OVERRIDES='mscoree,mshtml='" "$(grep '^WINE_DLL_OVERRIDES=' /etc/game-runtime.env)"
check "ARK without mods as steam" '{"ids": [], "config": "/etc/gamepanel/game-env/runtime.env"}' \
  "$(remote workshop_remote.py --overlay --unit palworld.service ark set /opt/game)"
check "runtime.env without the list" "" "$(grep '^GAMEPANEL_EXTRA_ARGS=' "$ENV_DIR/runtime.env" || true)"
cp "$work/systemctl.fake" /usr/local/sbin/systemctl
check "steam still owns the overlay files" "steam steam" \
  "$(stat -c '%U' "$ENV_DIR/service.env") $(stat -c '%U' "$ENV_DIR/runtime.env")"

overlay_snapshot() {
  for f in "$ENV_DIR"/* /usr/local/bin/win-run /etc/game-runtime.env "$dropins"/*; do
    stat -c '%n %a %U:%G' "$f"; sha256sum "$f"
  done
}
overlay_snapshot > "$work/ov1"
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1 || fail "install again failed"
overlay_snapshot > "$work/ov2"
if diff "$work/ov1" "$work/ov2" >/dev/null; then ok "install again does not change the converted overlay"
else fail "install again changed: $(diff "$work/ov1" "$work/ov2" | head -5)"; fi

# Shroudtopia/UE4SS (Windows) conversions: only their group comes out of the base.
(
  # shellcheck source=/dev/null
  source "$PIECE"
  set -Eeuo pipefail
  GP_GAME_RUNTIME_ENV="$work/base.env" GP_RUNTIME_OVERLAY="$work/over.env"
  printf "WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'\n" > "$work/base.env"
  : > "$work/over.env"
  # A win-run without the hook: nothing may move (the loader would vanish at the next restart).
  GP_WIN_RUN="$work/win-run-without-hook"
  printf '#!/bin/bash\n' > "$GP_WIN_RUN"
  gp_convert_wine_overrides /does-not-exist
  printf '%s|%s\n' "$(cat "$work/base.env")" "$(cat "$work/over.env")"
  GP_WIN_RUN=/usr/local/bin/win-run
  gp_convert_wine_overrides /does-not-exist
  printf '%s|%s\n' "$(cat "$work/base.env")" "$(cat "$work/over.env")"
) > "$work/winmm.out" 2>&1
check "without the hook in win-run nothing is converted" "WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'|" \
  "$(head -n 1 "$work/winmm.out")"
check "Shroudtopia conversion" "WINE_DLL_OVERRIDES='mscoree,mshtml='|WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'" \
  "$(tail -n 1 "$work/winmm.out")"
rm -f /etc/systemd/system/palworld.service "$dropins/gamepanel-by-hand.conf" /etc/game-runtime.env /usr/local/bin/win-run
rm -rf /opt/game

# ----- verify and lock -----
if bash "$PIECE" verify >/dev/null 2>&1; then ok "verify passes"; else fail "verify failed"; fi
# Lock refused while the helper path is broken: nothing may be locked then.
mv /etc/sudoers.d/gamepanel "$work/sudoers.bak"
if bash "$PIECE" lock >/dev/null 2>&1; then fail "lock with a broken sudo was accepted"; else ok "lock with a broken sudo is refused"; fi
if [ -e /etc/ssh/sshd_config.d/10-gamepanel.conf ]; then fail "a refused lock wrote the drop-in"; else ok "a refused lock locks nothing"; fi
if grep -qF "$(key_blob "$work/panel.pub")" /root/.ssh/authorized_keys; then
  ok "a refused lock leaves root as it was"; else fail "a refused lock touched root"; fi
mv "$work/sudoers.bak" /etc/sudoers.d/gamepanel

if bash "$PIECE" lock >"$work/lock.log" 2>&1; then ok "lock runs"; else fail "lock failed: $(tail -3 "$work/lock.log")"; fi
check "sshd drop-in" \
  "$(printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nAllowUsers gamepanel')" \
  "$(cat /etc/ssh/sshd_config.d/10-gamepanel.conf)"
if sshd -t >/dev/null 2>&1; then ok "sshd -t passes"; else fail "sshd -t refuses the configuration"; fi
check "effective sshd: root refused" "permitrootlogin no" "$(sshd -T 2>/dev/null | grep -i '^permitrootlogin')"
if grep -qF "$(key_blob "$work/panel.pub")" /root/.ssh/authorized_keys; then
  fail "the panel key stayed on root"; else ok "the panel key left root"; fi
if grep -qF "$(key_blob "$work/admin.pub")" /root/.ssh/authorized_keys; then
  ok "the admin key stayed on root"; else fail "the lock deleted the admin key"; fi
snapshot > "$work/snap4"
bash "$PIECE" lock >/dev/null 2>&1 || fail "second lock failed"
snapshot > "$work/snap5"
if diff "$work/snap4" "$work/snap5" >/dev/null; then ok "locking twice changes nothing"; else fail "the second lock changed something"; fi

# ----- a real SSH login against the real sshd -----
ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p 2222)
/usr/sbin/sshd -p 2222 -o PidFile=/run/sshd-sandbox.pid 2>"$work/sshd.log" || fail "sshd did not start: $(cat "$work/sshd.log")"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  (echo > /dev/tcp/127.0.0.1/2222) 2>/dev/null && break
  /usr/bin/sleep 0.3   # the sandbox's `sleep` is a no-op fake
done
check "ssh gamepanel + sudo gp-service --version" "gp-helpers 1" \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n /usr/local/sbin/gp-service --version 2>/dev/null </dev/null)"
check "ssh gamepanel + sudo -u steam" steam \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n -u steam id -un 2>/dev/null </dev/null)"
# !use_pty: uploads and backups stream binary data on stdin; a pty in the middle would mangle it.
head -c 300000 /dev/urandom > "$work/blob"
check "binary data goes through ssh + sudo -u steam intact" "$(sha256sum < "$work/blob" | cut -d' ' -f1)" \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n -u steam -- sha256sum < "$work/blob" 2>/dev/null | cut -d' ' -f1)"
if ssh "${ssh_opts[@]}" -i "$work/panel" root@127.0.0.1 true </dev/null >/dev/null 2>&1; then
  fail "root gets in with the panel key"; else ok "root refused with the panel key"; fi
if ssh "${ssh_opts[@]}" -i "$work/admin" root@127.0.0.1 true </dev/null >/dev/null 2>&1; then
  fail "root gets in with the admin key (PermitRootLogin no)"; else ok "root refused even with the key that stayed"; fi
check "tunnel refused (no-port-forwarding)" refused \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" -o ExitOnForwardFailure=yes -W 127.0.0.1:2222 gamepanel@127.0.0.1 </dev/null >/dev/null 2>&1 && echo opened || echo refused)"
kill "$(cat /run/sshd-sandbox.pid)" 2>/dev/null

echo
if [ "$failures" -eq 0 ]; then echo "panel-access: all OK"; else echo "panel-access: ${failures} failure(s)"; fi
exit "$failures"
