#!/usr/bin/env bash
# Proves lib/install-release.sh in the sandbox: sha256 check, version folder, symlink
# switch, removal of the old layout and rollback when the service does not come up.
# Needs Docker.
#
#   docker/ct-sandbox/release.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # path as Docker sees it (Git Bash on Windows)
docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(host_path):/repo:ro" ct-sandbox bash /usr/local/lib/run-release.sh /repo
