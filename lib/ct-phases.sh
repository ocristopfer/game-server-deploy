# shellcheck shell=bash
# Fases de instalacao que rodam DENTRO do container do jogo.
#
# NAO e um script executavel: e uma biblioteca lida com `source` por dois chamadores, e cada
# um define o TRANSPORTE das fases (como um comando chega ao CT):
#
#   provision-game-lxc.sh  (host Proxmox)  run_ct = `pct exec CT -- bash -lc`
#   lib/ct-install.sh      (dentro do CT)  run_ct = `bash -lc` local  (usado pelo broker)
#
# Um instalador so, com dois transportes: mexer numa fase vale para os dois caminhos, e o
# deploy manual e o do broker nao divergem em silencio.
#
# O chamador precisa fornecer, ANTES do source:
#   funcoes   msg warn die run_ct push_file_to_ct install_helper
#   constantes STEAMCMD_URL STEAMCMD_DIR GAME_DIR FIREWALL_SCRIPT (o lib/ct-firewall.sh do lado dele)
#   variaveis  as do game.env (GAME_KEY, STEAM_APP_ID, START_*, PRE/POST_INSTALL_CMD...)
# e chamar `resolve_game_variables` antes de qualquer fase.

# Le o que o game.env define e calcula o que as fases derivam dele. So decisoes do JOGO:
# nada de CTID, rede ou storage (isso e do host, ver resolve_variables no provision).
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
  # Receitas nomeadas (lista FECHADA em apply_recipes) - o jeito de um jogo cadastrado pela
  # API pedir uma instalacao especial sem escrever shell. Vazio para os games/*.env de sempre.
  RECIPES="${RECIPES:-}"
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
  # O valor e gravado entre aspas simples no /etc/game-runtime.env; uma aspa
  # simples aqui quebraria o arquivo e so apareceria como erro no start do jogo.
  case "$WINE_DLL_OVERRIDES" in
    *\'*) die "WINE_DLL_OVERRIDES nao pode conter aspa simples (')." ;;
  esac
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
}

install_base_packages_in_ct() {
  msg "Instalando pacotes base no CT (dependencias do SteamCMD)"
  run_ct "
    export DEBIAN_FRONTEND=noninteractive
    missing=''
    # libatomic1: o servidor do Euro Truck Simulator 2 (e o do American Truck, mesmo motor) nao
    # carrega sem ele ('libatomic.so.1: cannot open shared object file'), e jogo cadastrado pelo
    # painel nao tem como pedir pacote. E pequeno e do proprio Debian, entao vai em todo CT.
    for pkg in ca-certificates curl lib32gcc-s1 lib32stdc++6 libatomic1 locales; do
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

  local packages="xz-utils"
  [[ "$WINDOWS_RUNTIME" == "wine" ]] && packages="wine"
  # libvulkan1: o launcher do Proton importa vulkan.py, que faz CDLL('libvulkan.so.1')
  # na carga. Sem o loader ele nem comeca - morre em OSError antes de rodar o jogo,
  # mesmo em servidor headless que nunca vai renderizar nada.
  [[ "$WINDOWS_RUNTIME" == "proton" ]] && packages="python3 xz-utils libvulkan1"
  # xvfb-run precisa do xauth, que e apenas Recommends do xvfb: com
  # --no-install-recommends ele nao viria, e o start morreria com
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
# Os valores vao entre aspas simples porque este arquivo e lido com 'source': o
# WINE_DLL_OVERRIDES usa ';' como separador, e sem aspas o shell trataria cada
# trecho depois do ';' como um comando ("services.exe=d: command not found").
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

  # ESTAS DUAS LINHAS SAO O QUE FAZ SERVIDOR DEDICADO FUNCIONAR SOB PROTON.
  # Por padrao o Proton injeta o shim steam.exe, que espera um cliente Steam vivo
  # para completar um handshake. Sem cliente (o caso aqui), o servidor trava para
  # sempre bloqueado em pipe_read: processo de pe, 34MB, zero CPU, sem porta, sem
  # nem chegar a escrever o log do jogo.
  # O proprio proton tem o desvio: com UMU_ID definido e o executavel em caminho
  # WINDOWS, ele segue por "Executable is inside wine prefix, launching normally"
  # e chama o wine direto, sem shim nenhum.
  # O UMU_ID precisa ser o appid REAL do jogo, nao um valor qualquer: o Proton o
  # propaga como SteamAppId, e com 0 a API de game server da Steam falha. O Icarus
  # registrava "[AppId: 0] Game Server API initialized 0" e nunca abria a porta de
  # query - servidor de pe, invisivel no navegador e sem contagem no painel.
  # O appid vem do steam_appid.txt que acompanha o executavel.
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
  # Alguns servidores criam janela mesmo headless; -a escolhe um display livre,
  # o que importa quando o systemd reinicia rapido e o lock anterior ainda existe.
  exec xvfb-run -a -s "-screen 0 640x480x24 -nolisten tcp" "$@"
fi
exec "$@"
EOF
  install_helper "win-run" "$tmp_file"
  rm -f "$tmp_file"

  run_ct "install -d -o steam -g steam ${WINE_PREFIX_DIR} ${PROTON_PREFIX_DIR} /home/steam/.steam/steam"

  # A camada lsteamclient do Proton procura a steamclient.so NATIVA nos caminhos do
  # cliente Steam. Sem ela o processo aborta em assert. O SteamCMD ja traz essa
  # biblioteca, entao aponta-se para ela - mesmo truque que palworld/satisfactory
  # usam com o sdk64.
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

# Receitas nomeadas: a lista e FECHADA aqui, de proposito. Um jogo cadastrado pela API escolhe
# receitas, nunca escreve shell (o PRE/POST_INSTALL_CMD so existe nos games/*.env revisados
# no git). Receita desconhecida derruba a instalacao em vez de ser ignorada em silencio.
apply_recipes() {
  local recipes r
  IFS=' ' read -ra recipes <<<"${RECIPES:-}"
  for r in "${recipes[@]}"; do
    case "$r" in
      steamclient-sdk64)
        msg "Receita steamclient-sdk64: ligando a steamclient.so do SteamCMD ao SDK do jogo"
        run_ct "
          set -e
          # O pai (.steam) tambem e do steam: `install -d` so da o dono ao ultimo nivel, e um
          # ~/.steam de root deixaria o proprio SteamCMD sem poder escrever ali.
          install -d -o steam -g steam /home/steam/.steam /home/steam/.steam/sdk64
          ln -sf ${STEAMCMD_DIR}/linux64/steamclient.so /home/steam/.steam/sdk64/steamclient.so
          chown -h steam:steam /home/steam/.steam/sdk64/steamclient.so
        "
        ;;
      wine|proton|xvfb) ;;  # runtime de Windows e X virtual: quem trata e o setup_windows_runtime
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
  # {QUERY_PORT}: um jogo que anda de porta (varias instancias) precisa avisar as DUAS ao
  # servidor. Nenhum games/*.env usa o marcador, entao o deploy antigo nao muda.
  rendered_args="${rendered_args//\{QUERY_PORT\}/${QUERY_PORT}}"
  # {EXTRA_PORT}: a terceira porta que o jogo aceita por argumento (a "confiavel" do
  # Satisfactory, -ReliablePort). Sem porta extra o marcador nao existe no START_ARGS.
  rendered_args="${rendered_args//\{EXTRA_PORT\}/${EXTRA_PORT}}"
  # esync/fsync do Proton criam um descritor por objeto de sincronizacao; com o
  # limite padrao (1024) o servidor cai com "failed to create eventfd" sob carga.
  local extra_limits=""
  [[ -n "$WINDOWS_RUNTIME" ]] && extra_limits=$'LimitNOFILE=1048576\n'
  # Um .exe no START_SCRIPT (jogo de Windows cadastrado pelo painel, que nao tem
  # POST_INSTALL_CMD para escrever um wrapper .sh como os curados) passa pelo win-run.
  # Sem isto o ExecStart apontava o proprio .exe: o kernel nao sabe executa-lo, e o
  # servico morria com "Exec format error" logo depois de uma instalacao "com sucesso".
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

# Firewall de dentro do CT (lib/ct-firewall.sh, papel "game"): portas do jogo abertas para
# qualquer um, SSH e ping so do painel/broker, e nenhuma saida para a rede interna.
#
# Por ULTIMO de proposito: as fases anteriores baixam da internet (apt, SteamCMD, Proton), e
# uma regra de saida errada quebraria a instalacao no meio, sem dizer por que. Pelo broker a
# sessao SSH que roda isto ja esta aberta, e o `established` NAO a mantem: ela nasceu antes de
# o conntrack acompanhar qualquer coisa no CT. Quem a mantem e a regra de resposta do SSH para
# FW_MGMT_SOURCES no ct-firewall.sh (sem ela a instalacao do V Rising travou aqui). A limpeza
# da chave que vem depois precisa do IP do broker em FW_MGMT_SOURCES - o install.env garante.
#
# Sem FW_MGMT_SOURCES o firewall NAO e aplicado (com aviso): aplicar sem saber quem e o painel
# trancaria o proprio painel fora do servidor que acabou de nascer.
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
    # A porta do JOGO, para o painel contar quem esta conversando com ele. Fica de fora
    # quando a consulta divide a porta (Enshrouded): ali todo navegador de servidores que
    # pergunta pelo jogo contaria como jogador - e esse jogo ja conta pela consulta.
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
