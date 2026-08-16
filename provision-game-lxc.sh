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
  local cmd="$2"
  # O comando que falhou pode ser a linha do SteamCMD com a senha da conta Steam
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
  PRE_INSTALL_CMD="${PRE_INSTALL_CMD:-}"
  POST_INSTALL_CMD="${POST_INSTALL_CMD:-}"
  SERVICE_NAME="${GAME_KEY}.service"

  # Jogos sem build nativo Linux (ex.: Enshrouded) precisam baixar o build Windows
  # e rodar via Wine. O flag tem que vir ANTES do +login no SteamCMD.
  STEAM_PLATFORM="${STEAM_PLATFORM:-}"
  if [[ -n "$STEAM_PLATFORM" ]]; then
    STEAMCMD_PLATFORM_ARG="+@sSteamCmdForcePlatformType ${STEAM_PLATFORM} "
  else
    STEAMCMD_PLATFORM_ARG=""
  fi

  # ----- Runtime para .exe de Windows (vazio = jogo nativo Linux) -----
  # wine   = pacote da distro. Simples, mas sem esync/fsync: cada primitiva de
  #          sincronizacao do Windows vira syscall cara, e isso aparece como gargalo
  #          em jogo com muitas threads.
  # proton = build do Proton-GE baixado do GitHub. Traz o proprio wine com fsync
  #          (futex_waitv, kernel >= 5.16) ligado por padrao, que e o ganho real.
  # Os dois expoem o mesmo comando dentro do CT: win-run <exe> [args].
  WINDOWS_RUNTIME="${WINDOWS_RUNTIME:-}"
  case "$WINDOWS_RUNTIME" in
    ""|wine|proton) ;;
    *) die "WINDOWS_RUNTIME invalido: '${WINDOWS_RUNTIME}' (use wine, proton ou deixe vazio)" ;;
  esac
  # Versao FIXA de proposito: 'latest' faria o servidor trocar de runtime sozinho
  # num redeploy qualquer, e regressao de Proton e dificil de diagnosticar depois.
  PROTON_VERSION="${PROTON_VERSION:-GE-Proton11-5}"
  PROTON_DIR="/opt/proton/${PROTON_VERSION}"
  # Padrao conservador. Desligar explorer.exe/services.exe economiza processo em
  # servidor headless, mas quebra jogo que abre janela (ex.: Icarus) - por isso e
  # decisao de cada games/<jogo>.env, nao um default.
  WINE_DLL_OVERRIDES="${WINE_DLL_OVERRIDES:-mscoree,mshtml=}"
  # 1 quando o .exe insiste em criar janela mesmo sendo servidor.
  WINDOWS_RUNTIME_XVFB="${WINDOWS_RUNTIME_XVFB:-0}"
  WINE_PREFIX_DIR="${WINE_PREFIX_DIR:-/home/steam/.wine-${GAME_KEY}}"
  PROTON_PREFIX_DIR="${PROTON_PREFIX_DIR:-/home/steam/.proton-${GAME_KEY}}"

  # Quase todo servidor dedicado baixa com login anonimo. Alguns (DayZ) tem o depot
  # do servidor atras de uma conta que possua o jogo - o game.env marca com
  # STEAM_ANONYMOUS=0 e as credenciais vem do .env (deploy.env), nunca do game.env.
  STEAM_ANONYMOUS="${STEAM_ANONYMOUS:-1}"
  STEAM_USER="${STEAM_USER:-}"
  STEAM_PASS="${STEAM_PASS:-}"
  STEAM_GUARD_CODE="${STEAM_GUARD_CODE:-}"

  if [[ "$STEAM_ANONYMOUS" == "1" ]]; then
    STEAMCMD_LOGIN="+login anonymous"
    STEAMCMD_LOGIN_CACHED="+login anonymous"
    STEAMCMD_GUARD=""
    STEAMCMD_TIMEOUT_UPDATE=""
    STEAMCMD_TIMEOUT_INFO=""
  else
    [[ -n "$STEAM_USER" ]] || die "${GAME_DISPLAY_NAME} nao aceita login anonimo na Steam. Preencha STEAM_USER e STEAM_PASS no .env com uma conta que POSSUA o jogo."
    [[ -n "$STEAM_PASS" ]] || die "STEAM_PASS vazio (necessario para o primeiro login de ${STEAM_USER} na Steam)."
    # Os valores entram num `su - steam -c '...'`; uma aspa simples quebraria a linha
    case "${STEAM_USER}${STEAM_PASS}${STEAM_GUARD_CODE}" in
      *\'*) die "STEAM_USER/STEAM_PASS/STEAM_GUARD_CODE nao podem conter aspa simples (')." ;;
    esac
    STEAMCMD_GUARD=""
    [[ -n "$STEAM_GUARD_CODE" ]] && STEAMCMD_GUARD=" ${STEAM_GUARD_CODE}"
    STEAMCMD_LOGIN="+login ${STEAM_USER} ${STEAM_PASS}${STEAMCMD_GUARD}"
    # Depois do primeiro login o SteamCMD guarda o token em ~steam/Steam/config/config.vdf.
    # Os helpers dentro do CT usam so o usuario - a senha nao fica gravada la dentro.
    STEAMCMD_LOGIN_CACHED="+login ${STEAM_USER}"
    # Sem token valido o SteamCMD pediria a senha e ficaria parado; o timer nao tem
    # quem responda, entao os helpers rodam com prazo e sem stdin.
    STEAMCMD_TIMEOUT_UPDATE="timeout 7200 "
    STEAMCMD_TIMEOUT_INFO="timeout 300 "
  fi

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

# Instala o runtime de Windows (wine ou proton) e o comando win-run, que e o que
# os scripts de start dos jogos chamam. Roda ANTES do PRE_INSTALL_CMD para o jogo
# poder contar com o runtime pronto e so cuidar do que e especifico dele.
setup_windows_runtime() {
  [[ -n "$WINDOWS_RUNTIME" ]] || return 0
  msg "Preparando runtime de Windows: ${WINDOWS_RUNTIME}"

  local pacotes="xz-utils"
  [[ "$WINDOWS_RUNTIME" == "wine" ]] && pacotes="wine"
  [[ "$WINDOWS_RUNTIME" == "proton" ]] && pacotes="python3 xz-utils"
  # xvfb-run precisa do xauth, que e apenas Recommends do xvfb: com
  # --no-install-recommends ele nao viria, e o start morreria com
  # "xvfb-run: error: xauth command not found".
  [[ "$WINDOWS_RUNTIME_XVFB" == "1" ]] && pacotes="${pacotes} xvfb xauth"

  run_ct "
    set -e
    export DEBIAN_FRONTEND=noninteractive
    faltando=''
    for p in ${pacotes}; do
      dpkg -s \"\$p\" >/dev/null 2>&1 || faltando=\"\$faltando \$p\"
    done
    if [ -n \"\$faltando\" ]; then
      apt-get update
      apt-get install -y --no-install-recommends \$faltando
    else
      echo 'Pacotes do runtime ja instalados'
    fi
  " || die "Falha instalando pacotes do runtime ${WINDOWS_RUNTIME}"

  if [[ "$WINDOWS_RUNTIME" == "wine" ]]; then
    run_ct "command -v wine >/dev/null 2>&1" || die "wine nao ficou disponivel no CT"
    run_ct "echo \"Wine: \$(wine --version)\""
  fi

  if [[ "$WINDOWS_RUNTIME" == "proton" ]]; then
    local url="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/${PROTON_VERSION}/${PROTON_VERSION}-x86_64.tar.gz"
    run_ct "
      set -e
      if [ -x '${PROTON_DIR}/proton' ]; then
        echo 'Proton ${PROTON_VERSION} ja instalado'
        exit 0
      fi
      install -d '${PROTON_DIR}'
      tmp=\$(mktemp -d)
      echo 'Baixando ${PROTON_VERSION} (~450MB)...'
      curl -fsSL '${url}' -o \"\$tmp/proton.tar.gz\"
      # --strip-components=1: o tarball tem um diretorio raiz cujo nome nao segue a
      # tag (GE-Proton11-5 vira GE-Proton11-5-x86_64). Extrair o conteudo direto no
      # PROTON_DIR deixa o caminho previsivel qualquer que seja esse nome.
      tar -xzf \"\$tmp/proton.tar.gz\" -C '${PROTON_DIR}' --strip-components=1
      rm -rf \"\$tmp\"
      [ -x '${PROTON_DIR}/proton' ] || { echo 'ERRO: ${PROTON_DIR}/proton nao existe apos extrair'; ls -la '${PROTON_DIR}'; exit 1; }
      chmod -R a+rX '${PROTON_DIR}'
      echo 'Proton ${PROTON_VERSION} instalado'
    " || die "Falha instalando o Proton ${PROTON_VERSION}"
  fi

  # Configuracao lida pelo win-run. Fica fora do script para trocar runtime sem
  # reescrever o executavel.
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
# Gerado pelo deploy - nao edite a mao (o proximo deploy sobrescreve).
RUNTIME=${WINDOWS_RUNTIME}
GAME_KEY=${GAME_KEY}
PROTON_DIR=${PROTON_DIR}
PROTON_PREFIX=${PROTON_PREFIX_DIR}
WINE_PREFIX=${WINE_PREFIX_DIR}
WINE_DLL_OVERRIDES=${WINE_DLL_OVERRIDES}
USE_XVFB=${WINDOWS_RUNTIME_XVFB}
EOF
  push_file_to_ct "$tmp_file" "/etc/game-runtime.env" 0644
  rm -f "$tmp_file"

  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<'EOF'
#!/usr/bin/env bash
# win-run <exe> [args...] - roda um .exe de Windows com o runtime configurado
# no deploy (wine ou proton). Instalado por provision-game-lxc.sh.
set -Eeuo pipefail

[ -r /etc/game-runtime.env ] || { echo "win-run: /etc/game-runtime.env ausente"; exit 1; }
# shellcheck disable=SC1091
. /etc/game-runtime.env

[ $# -ge 1 ] || { echo "uso: win-run <exe> [args...]"; exit 2; }
exe="$1"; shift
[ -f "$exe" ] || { echo "win-run: executavel nao encontrado: $exe"; exit 1; }

export HOME="${HOME:-/home/steam}"

# Servico systemd nao passa por PAM, entao ninguem cria o XDG_RUNTIME_DIR e o
# libwayland-client polui o journal com "XDG_RUNTIME_DIR is invalid or not set".
export XDG_RUNTIME_DIR="/tmp/.xdg-${GAME_KEY}-$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# fixme-all e nao -all: as linhas "err:" sao a unica pista quando o .exe morre
# antes de gerar log proprio.
export WINEDEBUG="${WINEDEBUG:-fixme-all}"
export WINEDLLOVERRIDES="${WINE_DLL_OVERRIDES:-mscoree,mshtml=}"

# ntsync implementa as primitivas do NT dentro do kernel e e mais rapido que o
# fsync. Nao basta o device existir: no Proton ele e opt-in por variavel. Quando o
# /dev/ntsync nao esta exposto ao container, segue no fsync sem reclamar.
if [ -e /dev/ntsync ] && [ -w /dev/ntsync ]; then
  export PROTON_USE_NTSYNC="${PROTON_USE_NTSYNC:-1}"
  export WINE_NTSYNC="${WINE_NTSYNC:-1}"
fi

if [ "${RUNTIME}" = "proton" ]; then
  # O Proton espera o layout do Steam: um diretorio de compat (onde nasce o pfx) e
  # um "client install path". O segundo so precisa existir.
  export STEAM_COMPAT_DATA_PATH="${PROTON_PREFIX}"
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="${HOME}/.steam/steam"
  mkdir -p "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_CLIENT_INSTALL_PATH"
  [ -x "${PROTON_DIR}/proton" ] || { echo "win-run: ${PROTON_DIR}/proton ausente"; exit 1; }
  set -- "${PROTON_DIR}/proton" run "$exe" "$@"
else
  export WINEPREFIX="${WINE_PREFIX}"
  export WINEARCH=win64
  mkdir -p "$WINEPREFIX"
  set -- wine "$exe" "$@"
fi

if [ "${USE_XVFB:-0}" = "1" ]; then
  # Alguns servidores criam janela mesmo headless; -a escolhe um display livre,
  # o que importa quando o systemd reinicia rapido e o lock anterior ainda existe.
  exec xvfb-run -a -s "-screen 0 640x480x24 -nolisten tcp" "$@"
fi
exec "$@"
EOF
  install_helper "win-run" "$tmp_file"
  rm -f "$tmp_file"

  run_ct "install -d -o steam -g steam ${WINE_PREFIX_DIR} ${PROTON_PREFIX_DIR} /home/steam/.steam/steam"
}

run_pre_install() {
  [[ -n "$PRE_INSTALL_CMD" ]] || return 0
  msg "Executando PRE_INSTALL_CMD do jogo dentro do CT"
  run_ct "$PRE_INSTALL_CMD" || die "PRE_INSTALL_CMD falhou (veja a saida acima)"
}

install_game_in_ct() {
  msg "Instalando ${GAME_DISPLAY_NAME} (app ${STEAM_APP_ID}) via SteamCMD - pode demorar (download de varios GB)"
  if [[ -n "$STEAM_PLATFORM" ]]; then
    msg "Forcando plataforma do SteamCMD: ${STEAM_PLATFORM}"
  fi
  if [[ "$STEAM_ANONYMOUS" != "1" ]]; then
    msg "Login na Steam como ${STEAM_USER} (este app nao aceita login anonimo)"
  fi
  run_ct "install -d -o steam -g steam ${GAME_DIR}"

  local attempt
  for attempt in 1 2 3; do
    if run_ct "su - steam -c '${STEAMCMD_DIR}/steamcmd.sh ${STEAMCMD_PLATFORM_ARG}+force_install_dir ${GAME_DIR} ${STEAMCMD_LOGIN} +app_update ${STEAM_APP_ID} validate +quit'"; then
      return 0
    fi
    warn "SteamCMD falhou (tentativa ${attempt}/3), tentando novamente em 10s"
    sleep 10
  done
  if [[ "$STEAM_ANONYMOUS" != "1" ]]; then
    warn "Login com conta: se a saida acima fala em Steam Guard / Two-factor, rode o deploy"
    warn "de novo com o codigo do momento: .\\deploy-game.ps1 -Game ${GAME_KEY} -SteamGuardCode 12345"
  fi
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
${STEAMCMD_TIMEOUT_UPDATE}su - steam -c "${STEAMCMD_DIR}/steamcmd.sh ${STEAMCMD_PLATFORM_ARG}+force_install_dir ${GAME_DIR} ${STEAMCMD_LOGIN_CACHED} +app_update ${STEAM_APP_ID} validate +quit" </dev/null
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

latest=\$(${STEAMCMD_TIMEOUT_INFO}su - steam -c "${STEAMCMD_DIR}/steamcmd.sh ${STEAMCMD_PLATFORM_ARG}${STEAMCMD_LOGIN_CACHED} +app_info_update 1 +app_info_print ${STEAM_APP_ID} +quit" </dev/null \
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
  # esync/fsync do Proton criam um descritor por objeto de sincronizacao; com o
  # limite padrao (1024) o servidor cai com "failed to create eventfd" sob carga.
  local extra_limites=""
  [[ -n "$WINDOWS_RUNTIME" ]] && extra_limites=$'LimitNOFILE=1048576\n'
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
${extra_limites}

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
  setup_panel_access
  ensure_steam_user
  install_steamcmd_in_ct
  setup_windows_runtime
  run_pre_install
  install_game_in_ct
  # post-install roda antes da deteccao porque um jogo pode CRIAR o proprio
  # script de start ali (ex.: wrapper do Wine para builds sem versao Linux)
  run_post_install
  detect_start_script
  render_update_helper
  render_update_checker
  render_service_helpers
  render_systemd_unit
  start_game_service
  print_summary
}

main "$@"
