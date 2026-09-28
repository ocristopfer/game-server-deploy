#!/usr/bin/env bash
# Prova o lib/ct-firewall.sh com nftables DE VERDADE: nao so que as regras carregam no kernel,
# mas que bloqueiam e liberam o que devem. Precisa do Docker.
#
# Monta uma rede isolada com um container por papel (e um intruso na mesma LAN) e testa cada
# conexao que importa. O intruso e o caso que o OPNsense nao cobre: uma maquina da mesma
# sub-rede, que fala direto com os CTs.
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
API=$PREFIX.254      # faz o papel do Proxmox (:8006)
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

start() {  # nome ip
  MSYS_NO_PATHCONV=1 docker run -d --name "$1" --network "$NET" --ip "$2" --cap-add NET_ADMIN --cap-add NET_RAW \
    -v "$(host_path)/lib:/src:ro" ctfw-sandbox sleep infinity >/dev/null
  MSYS_NO_PATHCONV=1 docker exec "$1" install -m 0755 /src/ct-firewall.sh /usr/local/sbin/ct-firewall
}
for pair in "ctfw-panel $PANEL" "ctfw-broker $BROKER" "ctfw-game $GAME" "ctfw-intruder $INTRUDER" "ctfw-api $API"; do
  # shellcheck disable=SC2086
  start $pair
done

# Um "servico" escutando em cada porta que interessa (nc em laco: aceita varias conexoes).
listen() {  # container porta
  docker exec -d "$1" sh -c "while true; do nc -l -p $2 </dev/null >/dev/null 2>&1; done"
}
listen ctfw-panel 8080; listen ctfw-panel 22
listen ctfw-broker 8443
# O SSH do jogo responde 4s DEPOIS de aceitar: e a instalacao do broker, que continua
# escrevendo na sessao ja aberta depois que o firewall entra (ver "sessao anterior" abaixo).
# So a PRIMEIRA conexao (a do broker) espera; depois o laco normal, senao a porta ficaria 4s
# fechada entre um teste e outro e os casos seguintes dariam "fecha" por acaso.
docker exec -d ctfw-game sh -c "(sleep 4; echo fim-da-instalacao) | nc -l -p 22 >/dev/null 2>&1; while true; do nc -l -p 22 </dev/null >/dev/null 2>&1; done"
listen ctfw-game 8888; listen ctfw-game 9999
listen ctfw-intruder 22
listen ctfw-api 8006; listen ctfw-api 3306
sleep 1

configure() {  # container conteudo-do-env
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
# A sessao do broker abre ANTES do apply, como a do instalador real, e tem de continuar
# recebendo depois dele. AVISO de quem escreveu: este caso NAO reproduz a falha do V Rising. La,
# no CT do Proxmox, nada pedia conntrack antes do apply, e o primeiro pacote de saida depois
# dele virava conexao NOVA (tcp_loose=1) e caia na recusa da rede interna. Aqui, no kernel do
# WSL2/Docker, o conntrack ja acompanha a sessao desde o inicio, e o caso passa ate sem a regra
# de resposta do SSH (medido; nem um `notrack` antes do apply mudou isso). A prova da correcao
# foi no CT real: a regra de resposta destravou a sessao presa e a criacao terminou. O caso fica
# como guarda contra o grosseiro (uma saida que derrube TODA sessao aberta).
MSYS_NO_PATHCONV=1 docker exec -d ctfw-broker sh -c "nc -w 15 $GAME 22 </dev/null > /tmp/late.txt 2>&1"
sleep 1
configure ctfw-game "FW_ROLE=game
FW_MGMT_SOURCES=\"$PANEL $BROKER\"
FW_GAME_PORTS=\"8888/tcp 7777/udp\""

failures=0
tcp() {  # esperado(abre|fecha) origem destino porta descricao
  local got=fecha
  docker exec "$2" nc -z -w 2 "$3" "$4" >/dev/null 2>&1 && got=abre
  if [[ "$got" == "$1" ]]; then
    printf 'ok    %-6s %s\n' "$1" "$5"
  else
    printf 'FALHA esperava %s, deu %s: %s\n' "$1" "$got" "$5"
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
