#!/usr/bin/env bash
# Cria/atualiza o container do BROKER (cria instancias de jogo no Proxmox e abre portas no OPNsense).
# Executado NO HOST PROXMOX pelo deploy-broker.ps1 (que envia este bundle via scp).
#
# Bundle (pasta sem subpastas de config, so o que o scp leva):
#   broker.conf.env      configuracao NAO secreta (CT, rede, faixas, cotas)
#   broker.secrets.env   Proxmox e OPNsense (token, chave, segredo)  -> 0600, apagado no fim
#   broker/  lib/  games/   o codigo, os instaladores e o catalogo curado
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_ENV_FILE="${CONF_ENV_FILE:-$SCRIPT_DIR/broker.conf.env}"
SECRETS_ENV_FILE="${SECRETS_ENV_FILE:-$SCRIPT_DIR/broker.secrets.env}"

APP_DIR=/opt/gamebroker
CONF_DIR=/etc/gamebroker
DATA_DIR=/var/lib/gamebroker
APP_USER=gamebroker
# Modulos que ficam FORA do CT de producao: dobles de teste e o broker de brinquedo do compose.
NAO_ENVIAR='^(test_.*|conftest|fakes|http_falso|dev)\.py$'

msg() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[aviso]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[erro]\033[0m %s\n' "$*" >&2; exit 1; }

# Sem isto uma falha dentro de $(...) encerra o script em silencio (set -e + pipefail): o `die`
# com a explicacao, logo depois, nunca chega a rodar. BASH_COMMAND e o texto do comando ANTES da
# expansao, entao nenhum segredo aparece aqui.
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

# Uma linha NOME="valor" para o EnvironmentFile do systemd. So `\` e `"` precisam de escape
# ali ($ nao e expandido); quebra de linha nao tem como ser representada, entao e recusada.
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
  CT_PASSWORD="${CT_PASSWORD:-changeme}"
  TZ="${TZ:-America/Sao_Paulo}"
  RECREATE_CT="${RECREATE_BROKER_CT:-0}"

  IP_CIDR="${BROKER_IP_CIDR:-}"
  [[ -n "$IP_CIDR" && "$IP_CIDR" != "dhcp" ]] || die "BROKER_IP_CIDR precisa ser um IP fixo (ex.: 192.168.2.18/24): o certificado e a regra de firewall dependem dele"
  CT_IP="${IP_CIDR%%/*}"
  GATEWAY="${BROKER_GATEWAY:-${GATEWAY:-}}"
  [[ -n "$GATEWAY" ]] || die "BROKER_GATEWAY (ou GATEWAY) obrigatorio"
  NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY},type=veth"
  MEMORY="${BROKER_MEMORY:-512}"
  CORES="${BROKER_CORES:-1}"
  ROOTFS_SIZE_GB="${BROKER_DISK_GB:-4}"
  SWAP="${BROKER_SWAP:-256}"
  BROKER_PORT="${BROKER_PORT:-8443}"

  # Sem isto o broker nem sobe (config.py recusa); melhor falhar aqui, no deploy, com o nome.
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
  local f
  for f in api.py servico.py prod.py config.py proxmox.py opnsense.py ssh_install.py; do
    [[ -f "$SCRIPT_DIR/broker/$f" ]] || die "broker/$f nao encontrado no bundle"
  done
  [[ -f "$SCRIPT_DIR/lib/ct-install.sh" && -f "$SCRIPT_DIR/lib/ct-fases.sh" ]] || die "lib/ct-install.sh e lib/ct-fases.sh sao obrigatorios no bundle"
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

# O template que o broker vai usar para os CTs de JOGO (nao o do proprio broker). Sem
# PROXMOX_TEMPLATE no secrets, pega o Debian 13 mais novo do storage.
resolve_game_template() {
  [[ -z "${PROXMOX_TEMPLATE:-}" ]] || return 0
  local nome
  nome="$(pveam list "$PROXMOX_TEMPLATE_STORAGE" | awk '{print $1}' | sed 's#.*/##' \
          | grep -E 'debian-13-standard_.*_amd64\.tar\.zst' | sort -V | tail -n1 || true)"
  [[ -n "$nome" ]] || die "Nenhum template debian-13-standard em ${PROXMOX_TEMPLATE_STORAGE}; defina PROXMOX_TEMPLATE ou rode: pveam download ${PROXMOX_TEMPLATE_STORAGE} <template>"
  PROXMOX_TEMPLATE="${PROXMOX_TEMPLATE_STORAGE}:vztmpl/${nome}"
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

  # O CT do broker NAO entra no pool dos jogos: o token do Proxmox so enxerga o pool, e o
  # broker nao pode nem listar (muito menos destruir) o proprio container.
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
      --password "$CT_PASSWORD" \
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
  # iputils-ping: o broker confere se um IP ja responde na rede antes de escolhe-lo.
  # openssh-client: e ele que entra nos CTs de jogo. NAO instala openssh-server: nada entra
  # no broker por SSH (o codigo chega por `pct push`, do Proxmox).
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

# `pct push` nao cria diretorio e nao e recursivo: cria as pastas conforme aparecem.
push_tree() {
  local origem="$1" destino="$2" src rel
  while IFS= read -r src; do
    rel="${src#"$origem"/}"
    [[ "$(basename "$src")" =~ $NAO_ENVIAR ]] && continue
    if [[ "$rel" == */* ]]; then
      run_ct "install -d '${destino}/${rel%/*}'"
    fi
    pct push "$CTID" "$src" "${destino}/${rel}" --perms 0644
  done < <(find "$origem" -type f ! -name '*.pyc' ! -path '*__pycache__*' | sort)
}

push_application() {
  msg "Publicando o broker em ${APP_DIR}"
  run_ct "rm -rf ${APP_DIR}/broker ${APP_DIR}/lib ${APP_DIR}/games"
  run_ct "install -d ${APP_DIR}/broker ${APP_DIR}/lib ${APP_DIR}/games"
  push_tree "$SCRIPT_DIR/broker" "${APP_DIR}/broker"
  push_tree "$SCRIPT_DIR/lib" "${APP_DIR}/lib"
  push_tree "$SCRIPT_DIR/games" "${APP_DIR}/games"
  run_ct "chown -R root:root ${APP_DIR}"
  # Falhar aqui e melhor do que o servico cair no start com ModuleNotFoundError.
  run_ct "cd ${APP_DIR} && python3 -c 'import broker.prod'" \
    || die "O pacote do broker nao importa no CT (falta algum arquivo no bundle?)"
}

ensure_ssh_key() {
  msg "Chave SSH do broker (para entrar nos CTs de jogo durante a instalacao)"
  run_ct "test -f ${CONF_DIR}/ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -C 'gamebroker@${CT_HOSTNAME}' -f ${CONF_DIR}/ssh/id_ed25519 >/dev/null"
  run_ct "chown ${APP_USER}:${APP_USER} ${CONF_DIR}/ssh/id_ed25519 ${CONF_DIR}/ssh/id_ed25519.pub && chmod 0600 ${CONF_DIR}/ssh/id_ed25519 && chmod 0644 ${CONF_DIR}/ssh/id_ed25519.pub"
}

# Certificado autoassinado do PROPRIO broker. O painel o fixa pela impressao SHA-256 (nao ha CA
# nenhuma), entao ele so e trocado quando pedido: trocar invalida a configuracao do painel.
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

# Token que o PAINEL usa para falar com o broker. Persiste entre deploys (regenerar quebraria
# o painel), e so muda com BROKER_ROTATE_TOKEN=1.
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
  # A chave do painel entra em todo CT novo (junto com a do broker), para o painel operar o
  # servidor depois. Vem do proprio painel, como o deploy-game.ps1 ja faz.
  BROKER_PANEL_PUBKEY="${BROKER_PANEL_PUBKEY:-}"
  if [[ -z "$BROKER_PANEL_PUBKEY" && -n "$ADMIN_CTID" ]]; then
    BROKER_PANEL_PUBKEY="$(pct exec "$ADMIN_CTID" -- cat /etc/gamepanel/id_ed25519.pub 2>/dev/null | head -n1 | tr -d '\r\n' || true)"
  fi
  [[ -n "$BROKER_PANEL_PUBKEY" ]] || die "Chave publica do painel nao encontrada: defina ADMIN_CTID (o CT do painel) ou BROKER_PANEL_PUBKEY no .env"
}

# Impressao SHA-256 do certificado de um servidor https, lida do host. TOFU: confia no que o
# servidor apresenta AGORA e fixa. O resumo imprime as duas para voce conferir com o que o
# navegador mostra (ou com o verificar-broker-acesso.ps1).
fingerprint_de() {
  local url="$1" hostport host port
  hostport="${url#*://}"; hostport="${hostport%%/*}"
  host="${hostport%%:*}"; port="${hostport##*:}"
  [[ "$port" != "$hostport" ]] || port=443
  # timeout: um firewall que descarta o pacote deixaria o openssl esperando por minutos. O `|| true`
  # devolve texto vazio em vez de derrubar o $(...): quem chama explica o que fazer.
  { echo | timeout 15 openssl s_client -connect "${host}:${port}" -servername "$host" 2>/dev/null \
      | openssl x509 -noout -fingerprint -sha256 2>/dev/null | cut -d= -f2 | tr -d '\r\n'; } || true
}

resolve_upstream_fingerprints() {
  PROXMOX_CERT_SHA256="${PROXMOX_CERT_SHA256:-}"
  OPNSENSE_CERT_SHA256="${OPNSENSE_CERT_SHA256:-}"
  if [[ -z "$PROXMOX_CERT_SHA256" && "$PROXMOX_URL" == https://* ]]; then
    PROXMOX_CERT_SHA256="$(fingerprint_de "$PROXMOX_URL")"
    [[ -n "$PROXMOX_CERT_SHA256" ]] || die "O host Proxmox nao conseguiu ler o certificado de $PROXMOX_URL (firewall?). Defina PROXMOX_CERT_SHA256 no broker.secrets.env: o verificar-broker-acesso.ps1 imprime a impressao a partir da sua maquina"
    FIXOU_PROXMOX=1
  fi
  if [[ -z "$OPNSENSE_CERT_SHA256" && "$OPNSENSE_URL" == https://* ]]; then
    OPNSENSE_CERT_SHA256="$(fingerprint_de "$OPNSENSE_URL")"
    [[ -n "$OPNSENSE_CERT_SHA256" ]] || die "O host Proxmox nao conseguiu ler o certificado de $OPNSENSE_URL (firewall?). Defina OPNSENSE_CERT_SHA256 no broker.secrets.env: o verificar-broker-acesso.ps1 imprime a impressao a partir da sua maquina"
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
    # Loopback junto do painel: o teste de saude do proprio deploy roda de dentro do CT. So
    # processo do CT alcanca 127.0.0.1, e quem esta la dentro ja tem o token. Lista VAZIA = qualquer
    # origem (so o token), e ai o loopback nao entra: restringiria em vez de acrescentar.
    if [[ -n "${BROKER_ALLOW_IPS:-}" ]]; then
      env_line BROKER_ALLOW_IPS "${BROKER_ALLOW_IPS},127.0.0.1"
    else
      env_line BROKER_ALLOW_IPS ""
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
    # O CTID de cada jogo e a base + o ultimo numero do IP (.102 -> 302): "3" + os dois ultimos
    # digitos do IP. 0 = CTID escolhido a parte (BROKER_CTID_INICIO/FIM, so nesse modo).
    env_line BROKER_CTID_BASE "${BROKER_CTID_BASE:-200}"
    env_line BROKER_PORT_INICIO "${BROKER_PORT_INICIO:-31000}"
    env_line BROKER_PORT_FIM "${BROKER_PORT_FIM:-31999}"
    env_line BROKER_MAX_INSTANCIAS "${BROKER_MAX_INSTANCIAS:-8}"
    env_line BROKER_MAX_CRIACOES_HORA "${BROKER_MAX_CRIACOES_HORA:-4}"
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
WorkingDirectory=${APP_DIR}
EnvironmentFile=${CONF_DIR}/broker.env
# UM worker de proposito: a trava que impede duas criacoes escolherem o mesmo IP mora na
# memoria do processo. As threads atendem o polling do painel enquanto uma criacao roda.
ExecStart=/usr/bin/gunicorn --workers 1 --threads 8 --timeout 120 \\
  --certfile ${CONF_DIR}/tls/cert.pem --keyfile ${CONF_DIR}/tls/key.pem \\
  --bind 0.0.0.0:${BROKER_PORT} --access-logfile - 'broker.prod:criar_app_de_ambiente()'
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
  # Pede /v1/saude de dentro do CT: prova o TLS, o token e que Proxmox e OPNsense respondem.
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<PY
import json, ssl, sys, urllib.error, urllib.request
token = open('${CONF_DIR}/token').read().strip()
req = urllib.request.Request('https://127.0.0.1:${BROKER_PORT}/v1/saude', headers={'Authorization': 'Bearer ' + token})
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
  run_ct "python3 /root/saude-do-broker.py; rc=\$?; rm -f /root/saude-do-broker.py; exit \$rc" \
    || warn "O broker esta de pe, mas nem tudo respondeu (veja 'saude' acima). Se for a API do Proxmox ou do OPNsense, falta a regra de firewall do CT ${CT_IP} para ela (ver REGRAS DE FIREWALL no fim)"
}

# Opcional (BROKER_CONFIGURE_PANEL=1): grava no painel a URL, o token e a impressao do broker.
# O recurso continua DESLIGADO la (GAMEPANEL_ALLOW_BROKER=0) ate BROKER_ENABLE_IN_PANEL=1: ligar
# num painel exposto a internet exige uma camada extra de autenticacao antes.
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
Ou rode o deploy com -ConfigurarPainel.
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
  # O bundle no host tem copia dos segredos: nao deixa sobrando em /root.
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
  push_application
  ensure_ssh_key
  ensure_tls
  ensure_token
  resolve_panel_pubkey
  resolve_upstream_fingerprints
  render_broker_config
  render_service
  start_broker
  configure_panel
  print_summary
  cleanup_secrets
}

main "$@"
