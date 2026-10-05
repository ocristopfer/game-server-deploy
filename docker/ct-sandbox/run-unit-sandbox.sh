#!/bin/bash
# Runs INSIDE the systemd sandbox (docker/ct-sandbox/unit-sandbox.sh). Exits with the number of
# failures.
#
#   run-unit-sandbox.sh <repo-mounted-at-/repo>
#
# The fake game is a real service with the shape render_systemd_unit writes (User=steam,
# WorkingDirectory=/opt/game, Restart=on-failure): it writes where a real game writes (/opt/game,
# the Proton prefix in /home/steam, an XDG_RUNTIME_DIR in /tmp), binds a UDP and a TCP port plus an
# ephemeral one, and records what it could see. Its MODE file makes it fail the way a real game
# would under the sandbox: needing to write in /usr, needing the host's /tmp, or dying anyway.
set -u
REPO="${1:-/repo}"
TOOL="$REPO/lib/ct-sandbox-unit.sh"
UNIT=fakegame.service
DROPIN=/etc/systemd/system/fakegame.service.d/gamepanel-sandbox.conf
failures=0
work="$(mktemp -d)"

ok()   { printf 'OK        %s\n' "$*"; }
fail() { printf 'FAILED    %s\n' "$*"; failures=$((failures + 1)); }
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (expected '$2', got '$3')"; fi
}
contains() { # description, needle, file
  if grep -qF -- "$2" "$3"; then ok "$1"; else fail "$1 (no '$2' in: $(tail -5 "$3" | tr '\n' '|'))"; fi
}
run_tool() { # log file, args... -> exit code in $rc
  bash "$TOOL" "${@:2}" >"$1" 2>&1
  rc=$?
}
evidence() { sed -n "s/^$1=//p" /opt/game/evidence 2>/dev/null; }
wait_active() { # the game up and its two fixed ports bound
  local _
  for _ in $(seq 1 30); do
    if systemctl is-active --quiet "$UNIT" && [ -s /opt/game/evidence ] \
       && grep -q '^ports=bound' /opt/game/evidence; then return 0; fi
    sleep 1
  done
  return 1
}
set_mode() { printf '%s\n' "$1" > /opt/game/mode; rm -f /opt/game/evidence; }
restart_plain() { set_mode "$1"; systemctl restart "$UNIT"; wait_active || fail "the game did not come up WITHOUT the sandbox (mode $1)"; }
main_pid() { systemctl show -p MainPID --value "$UNIT"; }
nnp_of() { awk '/^NoNewPrivs:/ {print $2}' "/proc/$1/status"; }

# ----- the fake game -----
id steam >/dev/null 2>&1 || useradd -m -s /bin/bash steam
install -d -o steam -g steam /opt/game /usr/local/share/fakegame
cat > /opt/game/fakegame.py <<'PY'
import os, pathlib, socket, time

game = pathlib.Path("/opt/game")
mode = (game / "mode").read_text().strip() if (game / "mode").exists() else "ok"
starts = int((game / "starts").read_text() or 0) if (game / "starts").exists() else 0
(game / "starts").write_text(str(starts + 1))
lines = []

# Where a real game writes: its folder, the Proton prefix and win-run's XDG_RUNTIME_DIR.
(game / "saved").mkdir(exist_ok=True)
(game / "saved" / "world.sav").write_text("save")
pathlib.Path("/home/steam/.proton-fake/pfx").mkdir(parents=True, exist_ok=True)
os.makedirs(f"/tmp/.xdg-fake-{os.getuid()}", mode=0o700, exist_ok=True)

try:
    pathlib.Path("/usr/local/share/fakegame/probe").write_text("x")
    lines.append("usr=rw")
except OSError:
    lines.append("usr=ro")
host_tmp = os.path.exists("/tmp/host-marker")
lines.append("tmp=" + ("host" if host_tmp else "private"))

if mode == "needs-usr" and lines[0] == "usr=ro":
    raise SystemExit("cannot write /usr/local/share/fakegame")
if mode == "dies-after-first" and starts >= 1:
    raise SystemExit("dies on every start but the first")

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp.bind(("", 7777))
ephemeral = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ephemeral.bind(("", 0))
# A game that finds its config through the HOST's /tmp: under PrivateTmp it starts, stays up and
# never opens the second port - the failure only the port check catches.
if mode != "needs-host-tmp" or host_tmp:
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(("", 27015))
    tcp.listen()
lines.append("ports=bound")
lines.append(f"ephemeral={ephemeral.getsockname()[1]}")
(game / "evidence").write_text("\n".join(lines) + "\n")
while True:
    time.sleep(60)
PY
chown -R steam:steam /opt/game
cat > /etc/systemd/system/$UNIT <<'UNIT'
[Unit]
Description=fake game for the unit sandbox
[Service]
Type=simple
User=steam
Group=steam
WorkingDirectory=/opt/game
ExecStart=/usr/bin/python3 /opt/game/fakegame.py
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
: > /tmp/host-marker

# ----- render -----
expected="# gamepanel-sandbox 1 (lib/ct-sandbox-unit.sh). Remove with: ct-sandbox-unit.sh off <unit>
# without:
[Service]
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
ProtectClock=yes"
check "render is the drop-in of the plan" "$expected" "$(bash "$TOOL" render)"
out="$(bash "$TOOL" render --without LockPersonality --without ProtectClock)"
if grep -qE '^(LockPersonality|ProtectClock)=' <<<"$out"; then fail "--without left the directive in"; else ok "--without leaves the directive out"; fi
check "--without is recorded in the header" "# without: LockPersonality ProtectClock" "$(sed -n 2p <<<"$out")"
if grep -q MemoryDenyWriteExecute <<<"$out$expected"; then fail "MemoryDenyWriteExecute in the drop-in"; else ok "no MemoryDenyWriteExecute (Wine/Proton/Mono/UE4SS JIT)"; fi
if grep -q ProtectHome <<<"$expected"; then fail "ProtectHome in the drop-in"; else ok "no ProtectHome (Wine prefix in /home/steam)"; fi

# ----- refusals change nothing -----
systemctl stop "$UNIT"
run_tool "$work/inactive.log" on "$UNIT" --settle 4
check "on refuses a stopped game" 1 "$rc"
if [ -e "$DROPIN" ]; then fail "the refusal wrote the drop-in"; else ok "the refusal writes nothing"; fi
run_tool "$work/bad.log" on "$UNIT" --without Bogus
check "unknown --without refused" 1 "$rc"
run_tool "$work/bad.log" on 'x;reboot.service'
check "unit with a ; refused" 1 "$rc"
run_tool "$work/bad.log" on "$UNIT" --port 70000/udp
check "port out of range refused" 1 "$rc"

# ----- a game that lives with it -----
restart_plain ok
pid_before="$(main_pid)"
check "without the sandbox the game writes /usr" "rw" "$(evidence usr)"
check "without the sandbox the game sees the host /tmp" "host" "$(evidence tmp)"
ephemeral="$(evidence ephemeral)"
run_tool "$work/on.log" on "$UNIT" --settle 6
check "on applies to a game that lives with it" 0 "$rc"
contains "the ports the game had open are required back" "ports that must come back: 27015/tcp 7777/udp" "$work/on.log"
if grep -q "${ephemeral}/udp" "$work/on.log"; then fail "the ephemeral port ${ephemeral} was required"; else ok "the ephemeral port is not required"; fi
if [ -f "$DROPIN" ]; then ok "drop-in in place"; else fail "no drop-in after on"; fi
check "drop-in is root's 0644" "644 root:root" "$(stat -c '%a %U:%G' "$DROPIN")"
pid="$(main_pid)"
if [ "$pid" != "$pid_before" ]; then ok "the game was restarted"; else fail "the game was not restarted"; fi
check "the running game has NoNewPrivs" 1 "$(nnp_of "$pid")"
check "the running game has a seccomp filter" 2 "$(awk '/^Seccomp:/ {print $2}' "/proc/$pid/status")"
check "under the sandbox /usr is read-only for the game" "ro" "$(evidence usr)"
check "under the sandbox the game has its own /tmp" "private" "$(evidence tmp)"
contains "status shows the private mounts" "mounts=private" "$work/on.log"
if [ -s /opt/game/saved/world.sav ] && [ -d /home/steam/.proton-fake/pfx ]; then
  ok "the game still writes /opt/game and its prefix in /home/steam"; else fail "the game lost /opt/game or /home/steam"; fi
run_tool "$work/again.log" on "$UNIT" --settle 4
check "on again (rerun) still 0" 0 "$rc"
run_tool "$work/status.log" status "$UNIT"
check "status exits 0" 0 "$rc"
contains "status names the drop-in version" "version 1; without: nothing" "$work/status.log"

# ----- off -----
run_tool "$work/off.log" off "$UNIT"
check "off exits 0" 0 "$rc"
if [ -e "$DROPIN" ]; then fail "off left the drop-in"; else ok "off removes the drop-in"; fi
wait_active || true
check "after off the game has no NoNewPrivs" 0 "$(nnp_of "$(main_pid)")"
check "after off the game writes /usr again" "rw" "$(evidence usr)"
run_tool "$work/off2.log" off "$UNIT"
check "off without a drop-in is a no-op" 0 "$rc"

# ----- a game that dies under it: rolled back -----
restart_plain needs-usr
run_tool "$work/usr.log" on "$UNIT" --settle 8
check "a game that dies under the sandbox: exit 1" 1 "$rc"
contains "the reason is printed" "FAILED:" "$work/usr.log"
contains "the game's own error comes from the journal" "cannot write /usr/local/share/fakegame" "$work/usr.log"
contains "it says it rolled back" "rolled back:" "$work/usr.log"
if [ -e "$DROPIN" ]; then fail "rollback left the drop-in"; else ok "rollback removes the drop-in"; fi
if systemctl is-active --quiet "$UNIT"; then ok "the game runs again after the rollback"; else fail "the game is down after the rollback"; fi
check "after the rollback the game is unconfined again" 0 "$(nnp_of "$(main_pid)")"

# ----- a game that stays up but loses a port: rolled back -----
restart_plain needs-host-tmp
run_tool "$work/port.log" on "$UNIT" --settle 4 --port-timeout 10
check "a game that loses a port under the sandbox: exit 1" 1 "$rc"
contains "the missing port is named" "within 10s: 27015/tcp" "$work/port.log"
if [ -e "$DROPIN" ]; then fail "rollback left the drop-in"; else ok "rollback removes the drop-in"; fi
wait_active || true
check "the port is back after the rollback" "bound" "$(evidence ports)"

# ----- explicit --port that never opens -----
restart_plain ok
run_tool "$work/explicit.log" on "$UNIT" --settle 4 --port-timeout 6 --port 9999/udp
check "an explicit port that never opens: exit 1" 1 "$rc"
contains "the explicit port is named" "9999/udp" "$work/explicit.log"
# The restore demands only what was open before: 9999 never was, so the rollback is clean.
contains "the rollback does not demand a port that was never open" "rolled back:" "$work/explicit.log"

# ----- a game that does not come back at all: exit 2 -----
printf '0' > /opt/game/starts
set_mode dies-after-first
systemctl restart "$UNIT"
sleep 3
run_tool "$work/dead.log" on "$UNIT" --settle 4
check "rollback that cannot restore the game: exit 2" 2 "$rc"
contains "it says so loudly" "did NOT come back" "$work/dead.log"
if [ -e "$DROPIN" ]; then fail "the drop-in stayed after a failed rollback"; else ok "the drop-in is gone even then"; fi
systemctl stop "$UNIT"; systemctl reset-failed "$UNIT" 2>/dev/null

# ----- the deploy phase (lib/ct-phases.sh setup_unit_sandbox, local transport) -----
restart_plain ok
phase() { # GAME_UNIT_SANDBOX value -> runs the phase in a subshell, log in $work/phase.log
  ( msg() { echo "$*"; }; warn() { echo "WARN $*"; }; die() { echo "DIE $*"; exit 1; }
    run_ct() { bash -lc "$1"; }
    push_file_to_ct() { install -D -m "${3:-0644}" "$1" "$2"; }
    # shellcheck source=/dev/null
    source "$REPO/lib/ct-phases.sh"
    SERVICE_NAME=$UNIT UNIT_SANDBOX_SCRIPT="$TOOL" GAME_UNIT_SANDBOX="$1"
    setup_unit_sandbox ) >"$work/phase.log" 2>&1
}
phase 0
if [ -e "$DROPIN" ] || [ -e /usr/local/lib/gamepanel/ct-sandbox-unit.sh ]; then fail "the phase did something while off"; else ok "the phase is a no-op by default"; fi
phase 1
if [ -f "$DROPIN" ]; then ok "GAME_UNIT_SANDBOX=1 turns it on at deploy"; else fail "the phase did not apply it: $(tail -3 "$work/phase.log" | tr '\n' '|')"; fi
check "the tool stays in the CT for later" "755" "$(stat -c '%a' /usr/local/lib/gamepanel/ct-sandbox-unit.sh 2>/dev/null)"
bash "$TOOL" off "$UNIT" >/dev/null 2>&1
restart_plain needs-usr
phase 1
contains "a game that fails at deploy: warned, not fatal" "WARN The game stays WITHOUT the systemd sandbox" "$work/phase.log"
if systemctl is-active --quiet "$UNIT"; then ok "and the game was left running"; else fail "the deploy phase left the game down"; fi
systemctl stop "$UNIT"

# ----- the PANEL unit (deploy/admin/provision-admin-lxc.sh render_panel_unit) -----
unit_text="$(bash -c "source '$REPO/deploy/admin/provision-admin-lxc.sh'; PANEL_PORT=8080; render_panel_unit")"
for d in ProtectSystem=strict ReadWritePaths=/var/lib/gamepanel PrivateTmp=true NoNewPrivileges=true ProtectHome=true; do
  if grep -qx "$d" <<<"$unit_text"; then ok "panel unit has $d"; else fail "panel unit lacks $d"; fi
done
id gamepanel >/dev/null 2>&1 || useradd --system --home-dir /opt/gamepanel --shell /usr/sbin/nologin gamepanel
install -d -o gamepanel -g gamepanel -m 0750 /var/lib/gamepanel /etc/gamepanel
install -d /opt/gamepanel/releases/sandbox
cp -r "$REPO/src/gamepanel" /opt/gamepanel/releases/sandbox/
ln -sfn releases/sandbox /opt/gamepanel/current
ssh-keygen -q -t ed25519 -N '' -f /etc/gamepanel/id_ed25519
head -c 32 /dev/urandom > /etc/gamepanel/secret_key
touch /var/lib/gamepanel/known_hosts
chown gamepanel:gamepanel /etc/gamepanel/id_ed25519 /etc/gamepanel/id_ed25519.pub /etc/gamepanel/secret_key /var/lib/gamepanel/known_hosts
chmod 0600 /etc/gamepanel/id_ed25519 /etc/gamepanel/secret_key
printf 'GAMEPANEL_DB=/var/lib/gamepanel/panel.db\nGAMEPANEL_SECRET_FILE=/etc/gamepanel/secret_key\nGAMEPANEL_SSH_KEY=/etc/gamepanel/id_ed25519\nGAMEPANEL_KNOWN_HOSTS=/var/lib/gamepanel/known_hosts\nGAMEPANEL_PORT=8080\n' \
  > /etc/gamepanel/panel.env
chown root:gamepanel /etc/gamepanel/panel.env
chmod 0640 /etc/gamepanel/panel.env
printf '%s\n' "$unit_text" > /etc/systemd/system/gamepanel.service
systemctl daemon-reload
systemctl start gamepanel.service
health=""
for _ in $(seq 1 60); do
  health="$(python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2).status)' 2>/dev/null || true)"
  [ "$health" = 200 ] && break
  sleep 1
done
check "the real panel answers /health under the strict unit" 200 "$health"
if [ "$health" != 200 ]; then journalctl -u gamepanel.service --no-pager -n 30; fi
check "the panel created its database in DATA_DIR" "gamepanel" "$(stat -c '%U' /var/lib/gamepanel/panel.db 2>/dev/null)"
ppid="$(systemctl show -p MainPID --value gamepanel.service)"
if [ "${ppid:-0}" -gt 0 ]; then
  check "the panel process has NoNewPrivs" 1 "$(nnp_of "$ppid")"
  # The panel's own mount view, as the panel's user: what it can and cannot write.
  as_panel() { nsenter -t "$ppid" -m -- runuser -u gamepanel -- "$@" 2>/dev/null; }
  if as_panel touch /var/lib/gamepanel/probe; then ok "the panel writes DATA_DIR"; else fail "the panel cannot write DATA_DIR"; fi
  if as_panel mkdir -p /var/lib/gamepanel/ssh-control /var/lib/gamepanel/backups; then
    ok "the panel creates ssh-control/ and backups/"; else fail "the panel cannot create ssh-control/ or backups/"; fi
  # /etc/gamepanel is gamepanel's own folder (0750): only the sandbox makes it read-only.
  if as_panel touch /etc/gamepanel/probe; then fail "the panel writes /etc/gamepanel"; else ok "/etc/gamepanel is read-only for the panel (its own folder)"; fi
  if as_panel touch /var/tmp/probe && as_panel touch /tmp/probe; then ok "the panel has its private /tmp and /var/tmp"; else fail "no writable /tmp for the panel"; fi
  install -d -o gamepanel -g gamepanel /var/opt/gp-probe
  if as_panel touch /var/opt/gp-probe/x; then fail "the panel writes outside ReadWritePaths"; else ok "a folder the panel owns outside ReadWritePaths is read-only (strict)"; fi
else
  fail "the panel has no main process"
fi
systemctl stop gamepanel.service

echo
if [ "$failures" -eq 0 ]; then echo "unit sandbox: all OK"; else echo "unit sandbox: ${failures} FAILURE(S)"; fi
exit "$failures"
