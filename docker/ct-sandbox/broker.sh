#!/usr/bin/env bash
# Proves provision-broker-lxc.sh in the sandbox: file mode/owner, broker.env accepted by the
# real config loader, secrets kept out of the log, idempotence and token and certificate
# rotation. Needs Docker.
#
#   docker/ct-sandbox/broker.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # path as Docker sees it (Git Bash on Windows)
docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(host_path):/repo:ro" ct-sandbox bash /usr/local/lib/run-broker.sh /repo
