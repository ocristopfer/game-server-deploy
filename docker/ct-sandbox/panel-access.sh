#!/usr/bin/env bash
# Proves lib/ct-panel-access.sh in the sandbox, against the REAL sudo and sshd of Debian 13:
# the sudoers passes visudo, gamepanel runs exactly the allowed commands and nothing else, steam
# has no sudo, a rerun changes nothing, and the root lock really refuses root over SSH while
# gamepanel still gets in. Needs Docker.
#
#   docker/ct-sandbox/panel-access.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # path as Docker sees it (Git Bash on Windows)
docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(host_path):/repo:ro" ct-sandbox bash /usr/local/lib/run-panel-access.sh /repo
