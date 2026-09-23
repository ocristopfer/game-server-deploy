#!/usr/bin/env bash
# Prova o lib/install-release.sh no sandbox: verificacao de sha256, pasta da versao,
# virada do symlink, remocao do layout antigo e rollback quando o servico nao sobe.
# Precisa do Docker.
#
#   docker/ct-sandbox/release.sh
set -euo pipefail
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$raiz"
qual() { pwd -W 2>/dev/null || pwd; }   # caminho que o Docker enxerga (Git Bash no Windows)
docker build -q -t ct-sandbox "$raiz/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(qual):/repo:ro" ct-sandbox bash /usr/local/lib/run-release.sh /repo
