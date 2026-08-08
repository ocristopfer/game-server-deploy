#!/usr/bin/env bash
# Cria/atualiza o container do painel administrativo dos servidores de jogos.
# Executado NO HOST PROXMOX pelo deploy-admin.ps1 (que envia este bundle via scp).
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_ENV_FILE="${ADMIN_ENV_FILE:-$SCRIPT_DIR/admin.env}"
APP_SRC_DIR="${APP_SRC_DIR:-$SCRIPT_DIR/admin}"

APP_DIR=/opt/gamepanel
CONF_DIR=/etc/gamepanel
DATA_DIR=/var/lib/gamepanel
APP_USER=gamepanel

msg() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Comando obrigatorio ausente: $1"; }

run_ct() { pct exec "$CTID" -- bash -lc "$1"; }

push_file_to_ct() {
  local src="$1" dest="$2" mode="${3:-0644}"
  run_ct "install -d '$(dirname "$dest")'"
  pct exec "$CTID" -- tee "$dest" >/dev/null < "$src"
  run_ct "chmod ${mode} '$dest'"
}

load_env_file() {
  [[ -f "$1" ]] || die "Arquivo de ambiente nao encontrado: $1"
  set -a
  # shellcheck disable=SC1090
  source "$1"
  set +a
}

resolve_variables() {
  CTID="${ADMIN_CTID:-}"
  [[ -n "$CTID" ]] || die "ADMIN_CTID nao definido"
  [[ "$CTID" =~ ^[0-9]+$ ]] || die "ADMIN_CTID deve ser numerico: $CTID"

  CT_HOSTNAME="${ADMIN_HOSTNAME:-gamepanel}"
  STORAGE="${STORAGE:-local-zfs}"
  TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
  TEMPLATE_PATTERN="${TEMPLATE_PATTERN:-debian-13-standard_.*_amd64\.tar\.zst}"
  BRIDGE="${BRIDGE:-vmbr0}"
  IP_CIDR="${ADMIN_IP_CIDR:-dhcp}"
  GATEWAY="${ADMIN_GATEWAY:-${GATEWAY:-}}"
  CT_PASSWORD="${CT_PASSWORD:-changeme}"
  TZ="${TZ:-America/Sao_Paulo}"

  MEMORY="${ADMIN_MEMORY:-512}"
  CORES="${ADMIN_CORES:-1}"
  ROOTFS_SIZE_GB="${ADMIN_DISK_GB:-4}"
  SWAP="${ADMIN_SWAP:-256}"

  PANEL_PORT="${ADMIN_PORT:-8080}"
  PANEL_USER="${ADMIN_USER:-admin}"
  PANEL_PASSWORD="${ADMIN_PASSWORD:-}"
  ALLOW_SHELL="${ADMIN_ALLOW_SHELL:-1}"
  RECREATE_CT="${RECREATE_ADMIN_CT:-0}"

  if [[ "$IP_CIDR" == "dhcp" ]]; then
    NET0="name=eth0,bridge=${BRIDGE},ip=dhcp,type=veth"
  else
    [[ -n "$GATEWAY" ]] || die "ADMIN_GATEWAY obrigatorio quando ADMIN_IP_CIDR nao e dhcp"
    NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY},type=veth"
  fi
}

validate_host_requirements() {
  need_cmd pct
  need_cmd pveam
  [[ -d "$APP_SRC_DIR" ]] || die "Diretorio da aplicacao nao encontrado: $APP_SRC_DIR"
  [[ -f "$APP_SRC_DIR/app.py" ]] || die "app.py nao encontrado em $APP_SRC_DIR"
  # Sem estes o painel sobe e so quebra no navegador com 'TemplateNotFound'.
  [[ -f "$APP_SRC_DIR/templates/login.html" ]] || die "templates/ ausente ou incompleto em $APP_SRC_DIR"
  [[ -f "$APP_SRC_DIR/templates/base.html" ]] || die "templates/base.html nao encontrado em $APP_SRC_DIR"
  [[ -f "$APP_SRC_DIR/static/style.css" ]] || die "static/style.css nao encontrado em $APP_SRC_DIR"
}

ensure_debian_template() {
  if pct status "$CTID" >/dev/null 2>&1 && [[ "$RECREATE_CT" != "1" ]]; then
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
  pct status "$CTID" >/dev/null 2>&1 && ct_exists=1

  if [[ "$ct_exists" -eq 1 && "$RECREATE_CT" == "1" ]]; then
    msg "Recriando CT $CTID (RECREATE_ADMIN_CT=1)"
    pct stop "$CTID" >/dev/null 2>&1 || true
    pct destroy "$CTID" --destroy-unreferenced-disks 1
    ct_exists=0
  fi

  if [[ "$ct_exists" -eq 0 ]]; then
    msg "Criando CT $CTID ($CT_HOSTNAME) - ${CORES} core(s), ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB"
    pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" \
      --arch amd64 \
      --hostname "$CT_HOSTNAME" \
      --cores "$CORES" \
      --memory "$MEMORY" \
      --swap "$SWAP" \
      --rootfs "${STORAGE}:${ROOTFS_SIZE_GB}" \
      --ostype debian \
      --unprivileged 1 \
      --features nesting=1 \
      --net0 "$NET0" \
      --password "$CT_PASSWORD" \
      --onboot 1 \
      --timezone "$TZ" \
      --tags "admin;gamepanel"
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
      --tags "admin;gamepanel"
  fi
}

start_container() {
  if ! pct status "$CTID" 2>/dev/null | grep -q running; then
    msg "Iniciando CT $CTID"
    pct start "$CTID"
  fi
  local waited=0
  until pct exec "$CTID" -- true >/dev/null 2>&1; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 120 ]] || die "CT $CTID nao respondeu em 120s"
  done
  # Sem rede o apt falha com um erro bem menos claro do que este.
  waited=0
  until run_ct "getent hosts deb.debian.org >/dev/null 2>&1"; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 60 ]] || die "CT $CTID sem resolucao DNS/rede apos 60s"
  done
}

install_packages() {
  msg "Instalando dependencias no CT (python3-flask, gunicorn, openssh-client)"
  run_ct "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && \
    apt-get install -y -qq python3 python3-flask gunicorn openssh-client ca-certificates tar gzip"
}

ensure_app_user() {
  run_ct "id ${APP_USER} >/dev/null 2>&1 || useradd --system --home-dir ${APP_DIR} --shell /usr/sbin/nologin ${APP_USER}"
  run_ct "install -d -o ${APP_USER} -g ${APP_USER} -m 0750 ${DATA_DIR} ${CONF_DIR}"
  run_ct "install -d -o root -g root -m 0755 ${APP_DIR}"
}

push_application() {
  msg "Publicando a aplicacao em ${APP_DIR}"
  run_ct "rm -rf ${APP_DIR}/templates ${APP_DIR}/static"
  run_ct "install -d ${APP_DIR}/templates ${APP_DIR}/static"

  # pct push copia arquivo a arquivo. E mais lento que mandar um tar.gz pelo stdin do
  # 'pct exec', mas deterministico: aquele stream binario podia nao ser entregue, o tar
  # do outro lado extraia zero arquivos e ainda assim saia com 0 — o deploy passava e o
  # painel so quebrava em runtime com 'TemplateNotFound'.
  local src
  pct push "$CTID" "$APP_SRC_DIR/app.py" "${APP_DIR}/app.py" --perms 0644
  for src in "$APP_SRC_DIR"/templates/*.html; do
    [[ -f "$src" ]] || continue
    pct push "$CTID" "$src" "${APP_DIR}/templates/$(basename "$src")" --perms 0644
  done
  for src in "$APP_SRC_DIR"/static/*; do
    [[ -f "$src" ]] || continue
    pct push "$CTID" "$src" "${APP_DIR}/static/$(basename "$src")" --perms 0644
  done
  run_ct "chown -R root:root ${APP_DIR}"

  # Falhar aqui e melhor do que descobrir pela tela de erro do navegador.
  run_ct "test -f ${APP_DIR}/templates/base.html && test -f ${APP_DIR}/templates/login.html && test -f ${APP_DIR}/static/style.css" \
    || die "Templates/estaticos nao chegaram em ${APP_DIR} (veja a saida do pct push acima)"
  msg "Publicados: $(run_ct "ls ${APP_DIR}/templates | wc -l" | tr -d '\r') templates"
}

ensure_ssh_key() {
  msg "Preparando a chave SSH do painel"
  # A chave e do painel para os CONTAINERS DE JOGO. O painel nao recebe nenhuma chave
  # para o host Proxmox: ele nao fala com o hipervisor em momento algum.
  run_ct "test -f ${CONF_DIR}/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'gamepanel@${CT_HOSTNAME}' -f ${CONF_DIR}/id_ed25519 >/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/id_ed25519 ${CONF_DIR}/id_ed25519.pub && chmod 0600 ${CONF_DIR}/id_ed25519"
  # known_hosts fica em DATA_DIR porque precisa ser gravavel: as host keys dos
  # containers sao aprendidas no primeiro acesso (StrictHostKeyChecking=accept-new).
  run_ct "touch ${DATA_DIR}/known_hosts && chown ${APP_USER}:${APP_USER} ${DATA_DIR}/known_hosts && chmod 0644 ${DATA_DIR}/known_hosts"

  PANEL_PUBKEY="$(pct exec "$CTID" -- cat "${CONF_DIR}/id_ed25519.pub" | tr -d '\r\n')"
  [[ -n "$PANEL_PUBKEY" ]] || die "Nao consegui ler a chave publica do painel"
}

render_panel_config() {
  msg "Gravando configuracao do painel"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
GAMEPANEL_DB=${DATA_DIR}/panel.db
GAMEPANEL_SECRET_FILE=${CONF_DIR}/secret_key
GAMEPANEL_SSH_KEY=${CONF_DIR}/id_ed25519
GAMEPANEL_KNOWN_HOSTS=${DATA_DIR}/known_hosts
GAMEPANEL_PORT=${PANEL_PORT}
GAMEPANEL_ALLOW_SHELL=${ALLOW_SHELL}
EOF
  push_file_to_ct "$tmp_file" "${CONF_DIR}/panel.env" 0640
  rm -f "$tmp_file"
  run_ct "chown root:${APP_USER} ${CONF_DIR}/panel.env"
}

bootstrap_admin_user() {
  if [[ -z "$PANEL_PASSWORD" ]]; then
    PANEL_PASSWORD="$(head -c 12 /dev/urandom | base64 | tr -d '/+=' | cut -c1-14)"
    GENERATED_PASSWORD=1
    warn "ADMIN_PASSWORD nao definido - uma senha foi gerada e sera exibida no resumo"
  fi
  msg "Criando/atualizando o usuario '${PANEL_USER}' do painel"
  # A senha vai por stdin (nao pela linha de comando) para nao vazar no ps do CT.
  printf '%s' "$PANEL_PASSWORD" | pct exec "$CTID" -- env \
    GAMEPANEL_DB="${DATA_DIR}/panel.db" \
    GAMEPANEL_SECRET_FILE="${CONF_DIR}/secret_key" \
    python3 -c "
import os, sys
sys.path.insert(0, '${APP_DIR}')
import app as panel
panel.ensure_admin_user('${PANEL_USER}', sys.stdin.read())
"
  run_ct "chown -R ${APP_USER}:${APP_USER} ${DATA_DIR} && chown ${APP_USER}:${APP_USER} ${CONF_DIR}/secret_key && chmod 0600 ${CONF_DIR}/secret_key"
}

render_service() {
  msg "Criando o servico systemd gamepanel.service"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=Painel administrativo dos servidores de jogos
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${CONF_DIR}/panel.env
ExecStart=/usr/bin/gunicorn --workers 1 --threads 8 --timeout 120 \\
  --bind 0.0.0.0:${PANEL_PORT} --access-logfile - app:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/gamepanel.service" 0644
  rm -f "$tmp_file"
  run_ct "systemctl daemon-reload && systemctl enable gamepanel.service"
}

start_panel() {
  msg "Subindo o painel"
  run_ct "systemctl restart gamepanel.service"
  sleep 5
  if ! run_ct "systemctl is-active --quiet gamepanel.service"; then
    warn "O painel nao ficou ativo. Ultimas linhas do log:"
    run_ct "journalctl -u gamepanel.service --no-pager -n 40" || true
    die "gamepanel.service nao subiu"
  fi
}

authorize_in_game_cts() {
  # Bootstrap opcional: prepara os containers de jogo para receber o painel.
  # Roda aqui (no host, durante o deploy) porque so o host consegue entrar nos CTs sem
  # SSH previo - o painel em si nunca tem acesso ao hipervisor.
  local raw="${ADMIN_AUTHORIZE_CTIDS:-}"
  [[ -n "$raw" ]] || return 0

  local target
  for target in ${raw//,/ }; do
    if [[ ! "$target" =~ ^[0-9]+$ ]]; then
      warn "ADMIN_AUTHORIZE_CTIDS: ignorando valor nao numerico '$target'"
      continue
    fi
    if ! pct status "$target" >/dev/null 2>&1; then
      warn "CT $target nao existe; pulando"
      continue
    fi
    msg "Autorizando o painel no CT $target"
    pct start "$target" >/dev/null 2>&1 || true
    if ! pct exec "$target" -- true >/dev/null 2>&1; then
      warn "CT $target nao respondeu; pulando"
      continue
    fi
    pct exec "$target" -- bash -lc "
      set -e
      command -v sshd >/dev/null 2>&1 || {
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq && apt-get install -y -qq openssh-server
      }
      systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd
      install -d -m 700 /root/.ssh
      touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
      grep -qF '${PANEL_PUBKEY}' /root/.ssh/authorized_keys \
        || echo '${PANEL_PUBKEY}' >> /root/.ssh/authorized_keys
    " || warn "Falha ao autorizar o painel no CT $target (faca manualmente pela tela 'Acesso SSH')"
    AUTHORIZED_CTS="${AUTHORIZED_CTS:-} $target"
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
 Painel administrativo pronto
========================================================================

Container : CT ${CTID} (${CT_HOSTNAME}) - ${CORES} core(s), ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB
Acesse em : http://${CT_IP}:${PANEL_PORT}
Usuario   : ${PANEL_USER}
EOF
  if [[ "${GENERATED_PASSWORD:-0}" == "1" ]]; then
    cat <<EOF
Senha     : ${PANEL_PASSWORD}
            ^ senha gerada automaticamente - anote agora e troque em "Conta" apos entrar
EOF
  else
    echo "Senha     : a definida em ADMIN_PASSWORD no .env"
  fi
  cat <<EOF

O painel controla os servidores por SSH direto nos containers de jogo - ele nao tem
acesso nenhum ao host Proxmox.

Chave publica do painel (autorize nos containers de jogo):
  ${PANEL_PUBKEY}
EOF
  if [[ -n "${AUTHORIZED_CTS:-}" ]]; then
    echo "  ja autorizada automaticamente nos CTs:${AUTHORIZED_CTS}"
  else
    cat <<EOF

Para autorizar num container de jogo (a partir deste host):
  pct exec <CTID> -- bash -lc "apt-get update -qq && apt-get install -y -qq openssh-server && \\
    systemctl enable --now ssh && install -d -m 700 /root/.ssh && \\
    echo '${PANEL_PUBKEY}' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys"

  Ou preencha ADMIN_AUTHORIZE_CTIDS no .env e rode o deploy do painel de novo.
EOF
  fi
  cat <<EOF

Proximo passo: entre no painel e cadastre seus servidores em "Adicionar", informando o
IP do container e o servico (ex.: 192.168.2.20, dragonwilds.service).

Comandos uteis (no host Proxmox):
  pct exec ${CTID} -- systemctl status gamepanel.service --no-pager
  pct exec ${CTID} -- journalctl -u gamepanel.service -f

EOF
}

main() {
  load_env_file "$ADMIN_ENV_FILE"
  resolve_variables
  validate_host_requirements
  ensure_debian_template
  ensure_container
  start_container
  install_packages
  ensure_app_user
  push_application
  ensure_ssh_key
  render_panel_config
  bootstrap_admin_user
  render_service
  start_panel
  authorize_in_game_cts
  print_summary
}

main "$@"
