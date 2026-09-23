#!/usr/bin/env bash
# Provisiona um LXC no Proxmox com o TeamSpeak 6 Server.
# Roda NO HOST PROXMOX (enviado pelo deploy-game.ps1, via games/teamspeak.env:PROVISION_SCRIPT).
#
# Standalone de proposito: o TeamSpeak nao vem da Steam (e um tarball baixado direto do
# GitHub da TeamSpeak), entao nao reaproveita provision-game-lxc.sh nem o toca - os dois
# scripts evoluem sem risco cruzado. O contrato de bundle (deploy.env + game.env no mesmo
# diretorio) e identico, entao deploy-game.ps1 nao precisou mudar alem de qual .sh enviar.
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

GAME_DIR="/opt/game"
SVC_USER="teamspeak"

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

# Instala um atalho em /usr/local/bin e cria symlink em /usr/bin (pct exec nao usa shell
# de login, entao seu PATH nao inclui /usr/local/bin - mesmo motivo do script Steam).
install_helper() {
  local name="$1"
  local src="$2"
  push_file_to_ct "$src" "/usr/local/bin/${name}" 0755
  run_ct "ln -sfn /usr/local/bin/${name} /usr/bin/${name}"
}

resolve_variables() {
  GAME_KEY="${GAME_KEY:-teamspeak}"
  GAME_DISPLAY_NAME="${GAME_DISPLAY_NAME:-TeamSpeak 6 Server}"

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

  MEMORY="${MEMORY:-${RECOMMENDED_MEMORY:-1024}}"
  CORES="${CORES:-${RECOMMENDED_CORES:-1}}"
  ROOTFS_SIZE_GB="${ROOTFS_SIZE_GB:-${RECOMMENDED_DISK_GB:-8}}"
  SWAP="${SWAP:-512}"

  # Versao fixada de proposito (mesmo motivo do PROTON_VERSION no script Steam): "latest"
  # trocaria de versao sozinho num redeploy, e o TS6 ainda esta em beta. Atualizar = mudar
  # DOWNLOAD_VERSION/DOWNLOAD_URL aqui e rodar o deploy de novo.
  DOWNLOAD_VERSION="${DOWNLOAD_VERSION:-v6.0.0-beta12.1}"
  DOWNLOAD_URL="${DOWNLOAD_URL:-https://github.com/teamspeak/teamspeak6-server/releases/download/${DOWNLOAD_VERSION}/teamspeak6-server-linux-amd64.tar.xz}"

  VOICE_PORT="${GAME_PORT:-9987}"
  FILETRANSFER_PORT="${FILETRANSFER_PORT:-30033}"
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
      --tags "game;teamspeak"
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
      --tags "game;teamspeak"
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
  msg "Instalando pacotes base no CT"
  run_ct "
    export DEBIAN_FRONTEND=noninteractive
    missing=''
    for pkg in ca-certificates curl xz-utils locales; do
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

setup_panel_access() {
  # Deixa o CT pronto para ser controlado pelo painel administrativo (deploy-admin.ps1),
  # que fala SSH direto com cada container de jogo. Sem PANEL_PUBKEY, nada e instalado.
  [[ -n "${PANEL_PUBKEY:-}" ]] || return 0
  msg "Habilitando acesso do painel administrativo via SSH"
  run_ct "
    set -e
    if ! command -v sshd >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq && apt-get install -y -qq openssh-server
    fi
    systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd
    install -d -m 700 /root/.ssh
    touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
    grep -qF '${PANEL_PUBKEY}' /root/.ssh/authorized_keys \
      || echo '${PANEL_PUBKEY}' >> /root/.ssh/authorized_keys
  "
}

ensure_service_user() {
  msg "Garantindo usuario ${SVC_USER} no CT"
  run_ct "id -u ${SVC_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash ${SVC_USER}"
}

# A versao sem licenca do TeamSpeak usa /dev/shm pra detectar outra instancia rodando
# (shared memory). Sem isso montado o servidor morre com "instance check error" na
# largada. Nao forcamos o mount (pode nao ser permitido num CT nao-privilegiado sem
# nesting) - so avisamos, porque os templates Debian do Proxmox normalmente ja trazem
# /dev/shm montado via systemd.
check_dev_shm() {
  if ! run_ct "mountpoint -q /dev/shm"; then
    warn "/dev/shm nao esta montado como tmpfs dentro do CT. Sem licenca, o TeamSpeak" \
         "pode falhar com 'instance check error'. Veja a secao TeamSpeak 6 do README."
  fi
}

install_teamspeak() {
  local version_file="${GAME_DIR}/.install_version"
  run_ct "install -d -o ${SVC_USER} -g ${SVC_USER} ${GAME_DIR}"

  if run_ct "[ -f '${version_file}' ] && [ \"\$(cat '${version_file}')\" = '${DOWNLOAD_VERSION}' ]"; then
    msg "TeamSpeak ja instalado na versao ${DOWNLOAD_VERSION}, pulando download"
    return
  fi

  msg "Baixando TeamSpeak 6 Server (${DOWNLOAD_VERSION}) - ${DOWNLOAD_URL}"
  run_ct "
    set -e
    tmp=\$(mktemp -d)
    curl -fsSL '${DOWNLOAD_URL}' -o \"\$tmp/teamspeak.tar.xz\"
    tar -xJf \"\$tmp/teamspeak.tar.xz\" -C '${GAME_DIR}'
    rm -rf \"\$tmp\"
    echo '${DOWNLOAD_VERSION}' > '${version_file}'
    chown -R ${SVC_USER}:${SVC_USER} '${GAME_DIR}'
  " || die "Falha baixando/extraindo o TeamSpeak de ${DOWNLOAD_URL}"

  run_ct "test -x '${GAME_DIR}/tsserver'" \
    || die "tsserver nao encontrado em ${GAME_DIR} apos extrair (o layout do pacote mudou?)"
}

render_update_helper() {
  msg "Criando helper de atualizacao (/usr/local/bin/update-game)"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
# Reinstala ${GAME_DISPLAY_NAME} na versao configurada em games/teamspeak.env
# (DOWNLOAD_VERSION=${DOWNLOAD_VERSION}) e reinicia o servico. Para mudar de versao,
# edite games/teamspeak.env e rode o deploy de novo - aqui so reinstala a mesma.
set -Eeuo pipefail
systemctl stop ${SERVICE_NAME} || true
tmp=\$(mktemp -d)
curl -fsSL '${DOWNLOAD_URL}' -o "\$tmp/teamspeak.tar.xz"
tar -xJf "\$tmp/teamspeak.tar.xz" -C '${GAME_DIR}'
rm -rf "\$tmp"
echo '${DOWNLOAD_VERSION}' > '${GAME_DIR}/.install_version'
chown -R ${SVC_USER}:${SVC_USER} '${GAME_DIR}'
systemctl start ${SERVICE_NAME}
echo "Atualizacao concluida (versao ${DOWNLOAD_VERSION})."
EOF
  install_helper "update-game" "$tmp_file"
  rm -f "$tmp_file"

  msg "Sem checagem automatica de update (versao fixada de proposito - TS6 ainda esta em beta)"
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
echo "Atualizacao automatica nao existe para ${GAME_DISPLAY_NAME} (versao fixada)."
echo "Para atualizar: mude DOWNLOAD_VERSION/DOWNLOAD_URL em games/teamspeak.env e rode"
echo "o deploy de novo (.\\deploy-game.ps1 -Game teamspeak), ou rode update-game para"
echo "reinstalar a mesma versao ${DOWNLOAD_VERSION} (reparo)."
EOF
  install_helper "check-game-update" "$tmp_file"
  rm -f "$tmp_file"
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
# Controle do TeamSpeak (${SERVICE_NAME}).
set -Eeuo pipefail
${body}
EOF
    install_helper "$name" "$tmp_file"
  done
  rm -f "$tmp_file"
}

render_systemd_unit() {
  msg "Criando servico systemd ${SERVICE_NAME}"
  local args="license_accepted=1 default_voice_port=${VOICE_PORT} filetransfer_port=${FILETRANSFER_PORT} filetransfer_ip=0.0.0.0,0::0 query_protocols=raw,ssh,http query_port=10011 query_ip=127.0.0.1 query_ssh_port=10022 query_ssh_ip=127.0.0.1 query_http_port=10080 query_http_ip=127.0.0.1"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=${GAME_DISPLAY_NAME}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SVC_USER}
Group=${SVC_USER}
WorkingDirectory=${GAME_DIR}
ExecStart=${GAME_DIR}/tsserver ${args}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/${SERVICE_NAME}" 0644
  rm -f "$tmp_file"
  run_ct "systemctl daemon-reload && systemctl enable ${SERVICE_NAME}"
}

start_service() {
  msg "Iniciando o TeamSpeak"
  run_ct "systemctl restart ${SERVICE_NAME}"
  sleep 8
  if run_ct "systemctl is-active --quiet ${SERVICE_NAME}"; then
    msg "Servico ${SERVICE_NAME} ativo"
  else
    warn "Servico nao esta ativo. Ultimas linhas do log:"
    run_ct "journalctl -u ${SERVICE_NAME} --no-pager -n 40" || true
    die "O TeamSpeak nao subiu. Verifique o log acima."
  fi
}

# O TeamSpeak imprime o token de admin do cliente, o login/senha do ServerQuery e a
# api-key do WebQuery SO no primeiro start de verdade (quando ainda nao existe
# tsserver.sqlitedb) - depois disso ele nunca reemite. Captura pro CREDENTIALS.txt e nao
# sobrescreve num redeploy. Falha aqui e conveniencia perdida, nao motivo pra abortar.
capture_first_run_credentials() {
  local cred_file="${GAME_DIR}/CREDENTIALS.txt"
  if run_ct "[ -s '${cred_file}' ]"; then
    msg "CREDENTIALS.txt ja existe, mantendo"
    return
  fi
  msg "Capturando credenciais do primeiro start"
  run_ct "
    { echo '# Gerado no primeiro start do TeamSpeak - token/senha/apikey so aparecem UMA VEZ.'
      journalctl -u ${SERVICE_NAME} --no-pager -n 300 | grep -E 'token=|loginname=|password=|apikey=' \
        || echo '(nao encontrado no log - confira: pct exec ${CTID} -- journalctl -u ${SERVICE_NAME} -n 300)'
    } > '${cred_file}'
    chown ${SVC_USER}:${SVC_USER} '${cred_file}'
    chmod 600 '${cred_file}'
  " || warn "Nao consegui gravar CREDENTIALS.txt (nao interrompe o deploy)"
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
 Deploy concluido: ${GAME_DISPLAY_NAME} (versao ${DOWNLOAD_VERSION})
========================================================================

Container : CT ${CTID} (${CT_HOSTNAME}) - ${CORES} cores, ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB
IP do CT  : ${CT_IP}
Servico   : ${SERVICE_NAME} (start automatico no boot)

>>> PORTAS PARA REDIRECIONAR NO ROTEADOR (destino ${CT_IP}):
    - ${VOICE_PORT}/udp -> ${CT_IP}   (voz)
    - ${FILETRANSFER_PORT}/tcp -> ${CT_IP}   (transferencia de arquivos)

    Nota: as portas de query (10011 raw, 10022 ssh, 10080 http/WebQuery) ficam so em
    127.0.0.1 dentro do CT - NAO redirecione nenhuma delas no roteador.

Arquivos do jogo : ${GAME_DIR}
Credenciais      : ${GAME_DIR}/CREDENTIALS.txt (pct exec ${CTID} -- cat ${GAME_DIR}/CREDENTIALS.txt)
                    token de admin do cliente, login/senha do ServerQuery e api-key do
                    WebQuery - o TeamSpeak so mostra isso UMA VEZ, leia antes de perder.
Sem licenca paga : 1 virtual server, ate 32 slots.

Atalhos (funcionam logado no CT via 'pct enter ${CTID}' ou pelo host com 'pct exec ${CTID} -- <atalho>'):
  game-restart      # reinicia o servidor
  game-stop         # para o servidor
  game-start        # sobe o servidor
  game-status       # status do servico
  game-logs         # log ao vivo (aceita args do journalctl, ex.: game-logs -n 50)
  update-game       # reinstala a versao ${DOWNLOAD_VERSION} e reinicia (reparo)

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
  setup_panel_access
  ensure_service_user
  check_dev_shm
  install_teamspeak
  render_update_helper
  render_service_helpers
  render_systemd_unit
  start_service
  capture_first_run_credentials
  print_summary
}

main "$@"
