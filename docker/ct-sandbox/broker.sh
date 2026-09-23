#!/usr/bin/env bash
# Prova o provision-broker-lxc.sh no sandbox: modo/dono dos arquivos, o broker.env aceito pelo
# carregador de configuracao real, segredos fora do log, idempotencia e rotacao de token e
# certificado. Precisa do Docker.
#
#   docker/ct-sandbox/broker.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # caminho que o Docker enxerga (Git Bash no Windows)
docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
MSYS_NO_PATHCONV=1 docker run --rm -v "$(host_path):/repo:ro" ct-sandbox bash /usr/local/lib/run-broker.sh /repo
