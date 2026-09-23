#!/usr/bin/env bash
# Sobe o servidor de jogo dentro do container: instala/atualiza pelo SteamCMD, prepara
# o acesso do painel por SSH, liga o jogo e fica de pe com o sshd em primeiro plano.
#
# E a versao Docker do provision-game-lxc.sh: le o MESMO games/<jogo>.env (copiado para
# /etc/game/game.env na build), roda os mesmos PRE/POST_INSTALL_CMD e deixa os mesmos
# atalhos disponiveis. O que muda e so quem faz o papel do systemd (veja systemctl.sh).
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
  # 1 = valida os arquivos do jogo a cada start do container (mais lento, mais seguro).
  UPDATE_ON_START="${UPDATE_ON_START:-0}"
  AUTO_UPDATE="${AUTO_UPDATE:-1}"
  UPDATE_TIME="${UPDATE_TIME:-06:00}"

  # Jogo sem build nativo Linux (Enshrouded) baixa o build Windows e roda via Wine.
  STEAM_PLATFORM="${STEAM_PLATFORM:-}"
  if [[ -n "$STEAM_PLATFORM" ]]; then
    STEAMCMD_PLATFORM_ARG="+@sSteamCmdForcePlatformType ${STEAM_PLATFORM} "
  else
    STEAMCMD_PLATFORM_ARG=""
  fi

  # Quase todo servidor dedicado baixa com login anonimo; DayZ e a excecao e le a conta
  # das variaveis de ambiente do container (nunca do games/<jogo>.env, que vai pro git).
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
    # Depois do primeiro login o token fica em /home/steam (volume): a senha nao
    # precisa mais ficar no ambiente do container.
    STEAMCMD_LOGIN_CACHED="+login ${STEAM_USER}"
    STEAM_TIMEOUT_UPDATE="timeout 7200 "
    STEAM_TIMEOUT_INFO="timeout 300 "
  fi
}

preparar_pastas() {
  install -d -m 0755 "$LOG_DIR" /run/game /etc/game
  install -d -o steam -g steam "$GAME_DIR" /home/steam
  # O volume nasce vazio e pertencendo ao root; o jogo roda como steam.
  chown steam:steam "$GAME_DIR" /home/steam
}

liberar_painel() {
  # O painel entra por SSH com a chave publica dele. Ela chega pelo ambiente
  # (PANEL_PUBKEY, o jeito do deploy-docker.ps1) ou por um arquivo montado.
  local chave="${PANEL_PUBKEY:-}"
  if [[ -z "$chave" && -f /keys/panel.pub ]]; then
    chave="$(cat /keys/panel.pub)"
  fi
  install -d -m 700 /root/.ssh
  touch /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
  if [[ -n "$chave" ]]; then
    grep -qF "$chave" /root/.ssh/authorized_keys || echo "$chave" >>/root/.ssh/authorized_keys
    msg "Chave do painel autorizada"
  else
    warn "Sem PANEL_PUBKEY: o painel nao vai conseguir entrar neste container ainda."
    warn "Pegue a chave na tela 'Acesso SSH' do painel e recrie o container com ela."
  fi
  ssh-keygen -A >/dev/null
  install -d /run/sshd
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
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
# Gerado pelo entrypoint a cada start do container. E daqui que o systemctl/journalctl
# do container, o update-game e os atalhos game-* tiram o que precisam saber.
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
  # 'docker stop' manda TERM para o PID 1: o mundo precisa ser salvo antes de sair.
  msg "Recebi o pedido de parada; desligando ${UNIT}"
  systemctl stop "$UNIT" || true
  exit 0
}

main() {
  carregar_definicao
  preparar_pastas
  liberar_painel
  rodar_etapa "PRE_INSTALL_CMD" "$PRE_INSTALL_CMD"
  instalar_jogo
  # O post-install roda antes da deteccao porque um jogo pode CRIAR ali o proprio
  # script de start (o wrapper do Wine do Enshrouded e assim).
  rodar_etapa "POST_INSTALL_CMD" "$POST_INSTALL_CMD"
  detectar_start
  escrever_service_env
  subir_jogo
  subir_autoupdate

  trap parada_limpa TERM INT
  msg "Container pronto: sshd em $(hostname) (o painel entra por aqui)"
  # O sshd fica em primeiro plano, mas em background do shell: sem isso o trap acima
  # so seria processado quando o sshd terminasse.
  /usr/sbin/sshd -D -e &
  wait $!
}

main "$@"
