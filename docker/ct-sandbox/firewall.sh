#!/usr/bin/env bash
# Proves lib/ct-firewall.sh with REAL nftables: not only that the rules load into the kernel,
# but that they block and allow what they should. Needs Docker.
#
# Builds an isolated network with one container per role (and an intruder on the same LAN) and
# tests every connection that matters. The intruder is the case OPNsense does not cover: a machine
# on the same subnet, talking directly to the CTs.
#
#   docker/ct-sandbox/firewall.sh
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"
host_path() { pwd -W 2>/dev/null || pwd; }

NET=ctfw-sandbox
PREFIX=172.30.77
PANEL=$PREFIX.100
BROKER=$PREFIX.101
GAME=$PREFIX.102
INTRUDER=$PREFIX.50
API=$PREFIX.254      # plays the role of Proxmox (:8006)
names=(ctfw-panel ctfw-broker ctfw-game ctfw-intruder ctfw-api)

cleanup() {
  docker rm -f "${names[@]}" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker build -q -t ctfw-sandbox - >/dev/null <<'EOF'
FROM debian:13-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nftables netcat-openbsd iputils-ping >/dev/null
EOF
docker network create --subnet "$PREFIX.0/24" "$NET" >/dev/null

start() {  # name ip
  MSYS_NO_PATHCONV=1 docker run -d --name "$1" --network "$NET" --ip "$2" --cap-add NET_ADMIN --cap-add NET_RAW \
    -v "$(host_path)/lib:/src:ro" ctfw-sandbox sleep infinity >/dev/null
  MSYS_NO_PATHCONV=1 docker exec "$1" install -m 0755 /src/ct-firewall.sh /usr/local/sbin/ct-firewall
}
for pair in "ctfw-panel $PANEL" "ctfw-broker $BROKER" "ctfw-game $GAME" "ctfw-intruder $INTRUDER" "ctfw-api $API"; do
  # shellcheck disable=SC2086
  start $pair
done

# A "service" listening on each port that matters (nc in a loop: accepts several connections).
listen() {  # container port
  docker exec -d "$1" sh -c "while true; do nc -l -p $2 </dev/null >/dev/null 2>&1; done"
}
listen ctfw-panel 8080; listen ctfw-panel 22
listen ctfw-broker 8443
# The game's SSH answers 4s AFTER accepting: that is the broker install, which keeps
# writing on the already open session after the firewall goes in (see "sessao anterior" below).
# Only the FIRST connection (the broker's) waits; then the normal loop, otherwise the port would
# be closed for 4s between one test and the next and the following cases would give "fecha" by chance.
docker exec -d ctfw-game sh -c "(sleep 4; echo fim-da-instalacao) | nc -l -p 22 >/dev/null 2>&1; while true; do nc -l -p 22 </dev/null >/dev/null 2>&1; done"
listen ctfw-game 8888; listen ctfw-game 9999
# UDP has no "connected": what proves the packet got through is the file on the game side.
# -W 1 = one datagram per iteration, so the loop records each sender on its own line.
docker exec -d ctfw-game sh -c "while true; do nc -u -l -p 27015 -W 1 >> /tmp/udp.txt 2>/dev/null; done"
# The "game" on 7777 ANSWERS (like a real server): the answer is what makes the conversation
# established, and only an established conversation enters the player count.
docker exec -d ctfw-game sh -c "while true; do (sleep 1; echo pong) | nc -u -l -p 7777 -w 3 >/dev/null 2>&1; done"
listen ctfw-intruder 22
listen ctfw-api 8006; listen ctfw-api 3306
sleep 1

configure() {  # container env-contents
  MSYS_NO_PATHCONV=1 docker exec "$1" sh -c "printf '%s\n' \"\$0\" > /etc/ct-firewall.env && echo 'nameserver $PREFIX.1' > /etc/resolv.conf && ct-firewall apply" "$2" >/dev/null
}
configure ctfw-panel "FW_ROLE=panel
FW_ADMIN_SOURCES=\"$PREFIX.0/24\"
FW_PANEL_PORT=8080"
configure ctfw-broker "FW_ROLE=broker
FW_PANEL_SOURCES=\"$PANEL\"
FW_BROKER_PORT=8443
FW_API_ENDPOINTS=\"$API:8006\"
FW_GAME_NET=\"$PREFIX.102-$PREFIX.199\""
# The broker session opens BEFORE the apply, like the real installer's, and must keep
# receiving after it. WARNING from the author: this case does NOT reproduce the V Rising failure.
# There, in the Proxmox CT, nothing requested conntrack before the apply, and the first outgoing
# packet after it became a NEW connection (tcp_loose=1) and fell into the internal-network reject.
# Here, on the WSL2/Docker kernel, conntrack already tracks the session from the start, and the
# case passes even without the SSH reply rule (measured; not even a `notrack` before the apply
# changed that). The proof of the fix was on the real CT: the reply rule unblocked the stuck
# session and the creation finished. The case stays as a guard against the gross failure (an
# output rule that kills EVERY open session).
MSYS_NO_PATHCONV=1 docker exec -d ctfw-broker sh -c "nc -w 15 $GAME 22 </dev/null > /tmp/late.txt 2>&1"
sleep 1
configure ctfw-game "FW_ROLE=game
FW_MGMT_SOURCES=\"$PANEL $BROKER\"
FW_GAME_PORTS=\"8888/tcp 7777/udp\"
FW_PRESENCE_PORTS=\"7777\""

failures=0
tcp() {  # expected(abre|fecha) source destination port description
  local got=fecha
  docker exec "$2" nc -z -w 2 "$3" "$4" >/dev/null 2>&1 && got=abre
  if [[ "$got" == "$1" ]]; then
    printf 'ok    %-6s %s\n' "$1" "$5"
  else
    printf 'FALHA esperava %s, deu %s: %s\n' "$1" "$got" "$5"
    failures=$((failures + 1))
  fi
}

udp() {  # expected(abre|fecha) source description
  local got=fecha mark="udp-de-$2"
  docker exec "$2" sh -c "echo $mark | nc -u -w 1 $GAME 27015" >/dev/null 2>&1 || true
  sleep 1
  MSYS_NO_PATHCONV=1 docker exec ctfw-game grep -q "$mark" /tmp/udp.txt 2>/dev/null && got=abre
  if [[ "$got" == "$1" ]]; then
    printf 'ok    %-6s %s\n' "$1" "$3"
  else
    printf 'FALHA esperava %s, deu %s: %s\n' "$1" "$got" "$3"
    failures=$((failures + 1))
  fi
}

echo "== jogo"
sleep 6
if MSYS_NO_PATHCONV=1 docker exec ctfw-broker grep -q fim-da-instalacao /tmp/late.txt; then
  printf 'ok    %-6s %s\n' abre "sessao anterior ao apply (broker instalando) continua recebendo"
else
  printf 'FALHA sessao aberta antes do apply parou de receber (a instalacao travaria)\n'
  failures=$((failures + 1))
fi
tcp abre  ctfw-panel    "$GAME" 22   "painel -> SSH do jogo"
tcp abre  ctfw-broker   "$GAME" 22   "broker -> SSH do jogo (instalacao)"
tcp fecha ctfw-intruder "$GAME" 22   "intruso da LAN -> SSH do jogo"
tcp abre  ctfw-intruder "$GAME" 8888 "qualquer um -> porta publica do jogo"
tcp fecha ctfw-intruder "$GAME" 9999 "qualquer um -> porta que o jogo nao declarou"
# The panel's A2S query on a port the .env did not declare (27015 of an Unreal game).
udp abre  ctfw-panel    "painel -> UDP nao declarado do jogo (consulta A2S)"
udp fecha ctfw-intruder "intruso da LAN -> UDP nao declarado do jogo"

# Player count through the firewall: whoever talks to 7777 (the game answered) enters the
# `players` set; a stray packet on a port that does not answer does not.
presence() {  # expected(conta|nao-conta) source source-ip port description
  local got=nao-conta
  docker exec "$2" sh -c "(echo ping; sleep 2; echo de-novo; sleep 1) | nc -u -w 4 $GAME $4" >/dev/null 2>&1 || true
  MSYS_NO_PATHCONV=1 docker exec ctfw-game nft list set inet ct_firewall players 2>/dev/null \
    | grep -q "$3 \. " && got=conta
  if [[ "$got" == "$1" ]]; then
    printf 'ok    %-9s %s\n' "$1" "$5"
  else
    printf 'FALHA esperava %s, deu %s: %s\n' "$1" "$got" "$5"
    failures=$((failures + 1))
  fi
}
presence conta     ctfw-intruder "$INTRUDER" 7777 "jogador (conversa respondida) entra na contagem"
presence nao-conta ctfw-broker   "$BROKER"   8888 "pacote sem resposta nao vira jogador"
tcp fecha ctfw-game     "$PANEL" 8080 "jogo -> web do painel (rede interna)"
tcp fecha ctfw-game     "$INTRUDER" 22 "jogo -> outra maquina da LAN"
tcp fecha ctfw-game     "$API" 8006  "jogo -> Proxmox"

echo "== broker"
tcp abre  ctfw-panel    "$BROKER" 8443 "painel -> API do broker"
tcp fecha ctfw-intruder "$BROKER" 8443 "intruso da LAN -> API do broker"
tcp fecha ctfw-game     "$BROKER" 8443 "jogo -> API do broker"
tcp abre  ctfw-broker   "$API" 8006   "broker -> Proxmox"
tcp fecha ctfw-broker   "$API" 3306   "broker -> outra porta do mesmo host"
tcp fecha ctfw-broker   "$INTRUDER" 22 "broker -> SSH fora da faixa dos jogos"

echo "== painel"
tcp abre  ctfw-intruder "$PANEL" 8080 "LAN -> web do painel"
tcp abre  ctfw-intruder "$PANEL" 22   "LAN -> SSH do painel"
tcp abre  ctfw-panel    "$INTRUDER" 22 "painel -> fora (saida livre)"

echo "== desligar"
docker exec ctfw-game ct-firewall off >/dev/null
tcp abre  ctfw-intruder "$GAME" 22   "'ct-firewall off' devolve tudo (saida de emergencia)"

echo
if (( failures )); then
  echo "FALHOU: $failures verificacao(oes)"
  exit 1
fi
echo "TUDO OK"
