#!/usr/bin/env bash
# Instala um jogo DENTRO do proprio container (transporte local). E o que o broker roda por
# SSH depois de criar o CT: ele envia este arquivo, o ct-phases.sh e um install.env, e executa
#
#     bash ct-install.sh install.env
#
# As fases sao as MESMAS do deploy manual (lib/ct-phases.sh, lida tambem pelo
# provision-game-lxc.sh no host Proxmox); so o transporte muda: la e `pct exec`, aqui e um
# `bash -lc` local. O install.env e gerado pelo broker com aspas em todo valor (nunca e
# concatenado numa linha de comando), e nunca traz credencial de conta Steam.
set -Eeuo pipefail
IFS=$'\n\t'

INSTALL_ENV="${1:?uso: ct-install.sh <install.env>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

STEAMCMD_URL="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_DIR="/opt/steamcmd"
GAME_DIR="/opt/game"

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

on_error() {
  local cmd="$2"
  # O comando que falhou pode ser a linha do SteamCMD com a senha da conta Steam
  [[ -n "${STEAM_PASS:-}" ]] && cmd="${cmd//${STEAM_PASS}/******}"
  die "Instalacao falhou na linha ${1} executando: ${cmd}"
}
trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

# Transporte LOCAL das fases (o do host e `pct exec CT -- bash -lc`).
run_ct() {
  bash -lc "$1"
}

push_file_to_ct() {
  local src="$1"
  local dest="$2"
  local mode="${3:-0644}"
  install -D -m "$mode" "$src" "$dest"
}

# Mesmo atalho do provision-game-lxc.sh: /usr/local/bin + symlink em /usr/bin, porque o PATH
# de uma sessao sem login nao inclui /usr/local/bin.
install_helper() {
  local name="$1"
  local src="$2"
  push_file_to_ct "$src" "/usr/local/bin/${name}" 0755
  run_ct "ln -sfn /usr/local/bin/${name} /usr/bin/${name}"
}

LIB_FASES="${SCRIPT_DIR}/ct-phases.sh"
[[ -f "$LIB_FASES" ]] || die "ct-phases.sh nao encontrado ao lado de $0"
[[ -f "$INSTALL_ENV" ]] || die "Arquivo de ambiente nao encontrado: $INSTALL_ENV"
set -a
# shellcheck disable=SC1090
source "$INSTALL_ENV"
set +a
# shellcheck source=lib/ct-phases.sh
source "$LIB_FASES"

main() {
  resolve_game_variables
  install_base_packages_in_ct
  setup_panel_access
  ensure_steam_user
  install_steamcmd_in_ct
  setup_windows_runtime
  run_pre_install
  install_game_in_ct
  # post-install roda antes da deteccao porque um jogo pode CRIAR o proprio script de start
  run_post_install
  apply_recipes
  detect_start_script
  render_update_helper
  render_update_checker
  render_service_helpers
  render_systemd_unit
  start_game_service
  # Linha que o broker procura: sem ela, exit 0 nao basta para dar a instalacao por feita.
  msg "INSTALACAO CONCLUIDA: ${GAME_DISPLAY_NAME} (${SERVICE_NAME})"
}

main "$@"
