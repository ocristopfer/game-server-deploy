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
#   docker/ct-sandbox/comparar.sh
#   BASE_REF=main docker/ct-sandbox/comparar.sh
set -euo pipefail
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$raiz"
qual() { pwd -W 2>/dev/null || pwd; }   # caminho que o Docker enxerga (Git Bash no Windows)
BASE_REF="${BASE_REF:-HEAD}"
work="$raiz/docker/ct-sandbox/.work"
cd "$raiz"; rm -rf "$work"; mkdir -p "$work/orig/lib" "$work/novo" "$work/inst" "$work/games" "$work/out"

git show "$BASE_REF:provision-game-lxc.sh" > "$work/orig/provision-game-lxc.sh"
# A referencia pode ser anterior a lib/ (o `>` criaria o arquivo vazio antes do git falhar).
if git cat-file -e "$BASE_REF:lib/ct-fases.sh" 2>/dev/null; then
  git show "$BASE_REF:lib/ct-fases.sh" > "$work/orig/ct-fases.sh"
fi
rmdir "$work/orig/lib"
cp provision-game-lxc.sh "$work/novo/"
# Layout REAL do bundle do deploy-game.ps1: sem subpastas, a lib solta ao lado do script.
cp lib/ct-fases.sh "$work/novo/ct-fases.sh"
cp lib/ct-install.sh lib/ct-fases.sh "$work/inst/"
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

# O install.env que o BROKER gera (broker/ssh_install.py:montar_env), com portas da faixa do broker e uma
# receita: prova a costura entre o Python e o ct-install.sh de verdade.
PYBIN="$raiz/.venv/Scripts/python.exe"; [ -x "$PYBIN" ] || PYBIN=python3
"$PYBIN" - > "$work/games/gerado-pelo-broker.env" <<'PY'
from broker.alocador import PortaAlocada
from broker.catalogo import validar_dinamico
from broker.ssh_install import montar_env

jogo = validar_dinamico({
    "chave": "gerado", "nome": "Gerado pelo broker", "app_id": 999002,
    "portas": ["7777/udp", "27016/udp", "8888/tcp"], "porta_jogo": 7777, "porta_query": 27016, "porta_extra": 8888,
    "start_script": "Server.sh", "start_args": "-port={PORT} -queryport={QUERY_PORT} -reliable={EXTRA_PORT}",
    "receitas": ["steamclient-sdk64"], "deslocavel": True})
portas = [PortaAlocada(7777, 31000, "udp", "jogo"), PortaAlocada(27016, 31001, "udp", "query"),
          PortaAlocada(8888, 31002, "tcp", "extra")]
# Bytes, nao print(): no Windows o stdout em modo texto troca \n por \r\n, e o bash do CT leria
# cada valor com um \r no fim (o instalador de verdade grava com newline="\n").
import sys
sys.stdout.buffer.write(montar_env(jogo, portas).encode())
PY

docker build -q -t ct-sandbox "$raiz/docker/ct-sandbox" >/dev/null
W="$(cd "$work" && qual)"

# rodar <saida> <pasta-do-script> <jogo.env> [DEPLOY_EXTRA] [FAKE_EXTRA_FILES] [RUNNER]
rodar() {
  MSYS_NO_PATHCONV=1 docker run --rm -v "$W:/w" -e DEPLOY_EXTRA="${4:-}" -e FAKE_EXTRA_FILES="${5:-}" \
    -e RUNNER="${6:-provision}" ct-sandbox bash /usr/local/lib/run-provision.sh "/w/$2" "/w/games/$3" "/w/out/$1" \
    >/dev/null 2>&1 || true
}
limpa_hora() { sed -Ei 's/\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]/[T]/' "$1" 2>/dev/null || true; }

falhas=0
caso() {  # nome jogo.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
  local nome="$1"; shift
  rodar "$nome-orig" orig "$@"; rodar "$nome-novo" novo "$@"
  limpa_hora "$work/out/$nome-orig/saida.log"; limpa_hora "$work/out/$nome-novo/saida.log"
  local sai; sai="$(cat "$work/out/$nome-orig/exit" 2>/dev/null || echo '?')"
  if diff -r "$work/out/$nome-orig" "$work/out/$nome-novo" >"$work/out/$nome.diff" 2>&1; then
    printf 'IGUAL     antes x depois  %-20s (exit %s, %s arquivos)\n' "$nome" "$sai" "$(wc -l < "$work/out/$nome-novo/arquivos.txt")"
  else
    printf 'DIFERENTE antes x depois  %-20s (veja %s)\n' "$nome" "$work/out/$nome.diff"; falhas=$((falhas + 1))
  fi
}
caso_broker() {  # nome jogo.env [DEPLOY_EXTRA] [FAKE_EXTRA_FILES]
  local nome="$1"; shift
  rodar "$nome-inst" inst "$1" "${2:-}" "${3:-}" install
  [ -d "$work/out/$nome-novo" ] || rodar "$nome-novo" novo "$@"
  local exit_i; exit_i="$(cat "$work/out/$nome-inst/exit" 2>/dev/null || echo '?')"
  local ok=1
  for f in arquivos.txt conteudo.txt steamcmd.log; do
    diff -q "$work/out/$nome-novo/$f" "$work/out/$nome-inst/$f" >"$work/out/$nome-$f.diff" 2>&1 || ok=0
  done
  grep -q "INSTALACAO CONCLUIDA" "$work/out/$nome-inst/saida.log" 2>/dev/null || ok=0
  if [ "$ok" = 1 ] && [ "$exit_i" = 0 ]; then
    printf 'IGUAL     host x broker   %-20s (exit %s)\n' "$nome" "$exit_i"
  else
    printf 'DIFERENTE host x broker   %-20s (exit %s; veja %s/out/%s-*)\n' "$nome" "$exit_i" "$work" "$nome"; falhas=$((falhas + 1))
  fi
}

DAYZ_CONTA=$'STEAM_USER=fulano\nSTEAM_PASS=segredo\nSTEAM_GUARD_CODE=ABCDE'
PAL_ARQ="DefaultPalWorldSettings.ini"
caso palworld        palworld.env         ""             "$PAL_ARQ"
caso dragonwilds     dragonwilds.env
caso satisfactory-legado satisfactory-legado.env
caso enshrouded      enshrouded.env
caso icarus          icarus.env
caso dayz-conta      dayz.env             "$DAYZ_CONTA"
caso wine            sintetico-wine.env
caso painel-pubkey   palworld.env         "PANEL_PUBKEY='ssh-ed25519 AAAAteste painel@x'" "$PAL_ARQ"

caso_broker palworld      palworld.env      ""             "$PAL_ARQ"
caso_broker dragonwilds   dragonwilds.env
caso_broker satisfactory  satisfactory.env
caso_broker enshrouded    enshrouded.env
caso_broker icarus        icarus.env
caso_broker dayz-conta    dayz.env          "$DAYZ_CONTA"
caso_broker wine          sintetico-wine.env
caso_broker receita       sintetico-receita.env

# Recursos NOVOS (o script da referencia nao os conhece, entao nao ha "antes" para comparar):
# {EXTRA_PORT} no Satisfactory de hoje: o instalador troca pelo padrao do jogo (a confiavel, 8888).
s="$work/out/satisfactory-novo"
if grep -q -- 'ExecStart=/opt/game/FactoryServer.sh -Port=7787 -ReliablePort=8888 -log -unattended' "$s/conteudo.txt"; then
  printf 'OK        recursos novos  %-20s ({EXTRA_PORT} -> -ReliablePort=8888)\n' satisfactory
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' satisfactory "$s"; falhas=$((falhas + 1))
fi

# confere direto o resultado esperado da receita e do marcador {QUERY_PORT}.
r="$work/out/receita-inst"
esperado=1
grep -q -- '-port=7778 -queryport=27017' "$r/conteudo.txt" || esperado=0
grep -qE '/home/steam/.steam/sdk64/steamclient.so 777 steam:steam /opt/steamcmd/linux64/steamclient.so' "$r/arquivos.txt" || esperado=0
grep -qE '/home/steam/.steam 755 steam:steam' "$r/arquivos.txt" || esperado=0
if [ "$esperado" = 1 ]; then
  printf 'OK        recursos novos  %-20s (receita steamclient-sdk64 e {QUERY_PORT})\n' receita
else
  printf 'FALHOU    recursos novos  %-20s (veja %s)\n' receita "$r"; falhas=$((falhas + 1))
fi

# Costura Python -> ct-install.sh: o install.env gerado pelo broker, com portas 31000/31001/31002.
rodar gerado-inst inst gerado-pelo-broker.env "" "" install
g="$work/out/gerado-inst"
esperado=1
[ "$(cat "$g/exit" 2>/dev/null)" = 0 ] || esperado=0
grep -q "INSTALACAO CONCLUIDA: Gerado pelo broker" "$g/saida.log" || esperado=0
grep -q -- 'ExecStart=/opt/game/Server.sh -port=31000 -queryport=31001 -reliable=31002' "$g/conteudo.txt" || esperado=0
grep -q "app_update 999002 validate" "$g/steamcmd.log" || esperado=0
grep -q "login anonymous" "$g/steamcmd.log" || esperado=0
grep -q 'sdk64/steamclient.so' "$g/arquivos.txt" || esperado=0
if [ "$esperado" = 1 ]; then
  printf 'OK        costura         %-20s (install.env do broker -> ct-install.sh, portas 31000/31001/31002)\n' gerado
else
  printf 'FALHOU    costura         %-20s (veja %s)\n' gerado "$g"; falhas=$((falhas + 1))
fi
exit "$falhas"
