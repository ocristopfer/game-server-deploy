#!/usr/bin/env bash
# Cria/atualiza o container do painel administrativo dos servidores de jogos.
# Executado NO HOST PROXMOX pelo deploy-admin.ps1 (que envia este bundle via scp).
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
  # Terminal interativo (usa o mesmo ALLOW_SHELL) e editor de arquivos de config.
  ALLOW_FILES="${ADMIN_ALLOW_FILES:-1}"
  # 1 = todo usuario precisa ter o segundo fator (2FA) para usar o painel. Ligue DEPOIS de cada
  # admin ativar o dele em Conta: ligar antes tranca todo mundo fora.
  REQUIRE_2FA="${ADMIN_REQUIRE_2FA:-0}"
  # Endereco https (com dominio) por onde o painel e aberto; vazio = sem entrar por biometria.
  # O painel confere o formato no start e, se for ruim, recusa subir dizendo o nome da variavel.
  WEBAUTHN_ORIGIN="${ADMIN_WEBAUTHN_ORIGIN:-}"
  # Idioma da tela para quem ainda nao escolheu na Conta E para o que sai pelo webhook
  # (o canal e um so: a mensagem nao pode trocar de lingua conforme quem clicou).
  LANG_PADRAO="${ADMIN_LANG:-pt}"
  FILE_MAX_KB="${ADMIN_FILE_MAX_KB:-4096}"
  FILE_PREVIEW_KB="${ADMIN_FILE_PREVIEW_KB:-256}"
  FILE_DOWNLOAD_MAX_MB="${ADMIN_FILE_DOWNLOAD_MAX_MB:-2048}"
  FILE_ROOTS="${ADMIN_FILE_ROOTS:-/}"
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
  # O bundle traz UM tarball de release e o instalador que o abre do lado de la. Antes
  # aqui havia uma lista de arquivos do pacote (app.py, templates/base.html, static/js/
  # app.js...) que precisava crescer junto com o codigo e nunca crescia: ela conferia o
  # primeiro nivel e deixava passar pasta nova inteira. Quem confere o conteudo agora e o
  # sha256 do artefato.
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
  # openssh-server e do painel para fora: e ele que permite atualizar o codigo direto
  # do Windows (deploy-admin.ps1 sem -Full), sem passar pelo Proxmox.
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
  # pct push, e nao o `tee` do push_file_to_ct: o tarball e binario e tem de chegar byte
  # a byte — e o sha256 do outro lado nao perdoa um unico byte trocado.
  pct push "$CTID" "$SCRIPT_DIR/$RELEASE_TARBALL" "${remote_tmp}/${RELEASE_TARBALL}" --perms 0644
  pct push "$CTID" "$INSTALLER" "${remote_tmp}/install-release.sh" --perms 0755

  # A sonda VAI aqui: a unit e o panel.env ja foram escritos (ver o comentario no main),
  # entao o restart que o instalador faz sobe o codigo NOVO e a resposta dela quer dizer
  # algo. Enquanto a unit vinha depois, o instalador so encontrava servico inexistente e
  # se limitava a deixar o release no lugar -- o rollback dele nunca era exercitado. Num
  # CT novo o banco ainda esta sem usuario neste ponto, e isso nao atrapalha: o /health
  # nao depende de sessao.
  run_ct "bash '${remote_tmp}/install-release.sh' gamepanel \
'${remote_tmp}/${RELEASE_TARBALL}' '${RELEASE_SHA256}' ${APP_DIR} ${SERVICE_NAME} \
'wget -q -O /dev/null http://127.0.0.1:${PANEL_PORT}/health'" \
    || die "A instalacao do release falhou dentro do CT (veja a saida acima)"
  run_ct "rm -rf '$remote_tmp'"

  # Falhar aqui e melhor do que o servico cair no start com ModuleNotFoundError.
  run_ct "cd ${APP_DIR}/current && python3 -c 'import gamepanel.app'" \
    || die "O pacote do painel nao importa no CT a partir de ${APP_DIR}/current"
  # || true dentro do $(...): sem ele o `set -e` derruba o script aqui e o motivo
  # nunca chega a ser impresso.
  msg "No ar: $(run_ct "readlink ${APP_DIR}/current" | tr -d '\r' || true)"
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

enable_direct_deploy() {
  # Autoriza a chave do operador no CT do painel. Com ela, o proximo deploy manda os
  # arquivos direto por scp e nem toca no Proxmox.
  local pubkey="${ADMIN_SSH_PUBKEY:-}"
  run_ct "systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true"
  # So por chave: o CT nasce com senha de root conhecida do .env.
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
  # O broker grava as linhas GAMEPANEL_*BROKER* neste arquivo (deploy-broker.ps1
  # -ConfigurePanel), e este script reescreve o arquivo INTEIRO: sem guardar essas linhas antes,
  # cada deploy completo do painel desligava o broker em silencio.
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
  # A raiz de import e ${APP_DIR}/current, nunca ${APP_DIR}: desde que release virou
  # pasta por versao o pacote mora em releases/<versao>/gamepanel, e ${APP_DIR} guarda
  # so o symlink. Apontado para ${APP_DIR} o import falha e o set -e mata o script AQUI
  # - ja com o release publicado e ANTES do render_service, ou seja o painel volta a
  # subir pela unit VELHA com o codigo velho, e o resumo nem chega a dizer que faltou
  # metade do deploy.
  # A senha vai por stdin (nao pela linha de comando) para nao vazar no ps do CT.
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
# A release corrente, por symlink: trocar de versao (ou voltar) e mover o link e
# reiniciar. O systemd resolve o caminho no start, entao cada restart pega o que o
# link aponta AGORA.
WorkingDirectory=${APP_DIR}/current
EnvironmentFile=${CONF_DIR}/panel.env
# Um worker so: as sessoes de terminal vivem na memoria do processo, e com dois
# workers metade dos pedidos cairia no processo que nao tem a sessao. As threads
# sustentam os long-polls do terminal (um por aba aberta) alem das telas normais.
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
IP do container e o servico (ex.: 192.168.2.20, dragonwilds.service). Preencha tambem a
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

# Firewall de dentro do CT do painel (lib/ct-firewall.sh, papel "panel"): a web e o SSH so
# atendem a rede de administracao (ADMIN_FIREWALL_SOURCES, padrao a rede local inteira). A
# saida fica livre: o painel fala com os jogos, com o broker e com o webhook (Discord).
#
# Depois do `start_panel`: a sonda de saude dele usa 127.0.0.1, que o firewall sempre deixa
# passar. A prova de que a REDE ainda chega e feita aqui, do host - e se nao chegar, o
# firewall sai, em vez de um painel no ar que ninguem alcanca.
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
  # O host costuma estar na rede de administracao. Se ele nao alcanca a web do painel, ou a
  # lista esta errada ou o host esta fora dela: nos dois casos, melhor aberto e avisado.
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
  # A config e a unit vao ANTES de publicar, e a ordem importa: e o `install-release.sh`
  # que reinicia o servico e faz a sonda de saude, e ele roda dentro do publish. Com a
  # unit escrita depois, a sonda testava o binomio ERRADO -- unit velha com codigo novo --
  # e o resultado dela nao queria dizer nada:
  #
  #   - se a unit velha chamava algo que o codigo novo nao tem mais (foi o caso, com
  #     `gamebroker.wsgi:criar_app_de_ambiente()`), a sonda falha, o install-release faz
  #     rollback e o script morre AQUI, justamente antes do passo que consertaria a unit.
  #     O deploy fica sem saida: nao ha como chegar na unit nova;
  #   - e se o layout velho ainda estivesse importavel, a sonda PASSA contra o codigo
  #     velho e o deploy se declara bem-sucedido sem ter trocado nada.
  #
  # Nesta ordem a sonda ve unit nova, env novo e codigo novo, e o rollback dela volta
  # para um estado que de fato funcionava.
  publish_release
  # Depois do publish de proposito: importa `gamepanel` de ${APP_DIR}/current, que so
  # existe a partir dali. As migrations de esquema correm neste import -- e com a unit
  # ja certa, quem as roda e o processo NOVO, que ja esta servindo. Na ordem antiga o
  # processo velho continuava no ar com SQL em portugues enquanto o banco ja tinha sido
  # renomeado, e ele despejava `no such column: nome` por alguns segundos.
  bootstrap_admin_user
  start_panel
  apply_panel_firewall
  authorize_in_game_cts
  print_summary
}

main "$@"
