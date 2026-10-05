#!/bin/bash
# Runs INSIDE the sandbox: proves lib/ct-panel-access.sh with the real sudo, visudo and sshd.
# Exits with the number of failures.
#
#   run-panel-access.sh <repo-mounted-at-/repo>
#
# What is at stake: this file decides what the panel can do as root in every game container.
# A rule too wide is root for whoever steals the panel key; a rule too narrow, or a lock that
# runs before the helper path works, locks the panel out of a live server. Neither shows up in
# pytest - only here, or on a real CT.
set -u
REPO="${1:-/repo}"
PIECE="$REPO/lib/ct-panel-access.sh"
failures=0

ok()   { printf 'OK        %s\n' "$*"; }
fail() { printf 'FALHOU    %s\n' "$*"; failures=$((failures + 1)); }
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (esperado '$2', veio '$3')"; fi
}
allowed() { # description, command... (as gamepanel, through sudo -n)
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n "$@" </dev/null >/dev/null 2>&1; then ok "$d"; else fail "$d (sudo recusou)"; fi
}
denied() { # description, command... (as gamepanel, through sudo -n)
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n "$@" </dev/null >/dev/null 2>&1; then fail "$d (sudo DEIXOU)"; else ok "$d"; fi
}
# sudo -l <cmd> checks the rule WITHOUT running the command (nft does not exist here).
listed() {
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n -l "$@" >/dev/null 2>&1; then ok "$d"; else fail "$d (fora da regra)"; fi
}
not_listed() {
  local d="$1"; shift
  if runuser -u gamepanel -- sudo -n -l "$@" >/dev/null 2>&1; then fail "$d (dentro da regra)"; else ok "$d"; fi
}
key_blob() { cut -d' ' -f2 "$1"; }
# Every file the piece writes, with mode, owner and checksum, plus the user itself.
snapshot() {
  local f
  for f in /etc/sudoers.d/gamepanel /etc/gamepanel/ct.env /usr/local/sbin/gp-service \
           /usr/local/sbin/gp-clamav-ensure /var/lib/gamepanel-agent /var/lib/gamepanel-agent/.ssh \
           /var/lib/gamepanel-agent/.ssh/authorized_keys /etc/ssh/sshd_config.d/10-gamepanel.conf; do
    [ -e "$f" ] && stat -c '%n %a %U:%G' "$f"
    [ -f "$f" ] && sha256sum "$f"
  done
  getent passwd gamepanel
  id -nG gamepanel 2>/dev/null
  ls -A /etc/sudoers.d /etc/gamepanel /usr/local/sbin /etc/ssh/sshd_config.d /etc 2>/dev/null | grep -v '^\(ld.so.cache\|mtab\)$'
}

# ----- the "CT": steam exists (ensure_steam_user runs first), keys for the panel and an admin -----
useradd -m -s /bin/bash steam
work=$(mktemp -d)
ssh-keygen -q -t ed25519 -N '' -C painel@sandbox -f "$work/panel" >/dev/null
ssh-keygen -q -t ed25519 -N '' -C admin@sandbox -f "$work/admin" >/dev/null
panel_key="$(cat "$work/panel.pub")"
# Root has the panel key (the old way) AND an admin key: the lock must remove only the first.
install -d -m 700 /root/.ssh
cat "$work/panel.pub" "$work/admin.pub" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
printf '#!/bin/sh\necho update-game-fake\n' > /usr/local/bin/update-game
printf '#!/bin/sh\necho check-fake\n' > /usr/local/bin/check-game-update
# `sudo -l <cmd>` only answers for a command that exists; the sandbox's fake nft lives in
# /usr/local/sbin, and the rule names the real path.
printf '#!/bin/sh\necho nft-fake\n' > /usr/sbin/nft
chmod 755 /usr/local/bin/update-game /usr/local/bin/check-game-update /usr/sbin/nft
: > /var/log/fake-calls.log
chmod 666 /var/log/fake-calls.log

# ----- input validation: nothing is written on a bad call -----
if bash "$PIECE" install 'ssh.service; rm -rf /' "$panel_key" >/dev/null 2>&1; then
  fail "unidade com ; e recusada"; else ok "unidade com ; e recusada"; fi
if bash "$PIECE" install palworld.service "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIx'y" >/dev/null 2>&1; then
  fail "chave com aspa e recusada"; else ok "chave com aspa e recusada"; fi
if [ -e /etc/sudoers.d/gamepanel ]; then fail "chamada recusada escreveu o sudoers"; else ok "chamada recusada nao escreve nada"; fi
if bash "$PIECE" lock >/dev/null 2>&1; then fail "lock sem gamepanel foi aceito"; else ok "lock sem gamepanel e recusado"; fi
if [ -e /etc/ssh/sshd_config.d/10-gamepanel.conf ]; then fail "lock recusado escreveu o drop-in"; else ok "lock recusado nao escreve o drop-in"; fi

# ----- install -----
if bash "$PIECE" install palworld.service "$panel_key" >"$work/install1.log" 2>&1; then
  ok "install roda"; else fail "install falhou: $(tail -3 "$work/install1.log")"; fi
if visudo -cf /etc/sudoers.d/gamepanel >/dev/null 2>&1; then ok "visudo -cf passa"; else fail "visudo -cf recusou"; fi
check "sudoers 0440 do root" "440 root:root" "$(stat -c '%a %U:%G' /etc/sudoers.d/gamepanel)"
expected_sudoers='Defaults:gamepanel !requiretty, !use_pty, env_reset, !log_output
Cmnd_Alias GP_ROOT = /usr/local/sbin/gp-service start, /usr/local/sbin/gp-service stop, \
  /usr/local/sbin/gp-service restart, /usr/local/sbin/gp-service --version, \
  /usr/local/bin/update-game "", /usr/local/bin/check-game-update "", \
  /usr/sbin/nft -j list set inet ct_firewall players, /usr/local/sbin/gp-clamav-ensure ""
gamepanel ALL=(root)  NOPASSWD: GP_ROOT
gamepanel ALL=(steam) NOPASSWD: ALL'
check "sudoers e o texto do contrato" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"
check "ct.env" "$(printf 'GAME_UNIT=palworld.service\nGP_HELPERS_VERSION=1')" "$(cat /etc/gamepanel/ct.env)"
check "ct.env 0644 do root" "644 root:root" "$(stat -c '%a %U:%G' /etc/gamepanel/ct.env)"
check "gp-service 0755 do root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/sbin/gp-service)"
# Backups are written as steam: the folder must exist and be steam's, or the first backup of a
# CT that never had one dies on mkdir (it happened on a real CT right after migrating).
check "pasta de backup 0750 do steam" "750 steam:steam" "$(stat -c '%a %U:%G' /var/backups/gamepanel)"
check "steam escreve na pasta de backup" "0" "$(runuser -u steam -- touch /var/backups/gamepanel/x 2>/dev/null; echo $?)"
check "gp-clamav-ensure 0755 do root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/sbin/gp-clamav-ensure)"
if bash -n /usr/local/sbin/gp-service && bash -n /usr/local/sbin/gp-clamav-ensure; then
  ok "helpers passam no bash -n"; else fail "helper com erro de sintaxe"; fi
check "gamepanel: home e shell" "/var/lib/gamepanel-agent:/bin/bash" "$(getent passwd gamepanel | cut -d: -f6,7)"
check "home 0700 do gamepanel" "700 gamepanel" "$(stat -c '%a %U' /var/lib/gamepanel-agent)"
if id -nG gamepanel | tr ' ' '\n' | grep -qx systemd-journal; then ok "gamepanel no grupo systemd-journal"; else fail "gamepanel fora do systemd-journal"; fi
if id -nG gamepanel | tr ' ' '\n' | grep -qx steam; then fail "gamepanel NAO pode estar no grupo steam"; else ok "gamepanel fora do grupo steam"; fi
check "chave do painel no gamepanel, com as opcoes" \
  "no-agent-forwarding,no-port-forwarding,no-X11-forwarding ${panel_key}" \
  "$(cat /var/lib/gamepanel-agent/.ssh/authorized_keys)"
check "authorized_keys 0600 do gamepanel" "600 gamepanel" "$(stat -c '%a %U' /var/lib/gamepanel-agent/.ssh/authorized_keys)"

# ----- what gamepanel may do -----
allowed "agir como steam (sudo -n -u steam true)" -u steam true
check "o comando roda COMO steam" steam "$(runuser -u gamepanel -- sudo -n -u steam id -un 2>/dev/null)"
check "gp-service --version" "gp-helpers 1" "$(runuser -u gamepanel -- sudo -n /usr/local/sbin/gp-service --version 2>/dev/null)"
: > /var/log/fake-calls.log
allowed "gp-service restart" /usr/local/sbin/gp-service restart
allowed "gp-service stop" /usr/local/sbin/gp-service stop
allowed "gp-service start" /usr/local/sbin/gp-service start
check "o helper usa a unidade do ct.env" \
  "$(printf 'systemctl restart palworld.service\nsystemctl stop palworld.service\nsystemctl start palworld.service')" \
  "$(cat /var/log/fake-calls.log)"
: > /var/log/fake-calls.log
runuser -u gamepanel -- env GAME_UNIT=ssh.service sudo -n /usr/local/sbin/gp-service restart >/dev/null 2>&1
check "GAME_UNIT do ambiente nao vale" "systemctl restart palworld.service" "$(cat /var/log/fake-calls.log)"
allowed "update-game" /usr/local/bin/update-game
allowed "check-game-update" /usr/local/bin/check-game-update
listed "nft -j list set inet ct_firewall players" /usr/sbin/nft -j list set inet ct_firewall players
listed "gp-clamav-ensure" /usr/local/sbin/gp-clamav-ensure

# ----- what it may NOT do -----
: > /var/log/fake-calls.log
denied "gp-service stop ssh (argumento a mais)" /usr/local/sbin/gp-service stop ssh
denied "gp-service status (verbo fora da lista)" /usr/local/sbin/gp-service status
denied "systemctl stop ssh direto" systemctl stop ssh
denied "systemctl restart palworld.service direto" systemctl restart palworld.service
check "nada chegou ao systemctl" "" "$(cat /var/log/fake-calls.log)"
denied "bash como root" bash -c true
denied "sudo -u root bash" -u root bash -c true
denied "sudo -s" -s true
denied "sudo -i" -i true
not_listed "nft list ruleset" /usr/sbin/nft list ruleset
not_listed "nft flush ruleset" /usr/sbin/nft flush ruleset
# A sudoers command written WITHOUT arguments accepts ANY arguments, so the contract marks the
# helpers that take none with "" - and then it is sudo itself that refuses an extra argument,
# before the program even runs.
denied "gp-clamav-ensure com argumento" /usr/local/sbin/gp-clamav-ensure /etc
denied "update-game com argumento" /usr/local/bin/update-game --force
denied "escrever em /etc/sudoers.d" tee /etc/sudoers.d/x
denied "virar outro usuario (nobody)" -u nobody true

# ----- the helper itself, called by root by hand -----
/usr/local/sbin/gp-service stop ssh >/dev/null 2>&1; check "gp-service stop ssh sai com 2" 2 "$?"
/usr/local/sbin/gp-service >/dev/null 2>&1; check "gp-service sem argumento sai com 2" 2 "$?"
/usr/local/sbin/gp-service reload >/dev/null 2>&1; check "gp-service reload sai com 2" 2 "$?"
/usr/local/sbin/gp-clamav-ensure /etc >/dev/null 2>&1; check "gp-clamav-ensure com argumento sai com 2" 2 "$?"
cp /etc/gamepanel/ct.env "$work/ct.env"
printf 'GAME_UNIT=ssh.service -H x\n' > /etc/gamepanel/ct.env
/usr/local/sbin/gp-service restart >/dev/null 2>&1; check "unidade torta no ct.env sai com 3" 3 "$?"
cp "$work/ct.env" /etc/gamepanel/ct.env
chmod 0666 /etc/gamepanel/ct.env
/usr/local/sbin/gp-service restart >/dev/null 2>&1; check "ct.env gravavel por outros sai com 3" 3 "$?"
chmod 0644 /etc/gamepanel/ct.env

# ----- steam: no sudo at all -----
if runuser -u steam -- sudo -n true >/dev/null 2>&1; then fail "steam tem sudo"; else ok "steam sem sudo"; fi
if runuser -u steam -- sudo -n -u gamepanel true >/dev/null 2>&1; then fail "steam vira gamepanel"; else ok "steam nao vira gamepanel"; fi
if sudo -l -U steam 2>&1 | grep -q 'not allowed'; then ok "sudo -l -U steam: nada"; else fail "sudo -l -U steam lista algo"; fi

# ----- idempotence -----
snapshot > "$work/snap1"
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1 || fail "segunda instalacao falhou"
snapshot > "$work/snap2"
if diff "$work/snap1" "$work/snap2" >/dev/null; then ok "rodar duas vezes nao muda nada"
else fail "a segunda instalacao mudou algo: $(diff "$work/snap1" "$work/snap2" | head -5)"; fi
# A user someone broke by hand is repaired by a rerun.
usermod -s /bin/sh -a -G steam gamepanel
chmod 0755 /var/lib/gamepanel-agent
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1
snapshot > "$work/snap3"
if diff "$work/snap1" "$work/snap3" >/dev/null; then ok "rodar de novo conserta usuario mexido a mao"
else fail "nao consertou: $(diff "$work/snap1" "$work/snap3" | head -5)"; fi
# Key rotation: the new key REPLACES the old one.
ssh-keygen -q -t ed25519 -N '' -C painel2@sandbox -f "$work/panel2" >/dev/null
bash "$PIECE" install palworld.service "$(cat "$work/panel2.pub")" >/dev/null 2>&1
check "chave nova substitui a antiga" 1 "$(wc -l < /var/lib/gamepanel-agent/.ssh/authorized_keys)"
if grep -qF "$(key_blob "$work/panel2.pub")" /var/lib/gamepanel-agent/.ssh/authorized_keys; then
  ok "a chave nova esta la"; else fail "a chave nova nao esta la"; fi
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1

# ----- a broken sudoers never reaches /etc/sudoers.d -----
if (
  # shellcheck source=/dev/null
  source "$PIECE"
  set -Eeuo pipefail
  gp_render_sudoers() { echo 'gamepanel ALL=(root NOPASSWD: ALL'; }
  gp_install_sudoers
) >/dev/null 2>&1; then fail "sudoers quebrado foi aceito"; else ok "sudoers quebrado e recusado pelo visudo"; fi
check "o sudoers bom continua la" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"
check "nenhum temporario sobrou em /etc" "" "$(ls -A /etc | grep '^\.gp-' || true)"
if runuser -u gamepanel -- sudo -n -u steam true >/dev/null 2>&1; then ok "o sudo segue funcionando"; else fail "o sudo quebrou"; fi

# ----- mod environment overlay (phase 6) -----
# What a loader needs in the game's environment goes to two files STEAM owns in a folder ROOT owns.
# The folder being root's is the point: systemd reads the EnvironmentFile as root, and a file steam
# could swap for a symlink would leak root-only files into the game's environment.
ENV_DIR=/etc/gamepanel/game-env
check "pasta do overlay 0755 do root" "755 root:root" "$(stat -c '%a %U:%G' "$ENV_DIR")"
check "service.env 0644 do steam" "644 steam:steam" "$(stat -c '%a %U:%G' "$ENV_DIR/service.env")"
check "runtime.env 0644 do steam" "644 steam:steam" "$(stat -c '%a %U:%G' "$ENV_DIR/runtime.env")"
check "drop-in que entrega o overlay ao servico" \
  "$(printf '[Service]\nEnvironmentFile=-%s' "$ENV_DIR/service.env")" \
  "$(cat /etc/systemd/system/palworld.service.d/gamepanel-env.conf)"
if runuser -u gamepanel -- sudo -n -u steam sh -c "echo 'X_PROVA=1' >> $ENV_DIR/service.env" 2>/dev/null; then
  ok "gamepanel, como steam, escreve no overlay"; else fail "o steam nao escreve no overlay"; fi
sed -i '/^X_PROVA=/d' "$ENV_DIR/service.env"
if runuser -u steam -- ln -sf /etc/shadow "$ENV_DIR/service.env" 2>/dev/null; then
  fail "steam trocou o service.env por um link"; else ok "steam nao troca o arquivo por um link"; fi
if runuser -u steam -- rm -f "$ENV_DIR/runtime.env" 2>/dev/null && [ ! -e "$ENV_DIR/runtime.env" ]; then
  fail "steam apagou o runtime.env"; else ok "steam nao apaga nem cria arquivo na pasta"; fi
if runuser -u steam -- touch "$ENV_DIR/outro.env" 2>/dev/null; then fail "steam criou arquivo na pasta"; else ok "steam nao cria arquivo na pasta"; fi
check "nenhuma regra nova no sudoers" "$expected_sudoers" "$(cat /etc/sudoers.d/gamepanel)"

# A CT migrated with mods a ROOT installer put in place: drop-ins, /etc/game-runtime.env, root
# files in the game folder, a win-run from before the hook. Rerunning `install` converts it.
win_run_new="$(python3 - "$REPO/lib/ct-phases.sh" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
print(re.search(r"<<'EOF'\n(#!/usr/bin/env bash\n# win-run .*?\n)EOF\n", text, re.S).group(1), end="")
PY
)"
printf '%s' "$win_run_new" | python3 -c '
import re, sys
text = sys.stdin.read()
print(re.sub(r"# gamepanel-overlay:.*?\nfi\n", "", text, count=1, flags=re.S), end="")' > /usr/local/bin/win-run
chmod 0755 /usr/local/bin/win-run
if grep -q gamepanel-overlay /usr/local/bin/win-run; then fail "o win-run antigo ainda tem o gancho"; fi
install -d -o steam -g steam /opt/game /home/steam/pfx
printf '[Unit]\nDescription=x\n[Service]\nUser=steam\nWorkingDirectory=/opt/game\nExecStart=/usr/local/bin/win-run /opt/game/x.exe -log\n' \
  > /etc/systemd/system/palworld.service
dropins=/etc/systemd/system/palworld.service.d
printf '[Service]\nEnvironment=LD_PRELOAD=/opt/game/ue4ss/libUE4SS.so\nEnvironment=UE4SS_TARGET_EXE=TheFrontServer\n' \
  > "$dropins/gamepanel-ue4ss.conf"
printf '[Service]\nExecStartPre=/bin/true\n' > "$dropins/gamepanel-feito-a-mao.conf"
# The unit sandbox (lib/ct-sandbox-unit.sh) is not a loader drop-in: install keeps it, silently.
bash "$REPO/lib/ct-sandbox-unit.sh" render > "$dropins/gamepanel-sandbox.conf"
printf '# Written by the game panel\n# gamepanel-base: /usr/local/bin/win-run /opt/game/x.exe -log\n[Service]\nExecStart=\nExecStart=/usr/local/bin/win-run /opt/game/x.exe -log -mods=928988,929420\n' \
  > "$dropins/gamepanel-mods.conf"
printf "RUNTIME='wine'\nGAME_KEY='prova'\nWINE_PREFIX='/home/steam/pfx'\nWINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'\nUSE_XVFB='0'\n" \
  > /etc/game-runtime.env
install -d /opt/game/BepInEx/core
printf '{"full_name": "BepInEx-BepInExPack", "overrides_before": "mscoree,mshtml=", "files": ["BepInEx"]}' \
  > /opt/game/BepInEx/.gamepanel.json
echo dll > /opt/game/BepInEx/core/BepInEx.dll
: > /opt/game/x.exe
chown -R steam:steam /opt/game/x.exe
ln -sfn /etc/shadow /opt/game/link-plantado
chown -h root:root /opt/game/link-plantado
shadow_owner="$(stat -c '%U:%G' /etc/shadow)"

if bash "$PIECE" install palworld.service "$panel_key" >"$work/convert.log" 2>&1; then
  ok "install converte o CT antigo"; else fail "install na conversao falhou: $(tail -3 "$work/convert.log")"; fi
check "variaveis do drop-in do UE4SS no service.env" \
  "LD_PRELOAD='/opt/game/ue4ss/libUE4SS.so'
UE4SS_TARGET_EXE='TheFrontServer'" "$(grep -v '^#' "$ENV_DIR/service.env")"
if [ -e "$dropins/gamepanel-ue4ss.conf" ]; then fail "o drop-in do UE4SS ficou"; else ok "o drop-in do UE4SS saiu"; fi
if [ -e "$dropins/gamepanel-feito-a-mao.conf" ]; then ok "drop-in feito a mao ficou"; else fail "apagou um drop-in feito a mao"; fi
if grep -q 'gamepanel-feito-a-mao.conf' "$work/convert.log"; then ok "o drop-in feito a mao foi avisado"; else fail "sem aviso do drop-in feito a mao"; fi
if [ -e "$dropins/gamepanel-sandbox.conf" ]; then ok "the sandbox drop-in stays"; else fail "deleted the sandbox drop-in"; fi
if grep -q 'gamepanel-sandbox.conf' "$work/convert.log"; then fail "warned about the sandbox drop-in as if it were a loader"; else ok "the sandbox drop-in raises no warning"; fi
if [ -e "$dropins/gamepanel-mods.conf" ]; then fail "o drop-in do ARK ficou"; else ok "o drop-in do ARK saiu"; fi
check "runtime.env com o Wine do carregador e a lista do ARK" \
  "GAMEPANEL_EXTRA_ARGS='-mods=928988,929420'
WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'" "$(grep -v '^#' "$ENV_DIR/runtime.env" | sort)"
check "game-runtime.env volta ao original e mantem o resto" \
  "RUNTIME='wine'
GAME_KEY='prova'
WINE_PREFIX='/home/steam/pfx'
WINE_DLL_OVERRIDES='mscoree,mshtml='
USE_XVFB='0'" "$(cat /etc/game-runtime.env)"
check "win-run migrado e igual ao de um CT novo" "$win_run_new" "$(cat /usr/local/bin/win-run)"
check "win-run 0755 do root" "755 root:root" "$(stat -c '%a %U:%G' /usr/local/bin/win-run)"
check "arquivo do carregador devolvido ao steam" steam "$(stat -c '%U' /opt/game/BepInEx/core/BepInEx.dll)"
check "o link plantado muda de dono, o alvo nao" "steam $shadow_owner" \
  "$(stat -c '%U' /opt/game/link-plantado) $(stat -c '%U:%G' /etc/shadow)"

# win-run really reads the overlay - as steam, and only as steam.
printf '#!/bin/sh\necho "WINEDLLOVERRIDES=$WINEDLLOVERRIDES ARGS=$*"\n' > /usr/local/sbin/wine
chmod 0755 /usr/local/sbin/wine
check "win-run como steam usa o overlay e acrescenta a lista" \
  "WINEDLLOVERRIDES=mshtml=;winhttp=n,b ARGS=/opt/game/x.exe -log -mods=928988,929420" \
  "$(cd /opt/game && runuser -u steam -- env HOME=/home/steam /usr/local/bin/win-run /opt/game/x.exe -log 2>&1)"
check "win-run como root NAO le o arquivo do steam" \
  "WINEDLLOVERRIDES=mscoree,mshtml= ARGS=/opt/game/x.exe -log" \
  "$(cd /opt/game && HOME=/root /usr/local/bin/win-run /opt/game/x.exe -log 2>&1)"

# The installers themselves, as steam, against these real files: what the panel runs in helper mode.
# The workshop installer reads the unit with `systemctl cat`: the fake answers it from the file.
cp /usr/local/sbin/systemctl "$work/systemctl.fake"
cat > /usr/local/sbin/systemctl <<'SH'
#!/bin/bash
if [ "$1" = cat ]; then echo "# /etc/systemd/system/$2"; cat "/etc/systemd/system/$2"; exit; fi
echo "systemctl $*" >> /var/log/fake-calls.log
SH
remote() { # script, args...
  local src="$REPO/src/gamepanel/games/mods/$1"; shift
  runuser -u gamepanel -- sudo -n -u steam -- python3 -c "$(cat "$src")" "$@" 2>&1 | tail -n 1
}
check "UE4SS Linux desligado como steam" '{"enabled": false}' \
  "$(remote ue4ss_linux_remote.py --overlay --unit palworld.service loader-disable /opt/game/Pal/Binaries/Linux)"
check "service.env sem as variaveis do UE4SS" "" "$(grep -v '^#' "$ENV_DIR/service.env")"
check "Shroudtopia ligado como steam" '{"enabled": true}' "$(remote shroudtopia_remote.py --overlay loader-enable /opt/game)"
check "runtime.env com o winmm" "WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b;winmm=n,b'" \
  "$(grep '^WINE_DLL_OVERRIDES=' "$ENV_DIR/runtime.env")"
check "Shroudtopia desligado como steam" '{"enabled": false}' "$(remote shroudtopia_remote.py --overlay loader-disable /opt/game)"
check "base intocada pelo steam" "WINE_DLL_OVERRIDES='mscoree,mshtml='" "$(grep '^WINE_DLL_OVERRIDES=' /etc/game-runtime.env)"
check "ARK sem mods como steam" '{"ids": [], "config": "/etc/gamepanel/game-env/runtime.env"}' \
  "$(remote workshop_remote.py --overlay --unit palworld.service ark set /opt/game)"
check "runtime.env sem a lista" "" "$(grep '^GAMEPANEL_EXTRA_ARGS=' "$ENV_DIR/runtime.env" || true)"
cp "$work/systemctl.fake" /usr/local/sbin/systemctl
check "o steam continua dono dos arquivos do overlay" "steam steam" \
  "$(stat -c '%U' "$ENV_DIR/service.env") $(stat -c '%U' "$ENV_DIR/runtime.env")"

overlay_snapshot() {
  for f in "$ENV_DIR"/* /usr/local/bin/win-run /etc/game-runtime.env "$dropins"/*; do
    stat -c '%n %a %U:%G' "$f"; sha256sum "$f"
  done
}
overlay_snapshot > "$work/ov1"
bash "$PIECE" install palworld.service "$panel_key" >/dev/null 2>&1 || fail "install de novo falhou"
overlay_snapshot > "$work/ov2"
if diff "$work/ov1" "$work/ov2" >/dev/null; then ok "install de novo nao muda o overlay convertido"
else fail "o install de novo mudou: $(diff "$work/ov1" "$work/ov2" | head -5)"; fi

# Shroudtopia/UE4SS (Windows) conversions: only their group comes out of the base.
(
  # shellcheck source=/dev/null
  source "$PIECE"
  set -Eeuo pipefail
  GP_GAME_RUNTIME_ENV="$work/base.env" GP_RUNTIME_OVERLAY="$work/over.env"
  printf "WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'\n" > "$work/base.env"
  : > "$work/over.env"
  # A win-run without the hook: nothing may move (the loader would vanish at the next restart).
  GP_WIN_RUN="$work/win-run-sem-gancho"
  printf '#!/bin/bash\n' > "$GP_WIN_RUN"
  gp_convert_wine_overrides /nao-existe
  printf '%s|%s\n' "$(cat "$work/base.env")" "$(cat "$work/over.env")"
  GP_WIN_RUN=/usr/local/bin/win-run
  gp_convert_wine_overrides /nao-existe
  printf '%s|%s\n' "$(cat "$work/base.env")" "$(cat "$work/over.env")"
) > "$work/winmm.out" 2>&1
check "sem o gancho no win-run nada e convertido" "WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'|" \
  "$(head -n 1 "$work/winmm.out")"
check "conversao do Shroudtopia" "WINE_DLL_OVERRIDES='mscoree,mshtml='|WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'" \
  "$(tail -n 1 "$work/winmm.out")"
rm -f /etc/systemd/system/palworld.service "$dropins/gamepanel-feito-a-mao.conf" /etc/game-runtime.env /usr/local/bin/win-run
rm -rf /opt/game

# ----- verify and lock -----
if bash "$PIECE" verify >/dev/null 2>&1; then ok "verify passa"; else fail "verify falhou"; fi
# Lock refused while the helper path is broken: nothing may be locked then.
mv /etc/sudoers.d/gamepanel "$work/sudoers.bak"
if bash "$PIECE" lock >/dev/null 2>&1; then fail "lock com sudo quebrado foi aceito"; else ok "lock com sudo quebrado e recusado"; fi
if [ -e /etc/ssh/sshd_config.d/10-gamepanel.conf ]; then fail "lock recusado escreveu o drop-in"; else ok "lock recusado nao tranca nada"; fi
if grep -qF "$(key_blob "$work/panel.pub")" /root/.ssh/authorized_keys; then
  ok "lock recusado deixa o root como estava"; else fail "lock recusado mexeu no root"; fi
mv "$work/sudoers.bak" /etc/sudoers.d/gamepanel

if bash "$PIECE" lock >"$work/lock.log" 2>&1; then ok "lock roda"; else fail "lock falhou: $(tail -3 "$work/lock.log")"; fi
check "drop-in do sshd" \
  "$(printf 'PermitRootLogin no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nAllowUsers gamepanel')" \
  "$(cat /etc/ssh/sshd_config.d/10-gamepanel.conf)"
if sshd -t >/dev/null 2>&1; then ok "sshd -t passa"; else fail "sshd -t recusa a configuracao"; fi
check "sshd efetivo: root recusado" "permitrootlogin no" "$(sshd -T 2>/dev/null | grep -i '^permitrootlogin')"
if grep -qF "$(key_blob "$work/panel.pub")" /root/.ssh/authorized_keys; then
  fail "a chave do painel ficou no root"; else ok "chave do painel saiu do root"; fi
if grep -qF "$(key_blob "$work/admin.pub")" /root/.ssh/authorized_keys; then
  ok "a chave do admin ficou no root"; else fail "o lock apagou a chave do admin"; fi
snapshot > "$work/snap4"
bash "$PIECE" lock >/dev/null 2>&1 || fail "segundo lock falhou"
snapshot > "$work/snap5"
if diff "$work/snap4" "$work/snap5" >/dev/null; then ok "lock duas vezes nao muda nada"; else fail "o segundo lock mudou algo"; fi

# ----- a real SSH login against the real sshd -----
ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p 2222)
/usr/sbin/sshd -p 2222 -o PidFile=/run/sshd-sandbox.pid 2>"$work/sshd.log" || fail "sshd nao subiu: $(cat "$work/sshd.log")"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  (echo > /dev/tcp/127.0.0.1/2222) 2>/dev/null && break
  /usr/bin/sleep 0.3   # the sandbox's `sleep` is a no-op fake
done
check "ssh gamepanel + sudo gp-service --version" "gp-helpers 1" \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n /usr/local/sbin/gp-service --version 2>/dev/null </dev/null)"
check "ssh gamepanel + sudo -u steam" steam \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n -u steam id -un 2>/dev/null </dev/null)"
# !use_pty: uploads and backups stream binary data on stdin; a pty in the middle would mangle it.
head -c 300000 /dev/urandom > "$work/blob"
check "binario passa intacto por ssh + sudo -u steam" "$(sha256sum < "$work/blob" | cut -d' ' -f1)" \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" gamepanel@127.0.0.1 sudo -n -u steam -- sha256sum < "$work/blob" 2>/dev/null | cut -d' ' -f1)"
if ssh "${ssh_opts[@]}" -i "$work/panel" root@127.0.0.1 true </dev/null >/dev/null 2>&1; then
  fail "root entra com a chave do painel"; else ok "root recusado com a chave do painel"; fi
if ssh "${ssh_opts[@]}" -i "$work/admin" root@127.0.0.1 true </dev/null >/dev/null 2>&1; then
  fail "root entra com a chave do admin (PermitRootLogin no)"; else ok "root recusado ate com a chave que ficou"; fi
check "tunel recusado (no-port-forwarding)" refused \
  "$(ssh "${ssh_opts[@]}" -i "$work/panel" -o ExitOnForwardFailure=yes -W 127.0.0.1:2222 gamepanel@127.0.0.1 </dev/null >/dev/null 2>&1 && echo opened || echo refused)"
kill "$(cat /run/sshd-sandbox.pid)" 2>/dev/null

echo
if [ "$failures" -eq 0 ]; then echo "panel-access: tudo OK"; else echo "panel-access: ${failures} falha(s)"; fi
exit "$failures"
