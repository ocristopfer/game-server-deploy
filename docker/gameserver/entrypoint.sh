#!/usr/bin/env bash
# Brings up the game server inside the container: installs/updates through SteamCMD,
# prepares the panel's SSH access, starts the game and stays up with sshd in the foreground.
#
# It is the Docker version of provision-game-lxc.sh: it reads the SAME games/<game>.env
# (copied to /etc/game/game.env at build), runs the same PRE/POST_INSTALL_CMD and leaves the
# same shortcuts available. The only difference is who plays the role of systemd (see
# systemctl.sh).
set -Eeuo pipefail

GAME_ENV_FILE=/etc/game/game.env
SERVICE_ENV_FILE=/etc/game/service.env
STEAMCMD_DIR=/opt/steamcmd
GAME_DIR=/opt/game
LOG_DIR=/var/log/game

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n[AVISO] %s\n' "$*" >&2; }
die() { printf '\n[ERRO] %s\n' "$*" >&2; exit 1; }

carregar_definicao() {
  [[ -f "$GAME_ENV_FILE" ]] || die "definicao do jogo ausente ($GAME_ENV_FILE)"
  set -a
  # shellcheck disable=SC1090
  source "$GAME_ENV_FILE"
  set +a

  [[ -n "${GAME_KEY:-}" ]] || die "GAME_KEY nao definido no games/<jogo>.env"
  [[ -n "${STEAM_APP_ID:-}" ]] || die "STEAM_APP_ID nao definido no games/<jogo>.env"

  GAME_DISPLAY_NAME="${GAME_DISPLAY_NAME:-$GAME_KEY}"
  UNIT="${GAME_KEY}.service"
  GAME_PORT="${GAME_PORT:-}"
  START_SCRIPT="${START_SCRIPT:-}"
  START_ARGS="${START_ARGS:-}"
  PRE_INSTALL_CMD="${PRE_INSTALL_CMD:-}"
  POST_INSTALL_CMD="${POST_INSTALL_CMD:-}"
  # 1 = validate the game files on every container start (slower, safer).
  UPDATE_ON_START="${UPDATE_ON_START:-0}"
  AUTO_UPDATE="${AUTO_UPDATE:-1}"
  UPDATE_TIME="${UPDATE_TIME:-06:00}"

  # A game without a native Linux build (Enshrouded) downloads the Windows build and runs via Wine.
  STEAM_PLATFORM="${STEAM_PLATFORM:-}"
  if [[ -n "$STEAM_PLATFORM" ]]; then
    STEAMCMD_PLATFORM_ARG="+@sSteamCmdForcePlatformType ${STEAM_PLATFORM} "
  else
    STEAMCMD_PLATFORM_ARG=""
  fi

  # Almost every dedicated server downloads with anonymous login; DayZ is the exception and
  # reads the account from the container's environment variables (never from
  # games/<game>.env, which goes into git).
  STEAM_ANONYMOUS="${STEAM_ANONYMOUS:-1}"
  STEAM_USER="${STEAM_USER:-}"
  STEAM_PASS="${STEAM_PASS:-}"
  STEAM_GUARD_CODE="${STEAM_GUARD_CODE:-}"

  if [[ "$STEAM_ANONYMOUS" == "1" ]]; then
    STEAMCMD_LOGIN="+login anonymous"
    STEAMCMD_LOGIN_CACHED="+login anonymous"
    STEAM_TIMEOUT_UPDATE=""
    STEAM_TIMEOUT_INFO=""
  else
    [[ -n "$STEAM_USER" ]] || die "${GAME_DISPLAY_NAME} nao aceita login anonimo na Steam: passe STEAM_USER e STEAM_PASS (conta que POSSUA o jogo) no ambiente do container."
    [[ -n "$STEAM_PASS" ]] || die "STEAM_PASS vazio (necessario no primeiro login de ${STEAM_USER})."
    case "${STEAM_USER}${STEAM_PASS}${STEAM_GUARD_CODE}" in
      *\'*) die "STEAM_USER/STEAM_PASS/STEAM_GUARD_CODE nao podem conter aspa simples (')." ;;
    esac
    local guarda=""
    [[ -n "$STEAM_GUARD_CODE" ]] && guarda=" ${STEAM_GUARD_CODE}"
    STEAMCMD_LOGIN="+login ${STEAM_USER} ${STEAM_PASS}${guarda}"
    # After the first login the token stays in /home/steam (volume): the password no
    # longer needs to stay in the container's environment.
    STEAMCMD_LOGIN_CACHED="+login ${STEAM_USER}"
    STEAM_TIMEOUT_UPDATE="timeout 7200 "
    STEAM_TIMEOUT_INFO="timeout 300 "
  fi
}

preparar_pastas() {
  install -d -m 0755 "$LOG_DIR" /run/game /etc/game
  install -d -o steam -g steam "$GAME_DIR" /home/steam
  # The volume is born empty and owned by root; the game runs as steam.
  chown steam:steam "$GAME_DIR" /home/steam
}

grant_panel_access() {
  # The panel logs in over SSH with its public key, as the unprivileged `gamepanel` user - never
  # as root (docs/security-hardening-contract.md). The key arrives through the environment
  # (PANEL_PUBKEY, the deploy-docker.ps1 way) or through a mounted file.
  local key="${PANEL_PUBKEY:-}"
  if [[ -z "$key" && -f /keys/panel.pub ]]; then
    key="$(cat /keys/panel.pub)"
  fi
  ssh-keygen -A >/dev/null
  install -d /run/sshd
  # Root is never authorized here. A container recreated from an older image version may still
  # have the key in /root (the /root folder is not a volume, but a restart keeps it).
  rm -f /root/.ssh/authorized_keys
  # Belt and braces: the drop-in written by `lock` already says this, and wins (Debian's
  # sshd_config includes sshd_config.d at the top), but without a key there is no drop-in.
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
  if [[ -z "$key" ]]; then
    warn "Sem PANEL_PUBKEY: o painel nao vai conseguir entrar neste container ainda."
    warn "Pegue a chave na tela 'Acesso SSH' do painel e recrie o container com ela."
    return 0
  fi
  # The same piece a real CT gets: gamepanel user, sudo rules, gp-service (which here calls the
  # container's systemctl, the supervisor) and the key. `lock` checks that gamepanel reaches steam
  # and the helpers BEFORE writing the sshd drop-in; if it does not, the container fails here,
  # instead of coming up with a panel that cannot get in.
  bash /usr/local/lib/gamepanel/ct-panel-access.sh install "$UNIT" "$key" \
    || die "nao consegui preparar o acesso do painel (usuario gamepanel)"
  bash /usr/local/lib/gamepanel/ct-panel-access.sh lock \
    || die "o acesso pelo gamepanel nao passou na verificacao"
  msg "Chave do painel autorizada (usuario gamepanel; root recusado no SSH)"
}

instalar_jogo() {
  local manifesto="${GAME_DIR}/steamapps/appmanifest_${STEAM_APP_ID}.acf"
  if [[ -f "$manifesto" && "$UPDATE_ON_START" != "1" ]]; then
    msg "${GAME_DISPLAY_NAME} ja instalado (UPDATE_ON_START=1 forca revalidar)"
    return 0
  fi

  msg "Instalando ${GAME_DISPLAY_NAME} (app ${STEAM_APP_ID}) via SteamCMD - pode demorar"
  [[ -n "$STEAM_PLATFORM" ]] && msg "Plataforma forcada no SteamCMD: ${STEAM_PLATFORM}"
  [[ "$STEAM_ANONYMOUS" != "1" ]] && msg "Login na Steam como ${STEAM_USER}"

  local tentativa
  for tentativa in 1 2 3; do
    if setpriv --reuid=steam --regid=steam --init-groups \
         /usr/bin/env HOME=/home/steam \
         "${STEAMCMD_DIR}/steamcmd.sh" ${STEAMCMD_PLATFORM_ARG}+force_install_dir "$GAME_DIR" \
           ${STEAMCMD_LOGIN} +app_update "$STEAM_APP_ID" validate +quit </dev/null; then
      chown -R steam:steam "$GAME_DIR"
      return 0
    fi
    warn "SteamCMD falhou (tentativa ${tentativa}/3), tentando de novo em 10s"
    sleep 10
  done
  if [[ "$STEAM_ANONYMOUS" != "1" ]]; then
    warn "Se a saida acima fala em Steam Guard, refaca o deploy com o codigo do momento:"
    warn "  .\\deploy\\game\\deploy-docker.ps1 -Game ${GAME_KEY} -SteamGuardCode 12345"
  fi
  die "SteamCMD nao instalou o app ${STEAM_APP_ID} apos 3 tentativas"
}

rodar_etapa() {
  local rotulo="$1" comandos="$2"
  [[ -n "$comandos" ]] || return 0
  msg "Executando ${rotulo} do jogo"
  bash -c "$comandos" || die "${rotulo} falhou (veja a saida acima)"
}

detectar_start() {
  if [[ -n "$START_SCRIPT" ]]; then
    [[ -f "${GAME_DIR}/${START_SCRIPT}" ]] || die "Script de start nao encontrado: ${GAME_DIR}/${START_SCRIPT}"
  else
    msg "START_SCRIPT vazio, detectando automaticamente"
    START_SCRIPT="$(find "$GAME_DIR" -maxdepth 1 -name '*.sh' -printf '%f\n' | sort | head -n1)"
    [[ -n "$START_SCRIPT" ]] || die "Nao achei o script de start. Defina START_SCRIPT em games/${GAME_KEY}.env"
    msg "Script de start detectado: $START_SCRIPT"
  fi
  chmod +x "${GAME_DIR}/${START_SCRIPT}" 2>/dev/null || true
}

escrever_service_env() {
  local args="${START_ARGS//\{PORT\}/${GAME_PORT}}"
  cat >"$SERVICE_ENV_FILE" <<EOF
# Generated by the entrypoint on every container start. This is where the container's
# systemctl/journalctl, update-game and the game-* shortcuts get what they need to know.
GAME_UNIT="${UNIT}"
GAME_NAME="${GAME_DISPLAY_NAME}"
GAME_DIR="${GAME_DIR}"
GAME_USER="steam"
GAME_EXEC="${GAME_DIR}/${START_SCRIPT} ${args}"
RESTART_SEC="${RESTART_SEC:-10}"
STEAM_APP_ID="${STEAM_APP_ID}"
STEAMCMD_PLATFORM_ARG="${STEAMCMD_PLATFORM_ARG}"
STEAMCMD_LOGIN_CACHED="${STEAMCMD_LOGIN_CACHED}"
STEAM_TIMEOUT_UPDATE="${STEAM_TIMEOUT_UPDATE}"
STEAM_TIMEOUT_INFO="${STEAM_TIMEOUT_INFO}"
UPDATE_TIME="${UPDATE_TIME}"
EOF
  chmod 0600 "$SERVICE_ENV_FILE"
}

subir_jogo() {
  msg "Iniciando ${UNIT}"
  systemctl start "$UNIT" || die "o servidor nao subiu (veja o log com: game-logs -n 50)"
  sleep 5
  if systemctl is-active --quiet "$UNIT"; then
    msg "Servico ${UNIT} ativo"
  else
    warn "O servico caiu logo apos o start. Ultimas linhas:"
    journalctl -u "$UNIT" -n 40 || true
  fi
}

subir_autoupdate() {
  if [[ "$AUTO_UPDATE" != "1" ]]; then
    msg "AUTO_UPDATE=0: sem checagem automatica de update"
    return 0
  fi
  msg "Update automatico ligado (checa todo dia as ${UPDATE_TIME})"
  setsid nohup /usr/local/bin/game-autoupdate >>"${LOG_DIR}/autoupdate.log" 2>&1 &
}

parada_limpa() {
  # 'docker stop' sends TERM to PID 1: the world has to be saved before exiting.
  msg "Recebi o pedido de parada; desligando ${UNIT}"
  systemctl stop "$UNIT" || true
  exit 0
}

main() {
  carregar_definicao
  preparar_pastas
  grant_panel_access
  rodar_etapa "PRE_INSTALL_CMD" "$PRE_INSTALL_CMD"
  instalar_jogo
  # The post-install runs before the detection because a game may CREATE its own start
  # script there (the Enshrouded Wine wrapper is like that).
  rodar_etapa "POST_INSTALL_CMD" "$POST_INSTALL_CMD"
  detectar_start
  escrever_service_env
  subir_jogo
  subir_autoupdate

  trap parada_limpa TERM INT
  msg "Container pronto: sshd em $(hostname) (o painel entra por aqui)"
  # sshd stays in the foreground, but in the shell's background: without that the trap
  # above would only be processed when sshd exited.
  /usr/sbin/sshd -D -e &
  wait $!
}

main "$@"
