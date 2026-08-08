#!/usr/bin/env bash
# Provisiona um LXC no Proxmox com SteamCMD e instala um servidor dedicado de jogo.
# Roda NO HOST PROXMOX (enviado pelo deploy-game.ps1).
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
  die "Provisionamento falhou na linha ${1} executando: ${2}"
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

# Instala um atalho em /usr/local/bin e cria symlink em /usr/bin.
# `pct exec` nao usa shell de login e seu PATH nao inclui /usr/local/bin; o symlink
# faz o atalho funcionar tanto logado no CT quanto via `pct exec <CTID> -- <atalho>`.
install_helper() {
  local name="$1"
  local src="$2"
  push_file_to_ct "$src" "/usr/local/bin/${name}" 0755
  run_ct "ln -sfn /usr/local/bin/${name} /usr/bin/${name}"
}

resolve_variables() {
  [[ -n "${GAME_KEY:-}" ]] || die "GAME_KEY nao definido no game.env"
  [[ -n "${STEAM_APP_ID:-}" ]] || die "STEAM_APP_ID nao definido no game.env"

  CTID="${CTID:-}"
  [[ -n "$CTID" ]] || die "CTID nao definido (preencha o .env ou use -Interactive)"
  CT_HOSTNAME="${HOSTNAME_OVERRIDE:-${GAME_KEY}}"
  STORAGE="${STORAGE:-local-zfs}"
  TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
  TEMPLATE_PATTERN="${TEMPLATE_PATTERN:-debian-13-standard_.*_amd64\.tar\.zst}"
  BRIDGE="${BRIDGE:-vmbr0}"
  IP_CIDR="${IP_CIDR:-dhcp}"
  GATEWAY="${GATEWAY:-}"
  CT_PASSWORD="${CT_PASSWORD:-changeme}"
  TZ="${TZ:-America/Sao_Paulo}"
  RECREATE_CT="${RECREATE_CT:-0}"

  MEMORY="${MEMORY:-${RECOMMENDED_MEMORY:-4096}}"
  CORES="${CORES:-${RECOMMENDED_CORES:-2}}"
  ROOTFS_SIZE_GB="${ROOTFS_SIZE_GB:-${RECOMMENDED_DISK_GB:-20}}"
  SWAP="${SWAP:-512}"

  AUTO_UPDATE="${AUTO_UPDATE:-1}"
  UPDATE_SCHEDULE="${UPDATE_SCHEDULE:-*-*-* 06:00:00}"

  GAME_DISPLAY_NAME="${GAME_DISPLAY_NAME:-$GAME_KEY}"
  GAME_PORT="${GAME_PORT:-}"
  GAME_PORTS="${GAME_PORTS:-}"
  START_SCRIPT="${START_SCRIPT:-}"
  START_ARGS="${START_ARGS:-}"
  POST_INSTALL_CMD="${POST_INSTALL_CMD:-}"
  SERVICE_NAME="${GAME_KEY}.service"

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
      --password "$CT_PASSWORD" \
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

install_base_packages_in_ct() {
  msg "Instalando pacotes base no CT (dependencias do SteamCMD)"
  run_ct "
    export DEBIAN_FRONTEND=noninteractive
    missing=''
    for pkg in ca-certificates curl lib32gcc-s1 lib32stdc++6 locales; do
      dpkg -s \"\$pkg\" >/dev/null 2>&1 || missing=\"\$missing \$pkg\"
    done
    if [[ -n \"\$missing\" ]]; then
      apt-get update
      apt-get install -y \$missing
    else
      echo 'Pacotes base ja instalados'
    fi
  "
}

ensure_steam_user() {
  msg "Garantindo usuario steam no CT"
  run_ct "id -u steam >/dev/null 2>&1 || useradd -m -s /bin/bash steam"
}

install_steamcmd_in_ct() {
  msg "Instalando SteamCMD no CT"
  run_ct "
    if [[ -x ${STEAMCMD_DIR}/steamcmd.sh ]]; then
      echo 'SteamCMD ja instalado'
      exit 0
    fi
    install -d ${STEAMCMD_DIR}
    curl -fsSL '${STEAMCMD_URL}' | tar -xz -C ${STEAMCMD_DIR}
    chown -R steam:steam ${STEAMCMD_DIR}
  "
}

install_game_in_ct() {
  msg "Instalando ${GAME_DISPLAY_NAME} (app ${STEAM_APP_ID}) via SteamCMD - pode demorar (download de varios GB)"
  run_ct "install -d -o steam -g steam ${GAME_DIR}"

  local attempt
  for attempt in 1 2 3; do
    if run_ct "su - steam -c '${STEAMCMD_DIR}/steamcmd.sh +force_install_dir ${GAME_DIR} +login anonymous +app_update ${STEAM_APP_ID} validate +quit'"; then
      return 0
    fi
    warn "SteamCMD falhou (tentativa ${attempt}/3), tentando novamente em 10s"
    sleep 10
  done
  die "SteamCMD nao conseguiu instalar o app ${STEAM_APP_ID} apos 3 tentativas"
}

detect_start_script() {
  if [[ -n "$START_SCRIPT" ]]; then
    run_ct "test -f ${GAME_DIR}/${START_SCRIPT}" || die "Script de start nao encontrado: ${GAME_DIR}/${START_SCRIPT}"
    return
  fi

  msg "START_SCRIPT vazio, tentando detectar automaticamente"
  START_SCRIPT="$(run_ct "find ${GAME_DIR} -maxdepth 1 -name '*.sh' -printf '%f\n' | sort | head -n1" | tr -d '\r')"
  if [[ -z "$START_SCRIPT" ]]; then
    warn "Nao foi possivel detectar o script de start. Conteudo da raiz do jogo:"
    run_ct "ls -la ${GAME_DIR}" || true
    die "Defina START_SCRIPT no arquivo do jogo (games/<jogo>.env) e rode de novo"
  fi
  msg "Script de start detectado: $START_SCRIPT"
}

run_post_install() {
  [[ -n "$POST_INSTALL_CMD" ]] || return 0
  msg "Executando POST_INSTALL_CMD do jogo dentro do CT"
  run_ct "$POST_INSTALL_CMD" || die "POST_INSTALL_CMD falhou (veja a saida acima)"
}

render_update_helper() {
  msg "Criando helper de atualizacao (/usr/local/bin/update-game)"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
# Atualiza ${GAME_DISPLAY_NAME} e reinicia o servico.
set -Eeuo pipefail
systemctl stop ${SERVICE_NAME} || true
su - steam -c "${STEAMCMD_DIR}/steamcmd.sh +force_install_dir ${GAME_DIR} +login anonymous +app_update ${STEAM_APP_ID} validate +quit"
systemctl start ${SERVICE_NAME}
echo "Atualizacao concluida."
EOF
  install_helper "update-game" "$tmp_file"
  rm -f "$tmp_file"
}

render_update_checker() {
  msg "Criando verificacao automatica de update (timer systemd)"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
# Compara o buildid instalado com o mais recente da Steam.
# So para/atualiza/reinicia o servidor quando ha update de verdade.
set -Eeuo pipefail

MANIFEST="${GAME_DIR}/steamapps/appmanifest_${STEAM_APP_ID}.acf"

installed=\$(awk -F'"' '/"buildid"/{print \$4; exit}' "\$MANIFEST" 2>/dev/null || true)
if [[ -z "\$installed" ]]; then
  echo "Manifesto nao encontrado (\$MANIFEST); rodando update completo"
  exec /usr/local/bin/update-game
fi

latest=\$(su - steam -c "${STEAMCMD_DIR}/steamcmd.sh +login anonymous +app_info_update 1 +app_info_print ${STEAM_APP_ID} +quit" \
  | tr -d '\r' \
  | sed -n '/"branches"/,\$p' \
  | sed -n '/"public"/,/}/p' \
  | awk -F'"' '/"buildid"/{print \$4; exit}')

if [[ -z "\$latest" ]]; then
  echo "Nao foi possivel obter o buildid mais recente da Steam; tentando no proximo ciclo"
  exit 0
fi

if [[ "\$installed" == "\$latest" ]]; then
  echo "Jogo ja atualizado (buildid \$installed)"
  exit 0
fi

echo "Update disponivel: \$installed -> \$latest. Atualizando..."
exec /usr/local/bin/update-game
EOF
  install_helper "check-game-update" "$tmp_file"
  rm -f "$tmp_file"

  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=Checa e aplica update de ${GAME_DISPLAY_NAME}

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-game-update
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/game-update-check.service" 0644
  rm -f "$tmp_file"

  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=Verificacao periodica de update de ${GAME_DISPLAY_NAME}

[Timer]
OnCalendar=${UPDATE_SCHEDULE}
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/game-update-check.timer" 0644
  rm -f "$tmp_file"

  if [[ "$AUTO_UPDATE" == "1" ]]; then
    run_ct "systemctl daemon-reload && systemctl enable --now game-update-check.timer"
  else
    run_ct "systemctl daemon-reload && systemctl disable --now game-update-check.timer >/dev/null 2>&1 || true"
    msg "AUTO_UPDATE=0: timer instalado porem desabilitado"
  fi
}

render_service_helpers() {
  msg "Criando atalhos de controle (game-start/stop/restart/status/logs)"
  local tmp_file name body
  tmp_file="$(mktemp)"
  for name in game-start game-stop game-restart game-status game-logs; do
    case "$name" in
      game-start)   body="exec systemctl start ${SERVICE_NAME}" ;;
      game-stop)    body="exec systemctl stop ${SERVICE_NAME}" ;;
      game-restart) body="exec systemctl restart ${SERVICE_NAME}" ;;
      game-status)  body="exec systemctl status ${SERVICE_NAME} --no-pager \"\$@\"" ;;
      game-logs)    body="exec journalctl -u ${SERVICE_NAME} \"\${@:--f}\"" ;;
    esac
    cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
# Controle do servidor de ${GAME_DISPLAY_NAME} (${SERVICE_NAME}).
set -Eeuo pipefail
${body}
EOF
    install_helper "$name" "$tmp_file"
  done
  rm -f "$tmp_file"
}

render_systemd_unit() {
  msg "Criando servico systemd ${SERVICE_NAME}"
  local rendered_args="${START_ARGS//\{PORT\}/${GAME_PORT}}"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=${GAME_DISPLAY_NAME} dedicated server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=steam
Group=steam
WorkingDirectory=${GAME_DIR}
ExecStart=${GAME_DIR}/${START_SCRIPT} ${rendered_args}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/${SERVICE_NAME}" 0644
  rm -f "$tmp_file"
  run_ct "chmod +x ${GAME_DIR}/${START_SCRIPT} && chown -R steam:steam ${GAME_DIR}"
  run_ct "systemctl daemon-reload && systemctl enable ${SERVICE_NAME}"
}

start_game_service() {
  msg "Iniciando o servidor do jogo"
  run_ct "systemctl restart ${SERVICE_NAME}"
  sleep 15
  if run_ct "systemctl is-active --quiet ${SERVICE_NAME}"; then
    msg "Servico ${SERVICE_NAME} ativo"
  else
    warn "Servico nao esta ativo. Ultimas linhas do log:"
    run_ct "journalctl -u ${SERVICE_NAME} --no-pager -n 40" || true
    die "O servidor nao subiu. Verifique o log acima."
  fi
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
  install_steamcmd_in_ct
  install_game_in_ct
  detect_start_script
  run_post_install
  render_update_helper
  render_update_checker
  render_service_helpers
  render_systemd_unit
  start_game_service
  print_summary
}

main "$@"
