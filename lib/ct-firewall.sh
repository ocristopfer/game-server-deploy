#!/usr/bin/env bash
# Firewall de DENTRO do container (nftables), para o painel, o broker e os jogos.
#
# Por que existe: o OPNsense so ve o que ATRAVESSA ele. Dentro da mesma sub-rede
# (192.168.2.0/24) um CT fala com o outro direto, e um servidor de jogo invadido alcancaria o
# SSH do painel, a API do broker, o Proxmox (:8006) e a API do OPNsense sem passar por regra
# nenhuma. Aqui cada CT recusa por conta propria o que nao e dele.
#
# Instalado em /usr/local/sbin/ct-firewall; a configuracao do CT mora em /etc/ct-firewall.env
# (gravada pelo provisionamento). Um script so para os tres papeis, e o mesmo em todo caminho
# de deploy - o deploy manual e o do broker nao podem divergir em regra de seguranca.
#
#   ct-firewall apply    confere, grava /etc/nftables.conf, carrega e liga no boot
#   ct-firewall render   so imprime as regras (para conferir antes)
#   ct-firewall status   o que esta carregado agora
#   ct-firewall off      SAIDA DE EMERGENCIA: tira tudo e desliga no boot.
#                        Pelo host: pct exec <CT> -- ct-firewall off
#
# Chaves de /etc/ct-firewall.env (listas separadas por espaco ou virgula):
#   FW_ROLE             panel | broker | game
#   panel:  FW_ADMIN_SOURCES   quem chega na web e no SSH (ex.: 192.168.0.0/16)
#           FW_PANEL_PORT      porta da web (padrao 8080)
#   broker: FW_PANEL_SOURCES   quem chega na API (o IP do painel)
#           FW_BROKER_PORT     porta da API (padrao 8443)
#           FW_API_ENDPOINTS   ip:porta que o broker pode chamar (Proxmox, OPNsense)
#           FW_GAME_NET        faixa dos CTs de jogo (SSH e ping de instalacao)
#   game:   FW_MGMT_SOURCES    quem pode abrir SSH e pingar (painel e broker)
#           FW_GAME_PORTS      portas do jogo, abertas para qualquer origem ("7777/udp 8888/tcp")
set -Eeuo pipefail

CONF="${CT_FIREWALL_CONF:-/etc/ct-firewall.env}"
RULES="${CT_FIREWALL_RULES:-/etc/nftables.conf}"
RESOLV="${CT_FIREWALL_RESOLV:-/etc/resolv.conf}"

# Rede interna: o que um jogo nao pode alcancar e o que o broker so alcanca com regra propria.
# 100.64/10 (CGNAT) e 169.254/16 (link-local, onde mora metadado de nuvem) entram pelo mesmo
# motivo: nao sao internet.
PRIVATE_V4="10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 169.254.0.0/16"
PRIVATE_V6="fc00::/7, fe80::/10"

die() { printf 'ct-firewall: %s\n' "$*" >&2; exit 1; }

# --- conferencia do que entra nas regras ----------------------------------------------------
# Todo valor vai parar DENTRO de um texto do nft. Conferir a forma aqui e o que impede um
# valor torto de virar regra que ninguem pediu (ou uma regra que nao carrega no boot).

IPV4_RE='^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2}|-([0-9]{1,3}\.){3}[0-9]{1,3})?$'

# "a, b c" -> "a, b, c", recusando o que nao for IPv4, CIDR ou faixa a-b.
addr_list() {
  local name="$1" raw="$2" item out=""
  for item in ${raw//,/ }; do
    [[ "$item" =~ $IPV4_RE ]] || die "$name: '$item' nao e IPv4, CIDR nem faixa"
    out+="${out:+, }$item"
  done
  printf '%s' "$out"
}

valid_port() {
  [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )) || die "$2: porta invalida '$1'"
}

# Servidores DNS que o CT usa: sem eles o jogo nao resolve o nome da Steam, e o resolvedor
# pode ser um IP interno (o gateway, ou o host). So IPv4; loopback ja passa por `lo`.
dns_servers() {
  local out="" ip key
  [[ -f "$RESOLV" ]] || { printf ''; return; }
  while read -r key ip _; do
    [[ "$key" == nameserver && "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ && "$ip" != 127.* ]] || continue
    out+="${out:+, }$ip"
  done < "$RESOLV"
  printf '%s' "$out"
}

load_conf() {
  [[ -f "$CONF" ]] || die "$CONF nao existe: nada a aplicar"
  set -a
  # shellcheck disable=SC1090
  source "$CONF"
  set +a
  case "${FW_ROLE:-}" in
    panel|broker|game) ;;
    *) die "FW_ROLE invalido: '${FW_ROLE:-}' (use panel, broker ou game)" ;;
  esac
}

# --- regras ---------------------------------------------------------------------------------

# Comum aos tres: resposta de conexao ja aberta passa (e o que deixa o painel receber a volta
# do A2S e o jogo responder ao jogador), loopback passa (as APIs de admin do Palworld e do
# Satisfactory so escutam em 127.0.0.1), e o ICMPv6 de vizinhanca passa (sem ele o IPv6 do CT
# nao acha nem o roteador).
common_head() {
  cat <<'EOF'
    ct state invalid drop
    ct state established,related accept
EOF
  printf '    %s "lo" accept\n' "$1"
  cat <<'EOF'
    icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit, nd-router-advert } accept
EOF
}

input_panel() {
  local admin port="${FW_PANEL_PORT:-8080}"
  admin="$(addr_list FW_ADMIN_SOURCES "${FW_ADMIN_SOURCES:-}")"
  [[ -n "$admin" ]] || die "FW_ADMIN_SOURCES vazio: ninguem alcancaria o painel"
  valid_port "$port" FW_PANEL_PORT
  printf '    ip saddr { %s } tcp dport { 22, %s } accept\n' "$admin" "$port"
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$admin"
}

input_broker() {
  local panel port="${FW_BROKER_PORT:-8443}"
  panel="$(addr_list FW_PANEL_SOURCES "${FW_PANEL_SOURCES:-}")"
  [[ -n "$panel" ]] || die "FW_PANEL_SOURCES vazio: o painel nao alcancaria o broker"
  valid_port "$port" FW_BROKER_PORT
  # Sem SSH de proposito: o broker nao tem sshd, o codigo chega por `pct push`.
  printf '    ip saddr { %s } tcp dport %s accept\n' "$panel" "$port"
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$panel"
}

input_game() {
  local mgmt spec num proto tcp="" udp=""
  mgmt="$(addr_list FW_MGMT_SOURCES "${FW_MGMT_SOURCES:-}")"
  [[ -n "$mgmt" ]] || die "FW_MGMT_SOURCES vazio: o painel perderia o SSH deste servidor"
  for spec in ${FW_GAME_PORTS//,/ }; do
    num="${spec%%/*}"
    proto="${spec#*/}"
    [[ "$spec" == */* ]] || proto="udp"
    valid_port "$num" FW_GAME_PORTS
    case "$proto" in
      tcp) tcp+="${tcp:+, }$num" ;;
      udp) udp+="${udp:+, }$num" ;;
      *) die "FW_GAME_PORTS: protocolo invalido em '$spec'" ;;
    esac
  done
  # As portas do jogo sao publicas: o jogador chega pelo NAT do OPNsense, de qualquer lugar.
  [[ -n "$udp" ]] && printf '    udp dport { %s } accept\n' "$udp"
  [[ -n "$tcp" ]] && printf '    tcp dport { %s } accept\n' "$tcp"
  printf '    ip saddr { %s } tcp dport 22 accept\n' "$mgmt"
  # O broker pinga o IP antes de usa-lo; um jogo que nao responde pareceria endereco livre.
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$mgmt"
}

dns_rules() {
  local dns
  dns="$(dns_servers)"
  [[ -n "$dns" ]] || return 0
  printf '    ip daddr { %s } udp dport 53 accept\n' "$dns"
  printf '    ip daddr { %s } tcp dport 53 accept\n' "$dns"
}

output_game() {
  # Internet liberada (Steam, apt, Proton do GitHub); rede interna nao. `reject` e nao `drop`:
  # quem tentar ve o erro na hora, em vez de esperar um timeout que parece rede lenta.
  dns_rules
  printf '    ip daddr { %s } reject with icmp type admin-prohibited\n' "$PRIVATE_V4"
  printf '    ip6 daddr { %s } reject with icmpv6 type admin-prohibited\n' "$PRIVATE_V6"
}

output_broker() {
  local endpoint ip port pairs="" games
  for endpoint in ${FW_API_ENDPOINTS//,/ }; do
    ip="${endpoint%:*}"
    port="${endpoint##*:}"
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "FW_API_ENDPOINTS: '$endpoint' nao e ip:porta"
    valid_port "$port" FW_API_ENDPOINTS
    pairs+="${pairs:+, }$ip . $port"
  done
  [[ -n "$pairs" ]] || die "FW_API_ENDPOINTS vazio: o broker nao falaria com o Proxmox nem com o OPNsense"
  games="$(addr_list FW_GAME_NET "${FW_GAME_NET:-}")"
  [[ -n "$games" ]] || die "FW_GAME_NET vazio: o broker nao instalaria jogo nenhum"
  dns_rules
  printf '    ip daddr . tcp dport { %s } accept\n' "$pairs"
  printf '    ip daddr { %s } tcp dport 22 accept\n' "$games"
  printf '    ip daddr { %s } icmp type echo-request accept\n' "$games"
  # apt (atualizacao do proprio CT), so para a internet.
  printf '    ip daddr != { %s } tcp dport { 80, 443 } accept\n' "$PRIVATE_V4"
  # O resto sai com recusa visivel; a politica da cadeia e drop.
  printf '    reject with icmpx type admin-prohibited\n'
}

render() {
  local out_policy=accept
  [[ "$FW_ROLE" == broker ]] && out_policy=drop
  printf '#!/usr/sbin/nft -f\n'
  printf '# Gerado por ct-firewall (papel: %s). Edite %s e rode "ct-firewall apply".\n' "$FW_ROLE" "$CONF"
  printf 'flush ruleset\n\n'
  printf 'table inet ct_firewall {\n'
  printf '  chain input {\n    type filter hook input priority filter; policy drop;\n'
  common_head iif
  "input_${FW_ROLE}"
  printf '  }\n\n'
  # CT nao roteia nada: o que chegar para encaminhar e engano ou ataque.
  printf '  chain forward {\n    type filter hook forward priority filter; policy drop;\n  }\n\n'
  printf '  chain output {\n    type filter hook output priority filter; policy %s;\n' "$out_policy"
  common_head oif
  case "$FW_ROLE" in
    game) output_game ;;
    broker) output_broker ;;
  esac
  printf '  }\n}\n'
}

ensure_nft() {
  command -v nft >/dev/null 2>&1 && return 0
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q nftables >/dev/null \
    || die "nao consegui instalar o nftables (apt-get install nftables)"
}

cmd_apply() {
  load_conf
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  # Gera ANTES de mexer em qualquer coisa: valor torto para aqui, com a regra antiga intacta.
  render > "$tmp"
  ensure_nft
  # `nft -c` confere no kernel sem carregar: uma regra que nao entra nao pode virar o arquivo
  # de boot, senao o CT subiria sem firewall nenhum da proxima vez.
  nft -c -f "$tmp" || die "o kernel recusou as regras; nada foi alterado"
  install -m 0644 "$tmp" "$RULES"
  nft -f "$RULES"
  systemctl enable nftables >/dev/null 2>&1 || true
  printf 'ct-firewall: regras de %s aplicadas (%s)\n' "$FW_ROLE" "$RULES"
}

cmd_off() {
  command -v nft >/dev/null 2>&1 && nft flush ruleset
  systemctl disable nftables >/dev/null 2>&1 || true
  printf 'ct-firewall: firewall DESLIGADO neste CT (rode "ct-firewall apply" para religar)\n'
}

case "${1:-}" in
  apply) cmd_apply ;;
  render) load_conf; render ;;
  status) nft list ruleset ;;
  off) cmd_off ;;
  *) die "uso: ct-firewall apply | render | status | off" ;;
esac
