#!/usr/bin/env bash
# Creates/updates the BROKER container (creates game instances on Proxmox and opens ports on OPNsense).
# Run ON THE PROXMOX HOST by deploy-broker.ps1 (which sends this bundle via scp).
#
# Bundle (folder without config subfolders, only what scp carries):
#   broker.conf.env      NON-secret configuration (CT, network, ranges, quotas)
#   broker.secrets.env   Proxmox and OPNsense (token, key, secret)  -> 0600, deleted at the end
#   gamebroker/  lib/  games/   the code, the installers and the curated catalog
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_ENV_FILE="${CONF_ENV_FILE:-$SCRIPT_DIR/broker.conf.env}"
SECRETS_ENV_FILE="${SECRETS_ENV_FILE:-$SCRIPT_DIR/broker.secrets.env}"

APP_DIR=/opt/gamebroker
SERVICE_NAME=gamebroker.service
RELEASE_ENV_FILE="${RELEASE_ENV_FILE:-$SCRIPT_DIR/release.env}"
INSTALLER="${INSTALLER:-$SCRIPT_DIR/install-release.sh}"
CONF_DIR=/etc/gamebroker
DATA_DIR=/var/lib/gamebroker
APP_USER=gamebroker
# Modules kept OUT of the production CT: test doubles and the compose toy broker.
DO_NOT_SHIP='^(test_.*|conftest|fakes|fake_http|dev)\.py$'

msg() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

# Without this a failure inside $(...) ends the script silently (set -e + pipefail): the `die`
# with the explanation, right after it, never gets to run. BASH_COMMAND is the command text BEFORE
# expansion, so no secret shows up here.
on_error() { die "Provisionamento falhou na linha ${1} executando: ${2}"; }
trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

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

# One NAME="value" line for the systemd EnvironmentFile. Only `\` and `"` need escaping
# there ($ is not expanded); a line break cannot be represented, so it is refused.
env_line() {
  local name="$1" value="$2"
  [[ "$value" != *$'\n'* ]] || die "O valor de $name tem quebra de linha"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s="%s"\n' "$name" "$value"
}

resolve_variables() {
  CTID="${BROKER_CTID:-}"
  [[ -n "$CTID" ]] || die "BROKER_CTID nao definido no .env"
  [[ "$CTID" =~ ^[0-9]+$ ]] || die "BROKER_CTID deve ser numerico: $CTID"
  CT_HOSTNAME="${BROKER_HOSTNAME:-gamebroker}"
  STORAGE="${STORAGE:-local-zfs}"
  TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
  TEMPLATE_PATTERN="${TEMPLATE_PATTERN:-debian-13-standard_.*_amd64\.tar\.zst}"
  BRIDGE="${BRIDGE:-vmbr0}"
  # Without a password the CT root stays LOCKED (you get in with `pct enter` or the SSH key).
  # The default used to be "changeme": every CT was born with the same well-known console password.
  CT_PASSWORD="${CT_PASSWORD:-}"
  TZ="${TZ:-America/Sao_Paulo}"
  RECREATE_CT="${RECREATE_BROKER_CT:-0}"

  IP_CIDR="${BROKER_IP_CIDR:-}"
  [[ -n "$IP_CIDR" && "$IP_CIDR" != "dhcp" ]] || die "BROKER_IP_CIDR precisa ser um IP fixo (ex.: 10.20.1.18/24): o certificado e a regra de firewall dependem dele"
  CT_IP="${IP_CIDR%%/*}"
  GATEWAY="${BROKER_GATEWAY:-${GATEWAY:-}}"
  [[ -n "$GATEWAY" ]] || die "BROKER_GATEWAY (ou GATEWAY) obrigatorio"
  NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY},type=veth"
  MEMORY="${BROKER_MEMORY:-512}"
  CORES="${BROKER_CORES:-1}"
  ROOTFS_SIZE_GB="${BROKER_DISK_GB:-4}"
  SWAP="${BROKER_SWAP:-256}"
  BROKER_PORT="${BROKER_PORT:-8443}"

  # Without these the broker does not even start (config.py refuses); better to fail here, at deploy, with the name.
  local var
  for var in PROXMOX_URL PROXMOX_TOKEN PROXMOX_NODE PROXMOX_STORAGE PROXMOX_BRIDGE OPNSENSE_URL \
             OPNSENSE_KEY OPNSENSE_SECRET BROKER_IP_PREFIX; do
    [[ -n "${!var:-}" ]] || die "$var nao definido (broker.secrets.env / .env)"
  done
  PROXMOX_POOL="${PROXMOX_POOL:-games}"
  PROXMOX_TEMPLATE_STORAGE="${PROXMOX_TEMPLATE_STORAGE:-$TEMPLATE_STORAGE}"
  OPNSENSE_WAN="${OPNSENSE_WAN:-wan}"
  ADMIN_CTID="${ADMIN_CTID:-}"
  PANEL_IP="${PANEL_IP:-${BROKER_ALLOW_IPS%%,*}}"
}

validate_bundle() {
  need_cmd pct
  need_cmd pveam
  need_cmd openssl
  # There used to be a list of package files here (app.py, services/catalog.py, ...) that
  # had to grow along with the code and never did. The code now arrives in a single
  # tarball and its sha256 is what checks the content.
  [[ -f "$RELEASE_ENV_FILE" ]] || die "release.env nao encontrado: $RELEASE_ENV_FILE (rode pelo deploy-broker.ps1)"
  [[ -f "$INSTALLER" ]] || die "install-release.sh nao encontrado: $INSTALLER"
  load_env_file "$RELEASE_ENV_FILE"
  [[ -n "${RELEASE_TARBALL:-}" ]] || die "RELEASE_TARBALL vazio em $RELEASE_ENV_FILE"
  [[ -n "${RELEASE_SHA256:-}" ]] || die "RELEASE_SHA256 vazio em $RELEASE_ENV_FILE"
  [[ -f "$SCRIPT_DIR/$RELEASE_TARBALL" ]] || die "release nao encontrado no bundle: $RELEASE_TARBALL"
  # lib/ and games/ still go loose in the bundle: they are data, not the Python package.
  [[ -f "$SCRIPT_DIR/lib/ct-install.sh" && -f "$SCRIPT_DIR/lib/ct-phases.sh" && -f "$SCRIPT_DIR/lib/ct-firewall.sh" \
     && -f "$SCRIPT_DIR/lib/ct-panel-access.sh" ]] \
    || die "lib/ct-install.sh, lib/ct-phases.sh, lib/ct-firewall.sh e lib/ct-panel-access.sh sao obrigatorios no bundle"
  compgen -G "$SCRIPT_DIR/games/*.env" >/dev/null || die "games/*.env nao encontrado no bundle"
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

# The template the broker will use for GAME CTs (not the broker's own). Without
# PROXMOX_TEMPLATE in the secrets, takes the newest Debian 13 in the storage.
resolve_game_template() {
  [[ -z "${PROXMOX_TEMPLATE:-}" ]] || return 0
  local name
  name="$(pveam list "$PROXMOX_TEMPLATE_STORAGE" | awk '{print $1}' | sed 's#.*/##' \
          | grep -E 'debian-13-standard_.*_amd64\.tar\.zst' | sort -V | tail -n1 || true)"
  [[ -n "$name" ]] || die "Nenhum template debian-13-standard em ${PROXMOX_TEMPLATE_STORAGE}; defina PROXMOX_TEMPLATE ou rode: pveam download ${PROXMOX_TEMPLATE_STORAGE} <template>"
  PROXMOX_TEMPLATE="${PROXMOX_TEMPLATE_STORAGE}:vztmpl/${name}"
  msg "Template dos CTs de jogo: ${PROXMOX_TEMPLATE}"
}

ensure_container() {
  local ct_exists=0
  pct status "$CTID" >/dev/null 2>&1 && ct_exists=1

  if [[ "$ct_exists" -eq 1 && "$RECREATE_CT" == "1" ]]; then
    msg "Recriando CT $CTID (RECREATE_BROKER_CT=1)"
    pct stop "$CTID" >/dev/null 2>&1 || true
    pct destroy "$CTID" --destroy-unreferenced-disks 1
    ct_exists=0
  fi

  # The broker CT does NOT join the games pool: the Proxmox token only sees the pool, and the
  # broker must not even list (let alone destroy) its own container.
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
      --net0 "$NET0" \
      ${CT_PASSWORD:+--password "$CT_PASSWORD"} \
      --onboot 1 \
      --timezone "$TZ" \
      --tags "broker;gamepanel"
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
      --tags "broker;gamepanel"
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
  waited=0
  until run_ct "getent hosts deb.debian.org >/dev/null 2>&1"; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 60 ]] || die "CT $CTID sem resolucao DNS/rede apos 60s"
  done
}

install_packages() {
  # iputils-ping: the broker checks whether an IP already answers on the network before picking it.
  # openssh-client: it is what logs into the game CTs. Does NOT install openssh-server: nothing gets
  # into the broker over SSH (the code arrives via `pct push`, from Proxmox).
  msg "Instalando dependencias no CT (python3-flask, gunicorn, openssh-client, openssl, ping)"
  run_ct "export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && \
    apt-get install -y -qq python3 python3-flask gunicorn openssh-client openssl iputils-ping \
    ca-certificates"
}

ensure_app_user() {
  run_ct "id ${APP_USER} >/dev/null 2>&1 || useradd --system --home-dir ${DATA_DIR} --shell /usr/sbin/nologin ${APP_USER}"
  run_ct "install -d -o ${APP_USER} -g ${APP_USER} -m 0750 ${DATA_DIR}"
  run_ct "install -d -o root -g ${APP_USER} -m 0750 ${CONF_DIR}"
  run_ct "install -d -o ${APP_USER} -g ${APP_USER} -m 0700 ${CONF_DIR}/ssh ${CONF_DIR}/tls"
  run_ct "install -d -o root -g root -m 0755 ${APP_DIR}"
}

# `pct push` does not create directories and is not recursive: create the folders as they show up.
push_tree() {
  local source_dir="$1" dest_dir="$2" src rel
  while IFS= read -r src; do
    rel="${src#"$source_dir"/}"
    [[ "$(basename "$src")" =~ $DO_NOT_SHIP ]] && continue
    if [[ "$rel" == */* ]]; then
      run_ct "install -d '${dest_dir}/${rel%/*}'"
    fi
    pct push "$CTID" "$src" "${dest_dir}/${rel}" --perms 0644
  done < <(find "$source_dir" -type f ! -name '*.pyc' ! -path '*__pycache__*' | sort)
}

publish_application() {
  msg "Publicando o broker em ${APP_DIR}"

  # lib/ and games/ are not the Python package: they are the game install scripts and the
  # curated catalog, read by the broker at an absolute path. They still go loose, and are
  # replaced ENTIRELY - there is no subfolder list to fall behind.
  run_ct "rm -rf ${APP_DIR}/lib ${APP_DIR}/games"
  run_ct "install -d ${APP_DIR}/lib ${APP_DIR}/games"
  push_tree "$SCRIPT_DIR/lib" "${APP_DIR}/lib"
  push_tree "$SCRIPT_DIR/games" "${APP_DIR}/games"

  # The CODE comes in the release tarball, verified by its sha256 and installed in its own
  # folder with the `current` symlink pointing to it.
  local remote_tmp=/tmp/gamebroker-release
  run_ct "rm -rf '$remote_tmp' && install -d '$remote_tmp'"
  # pct push, and not the `tee` of push_file_to_ct: the tarball is binary and must arrive byte
  # for byte - and the sha256 on the other side does not forgive a single changed byte.
  pct push "$CTID" "$SCRIPT_DIR/$RELEASE_TARBALL" "${remote_tmp}/${RELEASE_TARBALL}" --perms 0644
  pct push "$CTID" "$INSTALLER" "${remote_tmp}/install-release.sh" --perms 0755

  # No health probe here, and the reason is no longer the ordering (the unit is already written):
  # the broker's /health is HTTPS with its own certificate and an IP list, and probing it from
  # inside the CT with wget would need --no-check-certificate, exactly what this project does
  # nowhere. The real probe lives in start_broker, which pins the certificate fingerprint;
  # the price is that the installer's rollback does not apply here, and that is why
  # start_broker fails LOUDLY when health does not answer.
  run_ct "bash '${remote_tmp}/install-release.sh' gamebroker '${remote_tmp}/${RELEASE_TARBALL}' '${RELEASE_SHA256}' ${APP_DIR} ${SERVICE_NAME}" \
    || die "A instalacao do release falhou dentro do CT (veja a saida acima)"
  run_ct "rm -rf '$remote_tmp'"
  run_ct "chown -R root:root ${APP_DIR}/lib ${APP_DIR}/games"

  # Failing here is better than the service dying at start with ModuleNotFoundError.
  run_ct "cd ${APP_DIR}/current && python3 -c 'import gamebroker.wsgi'" \
    || die "O pacote do broker nao importa no CT a partir de ${APP_DIR}/current"
}

ensure_ssh_key() {
  msg "Chave SSH do broker (para entrar nos CTs de jogo durante a instalacao)"
  run_ct "test -f ${CONF_DIR}/ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'gamebroker@${CT_HOSTNAME}' -f ${CONF_DIR}/ssh/id_ed25519 >/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/ssh/id_ed25519 ${CONF_DIR}/ssh/id_ed25519.pub && chmod 0600 ${CONF_DIR}/ssh/id_ed25519 && chmod 0644 ${CONF_DIR}/ssh/id_ed25519.pub"
}

# Self-signed certificate of the broker ITSELF. The panel pins it by SHA-256 fingerprint (there is
# no CA at all), so it is only replaced on request: replacing it invalidates the panel configuration.
ensure_tls() {
  msg "Certificado TLS do broker"
  if [[ "${BROKER_ROTATE_CERT:-0}" == "1" ]]; then
    run_ct "rm -f ${CONF_DIR}/tls/cert.pem ${CONF_DIR}/tls/key.pem"
  fi
  run_ct "test -f ${CONF_DIR}/tls/cert.pem || openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -subj '/CN=gamebroker' -addext 'subjectAltName=IP:${CT_IP}' \
    -keyout ${CONF_DIR}/tls/key.pem -out ${CONF_DIR}/tls/cert.pem 2>/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/tls/cert.pem ${CONF_DIR}/tls/key.pem && chmod 0644 ${CONF_DIR}/tls/cert.pem && chmod 0600 ${CONF_DIR}/tls/key.pem"
  BROKER_CERT_SHA256="$(pct exec "$CTID" -- openssl x509 -in "${CONF_DIR}/tls/cert.pem" -noout -fingerprint -sha256 \
    | cut -d= -f2 | tr -d '\r\n' || true)"
  [[ -n "$BROKER_CERT_SHA256" ]] || die "Nao consegui calcular a impressao do certificado do broker"
}

# Token the PANEL uses to talk to the broker. Persists across deploys (regenerating would break
# the panel), and only changes with BROKER_ROTATE_TOKEN=1.
ensure_token() {
  msg "Token do painel para o broker"
  if [[ "${BROKER_ROTATE_TOKEN:-0}" == "1" ]]; then
    run_ct "rm -f ${CONF_DIR}/token"
  fi
  run_ct "test -s ${CONF_DIR}/token || { head -c 36 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-48 > ${CONF_DIR}/token; }"
  run_ct "chown root:root ${CONF_DIR}/token && chmod 0600 ${CONF_DIR}/token"
  BROKER_TOKEN="$(pct exec "$CTID" -- cat "${CONF_DIR}/token" | tr -d '\r\n' || true)"
  [[ ${#BROKER_TOKEN} -ge 32 ]] || die "Token do broker invalido (menos de 32 caracteres)"
}

resolve_panel_pubkey() {
  # The panel key goes into every new CT (along with the broker's), so the panel can operate the
  # server afterwards. It comes from the panel itself, as deploy-game.ps1 already does.
  BROKER_PANEL_PUBKEY="${BROKER_PANEL_PUBKEY:-}"
  if [[ -z "$BROKER_PANEL_PUBKEY" && -n "$ADMIN_CTID" ]]; then
    BROKER_PANEL_PUBKEY="$(pct exec "$ADMIN_CTID" -- cat /etc/gamepanel/id_ed25519.pub 2>/dev/null | head -n1 | tr -d '\r\n' || true)"
  fi
  [[ -n "$BROKER_PANEL_PUBKEY" ]] || die "Chave publica do painel nao encontrada: defina ADMIN_CTID (o CT do painel) ou BROKER_PANEL_PUBKEY no .env"
}

# SHA-256 fingerprint of an https server's certificate, read from the host. TOFU: trusts what the
# server presents NOW and pins it. The summary prints both so you can compare them with what the
# browser shows (or with check-broker-access.ps1).
fingerprint_of() {
  local url="$1" hostport host port
  hostport="${url#*://}"; hostport="${hostport%%/*}"
  host="${hostport%%:*}"; port="${hostport##*:}"
  [[ "$port" != "$hostport" ]] || port=443
  # timeout: a firewall that drops the packet would leave openssl waiting for minutes. The `|| true`
  # returns empty text instead of killing the $(...): the caller explains what to do.
  { echo | timeout 15 openssl s_client -connect "${host}:${port}" -servername "$host" 2>/dev/null \
      | openssl x509 -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2 | tr -d '\r\n'; } || true
}

resolve_upstream_fingerprints() {
  PROXMOX_CERT_SHA256="${PROXMOX_CERT_SHA256:-}"
  OPNSENSE_CERT_SHA256="${OPNSENSE_CERT_SHA256:-}"
  if [[ -z "$PROXMOX_CERT_SHA256" && "$PROXMOX_URL" == https://* ]]; then
    PROXMOX_CERT_SHA256="$(fingerprint_of "$PROXMOX_URL")"
    [[ -n "$PROXMOX_CERT_SHA256" ]] || die "O host Proxmox nao conseguiu ler o certificado de $PROXMOX_URL (firewall?). Defina PROXMOX_CERT_SHA256 no broker.secrets.env: o check-broker-access.ps1 imprime a impressao a partir da sua maquina"
    FIXOU_PROXMOX=1
  fi
  if [[ -z "$OPNSENSE_CERT_SHA256" && "$OPNSENSE_URL" == https://* ]]; then
    OPNSENSE_CERT_SHA256="$(fingerprint_of "$OPNSENSE_URL")"
    [[ -n "$OPNSENSE_CERT_SHA256" ]] || die "O host Proxmox nao conseguiu ler o certificado de $OPNSENSE_URL (firewall?). Defina OPNSENSE_CERT_SHA256 no broker.secrets.env: o check-broker-access.ps1 imprime a impressao a partir da sua maquina"
    FIXOU_OPNSENSE=1
  fi
}

render_broker_config() {
  msg "Gravando a configuracao do broker (${CONF_DIR}/broker.env, 0640 root:${APP_USER})"
  local tmp_file
  tmp_file="$(mktemp)"
  chmod 600 "$tmp_file"
  {
    echo "# Gerado pelo provision-broker-lxc.sh - o proximo deploy sobrescreve."
    env_line BROKER_TOKEN "$BROKER_TOKEN"
    # Loopback next to the panel: the deploy's own health check runs from inside the CT. Only a
    # process in the CT reaches 127.0.0.1, and whoever is in there already has the token. EMPTY list = any
    # source (token only), and then loopback is not added: it would restrict instead of adding.
    if [[ -n "${BROKER_ALLOW_IPS:-}" ]]; then
      env_line BROKER_ALLOW_IPS "${BROKER_ALLOW_IPS},127.0.0.1"
    else
      env_line BROKER_ALLOW_IPS ""
    fi
    # Who may open SSH to the game CTs after they are installed (the firewall inside them,
    # lib/ct-firewall.sh): the panel, which manages them, and this broker, which installs and removes the key.
    # Without the panel IP the games are born WITHOUT an internal firewall - with it wrong, locked out.
    if [[ -n "${PANEL_IP:-}" && "${CT_FIREWALL:-1}" != "0" ]]; then
      env_line BROKER_FIREWALL_SOURCES "${PANEL_IP},${CT_IP}"
    fi
    env_line BROKER_STATE_DIR "$DATA_DIR"
    env_line BROKER_GAMES_DIR "${APP_DIR}/games"
    env_line BROKER_LIB_DIR "${APP_DIR}/lib"
    env_line BROKER_SSH_KEY "${CONF_DIR}/ssh/id_ed25519"
    env_line BROKER_PANEL_PUBKEY "$BROKER_PANEL_PUBKEY"
    env_line BROKER_GATEWAY "$GATEWAY"
    env_line BROKER_PREFIXO_REDE "${IP_CIDR##*/}"
    env_line BROKER_IP_PREFIX "$BROKER_IP_PREFIX"
    env_line BROKER_IP_INICIO "${BROKER_IP_INICIO:-102}"
    env_line BROKER_IP_FIM "${BROKER_IP_FIM:-199}"
    # Each game's CTID is the base + the last number of the IP (.102 -> 302): "3" + the last two
    # digits of the IP. 0 = CTID chosen separately (BROKER_CTID_INICIO/FIM, only in that mode).
    env_line BROKER_CTID_BASE "${BROKER_CTID_BASE:-200}"
    env_line BROKER_PORT_INICIO "${BROKER_PORT_INICIO:-31000}"
    env_line BROKER_PORT_FIM "${BROKER_PORT_FIM:-31999}"
    env_line BROKER_MAX_INSTANCIAS "${BROKER_MAX_INSTANCIAS:-8}"
    env_line BROKER_MAX_CREATIONS_PER_HOUR "${BROKER_MAX_CREATIONS_PER_HOUR:-10}"
    env_line PROXMOX_URL "$PROXMOX_URL"
    env_line PROXMOX_TOKEN "$PROXMOX_TOKEN"
    env_line PROXMOX_CERT_SHA256 "$PROXMOX_CERT_SHA256"
    env_line PROXMOX_NODE "$PROXMOX_NODE"
    env_line PROXMOX_POOL "$PROXMOX_POOL"
    env_line PROXMOX_STORAGE "$PROXMOX_STORAGE"
    env_line PROXMOX_TEMPLATE "$PROXMOX_TEMPLATE"
    env_line PROXMOX_BRIDGE "$PROXMOX_BRIDGE"
    env_line OPNSENSE_URL "$OPNSENSE_URL"
    env_line OPNSENSE_KEY "$OPNSENSE_KEY"
    env_line OPNSENSE_SECRET "$OPNSENSE_SECRET"
    env_line OPNSENSE_CERT_SHA256 "$OPNSENSE_CERT_SHA256"
    env_line OPNSENSE_WAN "$OPNSENSE_WAN"
    # Steam account: optional (only for a game that cannot download anonymously, DayZ). Empty = that game
    # stays manual; the broker refuses to start with only one of the two, and says which one is missing.
    env_line STEAM_USER "${STEAM_USER:-}"
    env_line STEAM_PASS "${STEAM_PASS:-}"
  } > "$tmp_file"
  push_file_to_ct "$tmp_file" "${CONF_DIR}/broker.env" 0640
  rm -f "$tmp_file"
  run_ct "chown root:${APP_USER} ${CONF_DIR}/broker.env"
}

render_service() {
  msg "Criando o servico systemd gamebroker.service"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
[Unit]
Description=Broker de provisionamento dos servidores de jogos
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
# The current release, via symlink: switching versions (or rolling back) is moving the link and
# restarting. systemd resolves the path at start, so every restart picks up what the
# link points to NOW.
WorkingDirectory=${APP_DIR}/current
EnvironmentFile=${CONF_DIR}/broker.env
# ONE worker on purpose: the lock that stops two creations from picking the same IP lives in
# process memory. The threads serve the panel's polling while a creation runs.
ExecStart=/usr/bin/gunicorn --workers 1 --threads 8 --timeout 120 \\
  --certfile ${CONF_DIR}/tls/cert.pem --keyfile ${CONF_DIR}/tls/key.pem \\
  --bind 0.0.0.0:${BROKER_PORT} --access-logfile - 'gamebroker.wsgi:create_app_from_env()'
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${DATA_DIR}
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/gamebroker.service" 0644
  rm -f "$tmp_file"
  run_ct "systemctl daemon-reload && systemctl enable gamebroker.service"
}

# "https://10.20.1.1:8443/" -> "10.20.1.1:8443" (the scheme's default port when missing).
endpoint_of() {
  local url="$1" rest host port
  rest="${url#*://}"
  rest="${rest%%/*}"
  host="${rest%%:*}"
  if [[ "$rest" == *:* ]]; then port="${rest##*:}"
  elif [[ "$url" == https://* ]]; then port=443
  else port=80
  fi
  printf '%s:%s' "$host" "$port"
}

# Firewall inside the broker CT (lib/ct-firewall.sh, role "broker"): the API only serves the
# panel, and the broker only goes out to Proxmox, OPNsense, the games' SSH/ping, DNS and apt. A
# compromised broker does not become a bridge to the rest of the network.
#
# Runs BEFORE starting the service: the `start_broker` health probe is what proves, with the
# new rules already in force, that Proxmox and OPNsense are still reachable. If they are not, the
# firewall comes off (the broker keeps working, with the warning), instead of a blind broker.
apply_broker_firewall() {
  if [[ "${CT_FIREWALL:-1}" == "0" ]]; then
    warn "CT_FIREWALL=0: o CT do broker fica SEM firewall interno"
    return 0
  fi
  if [[ -z "${PANEL_IP:-}" ]]; then
    warn "IP do painel desconhecido (ADMIN_HOST/BROKER_ALLOW_IPS): o CT do broker fica SEM firewall interno"
    return 0
  fi
  msg "Aplicando o firewall do CT do broker (nftables)"
  modprobe nf_tables 2>/dev/null || warn "nao consegui carregar o modulo nf_tables no host"
  { mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
    || warn "nao consegui deixar o nf_tables carregando no boot do host"
  local conf endpoints
  endpoints="$(endpoint_of "$PROXMOX_URL") $(endpoint_of "$OPNSENSE_URL")"
  conf="$(mktemp)"
  {
    printf 'FW_ROLE=broker\n'
    printf 'FW_PANEL_SOURCES="%s"\n' "$PANEL_IP"
    printf 'FW_BROKER_PORT="%s"\n' "$BROKER_PORT"
    printf 'FW_API_ENDPOINTS="%s"\n' "$endpoints"
    printf 'FW_GAME_NET="%s.%s-%s.%s"\n' "$BROKER_IP_PREFIX" "${BROKER_IP_INICIO:-102}" \
      "$BROKER_IP_PREFIX" "${BROKER_IP_FIM:-199}"
  } > "$conf"
  push_file_to_ct "$SCRIPT_DIR/lib/ct-firewall.sh" /usr/local/sbin/ct-firewall 0755
  push_file_to_ct "$conf" /etc/ct-firewall.env 0644
  rm -f "$conf"
  run_ct "/usr/local/sbin/ct-firewall apply" || die "o firewall do broker nao carregou (nada foi alterado nele)"
  BROKER_FIREWALL_APPLIED=1
}

start_broker() {
  msg "Subindo o broker"
  run_ct "systemctl restart gamebroker.service"
  sleep 4
  if ! run_ct "systemctl is-active --quiet gamebroker.service"; then
    warn "O broker nao ficou ativo. Ultimas linhas do log:"
    run_ct "journalctl -u gamebroker.service --no-pager -n 40" || true
    die "gamebroker.service nao subiu (a lista de problemas de configuracao esta no log acima)"
  fi
  [[ "${BROKER_SKIP_HEALTHCHECK:-0}" != "1" ]] || return 0
  # Requests /v1/health from inside the CT: proves TLS, the token, and that Proxmox and OPNsense answer.
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<PY
import json, ssl, sys, urllib.error, urllib.request
token = open('${CONF_DIR}/token').read().strip()
req = urllib.request.Request('https://127.0.0.1:${BROKER_PORT}/v1/health', headers={'Authorization': 'Bearer ' + token})
try:
    dados = json.loads(urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=40).read())
except urllib.error.HTTPError as erro:
    print('saude: o broker respondeu HTTP', erro.code, '(403 = origem fora de BROKER_ALLOW_IPS)')
    sys.exit(2)
except OSError as erro:
    print('saude: nao consegui falar com o broker:', type(erro).__name__)
    sys.exit(2)
for nome, rotulo in (('broker', 'broker'), ('proxmox', 'API do Proxmox'), ('opnsense', 'API do OPNsense')):
    print('saude: %-16s %s' % (rotulo, 'OK' if dados.get(nome) else 'NAO RESPONDE'))
sys.exit(0 if dados.get('proxmox') and dados.get('opnsense') else 3)
PY
  push_file_to_ct "$tmp_file" /root/saude-do-broker.py 0600
  rm -f "$tmp_file"
  local unhealthy="O broker esta de pe, mas nem tudo respondeu (veja 'saude' acima). Se for a API do Proxmox ou do OPNsense, falta a regra de firewall do CT ${CT_IP} para ela (ver REGRAS DE FIREWALL no fim)"
  if ! run_ct "python3 /root/saude-do-broker.py"; then
    if [[ "${BROKER_FIREWALL_APPLIED:-0}" == "1" ]]; then
      # With the new rules something did not answer: test without them. If it answers then, the rules
      # are to blame, and the broker keeps working WITHOUT a firewall (with the warning) instead of blind.
      warn "Com o firewall do CT ligado nem tudo respondeu; testando sem ele"
      run_ct "/usr/local/sbin/ct-firewall off"
      if run_ct "python3 /root/saude-do-broker.py"; then
        warn "SEM o firewall do CT tudo responde: as regras bloqueavam o Proxmox ou o OPNsense. O firewall do broker ficou DESLIGADO. Confira FW_API_ENDPOINTS em /etc/ct-firewall.env e religue com: pct exec ${CTID} -- ct-firewall apply"
      else
        run_ct "/usr/local/sbin/ct-firewall apply"
        warn "$unhealthy"
      fi
    else
      warn "$unhealthy"
    fi
  fi
  run_ct "rm -f /root/saude-do-broker.py"
}

# Optional (BROKER_CONFIGURE_PANEL=1): writes the broker URL, token and fingerprint into the panel.
# The feature stays OFF there (GAMEPANEL_ALLOW_BROKER=0) until BROKER_ENABLE_IN_PANEL=1: turning it on
# in a panel exposed to the internet requires an extra authentication layer first.
configure_panel() {
  [[ "${BROKER_CONFIGURE_PANEL:-0}" == "1" ]] || return 0
  [[ -n "$ADMIN_CTID" ]] || die "BROKER_CONFIGURE_PANEL=1 exige ADMIN_CTID"
  msg "Configurando o painel (CT ${ADMIN_CTID}) para falar com o broker"
  local enable="${BROKER_ENABLE_IN_PANEL:-0}" tmp_file
  tmp_file="$(mktemp)"
  chmod 600 "$tmp_file"
  printf '%s\n' "$BROKER_TOKEN" > "$tmp_file"
  pct exec "$ADMIN_CTID" -- tee /etc/gamepanel/broker.token >/dev/null < "$tmp_file"
  rm -f "$tmp_file"
  pct exec "$ADMIN_CTID" -- bash -lc "
    chown root:gamepanel /etc/gamepanel/broker.token && chmod 0640 /etc/gamepanel/broker.token
    sed -i '/^GAMEPANEL_BROKER_/d;/^GAMEPANEL_ALLOW_BROKER=/d' /etc/gamepanel/panel.env
    {
      echo 'GAMEPANEL_BROKER_URL=https://${CT_IP}:${BROKER_PORT}'
      echo 'GAMEPANEL_BROKER_TOKEN_FILE=/etc/gamepanel/broker.token'
      echo 'GAMEPANEL_BROKER_CERT_SHA256=${BROKER_CERT_SHA256}'
      echo 'GAMEPANEL_ALLOW_BROKER=${enable}'
    } >> /etc/gamepanel/panel.env
    systemctl restart gamepanel.service
  "
  PANEL_CONFIGURED=1
}

print_summary() {
  local url
  url="${PROXMOX_URL#*://}"; PROXMOX_HOSTPORT="${url%%/*}"
  url="${OPNSENSE_URL#*://}"; OPNSENSE_HOSTPORT="${url%%/*}"
  cat <<EOF

========================================================================
 Broker pronto
========================================================================

Container : CT ${CTID} (${CT_HOSTNAME}) - ${CORES} core(s), ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB
Endereco  : https://${CT_IP}:${BROKER_PORT}
Impressao : ${BROKER_CERT_SHA256}
            ^ certificado do PROPRIO broker (o painel fixa esta impressao)
Pool      : ${PROXMOX_POOL}  |  IPs ${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_FIM:-199}  |  CTID = ${BROKER_CTID_BASE:-200} + ultimo numero do IP
Portas    : jogos que andam de porta usam ${BROKER_PORT_INICIO:-31000}-${BROKER_PORT_FIM:-31999} (faixa propria, fora das portas padrao dos jogos)

Certificados que o broker fixou (CONFIRA: se nao forem os seus, algo esta no meio do caminho):
  Proxmox  : ${PROXMOX_CERT_SHA256:-(nao-https)}${FIXOU_PROXMOX:+   <- lido do servidor agora}
  OPNsense : ${OPNSENSE_CERT_SHA256:-(nao-https)}${FIXOU_OPNSENSE:+   <- lido do servidor agora}
EOF
  if [[ "${PANEL_CONFIGURED:-0}" == "1" ]]; then
    cat <<EOF

Painel (CT ${ADMIN_CTID}) configurado: URL, token e impressao gravados em /etc/gamepanel/.
  GAMEPANEL_ALLOW_BROKER=${BROKER_ENABLE_IN_PANEL:-0}  (0 = recurso DESLIGADO na tela)
EOF
  else
    cat <<EOF

Para o painel usar o broker, em /etc/gamepanel/panel.env do CT do painel:
  GAMEPANEL_BROKER_URL=https://${CT_IP}:${BROKER_PORT}
  GAMEPANEL_BROKER_TOKEN_FILE=/etc/gamepanel/broker.token   (arquivo com o token: pct exec ${CTID} -- cat ${CONF_DIR}/token)
  GAMEPANEL_BROKER_CERT_SHA256=${BROKER_CERT_SHA256}
  GAMEPANEL_ALLOW_BROKER=0   # so vire 1 depois de proteger o painel (Cloudflare Access ou 2FA)
Ou rode o deploy com -ConfigurePanel.
EOF
  fi
  cat <<EOF

REGRAS DE FIREWALL (OPNsense) - o broker tem chaves de infraestrutura, isole-o:
  1. ${PANEL_IP:-<IP do painel>} -> ${CT_IP}:${BROKER_PORT}/tcp        (so o painel fala com o broker)
  2. ${CT_IP} -> ${PROXMOX_HOSTPORT}      (API do Proxmox)
  3. ${CT_IP} -> ${OPNSENSE_HOSTPORT}     (API do OPNsense)
  4. ${CT_IP} -> ${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_FIM:-199}:22/tcp   (SSH nos CTs novos)
  5. ${CT_IP} -> internet DNS/HTTPS (apt); bloqueie o resto
  E no OPNsense, deixe o GUI/API (${OPNSENSE_HOSTPORT}) acessivel SO a ${CT_IP} e a voce.
  (Trafego entre maquinas da MESMA sub-rede, como o do Proxmox e dos CTs, passa pelo switch/bridge e
   nao pelo OPNsense: as regras 1, 2 e 4 so importam se algo estiver em outra sub-rede/VLAN.)

EOF
}

cleanup_secrets() {
  # The bundle on the host holds a copy of the secrets: do not leave it lying in /root.
  rm -f "$SECRETS_ENV_FILE"
}

main() {
  load_env_file "$CONF_ENV_FILE"
  load_env_file "$SECRETS_ENV_FILE"
  resolve_variables
  validate_bundle
  ensure_debian_template
  resolve_game_template
  ensure_container
  start_container
  install_packages
  ensure_app_user
  ensure_ssh_key
  ensure_tls
  ensure_token
  resolve_panel_pubkey
  resolve_upstream_fingerprints
  render_broker_config
  render_service
  # The config and the unit go BEFORE publishing, and the order matters: it is `install-release.sh`
  # that restarts the service and runs the health probe, and it runs inside the publish. With the
  # unit written afterwards, the probe tested the WRONG pair -- old unit with new code --
  # and its result meant nothing:
  #
  #   - if the old unit called something the new code no longer has (that was the case, with
  #     `gamebroker.wsgi:criar_app_de_ambiente()`), the probe fails, install-release rolls
  #     back and the script dies HERE, right before the step that would fix the unit.
  #     The deploy is stuck: there is no way to reach the new unit;
  #   - and if the old layout were still importable, the probe PASSES against the old
  #     code and the deploy declares success without having changed anything.
  #
  # In this order the probe sees the new unit, new env and new code, and its rollback goes back
  # to a state that actually worked.
  publish_application
  apply_broker_firewall
  start_broker
  configure_panel
  print_summary
  cleanup_secrets
}

main "$@"
