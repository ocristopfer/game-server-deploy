# shellcheck shell=bash
# Installation phases that run INSIDE the game container.
#
# This is NOT an executable script: it is a library loaded with `source` by two callers, and each
# one defines the TRANSPORT of the phases (how a command reaches the CT):
#
#   provision-game-lxc.sh  (Proxmox host)  run_ct = `pct exec CT -- bash -lc`
#   lib/ct-install.sh      (inside the CT) run_ct = local `bash -lc`  (used by the broker)
#
# One installer, two transports: changing a phase applies to both paths, and the manual
# deploy and the broker's deploy do not silently diverge.
#
# The caller must provide, BEFORE the source:
#   functions  msg warn die run_ct push_file_to_ct install_helper
#   constants  STEAMCMD_URL STEAMCMD_DIR GAME_DIR FIREWALL_SCRIPT (the lib/ct-firewall.sh on its side)
#              PANEL_ACCESS_SCRIPT (the lib/ct-panel-access.sh on its side)
#   variables  those of game.env (GAME_KEY, STEAM_APP_ID, START_*, PRE/POST_INSTALL_CMD...)
# and call `resolve_game_variables` before any phase.

# Reads what game.env defines and computes what the phases derive from it. Only GAME decisions:
# no CTID, network or storage (that belongs to the host, see resolve_variables in the provision).
resolve_game_variables() {
  [[ -n "${GAME_KEY:-}" ]] || die "GAME_KEY nao definido no game.env"
  [[ -n "${STEAM_APP_ID:-}" ]] || die "STEAM_APP_ID nao definido no game.env"

  AUTO_UPDATE="${AUTO_UPDATE:-1}"
  UPDATE_SCHEDULE="${UPDATE_SCHEDULE:-*-*-* 06:00:00}"

  GAME_DISPLAY_NAME="${GAME_DISPLAY_NAME:-$GAME_KEY}"
  GAME_PORT="${GAME_PORT:-}"
  GAME_PORTS="${GAME_PORTS:-}"
  QUERY_PORT="${QUERY_PORT:-0}"
  EXTRA_PORT="${EXTRA_PORT:-0}"
  # Named recipes (CLOSED list in apply_recipes) - the way a game registered through the
  # API asks for a special installation without writing shell. Empty for the usual games/*.env.
  RECIPES="${RECIPES:-}"
  START_SCRIPT="${START_SCRIPT:-}"
  START_ARGS="${START_ARGS:-}"
  PRE_INSTALL_CMD="${PRE_INSTALL_CMD:-}"
  POST_INSTALL_CMD="${POST_INSTALL_CMD:-}"
  SERVICE_NAME="${GAME_KEY}.service"

  # Games without a native Linux build (e.g. Enshrouded) must download the Windows build
  # and run it through Wine. The flag has to come BEFORE +login in SteamCMD.
  STEAM_PLATFORM="${STEAM_PLATFORM:-}"
  if [[ -n "$STEAM_PLATFORM" ]]; then
    STEAMCMD_PLATFORM_ARG="+@sSteamCmdForcePlatformType ${STEAM_PLATFORM} "
  else
    STEAMCMD_PLATFORM_ARG=""
  fi

  # ----- Runtime for Windows .exe files (empty = native Linux game) -----
  # wine   = the distro package. Simple, but without esync/fsync: every Windows
  #          synchronization primitive becomes an expensive syscall, and that shows up
  #          as a bottleneck in games with many threads.
  # proton = Proton-GE build downloaded from GitHub. Ships its own wine with fsync
  #          (futex_waitv, kernel >= 5.16) on by default, which is the real gain.
  # Both expose the same command inside the CT: win-run <exe> [args].
  WINDOWS_RUNTIME="${WINDOWS_RUNTIME:-}"
  case "$WINDOWS_RUNTIME" in
    ""|wine|proton) ;;
    *) die "WINDOWS_RUNTIME invalido: '${WINDOWS_RUNTIME}' (use wine, proton ou deixe vazio)" ;;
  esac
  # PINNED version on purpose: 'latest' would make the server switch runtime on its own
  # in any redeploy, and a Proton regression is hard to diagnose afterwards.
  PROTON_VERSION="${PROTON_VERSION:-GE-Proton11-5}"
  PROTON_DIR="/opt/proton/${PROTON_VERSION}"
  # Conservative default. Disabling explorer.exe/services.exe saves processes on a
  # headless server, but breaks games that open a window (e.g. Icarus) - so it is
  # a decision for each games/<game>.env, not a default.
  WINE_DLL_OVERRIDES="${WINE_DLL_OVERRIDES:-mscoree,mshtml=}"
  # The value is written between single quotes in /etc/game-runtime.env; a single
  # quote here would break the file and only show up as an error when the game starts.
  case "$WINE_DLL_OVERRIDES" in
    *\'*) die "WINE_DLL_OVERRIDES nao pode conter aspa simples (')." ;;
  esac
  # 1 when the .exe insists on creating a window even though it is a server.
  WINDOWS_RUNTIME_XVFB="${WINDOWS_RUNTIME_XVFB:-0}"
  WINE_PREFIX_DIR="${WINE_PREFIX_DIR:-/home/steam/.wine-${GAME_KEY}}"
  PROTON_PREFIX_DIR="${PROTON_PREFIX_DIR:-/home/steam/.proton-${GAME_KEY}}"

  # Almost every dedicated server downloads with an anonymous login. Some (DayZ) keep the
  # server depot behind an account that owns the game - game.env flags it with
  # STEAM_ANONYMOUS=0 and the credentials come from .env (deploy.env), never from game.env.
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
    # The values go into a `su - steam -c '...'`; a single quote would break the line
    case "${STEAM_USER}${STEAM_PASS}${STEAM_GUARD_CODE}" in
      *\'*) die "STEAM_USER/STEAM_PASS/STEAM_GUARD_CODE nao podem conter aspa simples (')." ;;
    esac
    STEAMCMD_GUARD=""
    [[ -n "$STEAM_GUARD_CODE" ]] && STEAMCMD_GUARD=" ${STEAM_GUARD_CODE}"
    STEAMCMD_LOGIN="+login ${STEAM_USER} ${STEAM_PASS}${STEAMCMD_GUARD}"
    # After the first login SteamCMD keeps the token in ~steam/Steam/config/config.vdf.
    # The helpers inside the CT use only the user - the password is not stored in there.
    STEAMCMD_LOGIN_CACHED="+login ${STEAM_USER}"
    # Without a valid token SteamCMD would ask for the password and hang; the timer has
    # no one to answer, so the helpers run with a deadline and without stdin.
    STEAMCMD_TIMEOUT_UPDATE="timeout 7200 "
    STEAMCMD_TIMEOUT_INFO="timeout 300 "
  fi
}

install_base_packages_in_ct() {
  msg "Instalando pacotes base no CT (dependencias do SteamCMD)"
  run_ct "
    export DEBIAN_FRONTEND=noninteractive
    missing=''
    # libatomic1: the Euro Truck Simulator 2 server (and American Truck's, same engine) does not
    # load without it ('libatomic.so.1: cannot open shared object file'), and a game registered
    # through the panel has no way to ask for a package. It is small and from Debian itself, so
    # it goes into every CT.
    # sudo: the panel logs in as gamepanel and reaches steam and the root helpers through it
    # (lib/ct-panel-access.sh). The Debian 13 template does not ship it.
    for pkg in ca-certificates curl lib32gcc-s1 lib32stdc++6 libatomic1 locales sudo; do
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

# Where the access piece lives inside the CT. It stays there (root-only, not a sudo helper): the
# broker's final cleanup runs its `lock`, and the future migration/helper update reuses it.
PANEL_ACCESS_IN_CT=/usr/local/lib/gamepanel/ct-panel-access.sh

setup_panel_access() {
  # Gets the CT ready to be controlled by the admin panel, which talks SSH directly to each game
  # container - as the unprivileged `gamepanel` user, never as root (lib/ct-panel-access.sh).
  # Without PANEL_PUBKEY, nothing is installed. Runs AFTER ensure_steam_user: the sudo rule
  # "gamepanel may act as steam" points at that user.
  [[ -n "${PANEL_PUBKEY:-}" ]] || return 0
  case "$PANEL_PUBKEY" in
    *\'*) die "PANEL_PUBKEY nao pode conter aspa simples (')." ;;
  esac
  [[ -f "${PANEL_ACCESS_SCRIPT:-}" ]] || die "ct-panel-access.sh nao encontrado (${PANEL_ACCESS_SCRIPT:-vazio})"
  msg "Habilitando acesso do painel administrativo via SSH (usuario gamepanel)"
  run_ct "
    set -e
    if ! command -v sshd >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq && apt-get install -y -qq openssh-server
    fi
    systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd
  "
  push_file_to_ct "$PANEL_ACCESS_SCRIPT" "$PANEL_ACCESS_IN_CT" 0755
  run_ct "bash ${PANEL_ACCESS_IN_CT} install '${SERVICE_NAME}' '${PANEL_PUBKEY}'" \
    || die "Falha preparando o acesso do painel (usuario gamepanel, sudo e helpers)"
}

# Refuses root over SSH: from here on the panel only gets in as gamepanel. LAST phase of the host
# path (`pct exec` does not need SSH, so nothing after this depends on root login). The broker
# does NOT call this from ct-install.sh: its own SSH session is root, and it locks in the same
# final command that removes its key (gamebroker/runtime/ssh_installer.py, _cleanup).
# The piece verifies first that gamepanel really reaches steam and the helpers; if not, nothing is
# locked and the deploy fails here, with root still open for whoever fixes it.
lock_root_login() {
  [[ -n "${PANEL_PUBKEY:-}" ]] || return 0
  msg "Trancando o login do root por SSH (o painel entra como gamepanel)"
  run_ct "bash ${PANEL_ACCESS_IN_CT} lock" || die "Nao tranquei o root: o acesso pelo gamepanel nao passou na verificacao"
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

# Installs the Windows runtime (wine or proton) and the win-run command, which is what
# the games' start scripts call. Runs BEFORE PRE_INSTALL_CMD so the game can count on
# the runtime being ready and only take care of what is specific to it.
setup_windows_runtime() {
  [[ -n "$WINDOWS_RUNTIME" ]] || return 0
  msg "Preparando runtime de Windows: ${WINDOWS_RUNTIME}"

  local packages="xz-utils"
  [[ "$WINDOWS_RUNTIME" == "wine" ]] && packages="wine"
  # libvulkan1: the Proton launcher imports vulkan.py, which does CDLL('libvulkan.so.1')
  # on load. Without the loader it does not even start - it dies with OSError before running
  # the game, even on a headless server that will never render anything.
  [[ "$WINDOWS_RUNTIME" == "proton" ]] && packages="python3 xz-utils libvulkan1"
  # xvfb-run needs xauth, which is only a Recommends of xvfb: with
  # --no-install-recommends it would not come along, and the start would die with
  # "xvfb-run: error: xauth command not found".
  [[ "$WINDOWS_RUNTIME_XVFB" == "1" ]] && packages="${packages} xvfb xauth"

  run_ct "
    set -e
    export DEBIAN_FRONTEND=noninteractive
    faltando=''
    for p in ${packages}; do
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
      # --strip-components=1: the tarball has a root directory whose name does not follow
      # the tag (GE-Proton11-5 becomes GE-Proton11-5-x86_64). Extracting the contents straight
      # into PROTON_DIR keeps the path predictable whatever that name is.
      tar -xzf \"\$tmp/proton.tar.gz\" -C '${PROTON_DIR}' --strip-components=1
      rm -rf \"\$tmp\"
      [ -x '${PROTON_DIR}/proton' ] || { echo 'ERRO: ${PROTON_DIR}/proton nao existe apos extrair'; ls -la '${PROTON_DIR}'; exit 1; }
      chmod -R a+rX '${PROTON_DIR}'
      echo 'Proton ${PROTON_VERSION} instalado'
    " || die "Falha instalando o Proton ${PROTON_VERSION}"
  fi

  # Configuration read by win-run. It lives outside the script so the runtime can be
  # switched without rewriting the executable.
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
# Generated by the deploy - do not edit by hand (the next deploy overwrites it).
# Values are single-quoted because this file is read with 'source': the
# WINE_DLL_OVERRIDES uses ';' as separator, and unquoted the shell would treat each
# piece after the ';' as a command ("services.exe=d: command not found").
RUNTIME='${WINDOWS_RUNTIME}'
GAME_KEY='${GAME_KEY}'
PROTON_DIR='${PROTON_DIR}'
PROTON_PREFIX='${PROTON_PREFIX_DIR}'
WINE_PREFIX='${WINE_PREFIX_DIR}'
WINE_DLL_OVERRIDES='${WINE_DLL_OVERRIDES}'
USE_XVFB='${WINDOWS_RUNTIME_XVFB}'
EOF
  push_file_to_ct "$tmp_file" "/etc/game-runtime.env" 0644
  rm -f "$tmp_file"

  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<'EOF'
#!/usr/bin/env bash
# win-run <exe> [args...] - runs a Windows .exe with the runtime configured
# at deploy time (wine or proton). Installed by provision-game-lxc.sh.
set -Eeuo pipefail

[ -r /etc/game-runtime.env ] || { echo "win-run: /etc/game-runtime.env ausente"; exit 1; }
# shellcheck disable=SC1091
. /etc/game-runtime.env

[ $# -ge 1 ] || { echo "uso: win-run <exe> [args...]"; exit 2; }
exe="$1"; shift
[ -f "$exe" ] || { echo "win-run: executavel nao encontrado: $exe"; exit 1; }

export HOME="${HOME:-/home/steam}"

# A systemd service does not go through PAM, so nobody creates XDG_RUNTIME_DIR and
# libwayland-client floods the journal with "XDG_RUNTIME_DIR is invalid or not set".
export XDG_RUNTIME_DIR="/tmp/.xdg-${GAME_KEY}-$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

# fixme-all and not -all: the "err:" lines are the only clue when the .exe dies
# before writing a log of its own.
export WINEDEBUG="${WINEDEBUG:-fixme-all}"
export WINEDLLOVERRIDES="${WINE_DLL_OVERRIDES:-mscoree,mshtml=}"

# ntsync implements the NT primitives in the kernel and is faster than
# fsync. The device existing is not enough: in Proton it is opt-in via a variable. When
# /dev/ntsync is not exposed to the container, it stays on fsync without complaining.
if [ -e /dev/ntsync ] && [ -w /dev/ntsync ]; then
  export PROTON_USE_NTSYNC="${PROTON_USE_NTSYNC:-1}"
  export WINE_NTSYNC="${WINE_NTSYNC:-1}"
fi

if [ "${RUNTIME}" = "proton" ]; then
  # Proton expects the Steam layout: a compat directory (where the pfx is created) and
  # a "client install path". The second one only needs to exist.
  export STEAM_COMPAT_DATA_PATH="${PROTON_PREFIX}"
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="${HOME}/.steam/steam"
  mkdir -p "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_CLIENT_INSTALL_PATH"
  [ -x "${PROTON_DIR}/proton" ] || { echo "win-run: ${PROTON_DIR}/proton ausente"; exit 1; }

  # THESE TWO LINES ARE WHAT MAKES A DEDICATED SERVER WORK UNDER PROTON.
  # By default Proton injects the steam.exe shim, which waits for a live Steam client
  # to complete a handshake. Without a client (our case), the server hangs
  # forever blocked on pipe_read: process up, 34MB, zero CPU, no port, without
  # even writing the game log.
  # Proton itself has the bypass: with UMU_ID set and the executable on a
  # WINDOWS path, it goes through "Executable is inside wine prefix, launching normally"
  # and calls wine directly, with no shim at all.
  # UMU_ID must be the game's REAL appid, not any value: Proton
  # propagates it as SteamAppId, and with 0 the Steam game server API fails. Icarus
  # logged "[AppId: 0] Game Server API initialized 0" and never opened the query
  # port - server up, invisible in the browser and with no count in the panel.
  # The appid comes from the steam_appid.txt shipped next to the executable.
  if [ -z "${UMU_ID:-}" ]; then
    arq_appid="$(dirname "$exe")/steam_appid.txt"
    if [ -r "$arq_appid" ]; then
      UMU_ID="$(tr -d '\r\n' < "$arq_appid")"
      export SteamAppId="$UMU_ID" SteamGameId="$UMU_ID"
    fi
  fi
  export UMU_ID="${UMU_ID:-0}"
  exe_win="Z:${exe//\//\\}"
  set -- "${PROTON_DIR}/proton" run "$exe_win" "$@"
else
  export WINEPREFIX="${WINE_PREFIX}"
  export WINEARCH=win64
  mkdir -p "$WINEPREFIX"
  set -- wine "$exe" "$@"
fi

if [ "${USE_XVFB:-0}" = "1" ]; then
  # Some servers create a window even headless; -a picks a free display,
  # which matters when systemd restarts quickly and the previous lock still exists.
  exec xvfb-run -a -s "-screen 0 640x480x24 -nolisten tcp" "$@"
fi
exec "$@"
EOF
  install_helper "win-run" "$tmp_file"
  rm -f "$tmp_file"

  run_ct "install -d -o steam -g steam ${WINE_PREFIX_DIR} ${PROTON_PREFIX_DIR} /home/steam/.steam/steam"

  # Proton's lsteamclient layer looks for the NATIVE steamclient.so in the Steam client
  # paths. Without it the process aborts on an assert. SteamCMD already ships that
  # library, so we point to it - the same trick palworld/satisfactory use with
  # sdk64.
  if [[ "$WINDOWS_RUNTIME" == "proton" ]]; then
    run_ct "
      set -e
      install -d -o steam -g steam /home/steam/.steam/steam/ubuntu12_64 /home/steam/.steam/root/ubuntu12_64 /home/steam/.steam/sdk64
      for target in /home/steam/.steam/steam/ubuntu12_64 /home/steam/.steam/root/ubuntu12_64 /home/steam/.steam/sdk64; do
        ln -sf ${STEAMCMD_DIR}/linux64/steamclient.so \"\$target/steamclient.so\"
      done
      chown -R steam:steam /home/steam/.steam
    " || die "Falha preparando os symlinks de steamclient.so para o Proton"
  fi
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
    warn "de novo com o codigo do momento: .\\deploy\\game\\deploy-game.ps1 -Game ${GAME_KEY} -SteamGuardCode 12345"
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

# Named recipes: the list is CLOSED here, on purpose. A game registered through the API picks
# recipes, it never writes shell (PRE/POST_INSTALL_CMD only exists in the games/*.env reviewed
# in git). An unknown recipe fails the installation instead of being silently ignored.
apply_recipes() {
  local recipes r
  IFS=' ' read -ra recipes <<<"${RECIPES:-}"
  for r in "${recipes[@]}"; do
    case "$r" in
      steamclient-sdk64)
        msg "Receita steamclient-sdk64: ligando a steamclient.so do SteamCMD ao SDK do jogo"
        run_ct "
          set -e
          # The parent (.steam) also belongs to steam: `install -d` only sets the owner of the last
          # level, and a root-owned ~/.steam would leave SteamCMD itself unable to write there.
          install -d -o steam -g steam /home/steam/.steam /home/steam/.steam/sdk64
          ln -sf ${STEAMCMD_DIR}/linux64/steamclient.so /home/steam/.steam/sdk64/steamclient.so
          chown -h steam:steam /home/steam/.steam/sdk64/steamclient.so
        "
        ;;
      wine|proton|xvfb) ;;  # Windows runtime and virtual X: setup_windows_runtime handles them
      *) die "Receita desconhecida: ${r}" ;;
    esac
  done
}

render_update_helper() {
  msg "Criando helper de atualizacao (/usr/local/bin/update-game)"
  local tmp_file
  tmp_file="$(mktemp)"
  cat > "$tmp_file" <<EOF
#!/usr/bin/env bash
# Updates ${GAME_DISPLAY_NAME} and restarts the service.
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
# Compares the installed buildid with the latest one on Steam.
# Only stops/updates/restarts the server when there is a real update.
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
# Control of the ${GAME_DISPLAY_NAME} server (${SERVICE_NAME}).
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
  # {QUERY_PORT}: a game that shifts ports (several instances) must tell the server BOTH.
  # No games/*.env uses the marker, so the old deploy does not change.
  rendered_args="${rendered_args//\{QUERY_PORT\}/${QUERY_PORT}}"
  # {EXTRA_PORT}: the third port the game accepts as an argument (Satisfactory's "reliable"
  # one, -ReliablePort). Without an extra port the marker does not exist in START_ARGS.
  rendered_args="${rendered_args//\{EXTRA_PORT\}/${EXTRA_PORT}}"
  # Proton's esync/fsync create one descriptor per synchronization object; with the
  # default limit (1024) the server dies with "failed to create eventfd" under load.
  local extra_limits=""
  [[ -n "$WINDOWS_RUNTIME" ]] && extra_limits=$'LimitNOFILE=1048576\n'
  # A .exe in START_SCRIPT (a Windows game registered through the panel, which has no
  # POST_INSTALL_CMD to write a .sh wrapper like the curated ones) goes through win-run.
  # Without this ExecStart pointed at the .exe itself: the kernel cannot execute it, and the
  # service died with "Exec format error" right after a "successful" installation.
  local exec_start="${GAME_DIR}/${START_SCRIPT}"
  if [[ -n "$WINDOWS_RUNTIME" && "${START_SCRIPT,,}" == *.exe ]]; then
    exec_start="/usr/local/bin/win-run ${GAME_DIR}/${START_SCRIPT}"
  fi
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
ExecStart=${exec_start} ${rendered_args}
Restart=on-failure
RestartSec=10
${extra_limits}

[Install]
WantedBy=multi-user.target
EOF
  push_file_to_ct "$tmp_file" "/etc/systemd/system/${SERVICE_NAME}" 0644
  rm -f "$tmp_file"
  run_ct "chmod +x ${GAME_DIR}/${START_SCRIPT} && chown -R steam:steam ${GAME_DIR}"
  run_ct "systemctl daemon-reload && systemctl enable ${SERVICE_NAME}"
}

# Firewall inside the CT (lib/ct-firewall.sh, role "game"): game ports open to anyone,
# SSH and ping only from the panel/broker, and no outbound traffic to the internal network.
#
# LAST on purpose: the earlier phases download from the internet (apt, SteamCMD, Proton), and
# a wrong outbound rule would break the installation halfway, without saying why. Through the
# broker, the SSH session running this is already open, and `established` does NOT keep it: it
# was born before conntrack tracked anything in the CT. What keeps it is the SSH reply rule for
# FW_MGMT_SOURCES in ct-firewall.sh (without it the V Rising installation hung here). The key
# cleanup that comes afterwards needs the broker IP in FW_MGMT_SOURCES - install.env ensures it.
#
# Without FW_MGMT_SOURCES the firewall is NOT applied (with a warning): applying it without
# knowing who the panel is would lock the panel itself out of the server that was just born.
setup_firewall() {
  if [[ "${CT_FIREWALL:-1}" == "0" ]]; then
    warn "CT_FIREWALL=0: firewall do CT NAO configurado"
    return 0
  fi
  if [[ -z "${FW_MGMT_SOURCES:-}" ]]; then
    warn "FW_MGMT_SOURCES vazio: firewall do CT NAO configurado (defina o IP do painel)"
    return 0
  fi
  [[ -f "${FIREWALL_SCRIPT:-}" ]] || die "ct-firewall.sh nao encontrado (${FIREWALL_SCRIPT:-vazio})"
  msg "Aplicando o firewall do CT (nftables)"
  local conf
  conf="$(mktemp)"
  {
    printf 'FW_ROLE=game\n'
    printf 'FW_MGMT_SOURCES="%s"\n' "$FW_MGMT_SOURCES"
    printf 'FW_GAME_PORTS="%s"\n' "$GAME_PORTS"
    # The GAME port, so the panel can count who is talking to it. Left out when the query
    # shares the port (Enshrouded): there every server browser asking about the game would
    # count as a player - and that game already counts through the query.
    if [[ -n "$GAME_PORT" && "$GAME_PORT" != "$QUERY_PORT" ]]; then
      printf 'FW_PRESENCE_PORTS="%s"\n' "$GAME_PORT"
    fi
  } > "$conf"
  push_file_to_ct "$FIREWALL_SCRIPT" /usr/local/sbin/ct-firewall 0755
  push_file_to_ct "$conf" /etc/ct-firewall.env 0644
  rm -f "$conf"
  run_ct "/usr/local/sbin/ct-firewall apply"
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
