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
