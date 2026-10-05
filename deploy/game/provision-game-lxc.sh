#!/usr/bin/env bash
# Provisions an LXC on Proxmox with SteamCMD and installs a dedicated game server.
# Runs ON THE PROXMOX HOST (sent by deploy-game.ps1).
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
if [[ "$SCRIPT_PATH" == "bash" || "$SCRIPT_PATH" == "-bash" ]]; then
  SCRIPT_DIR="$(pwd)"
else
  SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
fi

DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$SCRIPT_DIR/deploy.env}"
GAME_ENV_FILE="${GAME_ENV_FILE:-$SCRIPT_DIR/game.env}"

STEAMCMD_URL="https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_DIR="/opt/steamcmd"
GAME_DIR="/opt/game"

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n[WARN] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

on_error() {
  local cmd="$2"
  # The failed command may be the SteamCMD line with the Steam account password
  [[ -n "${STEAM_PASS:-}" ]] && cmd="${cmd//${STEAM_PASS}/******}"
  die "Provisionamento falhou na linha ${1} executando: ${cmd}"
}
trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Comando obrigatorio ausente: $1"
}

load_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || die "Arquivo de ambiente nao encontrado: $env_file"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

run_ct() {
  pct exec "$CTID" -- bash -lc "$1"
}

push_file_to_ct() {
  local src="$1"
  local dest="$2"
  local mode="${3:-0644}"
  run_ct "install -d '$(dirname "$dest")'"
  pct exec "$CTID" -- tee "$dest" >/dev/null < "$src"
  run_ct "chmod ${mode} '$dest'"
}

# Installs a shortcut in /usr/local/bin and creates a symlink in /usr/bin.
# `pct exec` does not use a login shell and its PATH does not include /usr/local/bin; the symlink
# makes the shortcut work both logged into the CT and via `pct exec <CTID> -- <shortcut>`.
install_helper() {
  local name="$1"
  local src="$2"
  push_file_to_ct "$src" "/usr/local/bin/${name}" 0755
  run_ct "ln -sfn /usr/local/bin/${name} /usr/bin/${name}"
}

# Phases that run INSIDE the CT (packages, SteamCMD, Wine/Proton, game, systemd). They live in
# lib/ct-phases.sh because the broker runs the SAME phases over another transport (see the top
# of that file). This script only defines the transport: `pct exec`.
# The deploy-game.ps1 bundle is a folder WITHOUT subfolders (scp only carries loose files),
# so there the lib comes next to the script; in the repository it lives in lib/.
FIREWALL_SCRIPT="${SCRIPT_DIR}/ct-firewall.sh"
[[ -f "$FIREWALL_SCRIPT" ]] || FIREWALL_SCRIPT="${SCRIPT_DIR}/../../lib/ct-firewall.sh"
PANEL_ACCESS_SCRIPT="${SCRIPT_DIR}/ct-panel-access.sh"
[[ -f "$PANEL_ACCESS_SCRIPT" ]] || PANEL_ACCESS_SCRIPT="${SCRIPT_DIR}/../../lib/ct-panel-access.sh"
LIB_FASES="${SCRIPT_DIR}/ct-phases.sh"
[[ -f "$LIB_FASES" ]] || LIB_FASES="${SCRIPT_DIR}/lib/ct-phases.sh"
[[ -f "$LIB_FASES" ]] || die "ct-phases.sh nao encontrado ao lado do script nem em lib/ (o bundle do deploy precisa leva-lo)"
# shellcheck source=lib/ct-phases.sh
source "$LIB_FASES"

resolve_variables() {
  resolve_game_variables

  CTID="${CTID:-}"
  [[ -n "$CTID" ]] || die "CTID nao definido (preencha o .env ou use -Interactive)"
  CT_HOSTNAME="${HOSTNAME_OVERRIDE:-${GAME_KEY}}"
  STORAGE="${STORAGE:-local-zfs}"
  TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
  TEMPLATE_PATTERN="${TEMPLATE_PATTERN:-debian-13-standard_.*_amd64\.tar\.zst}"
  BRIDGE="${BRIDGE:-vmbr0}"
  IP_CIDR="${IP_CIDR:-dhcp}"
  GATEWAY="${GATEWAY:-}"
  # Without a password the CT root is LOCKED (you get in through `pct enter` or the SSH key).
  # The default used to be "changeme": every CT was born with the same well-known console password.
  CT_PASSWORD="${CT_PASSWORD:-}"
  TZ="${TZ:-America/Sao_Paulo}"
  RECREATE_CT="${RECREATE_CT:-0}"

  MEMORY="${MEMORY:-${RECOMMENDED_MEMORY:-4096}}"
  CORES="${CORES:-${RECOMMENDED_CORES:-2}}"
  ROOTFS_SIZE_GB="${ROOTFS_SIZE_GB:-${RECOMMENDED_DISK_GB:-20}}"
  SWAP="${SWAP:-512}"

  if [[ "$IP_CIDR" == "dhcp" ]]; then
    NET0="name=eth0,bridge=${BRIDGE},ip=dhcp,type=veth"
  else
    [[ -n "$GATEWAY" ]] || die "GATEWAY obrigatorio quando IP_CIDR nao e dhcp"
    NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY},type=veth"
  fi
}

validate_host_requirements() {
  need_cmd pct
  need_cmd pveam
  need_cmd awk
}

ensure_debian_template() {
  if pct status "$CTID" >/dev/null 2>&1 && [[ "$RECREATE_CT" != "1" ]]; then
    msg "CT $CTID ja existe, pulando download de template"
    return
  fi

  msg "Atualizando lista de templates do Proxmox"
  pveam update >/dev/null
  TEMPLATE="$(pveam available --section system | awk -v pat="$TEMPLATE_PATTERN" '$2 ~ pat {print $2}' | tail -n1)"
  [[ -n "$TEMPLATE" ]] || die "Template Debian nao encontrado para o padrao $TEMPLATE_PATTERN"
  if ! pveam list "$TEMPLATE_STORAGE" | awk '{print $2}' | grep -qx "$TEMPLATE"; then
    msg "Baixando template $TEMPLATE"
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
  fi
}

ensure_container() {
  local ct_exists=0
  if pct status "$CTID" >/dev/null 2>&1; then
    ct_exists=1
  fi

  if [[ "$ct_exists" -eq 1 && "$RECREATE_CT" == "1" ]]; then
    msg "Recriando CT $CTID (RECREATE_CT=1)"
    pct stop "$CTID" >/dev/null 2>&1 || true
    pct destroy "$CTID" --destroy-unreferenced-disks 1
    ct_exists=0
  fi

  if [[ "$ct_exists" -eq 0 ]]; then
    msg "Criando CT $CTID ($CT_HOSTNAME) - ${CORES} cores, ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB disco"
    pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
      --arch amd64 \
      --hostname "$CT_HOSTNAME" \
      --cores "$CORES" \
      --memory "$MEMORY" \
      --swap "$SWAP" \
      --rootfs "${STORAGE}:${ROOTFS_SIZE_GB}" \
      --ostype debian \
      --unprivileged 1 \
      --features nesting=1,keyctl=1 \
      --net0 "$NET0" \
      ${CT_PASSWORD:+--password "$CT_PASSWORD"} \
      --onboot 1 \
      --timezone "$TZ" \
      --tags "game;steam;${GAME_KEY}"
  else
    msg "Atualizando configuracao do CT $CTID"
    pct set "$CTID" \
      --hostname "$CT_HOSTNAME" \
      --cores "$CORES" \
      --memory "$MEMORY" \
      --swap "$SWAP" \
      --net0 "$NET0" \
      --onboot 1 \
      --timezone "$TZ" \
      --tags "game;steam;${GAME_KEY}"
  fi
}

start_container() {
  if ! pct status "$CTID" 2>/dev/null | grep -q running; then
    msg "Iniciando CT $CTID"
    pct start "$CTID"
  fi

  local tries=0
  until pct exec "$CTID" -- true >/dev/null 2>&1; do
    tries=$((tries + 1))
    [[ "$tries" -lt 30 ]] || die "CT $CTID nao ficou pronto a tempo"
    sleep 2
  done
}


get_ct_ip() {
  if [[ "$IP_CIDR" == "dhcp" ]]; then
    CT_IP="$(run_ct "hostname -I | awk '{print \$1}'" | tr -d '\r' | tr -d ' \n' || true)"
    [[ -n "$CT_IP" ]] || CT_IP="<verifique com: pct exec $CTID -- hostname -I>"
  else
    CT_IP="${IP_CIDR%%/*}"
  fi
}

print_summary() {
  get_ct_ip
  cat <<EOF

========================================================================
 Deploy concluido: ${GAME_DISPLAY_NAME}
========================================================================

Container : CT ${CTID} (${CT_HOSTNAME}) - ${CORES} cores, ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB
IP do CT  : ${CT_IP}
Servico   : ${SERVICE_NAME} (start automatico no boot)

>>> PORTAS PARA REDIRECIONAR NO ROTEADOR (destino ${CT_IP}):
EOF
  if [[ -n "$GAME_PORTS" ]]; then
    local entry
    for entry in $GAME_PORTS; do
      printf '    - %s -> %s\n' "$entry" "$CT_IP"
    done
  else
    echo "    - (portas nao definidas para este jogo; verifique a documentacao do servidor)"
  fi
  [[ -n "${PORT_NOTES:-}" ]] && printf '\n    Nota: %s\n' "$PORT_NOTES"

  cat <<EOF

Arquivos do jogo : ${GAME_DIR}
EOF
  [[ -n "${CONFIG_HINT:-}" ]] && echo "Configuracao     : ${CONFIG_HINT}"
  [[ -n "${SAVE_HINT:-}" ]] && echo "Saves            : ${SAVE_HINT}"

  cat <<EOF

Atalhos (funcionam logado no CT via 'pct enter ${CTID}' ou pelo host com 'pct exec ${CTID} -- <atalho>'):
  game-restart      # reinicia o servidor
  game-stop         # para o servidor
  game-start        # sobe o servidor
  game-status       # status do servico
  game-logs         # log ao vivo (aceita args do journalctl, ex.: game-logs -n 50)
  update-game       # atualiza o jogo via SteamCMD (para/atualiza/reinicia)

Exemplo a partir do host Proxmox:
  pct exec ${CTID} -- game-restart

EOF
}

# The CT is unprivileged: it uses nftables, but cannot load kernel modules. The host loads it
# (and keeps it loading at boot), otherwise the `ct-firewall apply` inside fails with "Operation not
# supported" - or worse, the CT comes up without rules after a host reboot.
load_nf_tables_on_host() {
  [[ "${CT_FIREWALL:-1}" == "0" || -z "${FW_MGMT_SOURCES:-}" ]] && return 0
  modprobe nf_tables 2>/dev/null || warn "nao consegui carregar o modulo nf_tables no host"
  { mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
    || warn "nao consegui deixar o nf_tables carregando no boot do host"
}

main() {
  load_env_file "$DEPLOY_ENV_FILE"
  load_env_file "$GAME_ENV_FILE"
  resolve_variables
  validate_host_requirements
  ensure_debian_template
  ensure_container
  start_container
  install_base_packages_in_ct
  ensure_steam_user
  setup_panel_access
  install_steamcmd_in_ct
  setup_windows_runtime
  run_pre_install
  install_game_in_ct
  # post-install runs before detection because a game may CREATE its own
  # start script there (e.g. a Wine wrapper for builds without a Linux version)
  run_post_install
  apply_recipes
  detect_start_script
  render_update_helper
  render_update_checker
  render_service_helpers
  render_systemd_unit
  start_game_service
  load_nf_tables_on_host
  setup_firewall
  lock_root_login
  print_summary
}

main "$@"