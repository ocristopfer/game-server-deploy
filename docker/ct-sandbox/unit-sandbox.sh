#!/usr/bin/env bash
# Proves, against a REAL systemd (PID 1 in a privileged container), the two unit hardenings:
#   - lib/ct-sandbox-unit.sh: the game drop-in is applied to the running process, a game that
#     cannot live with it is rolled back on its own, and `off` undoes it;
#   - deploy/admin/provision-admin-lxc.sh: the REAL panel starts under its strict unit and writes
#     only where ReadWritePaths lets it.
# What it cannot prove: an unprivileged LXC's AppArmor (see Dockerfile.systemd). Needs Docker.
#
#   docker/ct-sandbox/unit-sandbox.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # path as Docker sees it (Git Bash on Windows)
image=ct-sandbox-systemd
name="ct-sandbox-systemd-$$"
docker build -q -t "$image" -f "$repo_root/docker/ct-sandbox/Dockerfile.systemd" "$repo_root/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run -d --rm --name "$name" --privileged --cgroupns=private \
  --tmpfs /run --tmpfs /run/lock -v "$(host_path):/repo:ro" "$image" >/dev/null
trap 'docker stop "$name" >/dev/null 2>&1 || true' EXIT
# "degraded" is fine (some unit of the image itself may fail in a container); "starting" is not.
for _ in $(seq 1 30); do
  state="$(docker exec "$name" systemctl is-system-running 2>/dev/null || true)"
  [[ "$state" == running || "$state" == degraded ]] && break
  sleep 1
done
MSYS_NO_PATHCONV=1 docker exec "$name" bash /repo/docker/ct-sandbox/run-unit-sandbox.sh /repo
