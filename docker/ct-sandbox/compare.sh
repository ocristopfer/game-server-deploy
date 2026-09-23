#!/usr/bin/env bash
# Prova que uma mudanca no instalador de jogo nao altera o que ele GERA. Dois testes:
#
#  1. ANTES x DEPOIS: roda o provision-game-lxc.sh da referencia (BASE_REF, padrao HEAD) e o
#     da arvore de trabalho, para cada jogo, e faz diff de arquivos criados, conteudo,
#     chamadas aos comandos falsos e saida.
#  2. HOST x BROKER: para cada jogo compara o que o provision-game-lxc.sh (`pct exec`) gera
#     com o que o lib/ct-install.sh (transporte local, o do broker) gera. Sao as MESMAS fases;
#     se divergirem, o deploy manual e o do broker deixaram de ser equivalentes.
#
#   docker/ct-sandbox/compare.sh
#   BASE_REF=main docker/ct-sandbox/compare.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }   # caminho que o Docker enxerga (Git Bash no Windows)
BASE_REF="${BASE_REF:-HEAD}"
work="$repo_root/docker/ct-sandbox/.work"
cd "$repo_root"; rm -rf "$work"; mkdir -p "$work/orig/lib" "$work/novo" "$work/inst" "$work/games" "$work/out"

# O script mudou de LUGAR (raiz -> deploy/game/), e a referencia pode ser de antes disso.
# Mesmo cuidado do `ct-fases.sh` logo abaixo: procura no caminho de hoje e cai no antigo.
# O `>` criaria o arquivo vazio antes de o git falhar, entao o teste vem primeiro.
for candidate in deploy/game/provision-game-lxc.sh provision-game-lxc.sh; do
  if git cat-file -e "$BASE_REF:${candidate}" 2>/dev/null; then
    git show "$BASE_REF:${candidate}" > "$work/orig/provision-game-lxc.sh"
    break
  fi
done
[[ -s "$work/orig/provision-game-lxc.sh" ]] || { echo "FALHA: nao achei o provision-game-lxc.sh em $BASE_REF" >&2; exit 1; }
# A referencia pode ser anterior a lib/ (o `>` criaria o arquivo vazio antes do git
# falhar) e, se for anterior a traducao dos nomes, a lib ainda se chamava `ct-fases.sh`.
# O nome ANTIGO tambem e procurado: sem isso, comparar contra um commit de antes do
# rename rodaria a referencia sem lib nenhuma e acusaria diferenca em todos os jogos.
# E o arquivo e gravado com o nome que a REFERENCIA usa, nao com o de hoje: quem o le
# la e o provision-game-lxc.sh daquele commit, e ele procura pelo nome que conhecia.
for candidate in ct-phases.sh ct-fases.sh; do
  if git cat-file -e "$BASE_REF:lib/${candidate}" 2>/dev/null; then
    git show "$BASE_REF:lib/${candidate}" > "$work/orig/${candidate}"
    break
  fi
done
rmdir "$work/orig/lib"
cp deploy/game/provision-game-lxc.sh "$work/novo/"
# Layout REAL do bundle do deploy-game.ps1: sem subpastas, a lib solta ao lado do script.
cp lib/ct-phases.sh "$work/novo/ct-phases.sh"
cp lib/ct-install.sh lib/ct-phases.sh "$work/inst/"
cp games/*.env "$work/games/"
# O script da referencia (antes desta mudanca) nao conhece {EXTRA_PORT}: com o games/satisfactory.env
# de hoje ele deixaria o marcador literal no ExecStart. Para o guarda "antes x depois" continuar
# provando que o RESTO do instalador nao mudou, o Satisfactory legado roda sem o marcador.
sed -e 's/ -ReliablePort={EXTRA_PORT}//' -e '/^EXTRA_PORT=/d' games/satisfactory.env > "$work/games/satisfactory-legado.env"
# Wine puro: nenhum jogo do repo usa, mas o caminho existe no instalador.
{ cat games/dragonwilds.env; echo 'WINDOWS_RUNTIME=wine'; } > "$work/games/sintetico-wine.env"
# Receita nomeada + porta de consulta deslocada: o que um jogo cadastrado pelo broker usa.
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

# O install.env que o BROKER gera (src/gamebroker/ssh_install.py:montar_env), com portas da faixa do broker e uma
# receita: prova a costura entre o Python e o ct-install.sh de verdade.
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
# Bytes, nao print(): no Windows o stdout em modo texto troca \n por \r\n, e o bash
# do CT leria cada valor com um \r no fim (o instalador de verdade grava com newline).
import sys
sys.stdout.buffer.write(build_env(game, ports).encode())
PY

docker build -q -t ct-sandbox "$repo_root/docker/ct-sandbox" >/dev/null
W="$(cd "$work" && host_path)"

# rodar <saida> <pasta-do-script> <jogo.env> [DEPLOY_EXTRA] [FAKE_EXTRA_FILES] [RUNNER]
run_one() {
  MSYS_NO_PATHCONV=1 docker run --rm -v "$W:/w" -e DEPLOY_EXTRA="${4:-}" -e FAKE_EXTRA_FILES="${5:-}" \
    -e RUNNER="${6:-provision}" ct-sandbox bash /usr/local/lib/run-provision.sh "/w/$2" "/w/games/$3" "/w/out/$1" \
    >/dev/null 2>&1 || true
}
strip_time() { sed -Ei 's/\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]/[T]/' "$1" 2>/dev/null || true; }

failures=0
run_case() {  # nome jogo.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
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
run_broker_case() {  # nome jogo.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
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
run_case painel-pubkey   palworld.env         "PANEL_PUBKEY='ssh-ed25519 AAAAteste painel@x'" "$PAL_ARQ"

run_broker_case palworld      palworld.env      ""             "$PAL_ARQ"
run_broker_case dragonwilds   dragonwilds.env
run_broker_case satisfactory  satisfactory.env
run_broker_case enshrouded    enshrouded.env
run_broker_case icarus        icarus.env
run_broker_case dayz-conta    dayz.env          "$DAYZ_CONTA"
run_broker_case wine          sintetico-wine.env
run_broker_case receita       sintetico-receita.env

# Recursos NOVOS (o script da referencia nao os conhece, entao nao ha "antes" para comparar):
# {EXTRA_PORT} no Satisfactory de hoje: o instalador troca pelo padrao do jogo (a confiavel, 8888).
s="$work/out/satisfactory-novo"
if grep -q -- 'ExecStart=/opt/game/FactoryServer.sh -Port=7787 -ReliablePort=8888 -log -unattended' "$s/conteudo.txt"; then
  printf 'OK        recursos novos  %-20s ({EXTRA_PORT} -> -ReliablePort=8888)\n' satisfactory
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' satisfactory "$s"; failures=$((failures + 1))
fi

# confere direto o resultado esperado da receita e do marcador {QUERY_PORT}.
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

# Costura Python -> ct-install.sh: o install.env gerado pelo broker, com portas 31000/31001/31002.
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
