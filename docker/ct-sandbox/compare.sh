#!/usr/bin/env bash
# Proves that a change to the game installer does not alter what it GENERATES. Two tests:
#
#  1. BEFORE x AFTER: runs the provision-game-lxc.sh from the reference (BASE_REF, default HEAD)
#     and the one from the working tree, for each game, and diffs the created files, contents,
#     calls to the fake commands and output.
#  2. HOST x BROKER: for each game compares what provision-game-lxc.sh (`pct exec`) generates
#     with what lib/ct-install.sh (local transport, the broker's) generates. They are the SAME
#     phases; if they diverge, the manual deploy and the broker's are no longer equivalent.
#
#   docker/ct-sandbox/compare.sh
#   BASE_REF=main docker/ct-sandbox/compare.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # path as Docker sees it (Git Bash on Windows)
BASE_REF="${BASE_REF:-HEAD}"
work="$repo_root/docker/ct-sandbox/.work"
cd "$repo_root"; rm -rf "$work"; mkdir -p "$work/orig/lib" "$work/novo" "$work/inst" "$work/games" "$work/out"

# The script changed LOCATION (root -> deploy/game/), and the reference may predate that.
# Same care as with `ct-fases.sh` just below: look in today's path and fall back to the old one.
# The `>` would create the empty file before git fails, so the check comes first.
for candidate in deploy/game/provision-game-lxc.sh provision-game-lxc.sh; do
  if git cat-file -e "$BASE_REF:${candidate}" 2>/dev/null; then
    git show "$BASE_REF:${candidate}" > "$work/orig/provision-game-lxc.sh"
    break
  fi
done
[[ -s "$work/orig/provision-game-lxc.sh" ]] || { echo "FALHA: nao achei o provision-game-lxc.sh em $BASE_REF" >&2; exit 1; }
# The reference may predate lib/ (the `>` would create the empty file before git
# fails) and, if it predates the name translation, the lib was still called `ct-fases.sh`.
# The OLD name is looked up too: without it, comparing against a commit from before the
# rename would run the reference with no lib at all and flag a difference in every game.
# And the file is written under the name the REFERENCE uses, not today's: whoever reads it
# there is that commit's provision-game-lxc.sh, and it looks for the name it knew.
for candidate in ct-phases.sh ct-fases.sh; do
  if git cat-file -e "$BASE_REF:lib/${candidate}" 2>/dev/null; then
    git show "$BASE_REF:lib/${candidate}" > "$work/orig/${candidate}"
    break
  fi
done
rmdir "$work/orig/lib"
cp deploy/game/provision-game-lxc.sh "$work/novo/"
# REAL layout of the deploy-game.ps1 bundle: no subfolders, the lib loose next to the script.
cp lib/ct-phases.sh lib/ct-firewall.sh lib/ct-panel-access.sh "$work/novo/"
cp lib/ct-install.sh lib/ct-phases.sh lib/ct-firewall.sh lib/ct-panel-access.sh "$work/inst/"
cp games/*.env "$work/games/"
# The reference script (before this change) does not know {EXTRA_PORT}: with today's
# games/satisfactory.env it would leave the placeholder literal in ExecStart. For the "before x after"
# guard to keep proving that the REST of the installer did not change, legacy Satisfactory runs
# without the placeholder.
sed -e 's/ -ReliablePort={EXTRA_PORT}//' -e '/^EXTRA_PORT=/d' games/satisfactory.env > "$work/games/satisfactory-legado.env"
# Plain Wine: no game in the repo uses it, but the path exists in the installer.
{ cat games/dragonwilds.env; echo 'WINDOWS_RUNTIME=wine'; } > "$work/games/sintetico-wine.env"
# Named recipe + shifted query port: what a game registered through the broker uses.
cat > "$work/games/sintetico-receita.env" <<'ENV'
GAME_KEY=receita
GAME_DISPLAY_NAME="Jogo com receita"
STEAM_APP_ID=999001
START_SCRIPT=Server.sh
START_ARGS="-port={PORT} -queryport={QUERY_PORT}"
GAME_PORT=7778
QUERY_PORT=27017
GAME_PORTS="7778/udp 27017/udp"
RECIPES="steamclient-sdk64"
ENV

# The install.env the BROKER generates (src/gamebroker/ssh_install.py:montar_env), with ports from the broker
# range and a recipe: proves the seam between the Python and the real ct-install.sh.
PYBIN="$repo_root/.venv/Scripts/python.exe"; [ -x "$PYBIN" ] || PYBIN=python3
"$PYBIN" - > "$work/games/gerado-pelo-broker.env" <<'PY'
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import validate_dynamic
from gamebroker.runtime.ssh_installer import build_env

game = validate_dynamic({
    "chave": "gerado", "nome": "Gerado pelo broker", "app_id": 999002,
    "portas": ["7777/udp", "27016/udp", "8888/tcp"], "porta_jogo": 7777, "porta_query": 27016, "porta_extra": 8888,
    "start_script": "Server.sh", "start_args": "-port={PORT} -queryport={QUERY_PORT} -reliable={EXTRA_PORT}",
    "receitas": ["steamclient-sdk64"], "deslocavel": True})
ports = [AllocatedPort(7777, 31000, "udp", "jogo"), AllocatedPort(27016, 31001, "udp", "query"),
         AllocatedPort(8888, 31002, "tcp", "extra")]
# Bytes, not print(): on Windows text-mode stdout turns \n into \r\n, and the CT's bash
# would read each value with a \r at the end (the real installer writes with newline).
import sys
sys.stdout.buffer.write(build_env(game, ports).encode())
PY

docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
W="$(cd "$work" && host_path)"

# run <output> <script-folder> <game.env> [DEPLOY_EXTRA] [FAKE_EXTRA_FILES] [RUNNER]
run_one() {
  MSYS_NO_PATHCONV=1 docker run --rm -v "$W:/w" -e DEPLOY_EXTRA="${4:-}" -e FAKE_EXTRA_FILES="${5:-}" \
    -e RUNNER="${6:-provision}" ct-sandbox bash /usr/local/lib/run-provision.sh "/w/$2" "/w/games/$3" "/w/out/$1" \
    >/dev/null 2>&1 || true
}
strip_time() { sed -Ei 's/\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]/[T]/' "$1" 2>/dev/null || true; }

failures=0
run_case() {  # name game.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
  local name="$1"; shift
  run_one "$name-orig" orig "$@"; run_one "$name-novo" novo "$@"
  strip_time "$work/out/$name-orig/saida.log"; strip_time "$work/out/$name-novo/saida.log"
  local exit_code; exit_code="$(cat "$work/out/$name-orig/exit" 2>/dev/null || echo '?')"
  if diff -r "$work/out/$name-orig" "$work/out/$name-novo" >"$work/out/$name.diff" 2>&1; then
    printf 'IGUAL     antes x depois  %-20s (exit %s, %s arquivos)\n' "$name" "$exit_code" "$(wc -l < "$work/out/$name-novo/arquivos.txt")"
  else
    printf 'DIFERENTE antes x depois  %-20s (veja %s)\n' "$name" "$work/out/$name.diff"; failures=$((failures + 1))
  fi
}
run_broker_case() {  # name game.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
  local name="$1"; shift
  run_one "$name-inst" inst "$1" "${2:-}" "${3:-}" install
  [ -d "$work/out/$name-novo" ] || run_one "$name-novo" novo "$@"
  local exit_i; exit_i="$(cat "$work/out/$name-inst/exit" 2>/dev/null || echo '?')"
  local ok=1
  for f in arquivos.txt conteudo.txt steamcmd.log; do
    diff -q "$work/out/$name-novo/$f" "$work/out/$name-inst/$f" >"$work/out/$name-$f.diff" 2>&1 || ok=0
  done
  grep -q "INSTALACAO CONCLUIDA" "$work/out/$name-inst/saida.log" 2>/dev/null || ok=0
  if [ "$ok" = 1 ] && [ "$exit_i" = 0 ]; then
    printf 'IGUAL     host x broker   %-20s (exit %s)\n' "$name" "$exit_i"
  else
    printf 'DIFERENTE host x broker   %-20s (exit %s; veja %s/out/%s-*)\n' "$name" "$exit_i" "$work" "$name"; failures=$((failures + 1))
  fi
}

DAYZ_CONTA=$'STEAM_USER=fulano\nSTEAM_PASS=segredo\nSTEAM_GUARD_CODE=ABCDE'
PAL_ARQ="DefaultPalWorldSettings.ini"
run_case palworld        palworld.env         ""             "$PAL_ARQ"
run_case dragonwilds     dragonwilds.env
run_case satisfactory-legado satisfactory-legado.env
run_case enshrouded      enshrouded.env
run_case icarus          icarus.env
run_case dayz-conta      dayz.env             "$DAYZ_CONTA"
run_case wine            sintetico-wine.env
PANEL_KEY_EXTRA="PANEL_PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelDoSandbox painel@x'"
run_case painel-pubkey   palworld.env         "$PANEL_KEY_EXTRA" "$PAL_ARQ"

run_broker_case palworld      palworld.env      ""             "$PAL_ARQ"
run_broker_case dragonwilds   dragonwilds.env
run_broker_case satisfactory  satisfactory.env
run_broker_case enshrouded    enshrouded.env
run_broker_case icarus        icarus.env
run_broker_case dayz-conta    dayz.env          "$DAYZ_CONTA"
run_broker_case wine          sintetico-wine.env
run_broker_case receita       sintetico-receita.env
# With the panel/broker IP the CT gets the firewall - and both transports must generate the SAME one.
FW_EXTRA="FW_MGMT_SOURCES='10.20.1.100 10.20.1.101'"
run_broker_case firewall      dragonwilds.env   "$FW_EXTRA"

# With the panel key: gamepanel user, sudo rules and helpers, and root locked at the end. The host
# locks in its last phase, the broker in its cleanup (emulated by run-provision.sh) - same CT.
run_broker_case painel-pubkey palworld.env      "$PANEL_KEY_EXTRA" "$PAL_ARQ"

# NEW features (the reference script does not know them, so there is no "before" to compare):
# Unprivileged panel access (docs/security-hardening-contract.md), on both transports.
for side in novo inst; do
  p="$work/out/painel-pubkey-$side"
  expected=1
  [ "$(cat "$p/exit" 2>/dev/null)" = 0 ] || expected=0
  grep -q '^/etc/sudoers.d/gamepanel 440 root:root' "$p/arquivos.txt" || expected=0
  grep -q '^/usr/local/sbin/gp-service 755 root:root' "$p/arquivos.txt" || expected=0
  grep -q '^/usr/local/sbin/gp-clamav-ensure 755 root:root' "$p/arquivos.txt" || expected=0
  grep -q '^/var/lib/gamepanel-agent 700 gamepanel:gamepanel' "$p/arquivos.txt" || expected=0
  grep -q '^gamepanel:/var/lib/gamepanel-agent:/bin/bash$' "$p/arquivos.txt" || expected=0
  grep -q '^GAME_UNIT=palworld.service$' "$p/conteudo.txt" || expected=0
  grep -q '^gamepanel ALL=(steam) NOPASSWD: ALL$' "$p/conteudo.txt" || expected=0
  grep -q '^no-agent-forwarding,no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelDoSandbox' "$p/conteudo.txt" || expected=0
  grep -q '^PermitRootLogin no$' "$p/conteudo.txt" || expected=0
  grep -q '^AllowUsers gamepanel$' "$p/conteudo.txt" || expected=0
  # The panel key never goes into root any more.
  grep -A2 '^=== /root/.ssh/authorized_keys' "$p/conteudo.txt" | grep -q PainelDoSandbox && expected=0
  if [ "$expected" = 1 ]; then
    printf 'OK        recursos novos  %-20s (gamepanel, sudoers, helpers e root trancado: %s)\n' painel-pubkey "$side"
  else
    printf 'FALHOU    recursos novos  %-20s (veja %s)\n' painel-pubkey "$p"; failures=$((failures + 1))
  fi
done
# Without the panel key nothing of it exists, and root is NOT locked (nobody else could get in).
if grep -q 'gamepanel\|10-gamepanel' "$work/out/dragonwilds-inst/arquivos.txt"; then
  printf 'FALHOU    recursos novos  %-20s (gamepanel sem PANEL_PUBKEY)\n' sem-chave; failures=$((failures + 1))
else
  printf 'OK        recursos novos  %-20s (sem PANEL_PUBKEY: nem gamepanel nem trava)\n' sem-chave
fi

# {EXTRA_PORT} in today's Satisfactory: the installer replaces it with the game default (the reliable one, 8888).
s="$work/out/satisfactory-novo"
if grep -q -- 'ExecStart=/opt/game/FactoryServer.sh -Port=7787 -ReliablePort=8888 -log -unattended' "$s/conteudo.txt"; then
  printf 'OK        recursos novos  %-20s ({EXTRA_PORT} -> -ReliablePort=8888)\n' satisfactory
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' satisfactory "$s"; failures=$((failures + 1))
fi

# Checks the expected result of the recipe and of the {QUERY_PORT} placeholder directly.
r="$work/out/receita-inst"
expected=1
grep -q -- '-port=7778 -queryport=27017' "$r/conteudo.txt" || expected=0
grep -qE '/home/steam/.steam/sdk64/steamclient.so 777 steam:steam /opt/steamcmd/linux64/steamclient.so' "$r/arquivos.txt" || expected=0
grep -qE '/home/steam/.steam 755 steam:steam' "$r/arquivos.txt" || expected=0
if [ "$expected" = 1 ]; then
  printf 'OK        recursos novos  %-20s (receita steamclient-sdk64 e {QUERY_PORT})\n' receita
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' receita "$r"; failures=$((failures + 1))
fi

# CT firewall: game rules (public port, SSH only from the administration) and loaded.
f="$work/out/firewall-inst"
expected=1
grep -q '^FW_ROLE=game$' "$f/conteudo.txt" || expected=0
grep -q '^FW_MGMT_SOURCES="10.20.1.100 10.20.1.101"$' "$f/conteudo.txt" || expected=0
grep -q 'udp dport { 7777 } accept' "$f/conteudo.txt" || expected=0
grep -q 'ip saddr { 10.20.1.100, 10.20.1.101 } tcp dport 22 accept' "$f/conteudo.txt" || expected=0
grep -q '^nft -f /etc/nftables.conf' "$f/chamadas.log" || expected=0
# Without the panel IP, NO firewall (applying it would lock the panel out): that is the case for all the others.
grep -q 'ct-firewall' "$work/out/dragonwilds-inst/arquivos.txt" && expected=0
if [ "$expected" = 1 ]; then
  printf 'OK        recursos novos  %-20s (regras de jogo aplicadas; sem IP do painel, nenhuma)\n' firewall
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' firewall "$f"; failures=$((failures + 1))
fi

# Python -> ct-install.sh seam: the install.env generated by the broker, with ports 31000/31001/31002.
run_one gerado-inst inst gerado-pelo-broker.env "" "" install
g="$work/out/gerado-inst"
expected=1
[ "$(cat "$g/exit" 2>/dev/null)" = 0 ] || expected=0
grep -q "INSTALACAO CONCLUIDA: Gerado pelo broker" "$g/saida.log" || expected=0
grep -q -- 'ExecStart=/opt/game/Server.sh -port=31000 -queryport=31001 -reliable=31002' "$g/conteudo.txt" || expected=0
grep -q "app_update 999002 validate" "$g/steamcmd.log" || expected=0
grep -q "login anonymous" "$g/steamcmd.log" || expected=0
grep -q 'sdk64/steamclient.so' "$g/arquivos.txt" || expected=0
if [ "$expected" = 1 ]; then
  printf 'OK        costura         %-20s (install.env do broker -> ct-install.sh, portas 31000/31001/31002)\n' gerado
else
  printf 'FALHOU    costura         %-20s (veja %s)\n' gerado "$g"; failures=$((failures + 1))
fi
exit "$failures"
