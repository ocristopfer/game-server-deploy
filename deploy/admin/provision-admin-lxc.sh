#!/usr/bin/env bash
# Creates/updates the container of the game servers' admin panel.
# Run ON THE PROXMOX HOST by deploy-admin.ps1 (which sends this bundle via scp).
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_ENV_FILE="${ADMIN_ENV_FILE:-$SCRIPT_DIR/admin.env}"
RELEASE_ENV_FILE="${RELEASE_ENV_FILE:-$SCRIPT_DIR/release.env}"
INSTALLER="${INSTALLER:-$SCRIPT_DIR/install-release.sh}"

APP_DIR=/opt/gamepanel
SERVICE_NAME=gamepanel.service
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
  # Without a password the CT root stays LOCKED (you get in via `pct enter` or the SSH key).
  # The default used to be "changeme": every CT was born with the same well-known console password.
  CT_PASSWORD="${CT_PASSWORD:-}"
  TZ="${TZ:-America/Sao_Paulo}"

  MEMORY="${ADMIN_MEMORY:-512}"
  CORES="${ADMIN_CORES:-1}"
  ROOTFS_SIZE_GB="${ADMIN_DISK_GB:-4}"
  SWAP="${ADMIN_SWAP:-256}"

  PANEL_PORT="${ADMIN_PORT:-8080}"
  PANEL_USER="${ADMIN_USER:-admin}"
  PANEL_PASSWORD="${ADMIN_PASSWORD:-}"
  ALLOW_SHELL="${ADMIN_ALLOW_SHELL:-1}"
  # Interactive terminal (uses the same ALLOW_SHELL) and config file editor.
  ALLOW_FILES="${ADMIN_ALLOW_FILES:-1}"
  # 1 = every user must have the second factor (2FA) to use the panel. Turn it on AFTER every
  # admin has enabled theirs in Account: turning it on before locks everyone out.
  REQUIRE_2FA="${ADMIN_REQUIRE_2FA:-0}"
  # https address (with a domain) the panel is opened through; empty = no biometric login.
  # The panel checks the format at start and, if it is bad, refuses to start, naming the variable.
  WEBAUTHN_ORIGIN="${ADMIN_WEBAUTHN_ORIGIN:-}"
  # Screen language for whoever has not chosen one in Account YET, AND for what goes out through
  # the webhook (there is a single channel: the message cannot switch language based on who clicked).
  LANG_PADRAO="${ADMIN_LANG:-pt}"
  FILE_MAX_KB="${ADMIN_FILE_MAX_KB:-4096}"
  FILE_PREVIEW_KB="${ADMIN_FILE_PREVIEW_KB:-256}"
  FILE_DOWNLOAD_MAX_MB="${ADMIN_FILE_DOWNLOAD_MAX_MB:-2048}"
  FILE_ROOTS="${ADMIN_FILE_ROOTS:-/opt/game,/home/steam}"
  FILE_DEFAULT="${ADMIN_FILE_DEFAULT:-/opt/game}"
  TERM_MAX="${ADMIN_TERM_MAX:-4}"
  TERM_IDLE="${ADMIN_TERM_IDLE:-900}"
  METRICS_TTL="${ADMIN_METRICS_TTL:-4}"
  QUERY_TIMEOUT="${ADMIN_QUERY_TIMEOUT:-3}"
  PLAYERS_TTL="${ADMIN_PLAYERS_TTL:-5}"
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
  # The bundle carries ONE release tarball and the installer that unpacks it on the other side.
  # There used to be a list of package files here (app.py, templates/base.html, static/js/
  # app.js...) that had to grow along with the code and never did: it checked the
  # first level and let a whole new folder slip by. What checks the content now is the
  # artifact's sha256.
  [[ -f "$RELEASE_ENV_FILE" ]] || die "release.env nao encontrado: $RELEASE_ENV_FILE (rode pelo deploy-admin.ps1)"
  [[ -f "$INSTALLER" ]] || die "install-release.sh nao encontrado: $INSTALLER"
  load_env_file "$RELEASE_ENV_FILE"
  [[ -n "${RELEASE_TARBALL:-}" ]] || die "RELEASE_TARBALL vazio em $RELEASE_ENV_FILE"
  [[ -n "${RELEASE_SHA256:-}" ]] || die "RELEASE_SHA256 vazio em $RELEASE_ENV_FILE"
  [[ -f "$SCRIPT_DIR/$RELEASE_TARBALL" ]] || die "release nao encontrado no bundle: $RELEASE_TARBALL"
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
      ${CT_PASSWORD:+--password "$CT_PASSWORD"} \
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
  # Without network apt fails with an error far less clear than this one.
  waited=0
  until run_ct "getent hosts deb.debian.org >/dev/null 2>&1"; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 60 ]] || die "CT $CTID sem resolucao DNS/rede apos 60s"
  done
}

install_packages() {
  # openssh-server is for reaching the panel from outside: it is what allows updating the code
  # straight from Windows (deploy-admin.ps1 without -Full), without going through Proxmox.
  msg "Instalando dependencias no CT (python3-flask, gunicorn, openssh-client/server)"
  run_ct "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && \
    apt-get install -y -qq python3 python3-flask gunicorn openssh-client openssh-server \
    wget \
    ca-certificates tar gzip"
}

ensure_app_user() {
  run_ct "id ${APP_USER} >/dev/null 2>&1 || useradd --system --home-dir ${APP_DIR} --shell /usr/sbin/nologin ${APP_USER}"
  run_ct "install -d -o ${APP_USER} -g ${APP_USER} -m 0750 ${DATA_DIR} ${CONF_DIR}"
  run_ct "install -d -o root -g root -m 0755 ${APP_DIR}"
}

publish_release() {
  msg "Publicando o release ${RELEASE_TARBALL} em ${APP_DIR}"
  local remote_tmp=/tmp/gamepanel-release

  run_ct "rm -rf '$remote_tmp' && install -d '$remote_tmp'"
  # pct push, and not push_file_to_ct's `tee`: the tarball is binary and has to arrive byte
  # for byte -- and the sha256 on the other side does not forgive a single swapped byte.
  pct push "$CTID" "$SCRIPT_DIR/$RELEASE_TARBALL" "${remote_tmp}/${RELEASE_TARBALL}" --perms 0644
  pct push "$CTID" "$INSTALLER" "${remote_tmp}/install-release.sh" --perms 0755

  # The probe GOES here: the unit and panel.env have already been written (see the comment in main),
  # so the restart the installer does brings up the NEW code and the probe's answer means
  # something. While the unit came afterwards, the installer only found a nonexistent service and
  # just left the release in place -- its rollback was never exercised. On a
  # new CT the database still has no user at this point, and that does not get in the way: /health
  # does not depend on a session.
  run_ct "bash '${remote_tmp}/install-release.sh' gamepanel \
'${remote_tmp}/${RELEASE_TARBALL}' '${RELEASE_SHA256}' ${APP_DIR} ${SERVICE_NAME} \
'wget -q -O /dev/null http://127.0.0.1:${PANEL_PORT}/health'" \
    || die "A instalacao do release falhou dentro do CT (veja a saida acima)"
  run_ct "rm -rf '$remote_tmp'"

  # Failing here is better than the service dying at start with ModuleNotFoundError.
  run_ct "cd ${APP_DIR}/current && python3 -c 'import gamepanel.app'" \
    || die "O pacote do painel nao importa no CT a partir de ${APP_DIR}/current"
  # || true inside the $(...): without it `set -e` kills the script here and the reason
  # never gets printed.
  msg "No ar: $(run_ct "readlink ${APP_DIR}/current" | tr -d '\r' || true)"
}

ensure_ssh_key() {
  msg "Preparando a chave SSH do painel"
  # The key is from the panel to the GAME CONTAINERS. The panel gets no key at all
  # for the Proxmox host: it never talks to the hypervisor.
  run_ct "test -f ${CONF_DIR}/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'gamepanel@${CT_HOSTNAME}' -f ${CONF_DIR}/id_ed25519 >/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/id_ed25519 ${CONF_DIR}/id_ed25519.pub && chmod 0600 ${CONF_DIR}/id_ed25519"
  # known_hosts lives in DATA_DIR because it must be writable: the containers' host keys
  # are learned on first access (StrictHostKeyChecking=accept-new).
  run_ct "touch ${DATA_DIR}/known_hosts && chown ${APP_USER}:${APP_USER} ${DATA_DIR}/known_hosts && chmod 0644 ${DATA_DIR}/known_hosts"

  PANEL_PUBKEY="$(pct exec "$CTID" -- cat "${CONF_DIR}/id_ed25519.pub" | tr -d '\r\n')"
  [[ -n "$PANEL_PUBKEY" ]] || die "Nao consegui ler a chave publica do painel"
}

enable_direct_deploy() {
  # Authorizes the operator's key on the panel CT. With it, the next deploy sends the
  # files straight over scp and does not even touch Proxmox.
  local pubkey="${ADMIN_SSH_PUBKEY:-}"
  run_ct "systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true"
  # Key only: the CT is born with a root password known from the .env.
  run_ct "sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config && \
    systemctl reload ssh >/dev/null 2>&1 || true"

  if [[ -z "$pubkey" ]]; then
    warn "ADMIN_SSH_PUBKEY vazio: o envio direto para o CT nao vai funcionar"
    return 0
  fi
  msg "Autorizando sua chave SSH no CT do painel (para o envio direto)"
  run_ct "install -d -m 700 /root/.ssh && touch /root/.ssh/authorized_keys && \
    chmod 600 /root/.ssh/authorized_keys && \
    grep -qF '${pubkey}' /root/.ssh/authorized_keys || echo '${pubkey}' >> /root/.ssh/authorized_keys"
}

render_panel_config() {
  msg "Gravando configuracao do painel"
  local tmp_file preserved
  tmp_file="$(mktemp)"
  # The broker writes the GAMEPANEL_*BROKER* lines into this file (deploy-broker.ps1
  # -ConfigurePanel), and this script rewrites the WHOLE file: without saving those lines first,
  # every full panel deploy silently turned the broker off.
  preserved="$(pct exec "$CTID" -- sh -c "grep -E '^GAMEPANEL_(BROKER_|ALLOW_BROKER)' ${CONF_DIR}/panel.env 2>/dev/null || true" | tr -d '\r')"
  cat > "$tmp_file" <<EOF
GAMEPANEL_DB=${DATA_DIR}/panel.db
GAMEPANEL_SECRET_FILE=${CONF_DIR}/secret_key
GAMEPANEL_SSH_KEY=${CONF_DIR}/id_ed25519
GAMEPANEL_KNOWN_HOSTS=${DATA_DIR}/known_hosts
GAMEPANEL_PORT=${PANEL_PORT}
GAMEPANEL_ALLOW_SHELL=${ALLOW_SHELL}
GAMEPANEL_TERM_MAX=${TERM_MAX}
GAMEPANEL_TERM_IDLE=${TERM_IDLE}
GAMEPANEL_METRICS_TTL=${METRICS_TTL}
GAMEPANEL_QUERY_TIMEOUT=${QUERY_TIMEOUT}
GAMEPANEL_PLAYERS_TTL=${PLAYERS_TTL}
GAMEPANEL_ALLOW_FILES=${ALLOW_FILES}
GAMEPANEL_FILE_MAX=$((FILE_MAX_KB * 1024))
GAMEPANEL_FILE_PREVIEW=$((FILE_PREVIEW_KB * 1024))
GAMEPANEL_FILE_DOWNLOAD_MAX=$((FILE_DOWNLOAD_MAX_MB * 1024 * 1024))
GAMEPANEL_FILE_ROOTS=${FILE_ROOTS}
GAMEPANEL_FILE_DEFAULT=${FILE_DEFAULT}
GAMEPANEL_REQUIRE_2FA=${REQUIRE_2FA}
GAMEPANEL_WEBAUTHN_ORIGIN=${WEBAUTHN_ORIGIN}
GAMEPANEL_LANG=${LANG_PADRAO}
EOF
  [[ -z "$preserved" ]] || printf '%s\n' "$preserved" >> "$tmp_file"
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
  # The import root is ${APP_DIR}/current, never ${APP_DIR}: since releases became one
  # folder per version the package lives in releases/<version>/gamepanel, and ${APP_DIR} holds
  # only the symlink. Pointed at ${APP_DIR} the import fails and set -e kills the script HERE
  # - with the release already published and BEFORE render_service, meaning the panel comes back
  # up through the OLD unit with the old code, and the summary never even says that half
  # of the deploy was missing.
  # The password goes through stdin (not the command line) so it does not leak in the CT's ps.
  printf '%s' "$PANEL_PASSWORD" | pct exec "$CTID" -- env \
    GAMEPANEL_DB="${DATA_DIR}/panel.db" \
    GAMEPANEL_SECRET_FILE="${CONF_DIR}/secret_key" \
    python3 -c "
import sys
sys.path.insert(0, '${APP_DIR}/current')
from gamepanel import app as panel
panel.ensure_admin_user('${PANEL_USER}', sys.stdin.read())
"
  run_ct "chown -R ${APP_USER}:${APP_USER} ${DATA_DIR} && chown ${APP_USER}:${APP_USER} ${CONF_DIR}/secret_key && chmod 0600 ${CONF_DIR}/secret_key"
}

render_service() {
  msg "Criando o servico systemd ${SERVICE_NAME}"
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
# The current release, via symlink: switching versions (or going back) is moving the link and
# restarting. systemd resolves the path at start, so every restart picks up what the
# link points to NOW.
WorkingDirectory=${APP_DIR}/current
EnvironmentFile=${CONF_DIR}/panel.env
# A single worker: terminal sessions live in the process memory, and with two
# workers half of the requests would land on the process that does not have the session. The threads
# sustain the terminal long-polls (one per open tab) on top of the normal screens.
ExecStart=/usr/bin/gunicorn --workers 1 --threads 16 --timeout 120 \\
  --bind 0.0.0.0:${PANEL_PORT} --access-logfile - gamepanel.wsgi:app
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/${SERVICE_NAME}" 0644
  rm -f "$tmp_file"
  run_ct "systemctl daemon-reload && systemctl enable ${SERVICE_NAME}"
}

start_panel() {
  msg "Subindo o painel"
  run_ct "systemctl restart ${SERVICE_NAME}"
  sleep 5
  if ! run_ct "systemctl is-active --quiet ${SERVICE_NAME}"; then
    warn "O painel nao ficou ativo. Ultimas linhas do log:"
    run_ct "journalctl -u gamepanel.service --no-pager -n 40" || true
    die "gamepanel.service nao subiu"
  fi
}

authorize_in_game_cts() {
  # Optional bootstrap: prepares the game containers to accept the panel.
  # Runs here (on the host, during the deploy) because only the host can get into the CTs without
  # prior SSH - the panel itself never has access to the hypervisor.
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
IP do container e o servico (ex.: 10.20.1.20, dragonwilds.service). Preencha tambem a
"Pasta de configuracao" (ex.: /opt/game) para a tela Arquivos abrir no lugar certo, e a
"Porta de consulta" (Palworld: 27015) para o painel contar os jogadores online.

Cada servidor tem tres formas de mexer no container:
  Terminal  - shell interativo de verdade (htop, nano, prompts) direto no navegador
  Arquivos  - editor de texto dos .ini/.cfg do jogo, com backup .bak automatico
  Console   - um comando por vez, com o resultado gravado no historico

Comandos uteis (no host Proxmox):
  pct exec ${CTID} -- systemctl status gamepanel.service --no-pager
  pct exec ${CTID} -- journalctl -u gamepanel.service -f

Proximos deploys: com o CT ja criado, .\\deploy-admin.ps1 manda o codigo direto para
ele por SSH (segundos, sem tocar no Proxmox). Use -Full para mexer no CT em si
(recursos, rede, senha do painel) ou recriar.

EOF
}

# Firewall inside the panel CT (lib/ct-firewall.sh, role "panel"): the web and SSH only
# serve the administration network (ADMIN_FIREWALL_SOURCES, default the whole local network).
# Outbound stays open: the panel talks to the games, the broker and the webhook (Discord).
#
# After `start_panel`: its health probe uses 127.0.0.1, which the firewall always lets
# through. The proof that the NETWORK still gets in is done here, from the host - and if it does not,
# the firewall comes off, instead of a live panel that nobody can reach.
apply_panel_firewall() {
  if [[ "${CT_FIREWALL:-1}" == "0" ]]; then
    warn "CT_FIREWALL=0: o CT do painel fica SEM firewall interno"
    return 0
  fi
  local sources="${ADMIN_FIREWALL_SOURCES:-192.168.0.0/16}" conf ip
  msg "Aplicando o firewall do CT do painel (nftables): web e SSH so de ${sources}"
  modprobe nf_tables 2>/dev/null || warn "nao consegui carregar o modulo nf_tables no host"
  { mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
    || warn "nao consegui deixar o nf_tables carregando no boot do host"
  conf="$(mktemp)"
  {
    printf 'FW_ROLE=panel\n'
    printf 'FW_ADMIN_SOURCES="%s"\n' "$sources"
    printf 'FW_PANEL_PORT="%s"\n' "$PANEL_PORT"
  } > "$conf"
  push_file_to_ct "$SCRIPT_DIR/ct-firewall.sh" /usr/local/sbin/ct-firewall 0755
  push_file_to_ct "$conf" /etc/ct-firewall.env 0644
  rm -f "$conf"
  run_ct "/usr/local/sbin/ct-firewall apply" || die "o firewall do painel nao carregou (nada foi alterado nele)"
  ip="$(run_ct "hostname -I | awk '{print \$1}'" | tr -d '\r \n' || true)"
  [[ -n "$ip" ]] || return 0
  # The host is usually on the administration network. If it cannot reach the panel web, either the
  # list is wrong or the host is outside it: in both cases, better open and warned.
  if ! timeout 5 bash -c "</dev/tcp/${ip}/${PANEL_PORT}" 2>/dev/null; then
    run_ct "/usr/local/sbin/ct-firewall off"
    warn "O host nao alcancou ${ip}:${PANEL_PORT} com o firewall ligado: ele foi DESLIGADO. Confira ADMIN_FIREWALL_SOURCES (${sources}) e religue com: pct exec ${CTID} -- ct-firewall apply"
  fi
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
  ensure_ssh_key
  enable_direct_deploy
  render_panel_config
  render_service
  # The config and the unit go BEFORE publishing, and the order matters: it is `install-release.sh`
  # that restarts the service and runs the health probe, and it runs inside the publish. With the
  # unit written afterwards, the probe tested the WRONG pair -- old unit with new code --
  # and its result meant nothing:
  #
  #   - if the old unit called something the new code no longer has (that was the case, with
  #     `gamebroker.wsgi:criar_app_de_ambiente()`), the probe fails, install-release
  #     rolls back and the script dies HERE, right before the step that would fix the unit.
  #     The deploy is stuck: there is no way to reach the new unit;
  #   - and if the old layout were still importable, the probe PASSES against the old
  #     code and the deploy declares itself successful without having changed anything.
  #
  # In this order the probe sees new unit, new env and new code, and its rollback goes back
  # to a state that actually worked.
  publish_release
  # After the publish on purpose: imports `gamepanel` from ${APP_DIR}/current, which only
  # exists from that point on. The schema migrations run on this import -- and with the unit
  # already right, whoever runs them is the NEW process, which is already serving. In the old order the
  # old process stayed up with SQL in Portuguese while the database had already been
  # renamed, and it spewed `no such column: nome` for a few seconds.
  bootstrap_admin_user
  start_panel
  apply_panel_firewall
  authorize_in_game_cts
  print_summary
}

main "$@"
