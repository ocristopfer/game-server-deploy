#!/bin/bash
# Runs INSIDE the sandbox: runs an installer with a game.env and leaves in <output> everything
# it generated, so two runs can be compared with `diff -r`.
#
#   run-provision.sh <script-folder> <game.env> <output>
#   RUNNER=provision (default) provision-game-lxc.sh, the Proxmox host path (fake pct)
#   RUNNER=install            lib/ct-install.sh, the broker path (local transport)
#   DEPLOY_EXTRA   extra environment lines (e.g. Steam account credentials)
#   FAKE_EXTRA_FILES  files the "downloaded game" must have besides START_SCRIPT
set -u
SRC="$1"; GAME_ENV="$2"; OUT="$3"
mkdir -p "$OUT"
work=$(mktemp -d)
cp -a "$SRC"/. "$work"/
cp "$GAME_ENV" "$work/game.env"
if [ "${RUNNER:-provision}" = "install" ]; then
  { cat "$GAME_ENV"; echo; printf '%s\n' "${DEPLOY_EXTRA:-}"; } > "$work/install.env"
else
  cat > "$work/deploy.env" <<DEP
CTID=999
IP_CIDR=10.0.0.99/24
GATEWAY=10.0.0.1
STORAGE=fake
TEMPLATE_STORAGE=fake
${DEPLOY_EXTRA:-}
DEP
fi
{ grep -E '^START_SCRIPT=' "$GAME_ENV" | head -1 | cut -d= -f2- | tr -d "\"'"
  for f in ${FAKE_EXTRA_FILES:-}; do echo "$f"; done; } > /etc/fake-game-files
: > /var/log/fake-calls.log; : > /var/log/fake-steamcmd.log
# The fake SteamCMD runs as the steam user: without this it cannot record the arguments.
chmod 666 /var/log/fake-calls.log /var/log/fake-steamcmd.log
if [ "${RUNNER:-provision}" = "install" ]; then
  ( cd "$work" && bash ./ct-install.sh install.env ) > "$OUT/saida.log" 2>&1
  rc=$?
  # The broker locks root in its final cleanup command (ssh_installer._cleanup), not inside
  # ct-install.sh. Emulated here, with the SAME call, so host x broker still compare the whole CT.
  if [ "$rc" = 0 ] && grep -q '^PANEL_PUBKEY=' "$work/install.env" 2>/dev/null; then
    bash /usr/local/lib/gamepanel/ct-panel-access.sh lock >> "$OUT/saida.log" 2>&1 || rc=3
  fi
  echo "$rc" > "$OUT/exit"
else
  ( cd "$work" && bash ./provision-game-lxc.sh ) > "$OUT/saida.log" 2>&1
  echo $? > "$OUT/exit"
fi
find /etc/systemd/system /usr/local/bin /etc/game-runtime.env /home/steam /opt/game /opt/steamcmd \
     /opt/proton /root/.ssh /usr/local/sbin/ct-firewall /etc/ct-firewall.env \
     /usr/local/sbin/gp-service /usr/local/sbin/gp-clamav-ensure /usr/local/lib/gamepanel \
     /etc/gamepanel /etc/sudoers.d/gamepanel /var/lib/gamepanel-agent \
     /etc/ssh/sshd_config.d -printf '%p %m %u:%g %l\n' 2>/dev/null | sort > "$OUT/arquivos.txt"
find /usr/bin -maxdepth 1 -type l -lname '/usr/local/bin/*' -printf '%p -> %l\n' | sort >> "$OUT/arquivos.txt"
# The panel user: shell, home and groups are part of what the installer decides.
{ getent passwd gamepanel | cut -d: -f1,6,7; id -nG gamepanel 2>/dev/null; } >> "$OUT/arquivos.txt"
for f in /etc/systemd/system/*.service /etc/systemd/system/*.timer /usr/local/bin/* \
         /etc/game-runtime.env /root/.ssh/authorized_keys /etc/ct-firewall.env /etc/nftables.conf \
         /etc/gamepanel/ct.env /etc/sudoers.d/gamepanel /usr/local/sbin/gp-service \
         /usr/local/sbin/gp-clamav-ensure /var/lib/gamepanel-agent/.ssh/authorized_keys \
         /etc/ssh/sshd_config.d/*.conf; do
  [ -f "$f" ] && { echo "=== $f"; cat "$f"; }
done > "$OUT/conteudo.txt" 2>/dev/null
cp /var/log/fake-calls.log "$OUT/chamadas.log"
cp /var/log/fake-steamcmd.log "$OUT/steamcmd.log"
