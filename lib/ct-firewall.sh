#!/usr/bin/env bash
# Firewall INSIDE the container (nftables), for the panel, the broker and the games.
#
# Why it exists: OPNsense only sees what CROSSES it. Within the same subnet
# (10.20.1.0/24) one CT talks to another directly, and a compromised game server would reach the
# panel's SSH, the broker API, Proxmox (:8006) and the OPNsense API without going through any
# rule at all. Here each CT refuses on its own whatever is not meant for it.
#
# Installed at /usr/local/sbin/ct-firewall; the CT configuration lives in /etc/ct-firewall.env
# (written by provisioning). One script for all three roles, and the same on every deploy
# path - the manual deploy and the broker's cannot diverge on a security rule.
#
#   ct-firewall apply    checks, writes /etc/nftables.conf, loads it and enables it at boot
#   ct-firewall render   only prints the rules (to check them first)
#   ct-firewall status   what is loaded right now
#   ct-firewall off      EMERGENCY EXIT: removes everything and disables it at boot.
#                        From the host: pct exec <CT> -- ct-firewall off
#
# Keys of /etc/ct-firewall.env (lists separated by spaces or commas):
#   FW_ROLE             panel | broker | game
#   panel:  FW_ADMIN_SOURCES   who reaches the web and SSH (e.g. 192.168.0.0/16)
#           FW_PANEL_PORT      web port (default 8080)
#   broker: FW_PANEL_SOURCES   who reaches the API (the panel IP)
#           FW_BROKER_PORT     API port (default 8443)
#           FW_API_ENDPOINTS   ip:port the broker may call (Proxmox, OPNsense)
#           FW_GAME_NET        range of the game CTs (SSH and ping during installation)
#   game:   FW_MGMT_SOURCES    who may open SSH and ping (panel and broker)
#           FW_GAME_PORTS      game ports, open to any source ("7777/udp 8888/tcp")
#           FW_PRESENCE_PORTS  UDP port(s) of the GAME whose conversations the panel counts as
#                              players ("7777"); empty = no counting. Never the query port.
set -Eeuo pipefail

CONF="${CT_FIREWALL_CONF:-/etc/ct-firewall.env}"
RULES="${CT_FIREWALL_RULES:-/etc/nftables.conf}"
RESOLV="${CT_FIREWALL_RESOLV:-/etc/resolv.conf}"

# Internal network: what a game cannot reach and what the broker only reaches with its own rule.
# 100.64/10 (CGNAT) and 169.254/16 (link-local, where cloud metadata lives) are included for the
# same reason: they are not the internet.
PRIVATE_V4="10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 169.254.0.0/16"
PRIVATE_V6="fc00::/7, fe80::/10"

die() { printf 'ct-firewall: %s\n' "$*" >&2; exit 1; }

# --- validation of what goes into the rules -------------------------------------------------
# Every value ends up INSIDE nft text. Checking its shape here is what stops a malformed
# value from becoming a rule nobody asked for (or a rule that does not load at boot).

IPV4_RE='^([0-9]{1,3}\.){3}[0-9]{1,3}(/[0-9]{1,2}|-([0-9]{1,3}\.){3}[0-9]{1,3})?$'

# "a, b c" -> "a, b, c", rejecting anything that is not IPv4, CIDR or an a-b range.
addr_list() {
  local name="$1" raw="$2" item out=""
  for item in ${raw//,/ }; do
    [[ "$item" =~ $IPV4_RE ]] || die "$name: '$item' is not an IPv4 address, CIDR or range"
    out+="${out:+, }$item"
  done
  printf '%s' "$out"
}

valid_port() {
  [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )) || die "$2: invalid port '$1'"
}

# DNS servers the CT uses: without them the game cannot resolve Steam's name, and the resolver
# may be an internal IP (the gateway, or the host). IPv4 only; loopback already passes via `lo`.
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
  [[ -f "$CONF" ]] || die "$CONF does not exist: nothing to apply"
  set -a
  # shellcheck disable=SC1090
  source "$CONF"
  set +a
  case "${FW_ROLE:-}" in
    panel|broker|game) ;;
    *) die "invalid FW_ROLE: '${FW_ROLE:-}' (use panel, broker or game)" ;;
  esac
}

# --- rules ----------------------------------------------------------------------------------

# Lifetime of a conversation in the presence set. A game client sends packets several times
# per second (even on the loading screen); 20 s of silence means someone closed the game or dropped.
PRESENCE_TIMEOUT="20s"

presence_ports() {
  local num out=""
  for num in ${FW_PRESENCE_PORTS:+${FW_PRESENCE_PORTS//,/ }}; do
    num="${num%%/*}"
    valid_port "$num" FW_PRESENCE_PORTS
    out+="${out:+, }$num"
  done
  printf '%s' "$out"
}

# The set the panel reads (`runtime/presence_probe.py`): source IP:port of whoever talks to the
# game port. Only ESTABLISHED conversations go in - the server has already replied -, so a scanner
# sending a stray packet does not become a player. It decides nothing: it only records, and the
# rule runs BEFORE the `established accept` of common_head, otherwise the packets of someone
# playing would never reach it.
presence_set() {
  [[ "$FW_ROLE" == game && -n "$(presence_ports)" ]] || return 0
  printf '  set players {\n    type ipv4_addr . inet_service\n'
  printf '    flags dynamic, timeout\n    timeout %s\n  }\n\n' "$PRESENCE_TIMEOUT"
}

presence_rule() {
  local ports
  ports="$(presence_ports)"
  [[ "$FW_ROLE" == game && -n "$ports" ]] || return 0
  printf '    udp dport { %s } ct state established update @players { ip saddr . udp sport }\n' "$ports"
}

# Common to all three: replies on an already open connection pass (that is what lets the panel
# receive the A2S answer and the game reply to the player), loopback passes (the Palworld and
# Satisfactory admin APIs only listen on 127.0.0.1), and ICMPv6 neighbor discovery passes
# (without it the CT's IPv6 cannot even find the router).
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
  [[ -n "$admin" ]] || die "FW_ADMIN_SOURCES is empty: nobody would reach the panel"
  valid_port "$port" FW_PANEL_PORT
  printf '    ip saddr { %s } tcp dport { 22, %s } accept\n' "$admin" "$port"
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$admin"
}

input_broker() {
  local panel port="${FW_BROKER_PORT:-8443}"
  panel="$(addr_list FW_PANEL_SOURCES "${FW_PANEL_SOURCES:-}")"
  [[ -n "$panel" ]] || die "FW_PANEL_SOURCES is empty: the panel would not reach the broker"
  valid_port "$port" FW_BROKER_PORT
  # No SSH on purpose: the broker has no sshd, the code arrives via `pct push`.
  printf '    ip saddr { %s } tcp dport %s accept\n' "$panel" "$port"
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$panel"
}

input_game() {
  local mgmt spec num proto tcp="" udp=""
  mgmt="$(addr_list FW_MGMT_SOURCES "${FW_MGMT_SOURCES:-}")"
  [[ -n "$mgmt" ]] || die "FW_MGMT_SOURCES is empty: the panel would lose SSH to this server"
  for spec in ${FW_GAME_PORTS//,/ }; do
    num="${spec%%/*}"
    proto="${spec#*/}"
    [[ "$spec" == */* ]] || proto="udp"
    valid_port "$num" FW_GAME_PORTS
    case "$proto" in
      tcp) tcp+="${tcp:+, }$num" ;;
      udp) udp+="${udp:+, }$num" ;;
      *) die "FW_GAME_PORTS: invalid protocol in '$spec'" ;;
    esac
  done
  # The game ports are public: the player arrives through the OPNsense NAT, from anywhere.
  [[ -n "$udp" ]] && printf '    udp dport { %s } accept\n' "$udp"
  [[ -n "$tcp" ]] && printf '    tcp dport { %s } accept\n' "$tcp"
  printf '    ip saddr { %s } tcp dport 22 accept\n' "$mgmt"
  # UDP from the administrators, on ANY port: that is how the panel runs the A2S query and the
  # wizard probes the game ports. With only the GAME_PORTS ones, a query port the .env did not
  # declare (Steam's 27015 in an Unreal game) was dropped here and the screen said
  # "no response" - it looked like a game without A2S. It opens nothing new: that source
  # already has root over SSH.
  printf '    ip saddr { %s } udp dport 1-65535 accept\n' "$mgmt"
  # The broker pings the IP before using it; a game that does not answer would look like a free address.
  printf '    ip saddr { %s } icmp type echo-request accept\n' "$mgmt"
}

dns_rules() {
  local dns
  dns="$(dns_servers)"
  [[ -n "$dns" ]] || return 0
  printf '    ip daddr { %s } udp dport 53 accept\n' "$dns"
  printf '    ip daddr { %s } tcp dport 53 accept\n' "$dns"
}

# The SSH and ping REPLY to the administrators, BEFORE everything else in the game's output -
# even before `ct state invalid drop`. Before this ruleset nothing in the CT requested conntrack,
# so the broker's SSH session, opened BEFORE the apply, was not tracked: the first outgoing packet
# after it reaches conntrack in the middle of the connection and leaves as invalid or as NEW -
# and both get dropped (by the invalid drop or by the internal network rejection). The V Rising
# installation hung like that, with the end of the log stuck in the socket queue and the
# operation "executando" forever. Measured in docker/ct-sandbox/firewall.sh ("sessao anterior
# ao apply"): with the rule after `invalid drop` the case keeps failing.
output_game_first() {
  local mgmt
  mgmt="$(addr_list FW_MGMT_SOURCES "${FW_MGMT_SOURCES:-}")"
  printf '    ip daddr { %s } tcp sport 22 accept\n' "$mgmt"
  printf '    ip daddr { %s } icmp type echo-reply accept\n' "$mgmt"
}

output_game() {
  # Internet allowed (Steam, apt, Proton from GitHub); internal network not. `reject`, not `drop`:
  # whoever tries sees the error right away, instead of waiting for a timeout that looks like a
  # slow network.
  dns_rules
  printf '    ip daddr { %s } reject with icmp type admin-prohibited\n' "$PRIVATE_V4"
  printf '    ip6 daddr { %s } reject with icmpv6 type admin-prohibited\n' "$PRIVATE_V6"
}

output_broker() {
  local endpoint ip port pairs="" games
  for endpoint in ${FW_API_ENDPOINTS//,/ }; do
    ip="${endpoint%:*}"
    port="${endpoint##*:}"
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "FW_API_ENDPOINTS: '$endpoint' is not ip:port"
    valid_port "$port" FW_API_ENDPOINTS
    pairs+="${pairs:+, }$ip . $port"
  done
  [[ -n "$pairs" ]] || die "FW_API_ENDPOINTS is empty: the broker would talk to neither Proxmox nor OPNsense"
  games="$(addr_list FW_GAME_NET "${FW_GAME_NET:-}")"
  [[ -n "$games" ]] || die "FW_GAME_NET is empty: the broker would not install any game"
  dns_rules
  printf '    ip daddr . tcp dport { %s } accept\n' "$pairs"
  printf '    ip daddr { %s } tcp dport 22 accept\n' "$games"
  printf '    ip daddr { %s } icmp type echo-request accept\n' "$games"
  # apt (updates of the CT itself), only towards the internet.
  printf '    ip daddr != { %s } tcp dport { 80, 443 } accept\n' "$PRIVATE_V4"
  # Everything else leaves with a visible rejection; the chain policy is drop.
  printf '    reject with icmpx type admin-prohibited\n'
}

render() {
  local out_policy=accept
  [[ "$FW_ROLE" == broker ]] && out_policy=drop
  printf '#!/usr/sbin/nft -f\n'
  printf '# Gerado por ct-firewall (papel: %s). Edite %s e rode "ct-firewall apply".\n' "$FW_ROLE" "$CONF"
  printf 'flush ruleset\n\n'
  printf 'table inet ct_firewall {\n'
  presence_set
  printf '  chain input {\n    type filter hook input priority filter; policy drop;\n'
  presence_rule
  common_head iif
  "input_${FW_ROLE}"
  printf '  }\n\n'
  # A CT routes nothing: anything arriving to be forwarded is a mistake or an attack.
  printf '  chain forward {\n    type filter hook forward priority filter; policy drop;\n  }\n\n'
  printf '  chain output {\n    type filter hook output priority filter; policy %s;\n' "$out_policy"
  [[ "$FW_ROLE" != game ]] || output_game_first
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
    || die "could not install nftables (apt-get install nftables)"
}

cmd_apply() {
  load_conf
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  # Render BEFORE touching anything: a malformed value stops here, with the old rules intact.
  render > "$tmp"
  ensure_nft
  # `nft -c` checks against the kernel without loading: a rule that does not go in cannot become
  # the boot file, otherwise the CT would come up with no firewall at all next time.
  nft -c -f "$tmp" || die "the kernel refused the rules; nothing was changed"
  install -m 0644 "$tmp" "$RULES"
  nft -f "$RULES"
  systemctl enable nftables >/dev/null 2>&1 || true
  printf 'ct-firewall: %s rules applied (%s)\n' "$FW_ROLE" "$RULES"
}

cmd_off() {
  command -v nft >/dev/null 2>&1 && nft flush ruleset
  systemctl disable nftables >/dev/null 2>&1 || true
  printf 'ct-firewall: firewall OFF in this CT (run "ct-firewall apply" to turn it back on)\n'
}

case "${1:-}" in
  apply) cmd_apply ;;
  render) load_conf; render ;;
  status) nft list ruleset ;;
  off) cmd_off ;;
  *) die "usage: ct-firewall apply | render | status | off" ;;
esac
