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
UPDATER_DIR=/var/lib/gamebroker-updater

msg() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# Without this a failure inside $(...) ends the script silently (set -e + pipefail): the `die`
# with the explanation, right after it, never gets to run. BASH_COMMAND is the command text BEFORE
# expansion, so no secret shows up here.
on_error() { die "Provisioning failed at line ${1} running: ${2}"; }
trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Required command missing: $1"; }

run_ct() { pct exec "$CTID" -- bash -lc "$1"; }

push_file_to_ct() {
  local src="$1" dest="$2" mode="${3:-0644}"
  run_ct "install -d '$(dirname "$dest")'"
  pct exec "$CTID" -- tee "$dest" >/dev/null < "$src"
  run_ct "chmod ${mode} '$dest'"
}

load_env_file() {
  [[ -f "$1" ]] || die "Environment file not found: $1"
  set -a
  # shellcheck disable=SC1090
  source "$1"
  set +a
}

# One NAME="value" line for the systemd EnvironmentFile. Only `\` and `"` need escaping
# there ($ is not expanded); a line break cannot be represented, so it is refused.
env_line() {
  local name="$1" value="$2"
  [[ "$value" != *$'\n'* ]] || die "The value of $name contains a line break"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s="%s"\n' "$name" "$value"
}

resolve_variables() {
  CTID="${BROKER_CTID:-}"
  [[ -n "$CTID" ]] || die "BROKER_CTID is not set in .env"
  [[ "$CTID" =~ ^[0-9]+$ ]] || die "BROKER_CTID must be numeric: $CTID"
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
  [[ -n "$IP_CIDR" && "$IP_CIDR" != "dhcp" ]] || die "BROKER_IP_CIDR must be a fixed IP (e.g. 10.20.1.18/24): the certificate and the firewall rule depend on it"
  CT_IP="${IP_CIDR%%/*}"
  GATEWAY="${BROKER_GATEWAY:-${GATEWAY:-}}"
  [[ -n "$GATEWAY" ]] || die "BROKER_GATEWAY (or GATEWAY) is required"
  NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY},type=veth"
  MEMORY="${BROKER_MEMORY:-512}"
  CORES="${BROKER_CORES:-1}"
  ROOTFS_SIZE_GB="${BROKER_DISK_GB:-4}"
  SWAP="${BROKER_SWAP:-256}"
  BROKER_PORT="${BROKER_PORT:-8443}"
  # Automatic update from the GitHub releases: auto|notify|off, and the repository it follows.
  UPDATE_MODE="${BROKER_AUTO_UPDATE:-auto}"
  UPDATE_REPO="${BROKER_UPDATE_REPO:-ocristopfer/game-server-deploy}"
  [[ "$UPDATE_MODE" =~ ^(auto|notify|off)$ ]] || die "BROKER_AUTO_UPDATE must be auto, notify or off"
  [[ "$UPDATE_REPO" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "ADMIN_UPDATE_REPO must be owner/name"

  # Without these the broker does not even start (config.py refuses); better to fail here, at deploy, with the name.
  local var
  for var in PROXMOX_URL PROXMOX_TOKEN PROXMOX_NODE PROXMOX_STORAGE PROXMOX_BRIDGE OPNSENSE_URL \
             OPNSENSE_KEY OPNSENSE_SECRET BROKER_IP_PREFIX; do
    [[ -n "${!var:-}" ]] || die "$var is not set (broker.secrets.env / .env)"
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
  [[ -f "$RELEASE_ENV_FILE" ]] || die "release.env not found: $RELEASE_ENV_FILE (run it through deploy-broker.ps1)"
  [[ -f "$INSTALLER" ]] || die "install-release.sh not found: $INSTALLER"
  load_env_file "$RELEASE_ENV_FILE"
  [[ -n "${RELEASE_TARBALL:-}" ]] || die "RELEASE_TARBALL is empty in $RELEASE_ENV_FILE"
  [[ -n "${RELEASE_SHA256:-}" ]] || die "RELEASE_SHA256 is empty in $RELEASE_ENV_FILE"
  [[ -f "$SCRIPT_DIR/$RELEASE_TARBALL" ]] || die "release not found in the bundle: $RELEASE_TARBALL"
  # lib/ and games/ still go loose in the bundle: they are data, not the Python package.
  [[ -f "$SCRIPT_DIR/lib/ct-install.sh" && -f "$SCRIPT_DIR/lib/ct-phases.sh" && -f "$SCRIPT_DIR/lib/ct-firewall.sh" \
     && -f "$SCRIPT_DIR/lib/ct-panel-access.sh" ]] \
    || die "lib/ct-install.sh, lib/ct-phases.sh, lib/ct-firewall.sh and lib/ct-panel-access.sh are required in the bundle"
  compgen -G "$SCRIPT_DIR/games/*.env" >/dev/null || die "games/*.env not found in the bundle"
}

ensure_debian_template() {
  if pct status "$CTID" >/dev/null 2>&1 && [[ "$RECREATE_CT" != "1" ]]; then
    return
  fi
  msg "Updating the Proxmox template list"
  pveam update >/dev/null
  TEMPLATE="$(pveam available --section system | awk -v pat="$TEMPLATE_PATTERN" '$2 ~ pat {print $2}' | tail -n1)"
  [[ -n "$TEMPLATE" ]] || die "No Debian template found for the pattern $TEMPLATE_PATTERN"
  if ! pveam list "$TEMPLATE_STORAGE" | awk '{print $2}' | grep -qx "$TEMPLATE"; then
    msg "Downloading template $TEMPLATE"
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
  [[ -n "$name" ]] || die "No debian-13-standard template in ${PROXMOX_TEMPLATE_STORAGE}; set PROXMOX_TEMPLATE or run: pveam download ${PROXMOX_TEMPLATE_STORAGE} <template>"
  PROXMOX_TEMPLATE="${PROXMOX_TEMPLATE_STORAGE}:vztmpl/${name}"
  msg "Template for the game CTs: ${PROXMOX_TEMPLATE}"
}

ensure_container() {
  local ct_exists=0
  pct status "$CTID" >/dev/null 2>&1 && ct_exists=1

  if [[ "$ct_exists" -eq 1 && "$RECREATE_CT" == "1" ]]; then
    msg "Recreating CT $CTID (RECREATE_BROKER_CT=1)"
    pct stop "$CTID" >/dev/null 2>&1 || true
    pct destroy "$CTID" --destroy-unreferenced-disks 1
    ct_exists=0
  fi

  # The broker CT does NOT join the games pool: the Proxmox token only sees the pool, and the
  # broker must not even list (let alone destroy) its own container.
  if [[ "$ct_exists" -eq 0 ]]; then
    msg "Creating CT $CTID ($CT_HOSTNAME) - ${CORES} core(s), ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB"
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
    msg "Updating the configuration of CT $CTID"
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
    msg "Starting CT $CTID"
    pct start "$CTID"
  fi
  local waited=0
  until pct exec "$CTID" -- true >/dev/null 2>&1; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 120 ]] || die "CT $CTID did not respond within 120s"
  done
  waited=0
  until run_ct "getent hosts deb.debian.org >/dev/null 2>&1"; do
    sleep 2
    waited=$((waited + 2))
    [[ "$waited" -lt 60 ]] || die "CT $CTID has no DNS resolution/network after 60s"
  done
}

install_packages() {
  # iputils-ping: the broker checks whether an IP already answers on the network before picking it.
  # openssh-client: it is what logs into the game CTs. Does NOT install openssh-server: nothing gets
  # into the broker over SSH (the code arrives via `pct push`, from Proxmox).
  msg "Installing dependencies in the CT (python3-flask, gunicorn, openssh-client, openssl, ping)"
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

publish_application() {
  msg "Publishing the broker to ${APP_DIR}"

  # The CODE comes in the release tarball, and so do lib/ and games/ (the game install scripts
  # and the curated catalog, EXTRA_TREES in tools/build-release.py): they land in the release
  # folder, so an automatic update or a rollback moves them together with the code. Verified by
  # its sha256 and installed in its own folder with the `current` symlink pointing to it.
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
    || die "Installing the release failed inside the CT (see the output above)"
  run_ct "rm -rf '$remote_tmp'"
  # The loose copies an older deploy left next to the releases: the broker reads the ones inside
  # the release now (BROKER_LIB_DIR/BROKER_GAMES_DIR), and a stale copy only misleads whoever looks.
  run_ct "rm -rf ${APP_DIR}/lib ${APP_DIR}/games"

  # Failing here is better than the service dying at start with ModuleNotFoundError.
  run_ct "cd ${APP_DIR}/current && python3 -c 'import gamebroker.wsgi'" \
    || die "The broker package does not import in the CT from ${APP_DIR}/current"
}

ensure_ssh_key() {
  msg "Broker SSH key (to log into the game CTs during installation)"
  run_ct "test -f ${CONF_DIR}/ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'gamebroker@${CT_HOSTNAME}' -f ${CONF_DIR}/ssh/id_ed25519 >/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/ssh/id_ed25519 ${CONF_DIR}/ssh/id_ed25519.pub && chmod 0600 ${CONF_DIR}/ssh/id_ed25519 && chmod 0644 ${CONF_DIR}/ssh/id_ed25519.pub"
}

# Self-signed certificate of the broker ITSELF. The panel pins it by SHA-256 fingerprint (there is
# no CA at all), so it is only replaced on request: replacing it invalidates the panel configuration.
ensure_tls() {
  msg "Broker TLS certificate"
  if [[ "${BROKER_ROTATE_CERT:-0}" == "1" ]]; then
    run_ct "rm -f ${CONF_DIR}/tls/cert.pem ${CONF_DIR}/tls/key.pem"
  fi
  run_ct "test -f ${CONF_DIR}/tls/cert.pem || openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
    -subj '/CN=gamebroker' -addext 'subjectAltName=IP:${CT_IP}' \
    -keyout ${CONF_DIR}/tls/key.pem -out ${CONF_DIR}/tls/cert.pem 2>/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/tls/cert.pem ${CONF_DIR}/tls/key.pem && chmod 0644 ${CONF_DIR}/tls/cert.pem && chmod 0600 ${CONF_DIR}/tls/key.pem"
  BROKER_CERT_SHA256="$(pct exec "$CTID" -- openssl x509 -in "${CONF_DIR}/tls/cert.pem" -noout -fingerprint -sha256 \
    | cut -d= -f2 | tr -d '\r\n' || true)"
  [[ -n "$BROKER_CERT_SHA256" ]] || die "Could not compute the broker certificate fingerprint"
}

# Token the PANEL uses to talk to the broker. Persists across deploys (regenerating would break
# the panel), and only changes with BROKER_ROTATE_TOKEN=1.
ensure_token() {
  msg "Panel token for the broker"
  if [[ "${BROKER_ROTATE_TOKEN:-0}" == "1" ]]; then
    run_ct "rm -f ${CONF_DIR}/token"
  fi
  run_ct "test -s ${CONF_DIR}/token || { head -c 36 /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-48 > ${CONF_DIR}/token; }"
  run_ct "chown root:root ${CONF_DIR}/token && chmod 0600 ${CONF_DIR}/token"
  BROKER_TOKEN="$(pct exec "$CTID" -- cat "${CONF_DIR}/token" | tr -d '\r\n' || true)"
  [[ ${#BROKER_TOKEN} -ge 32 ]] || die "Invalid broker token (fewer than 32 characters)"
}

resolve_panel_pubkey() {
  # The panel key goes into every new CT (along with the broker's), so the panel can operate the
  # server afterwards. It comes from the panel itself, as deploy-game.ps1 already does.
  BROKER_PANEL_PUBKEY="${BROKER_PANEL_PUBKEY:-}"
  if [[ -z "$BROKER_PANEL_PUBKEY" && -n "$ADMIN_CTID" ]]; then
    BROKER_PANEL_PUBKEY="$(pct exec "$ADMIN_CTID" -- cat /etc/gamepanel/id_ed25519.pub 2>/dev/null | head -n1 | tr -d '\r\n' || true)"
  fi
  [[ -n "$BROKER_PANEL_PUBKEY" ]] || die "Panel public key not found: set ADMIN_CTID (the panel CT) or BROKER_PANEL_PUBKEY in .env"
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
    [[ -n "$PROXMOX_CERT_SHA256" ]] || die "The Proxmox host could not read the certificate of $PROXMOX_URL (firewall?). Set PROXMOX_CERT_SHA256 in broker.secrets.env: check-broker-access.ps1 prints the fingerprint from your machine"
    FIXOU_PROXMOX=1
  fi
  if [[ -z "$OPNSENSE_CERT_SHA256" && "$OPNSENSE_URL" == https://* ]]; then
    OPNSENSE_CERT_SHA256="$(fingerprint_of "$OPNSENSE_URL")"
    [[ -n "$OPNSENSE_CERT_SHA256" ]] || die "The Proxmox host could not read the certificate of $OPNSENSE_URL (firewall?). Set OPNSENSE_CERT_SHA256 in broker.secrets.env: check-broker-access.ps1 prints the fingerprint from your machine"
    FIXOU_OPNSENSE=1
  fi
}

render_broker_config() {
  msg "Writing the broker configuration (${CONF_DIR}/broker.env, 0640 root:${APP_USER})"
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
    env_line BROKER_GAMES_DIR "${APP_DIR}/current/games"
    env_line BROKER_LIB_DIR "${APP_DIR}/current/lib"
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

# The automatic updater (src/gamebroker/updater.py): a oneshot service that runs as ROOT (it
# installs releases and restarts the broker), a daily timer, and a path unit for the requests the
# panel leaves through the broker API ("check"/"install", written by the unprivileged broker in
# ${DATA_DIR}/update - the panel's own arrangement: root only reads that folder, with O_NOFOLLOW).
render_update_unit() {
  case "$1" in
    service) cat <<UNIT
[Unit]
Description=Game broker automatic update (GitHub releases)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# The CURRENT release's code runs the update, so the updater updates along with the broker.
WorkingDirectory=${APP_DIR}/current
ExecStart=/usr/bin/python3 -m gamebroker.updater run --repo ${UPDATE_REPO} --mode ${UPDATE_MODE} --port ${BROKER_PORT}
TimeoutStartSec=900
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
# The releases and the symlink, the installer's own copy, the status, and the request folder
# (the updater deletes the request once it has read it).
ReadWritePaths=${APP_DIR} /usr/local/lib/gamebroker ${UPDATER_DIR} ${DATA_DIR}/update
UNIT
      ;;
    timer) cat <<UNIT
[Unit]
Description=Daily check for a new game broker release

[Timer]
OnCalendar=daily
# Spread out, and away from the panel's own check, so both CTs do not restart together.
RandomizedDelaySec=4h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
      ;;
    path) cat <<UNIT
[Unit]
Description=Game broker update requests from the panel

[Path]
PathExists=${DATA_DIR}/update/request
Unit=gamebroker-update.service

[Install]
WantedBy=paths.target
UNIT
      ;;
    *) die "unknown updater unit: $1" ;;
  esac
}

render_update_units() {
  msg "Installing the automatic updater (mode: ${UPDATE_MODE})"
  run_ct "install -d -m 0755 /usr/local/lib/gamebroker && install -d -o root -g root -m 0755 ${UPDATER_DIR}"
  # The broker's to write (its API leaves the panel's requests here), root's to read.
  run_ct "install -d -o ${APP_USER} -g ${APP_USER} -m 0755 ${DATA_DIR}/update"
  # The installer refreshes this copy on every install; this covers the very first one.
  pct push "$CTID" "$INSTALLER" /usr/local/lib/gamebroker/install-release.sh --perms 0755
  local kind tmp_file
  for kind in service timer path; do
    tmp_file="$(mktemp)"
    render_update_unit "$kind" > "$tmp_file"
    push_file_to_ct "$tmp_file" "/etc/systemd/system/gamebroker-update.${kind}" 0644
    rm -f "$tmp_file"
  done
  run_ct "systemctl daemon-reload && systemctl enable --now gamebroker-update.timer gamebroker-update.path >/dev/null"
}

render_service() {
  msg "Creating the systemd service gamebroker.service"
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
    warn "CT_FIREWALL=0: the broker CT is left WITHOUT an internal firewall"
    return 0
  fi
  if [[ -z "${PANEL_IP:-}" ]]; then
    warn "Panel IP unknown (ADMIN_HOST/BROKER_ALLOW_IPS): the broker CT is left WITHOUT an internal firewall"
    return 0
  fi
  msg "Applying the broker CT firewall (nftables)"
  modprobe nf_tables 2>/dev/null || warn "could not load the nf_tables module on the host"
  { mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
    || warn "could not make nf_tables load at host boot"
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
  run_ct "/usr/local/sbin/ct-firewall apply" || die "the broker firewall did not load (nothing in it was changed)"
  BROKER_FIREWALL_APPLIED=1
}

start_broker() {
  msg "Starting the broker"
  run_ct "systemctl restart gamebroker.service"
  sleep 4
  if ! run_ct "systemctl is-active --quiet gamebroker.service"; then
    warn "The broker did not stay active. Last lines of the log:"
    run_ct "journalctl -u gamebroker.service --no-pager -n 40" || true
    die "gamebroker.service did not start (the list of configuration problems is in the log above)"
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
    print('health: the broker answered HTTP', erro.code, '(403 = source outside BROKER_ALLOW_IPS)')
    sys.exit(2)
except OSError as erro:
    print('health: could not talk to the broker:', type(erro).__name__)
    sys.exit(2)
for nome, rotulo in (('broker', 'broker'), ('proxmox', 'Proxmox API'), ('opnsense', 'OPNsense API')):
    print('health: %-16s %s' % (rotulo, 'OK' if dados.get(nome) else 'NOT RESPONDING'))
sys.exit(0 if dados.get('proxmox') and dados.get('opnsense') else 3)
PY
  push_file_to_ct "$tmp_file" /root/saude-do-broker.py 0600
  rm -f "$tmp_file"
  local unhealthy="The broker is up, but not everything answered (see 'health' above). If it is the Proxmox or OPNsense API, the firewall rule for CT ${CT_IP} to reach it is missing (see FIREWALL RULES at the end)"
  if ! run_ct "python3 /root/saude-do-broker.py"; then
    if [[ "${BROKER_FIREWALL_APPLIED:-0}" == "1" ]]; then
      # With the new rules something did not answer: test without them. If it answers then, the rules
      # are to blame, and the broker keeps working WITHOUT a firewall (with the warning) instead of blind.
      warn "With the CT firewall on not everything answered; testing without it"
      run_ct "/usr/local/sbin/ct-firewall off"
      if run_ct "python3 /root/saude-do-broker.py"; then
        warn "WITHOUT the CT firewall everything answers: the rules were blocking Proxmox or OPNsense. The broker firewall was left OFF. Check FW_API_ENDPOINTS in /etc/ct-firewall.env and turn it back on with: pct exec ${CTID} -- ct-firewall apply"
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
  [[ -n "$ADMIN_CTID" ]] || die "BROKER_CONFIGURE_PANEL=1 requires ADMIN_CTID"
  msg "Configuring the panel (CT ${ADMIN_CTID}) to talk to the broker"
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
 Broker ready
========================================================================

Container  : CT ${CTID} (${CT_HOSTNAME}) - ${CORES} core(s), ${MEMORY}MB RAM, ${ROOTFS_SIZE_GB}GB
Address    : https://${CT_IP}:${BROKER_PORT}
Fingerprint: ${BROKER_CERT_SHA256}
             ^ certificate of the broker ITSELF (the panel pins this fingerprint)
Pool       : ${PROXMOX_POOL}  |  IPs ${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_FIM:-199}  |  CTID = ${BROKER_CTID_BASE:-200} + last number of the IP
Ports      : games that can shift ports use ${BROKER_PORT_INICIO:-31000}-${BROKER_PORT_FIM:-31999} (own range, away from the games' default ports)

Certificates the broker pinned (CHECK THEM: if they are not yours, something is in the middle):
  Proxmox  : ${PROXMOX_CERT_SHA256:-(not https)}${FIXOU_PROXMOX:+   <- read from the server just now}
  OPNsense : ${OPNSENSE_CERT_SHA256:-(not https)}${FIXOU_OPNSENSE:+   <- read from the server just now}
EOF
  if [[ "${PANEL_CONFIGURED:-0}" == "1" ]]; then
    cat <<EOF

Panel (CT ${ADMIN_CTID}) configured: URL, token and fingerprint written to /etc/gamepanel/.
  GAMEPANEL_ALLOW_BROKER=${BROKER_ENABLE_IN_PANEL:-0}  (0 = feature OFF on screen)
EOF
  else
    cat <<EOF

For the panel to use the broker, in /etc/gamepanel/panel.env of the panel CT:
  GAMEPANEL_BROKER_URL=https://${CT_IP}:${BROKER_PORT}
  GAMEPANEL_BROKER_TOKEN_FILE=/etc/gamepanel/broker.token   (file with the token: pct exec ${CTID} -- cat ${CONF_DIR}/token)
  GAMEPANEL_BROKER_CERT_SHA256=${BROKER_CERT_SHA256}
  GAMEPANEL_ALLOW_BROKER=0   # only set it to 1 after protecting the panel (Cloudflare Access or 2FA)
Or run the deploy with -ConfigurePanel.
EOF
  fi
  cat <<EOF

FIREWALL RULES (OPNsense) - the broker holds infrastructure keys, isolate it:
  1. ${PANEL_IP:-<panel IP>} -> ${CT_IP}:${BROKER_PORT}/tcp        (only the panel talks to the broker)
  2. ${CT_IP} -> ${PROXMOX_HOSTPORT}      (Proxmox API)
  3. ${CT_IP} -> ${OPNSENSE_HOSTPORT}     (OPNsense API)
  4. ${CT_IP} -> ${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_FIM:-199}:22/tcp   (SSH into the new CTs)
  5. ${CT_IP} -> internet DNS/HTTPS (apt); block the rest
  And on OPNsense, make the GUI/API (${OPNSENSE_HOSTPORT}) reachable ONLY from ${CT_IP} and from you.
  (Traffic between machines on the SAME subnet, like Proxmox and the CTs, goes through the switch/bridge
   and not through OPNsense: rules 1, 2 and 4 only matter if something is on another subnet/VLAN.)

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
  render_update_units
  configure_panel
  print_summary
  cleanup_secrets
}

main "$@"
