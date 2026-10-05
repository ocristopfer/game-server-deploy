#!/usr/bin/env bash
# Proves the REAL Docker game image (docker/gameserver, what deploy/game/deploy-docker.ps1 runs)
# against the access contract of docs/security-hardening-contract.md, with a real SteamCMD install
# and a real sshd. Needs Docker and internet (apt, SteamCMD).
#
#   docker/ct-sandbox/gameserver.sh                 # app 1007 (Steamworks SDK): small and fast
#   docker/ct-sandbox/gameserver.sh --game ets2     # a real game from games/<key>.env (GBs, slow)
#
# A second container of the same image plays the panel: it logs in as gamepanel with its own key
# and sends the SAME command strings src/gamepanel/runtime/remote_cmd.py builds in helper mode
# (status_service, metrics_probe, read_logs, as_root_action, as_steam). Nothing here is a fake:
# sudo, sshd, SteamCMD and the image's systemctl/journalctl/supervisor are the ones that ship.
#
# The Portuguese strings it greps for ("Container pronto", "parado a pedido", "ja instalado"...)
# are the image's existing output, matched as they are.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
# Git Bash would rewrite every /usr/local/... argument below into a Windows path.
export MSYS_NO_PATHCONV=1

game_env=docker/ct-sandbox/gameserver-sdk.env
ready_timeout=600
while [ $# -gt 0 ]; do
  case "$1" in
    --game) game_env="games/${2:?--game needs the game key}.env"; ready_timeout=7200; shift ;;
    *) echo "usage: $0 [--game <key>]" >&2; exit 2 ;;
  esac
  shift
done
[ -f "$game_env" ] || { echo "not found: $game_env" >&2; exit 2; }
env_value() { sed -n "s/^$1=//p" "$game_env" | head -n 1 | tr -d '"'; }
key="$(env_value GAME_KEY)"
unit="${key}.service"
start_script="$(env_value START_SCRIPT)"

IMAGE="gameserver-sandbox:${key}"
NET=gs-sandbox
HOST=gs-host           # network alias: the recreated container answers on the same name
names=(gs-panel gs-game gs-game2)
failures=0

ok()   { printf 'OK        %s\n' "$*"; }
fail() { printf 'FAILED    %s\n' "$*"; failures=$((failures + 1)); }
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (expected '$2', got '$3')"; fi
}
contains() { # description, needle, haystack
  if [[ "$3" == *"$2"* ]]; then ok "$1"; else fail "$1 (no '$2' in: $(printf '%s' "$3" | tail -n 3 | tr '\n' ' '))"; fi
}

cleanup() {
  docker rm -f -v "${names[@]}" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "== building the real image ($game_env)"
docker build -q -f docker/gameserver/Dockerfile --build-arg "GAME_ENV=$game_env" -t "$IMAGE" . >/dev/null
docker network create "$NET" >/dev/null

# The "panel": the same image, only for its ssh client. Its key is the one the game container
# authorizes (PANEL_PUBKEY, the deploy-docker.ps1 way).
docker run -d --name gs-panel --network "$NET" --entrypoint sleep "$IMAGE" infinity >/dev/null
docker exec gs-panel sh -c 'install -d -m 700 /root/.ssh && ssh-keygen -q -t ed25519 -N "" -C panel@sandbox -f /root/.ssh/id_ed25519'
panel_pub="$(docker exec gs-panel cat /root/.ssh/id_ed25519.pub)"

ssh_as() { # user, remote command (one string, as the panel sends it)
  docker exec gs-panel ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR -o ConnectTimeout=10 "$1@$HOST" "$2"
}
gp() { ssh_as gamepanel "$1" 2>&1; }
# stdin goes through untouched, the way the panel pushes uploads and installer files.
gp_stdin() {
  docker exec -i gs-panel ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR "gamepanel@$HOST" "$1" 2>&1
}
as_root() { docker exec "$game" bash -c "$1" 2>&1; }
# The game's environment, read as steam: root in a container has no CAP_SYS_PTRACE, and the kernel
# refuses it /proc/<pid>/environ of another user's process.
game_environ() {
  as_root "runuser -u steam -- cat /proc/\$(cat /run/game/${key}.main)/environ | tr '\\0' '\\n'"
}

# Waits for the entrypoint's "Container pronto" line number $2 (a recreated container prints
# its own first one; a restarted one adds a second).
wait_ready() { # container, how many ready lines
  local waited=0
  while [ "$waited" -lt "$ready_timeout" ]; do
    if [ "$(docker logs "$1" 2>&1 | grep -c 'Container pronto')" -ge "$2" ]; then return 0; fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$1")" != true ]; then break; fi
    sleep 3
    waited=$((waited + 3))
  done
  echo "--- last lines of $1"; docker logs "$1" 2>&1 | tail -n 40
  return 1
}

start_game() { # name, extra docker run args...
  local name="$1"; shift
  docker run -d --name "$name" --network "$NET" --network-alias "$HOST" --hostname "$key" \
    -e PANEL_PUBKEY="$panel_pub" -e AUTO_UPDATE=0 "$@" "$IMAGE" >/dev/null
}

game=gs-game
echo "== starting the game container (real SteamCMD; the first download takes a while)"
start_game "$game"
if wait_ready "$game" 1; then ok "container ready (SteamCMD installed app $(env_value STEAM_APP_ID))"; else
  fail "container never became ready"; echo; echo "FAILED: $failures check(s)"; exit 1; fi

status() { gp "systemctl show $unit -p ActiveState -p SubState -p NRestarts -p Result" | tr '\n' ' ' | sed 's/ $//'; }
main_pid() { gp "systemctl show -p MainPID --value $unit"; }
restart_sec="$(as_root '. /etc/game/service.env; echo "${RESTART_SEC:-10}"')"

# From here on a failed command is a FAILED line, never the end of the run.
set +e

echo "== access"
check "gamepanel runs gp-service --version through sudo" "gp-helpers 1" "$(gp 'sudo -n /usr/local/sbin/gp-service --version')"
check "gamepanel acts as steam" "steam" "$(gp 'cd / && sudo -n -u steam -- id -un')"
check "terminal: steam login shell" "steam" "$(gp 'sudo -n -u steam -i id -un')"
if ssh_as root true >/dev/null 2>&1; then fail "root logged in over SSH"; else ok "root refused over SSH (no key)"; fi
as_root "install -d -m 700 /root/.ssh && echo '$panel_pub' > /root/.ssh/authorized_keys" >/dev/null
if ssh_as root true >/dev/null 2>&1; then fail "root logged in with the panel key"; else ok "root refused over SSH even with the key in /root"; fi
as_root "rm -f /root/.ssh/authorized_keys" >/dev/null
check "effective sshd: PermitRootLogin no" "permitrootlogin no" "$(as_root 'sshd -T | grep -i ^permitrootlogin')"
contains "steam has no sudo at all" "not allowed to run sudo" "$(as_root 'sudo -l -U steam')"
if gp 'sudo -n -l /usr/local/sbin/gp-service stop ssh' >/dev/null; then fail "gp-service with a unit was allowed"; else ok "gp-service with a unit is refused"; fi
if gp "sudo -n -l /usr/local/bin/systemctl stop $unit" >/dev/null; then fail "systemctl through sudo was allowed"; else ok "systemctl through sudo is refused"; fi
if gp 'sudo -n -l /bin/bash' >/dev/null; then fail "bash as root was allowed"; else ok "root shell through sudo is refused"; fi
if gp 'sudo -n -l /usr/local/bin/update-game --anything' >/dev/null; then fail "update-game with an argument was allowed"; else ok "update-game with an argument is refused"; fi
if gp 'cat /etc/game/service.env' >/dev/null; then fail "gamepanel read service.env (0600)"; else ok "gamepanel cannot read root's service.env"; fi

echo "== service (the panel's helper-mode commands)"
check "status: show with several -p" "ActiveState=active SubState=running NRestarts=0 Result=success" "$(status)"
pid="$(main_pid)"
check "MainPID is a steam process" "steam" "$(gp "stat -c %U /proc/$pid")"
contains "MainPID is the game, not the supervisor" "$start_script" "$(gp "tr '\\0' ' ' < /proc/$pid/cmdline")"
if gp "cd / && sudo -n -u steam -- ls /proc/$pid/fd" >/dev/null; then ok "steam reads the game's sockets (port discovery)"; else fail "steam cannot read /proc/$pid/fd"; fi
gp 'sudo -n /usr/local/sbin/gp-service restart' >/dev/null
new_pid="$(main_pid)"
if [ -n "$new_pid" ] && [ "$new_pid" != 0 ] && [ "$new_pid" != "$pid" ]; then ok "gp-service restart replaces the game process"; else fail "restart kept the MainPID ($pid -> $new_pid)"; fi
check "after the restart" "ActiveState=active SubState=running NRestarts=0 Result=success" "$(status)"
gp 'sudo -n /usr/local/sbin/gp-service stop' >/dev/null
check "gp-service stop" "ActiveState=inactive SubState=dead" "$(status | cut -d' ' -f1-2)"
# The stop must return only AFTER the game finished saving (the sandbox game takes 2 s; a real
# game prints whatever it prints, so only the supervisor's line is checked there).
stop_log="$(gp "journalctl -u $unit --no-pager -n 6")"
if [ "$key" = sdkprobe ]; then contains "stop waits for the game to save" "world saved" "$stop_log"; fi
contains "the supervisor outlives the TERM and records the stop" "parado a pedido" "$stop_log"
check "is-active as the restore uses it" "inactive" "$(gp "systemctl is-active $unit")"
gp 'sudo -n /usr/local/sbin/gp-service start' >/dev/null
check "gp-service start" "ActiveState=active SubState=running" "$(status | cut -d' ' -f1-2)"

logs="$(gp "journalctl -u $unit --no-pager --show-cursor -n 50")"
contains "journalctl without sudo brings the log" "iniciando:" "$logs"
cursor="$(printf '%s\n' "$logs" | sed -n 's/^-- cursor: //p')"
contains "journalctl returns the cursor" "b=" "$cursor"
check "after-cursor with nothing new" "-- No entries --" "$(gp "journalctl -u $unit --no-pager --show-cursor --after-cursor $cursor -n 200" | head -n 1)"

echo "== crash and automatic restart (NRestarts for the loop alert)"
as_root "kill -9 $(main_pid)" >/dev/null
sleep 1
check "between the crash and the restart" "ActiveState=active SubState=auto-restart NRestarts=1 Result=exit-code" "$(status)"
sleep "$((restart_sec + 2))"
check "the supervisor brought the game back" "ActiveState=active SubState=running NRestarts=1" "$(status | cut -d' ' -f1-3)"
gp 'sudo -n /usr/local/sbin/gp-service restart' >/dev/null
check "a manual restart resets the counter" "NRestarts=0" "$(status | cut -d' ' -f3)"

echo "== content as steam"
contains "ls /opt/game as steam" "steamapps" "$(gp 'cd / && sudo -n -u steam -- ls /opt/game')"
gp "cd / && sudo -n -u steam -- sh -c 'echo panel > /opt/game/panel.txt'" >/dev/null
check "a file the panel writes belongs to steam" "steam" "$(as_root 'stat -c %U /opt/game/panel.txt')"
check "backup folder belongs to steam" "steam 750" "$(as_root 'stat -c "%U %a" /var/backups/gamepanel')"
gp "cd / && sudo -n -u steam -- tar -czf /var/backups/gamepanel/sandbox.tar.gz -C / opt/game/panel.txt" >/dev/null
check "backup written as steam" "steam" "$(as_root 'stat -c %U /var/backups/gamepanel/sandbox.tar.gz 2>/dev/null || echo missing')"

echo "== mod environment (drop-in + steam overlay)"
check "overlay drop-in installed" "EnvironmentFile=-/etc/gamepanel/game-env/service.env" \
  "$(as_root "grep ^EnvironmentFile= /etc/systemd/system/$unit.d/gamepanel-env.conf")"
# What a Mods screen installer does as steam: append KEY='value' lines to the overlay. The second
# line is what a compromised game would plant, hoping root sources the file.
printf '%s\n' "GP_SANDBOX_MARK='overlay ok'" 'GP_SANDBOX_RAW=$(touch /tmp/gp-pwned)' \
  | gp_stdin 'cd / && sudo -n -u steam -- tee -a /etc/gamepanel/game-env/service.env' >/dev/null
check "daemon-reload as steam does not fail" "0" "$(gp 'cd / && sudo -n -u steam -- systemctl daemon-reload >/dev/null 2>&1; echo $?')"
gp 'sudo -n /usr/local/sbin/gp-service restart' >/dev/null
environ="$(game_environ)"
contains "the game gets the overlay variable (quotes removed)" "GP_SANDBOX_MARK=overlay ok" "$environ"
contains "an overlay value arrives literally, never expanded" 'GP_SANDBOX_RAW=$(touch /tmp/gp-pwned)' "$environ"
check "the overlay is parsed, never run as root" "missing" "$(as_root '[ -e /tmp/gp-pwned ] && echo exists || echo missing')"
contains "the log names the variables that went in" "environment from drop-ins: GP_SANDBOX_MARK GP_SANDBOX_RAW" "$(gp "journalctl -u $unit --no-pager -n 20")"
if gp "cd / && sudo -n -u steam -- ln -sf /etc/shadow /etc/gamepanel/game-env/service.env" >/dev/null; then
  fail "steam replaced the overlay with a link"; else ok "steam cannot replace the overlay file with a link (root's folder)"; fi

echo "== update through sudo (real SteamCMD)"
contains "check-game-update" "Jogo ja atualizado" "$(gp 'sudo -n /usr/local/bin/check-game-update')"
contains "update-game" "Atualizacao concluida." "$(gp 'sudo -n /usr/local/bin/update-game')"
check "server back up after the update" "ActiveState=active SubState=running" "$(status | cut -d' ' -f1-2)"

echo "== recreated container (the image's volumes)"
docker stop -t 30 "$game" >/dev/null
contains "docker stop shuts the game down through systemctl" "Recebi o pedido de parada" "$(docker logs "$game" 2>&1 | tail -n 20)"
game=gs-game2
start_game "$game" --volumes-from gs-game
if wait_ready "$game" 1; then ok "recreated container ready"; else fail "recreated container never became ready"; fi
contains "the game is not downloaded again" "ja instalado" "$(docker logs "$game" 2>&1)"
check "gamepanel gets into the new container" "gp-helpers 1" "$(gp 'sudo -n /usr/local/sbin/gp-service --version')"
check "game up in the new container" "ActiveState=active SubState=running" "$(status | cut -d' ' -f1-2)"
check "the backup survived" "steam" "$(as_root 'stat -c %U /var/backups/gamepanel/sandbox.tar.gz 2>/dev/null || echo missing')"
contains "the mod overlay survived and reaches the game" "GP_SANDBOX_MARK=overlay ok" "$(game_environ)"
docker restart -t 30 "$game" >/dev/null
if wait_ready "$game" 2; then ok "container restart: install and lock run again"; else fail "container restart failed"; fi
check "gamepanel gets in after the restart" "ActiveState=active SubState=running" "$(status | cut -d' ' -f1-2)"
if ssh_as root true >/dev/null 2>&1; then fail "root logged in after the restart"; else ok "root still refused after the restart"; fi

echo
if (( failures )); then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "ALL OK"
