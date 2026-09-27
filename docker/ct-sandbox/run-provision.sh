#!/bin/bash
# Roda DENTRO do sandbox: executa um instalador com um game.env e deixa em <saida> tudo o que
# ele gerou, para dois runs poderem ser comparados com `diff -r`.
#
#   run-provision.sh <pasta-do-script> <game.env> <saida>
#   RUNNER=provision (padrao)  provision-game-lxc.sh, o caminho do host Proxmox (pct falso)
#   RUNNER=install            lib/ct-install.sh, o caminho do broker (transporte local)
#   DEPLOY_EXTRA   linhas extras de ambiente (ex.: credenciais de conta Steam)
#   FAKE_EXTRA_FILES  arquivos que o "jogo baixado" precisa ter alem do START_SCRIPT
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
# O SteamCMD falso roda como o usuario steam: sem isto nao consegue registrar os argumentos.
chmod 666 /var/log/fake-calls.log /var/log/fake-steamcmd.log
if [ "${RUNNER:-provision}" = "install" ]; then
  ( cd "$work" && bash ./ct-install.sh install.env ) > "$OUT/saida.log" 2>&1
else
  ( cd "$work" && bash ./provision-game-lxc.sh ) > "$OUT/saida.log" 2>&1
fi
echo $? > "$OUT/exit"
find /etc/systemd/system /usr/local/bin /etc/game-runtime.env /home/steam /opt/game /opt/steamcmd \
     /opt/proton /root/.ssh /usr/local/sbin/ct-firewall /etc/ct-firewall.env -printf '%p %m %u:%g %l\n' 2>/dev/null | sort > "$OUT/arquivos.txt"
find /usr/bin -maxdepth 1 -type l -lname '/usr/local/bin/*' -printf '%p -> %l\n' | sort >> "$OUT/arquivos.txt"
for f in /etc/systemd/system/*.service /etc/systemd/system/*.timer /usr/local/bin/* \
         /etc/game-runtime.env /root/.ssh/authorized_keys /etc/ct-firewall.env /etc/nftables.conf; do
  [ -f "$f" ] && { echo "=== $f"; cat "$f"; }
done > "$OUT/conteudo.txt" 2>/dev/null
cp /var/log/fake-calls.log "$OUT/chamadas.log"
cp /var/log/fake-steamcmd.log "$OUT/steamcmd.log"
