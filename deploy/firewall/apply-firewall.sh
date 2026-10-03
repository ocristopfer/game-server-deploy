#!/usr/bin/env bash
# Aplica o firewall de dentro do CT (lib/ct-firewall.sh) nos containers que JA EXISTEM:
# painel, broker e os jogos. Os CTs novos ja nascem com ele (provision-*-lxc.sh e o
# instalador do broker); este script e para os que vieram antes.
#
# Roda no HOST do Proxmox, chamado pelo apply-firewall.ps1. Tudo passa por `pct`, e nao pela
# rede: uma regra errada nunca tranca este script fora do CT que ele acabou de mexer. Cada CT
# e TESTADO depois de aplicar (a conexao que importa para ele) e, se o teste falhar, o
# firewall daquele CT e desligado na hora - fica o aviso, nao um servidor inalcancavel.
#
# Le fw.env (ao lado): PANEL_CTID BROKER_CTID ADMIN_FIREWALL_SOURCES PANEL_PORT BROKER_PORT
# BROKER_IP_PREFIX BROKER_IP_INICIO BROKER_IP_FIM EXTRA_GAME_CTS ONLY_CTS DRY_RUN
set -Eeuo pipefail
trap 'printf "\n[ERROR] linha %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIREWALL="$SCRIPT_DIR/ct-firewall.sh"
GAMES_DIR="$SCRIPT_DIR/games"

msg() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "$SCRIPT_DIR/fw.env" ]] || die "fw.env nao encontrado ao lado do script"
[[ -f "$FIREWALL" ]] || die "ct-firewall.sh nao encontrado ao lado do script"
set -a
# shellcheck disable=SC1091
source "$SCRIPT_DIR/fw.env"
set +a

PANEL_CTID="${PANEL_CTID:-}"
BROKER_CTID="${BROKER_CTID:-}"
PANEL_PORT="${PANEL_PORT:-8080}"
BROKER_PORT="${BROKER_PORT:-8443}"
ADMIN_FIREWALL_SOURCES="${ADMIN_FIREWALL_SOURCES:-192.168.0.0/16}"
DRY_RUN="${DRY_RUN:-0}"
ok_count=0
failed=()
skipped=()

selected() {  # ctid -> 0 se o CT entra nesta rodada
  [[ -z "${ONLY_CTS:-}" ]] && return 0
  [[ " ${ONLY_CTS//,/ } " == *" $1 "* ]]
}

running() { pct status "$1" 2>/dev/null | grep -q running; }

ct_ip() { pct exec "$1" -- hostname -I 2>/dev/null | awk '{print $1}'; }

# De dentro de `from`, abre TCP em ip:porta. E a prova de que a regra deixa passar quem deve.
reaches() {  # from ip porta
  pct exec "$1" -- timeout 5 bash -c "</dev/tcp/$2/$3" >/dev/null 2>&1
}

# "https://192.168.2.1:8443/" -> "192.168.2.1:8443"
endpoint_of() {
  local url="$1" rest host port
  rest="${url#*://}"
  rest="${rest%%/*}"
  host="${rest%%:*}"
  if [[ "$rest" == *:* ]]; then port="${rest##*:}"
  elif [[ "$url" == https://* ]]; then port=443
  else port=80
  fi
  printf '%s:%s' "$host" "$port"
}

# Aplica num CT e roda `verify` (um comando do host). Falhou o teste: desliga e avisa.
apply_to() {  # ctid descricao conf verify...
  local ctid="$1" label="$2" conf="$3"
  shift 3
  if ! running "$ctid"; then
    skipped+=("$ctid ($label): CT parado")
    return 0
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    # So mostra: arquivos em /tmp do CT, nada do que vale e tocado.
    pct push "$ctid" "$FIREWALL" /tmp/ct-firewall --perms 0755
    pct push "$ctid" "$conf" /tmp/ct-firewall.env --perms 0600
    msg "CT $ctid ($label) - regras que seriam aplicadas:"
    pct exec "$ctid" -- env CT_FIREWALL_CONF=/tmp/ct-firewall.env bash /tmp/ct-firewall render \
      || failed+=("$ctid ($label): configuracao recusada")
    pct exec "$ctid" -- rm -f /tmp/ct-firewall /tmp/ct-firewall.env
    return 0
  fi
  msg "CT $ctid ($label)"
  pct push "$ctid" "$FIREWALL" /usr/local/sbin/ct-firewall --perms 0755
  pct push "$ctid" "$conf" /etc/ct-firewall.env --perms 0644
  if ! pct exec "$ctid" -- /usr/local/sbin/ct-firewall apply; then
    failed+=("$ctid ($label): as regras nao carregaram (o CT ficou como estava)")
    return 0
  fi
  if "$@"; then
    printf '  teste ok\n'
    ok_count=$((ok_count + 1))
  else
    pct exec "$ctid" -- /usr/local/sbin/ct-firewall off || true
    failed+=("$ctid ($label): o teste de conexao falhou - firewall DESLIGADO neste CT")
  fi
}

write_conf() {  # arquivo linhas...
  local file="$1"
  shift
  printf '%s\n' "$@" > "$file"
}

# ---------------------------------------------------------------------------------- inicio
modprobe nf_tables 2>/dev/null || warn "nao consegui carregar o modulo nf_tables no host"
{ mkdir -p /etc/modules-load.d && echo nf_tables > /etc/modules-load.d/ct-firewall.conf; } \
  || warn "nao consegui deixar o nf_tables carregando no boot do host"

[[ -n "$PANEL_CTID" ]] && running "$PANEL_CTID" || die "o CT do painel (${PANEL_CTID:-?}) precisa estar ligado: e dele que os testes partem"
PANEL_IP="$(ct_ip "$PANEL_CTID")"
[[ -n "$PANEL_IP" ]] || die "nao descobri o IP do painel (CT $PANEL_CTID)"
BROKER_IP=""
if [[ -n "$BROKER_CTID" ]] && running "$BROKER_CTID"; then
  BROKER_IP="$(ct_ip "$BROKER_CTID")"
fi
MGMT="$PANEL_IP${BROKER_IP:+ $BROKER_IP}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- broker ---------------------------------------------------------------------------------
if [[ -n "$BROKER_IP" ]] && selected "$BROKER_CTID"; then
  urls="$(pct exec "$BROKER_CTID" -- sh -c '. /etc/gamebroker/broker.env; echo "$PROXMOX_URL $OPNSENSE_URL"')"
  read -r px_url op_url <<<"$urls"
  px="$(endpoint_of "$px_url")"
  op="$(endpoint_of "$op_url")"
  write_conf "$tmp/broker.env" "FW_ROLE=broker" "FW_PANEL_SOURCES=\"$PANEL_IP\"" \
    "FW_BROKER_PORT=\"$BROKER_PORT\"" "FW_API_ENDPOINTS=\"$px $op\"" \
    "FW_GAME_NET=\"${BROKER_IP_PREFIX}.${BROKER_IP_INICIO:-102}-${BROKER_IP_PREFIX}.${BROKER_IP_FIM:-199}\""
  verify_broker() {
    reaches "$PANEL_CTID" "$BROKER_IP" "$BROKER_PORT" \
      && reaches "$BROKER_CTID" "${px%:*}" "${px##*:}" \
      && reaches "$BROKER_CTID" "${op%:*}" "${op##*:}"
  }
  apply_to "$BROKER_CTID" "broker" "$tmp/broker.env" verify_broker
fi

# --- jogos do broker --------------------------------------------------------------------------
# A lista e as portas vem do banco do broker: e la que esta o que cada instancia recebeu (um
# jogo que anda de porta nao esta nas portas do games/*.env).
game_lines=""
if [[ -n "$BROKER_IP" ]]; then
  game_lines="$(pct exec "$BROKER_CTID" -- python3 -c '
import sqlite3
c = sqlite3.connect("file:/var/lib/gamebroker/broker.db?mode=ro", uri=True)
for iid, handle, ip in c.execute("SELECT id, handle, ip FROM instances").fetchall():
    ports = c.execute("SELECT number, proto, role FROM ports WHERE instance_id = ?", (iid,)).fetchall()
    game = [str(n) for n, p, r in ports if r == "jogo" and p == "udp"]
    print(handle, ip, ",".join(game) or "-", " ".join(f"{n}/{p}" for n, p, _ in ports))
')"
fi

# A presenca (FW_PRESENCE_PORTS) e a porta UDP do JOGO, por onde o painel conta quem esta
# conversando com ele; "-" = nenhuma. Ver o ct-firewall.sh.
apply_game() {  # ctid ip portas descricao presenca
  local ctid="$1" ip="$2" ports="$3" label="$4" presence="${5:--}"
  [[ "$presence" != "-" ]] || presence=""
  if [[ -z "$ports" ]]; then
    skipped+=("$ctid ($label): nao sei as portas do jogo")
    return 0
  fi
  write_conf "$tmp/game-$ctid.env" "FW_ROLE=game" "FW_MGMT_SOURCES=\"$MGMT\"" "FW_GAME_PORTS=\"$ports\""     "FW_PRESENCE_PORTS=\"$presence\""
  # shellcheck disable=SC2317
  verify_game() { reaches "$PANEL_CTID" "$ip" 22; }
  apply_to "$ctid" "$label" "$tmp/game-$ctid.env" verify_game
}

while read -r handle ip presence ports; do
  [[ -n "${handle:-}" ]] || continue
  selected "$handle" || continue
  apply_game "$handle" "$ip" "$ports" "jogo do broker, $ip" "$presence"
done <<<"$game_lines"

# --- jogos legados (feitos pelo deploy-game.ps1) ----------------------------------------------
# Portas do games/<jogo>.env; o jogo e reconhecido pela unit <jogo>.service dentro do CT.
for ctid in ${EXTRA_GAME_CTS//,/ }; do
  selected "$ctid" || continue
  if ! running "$ctid"; then
    skipped+=("$ctid (legado): CT parado")
    continue
  fi
  key=""
  for env_file in "$GAMES_DIR"/*.env; do
    k="$(basename "$env_file" .env)"
    if pct exec "$ctid" -- test -f "/etc/systemd/system/${k}.service"; then key="$k"; break; fi
  done
  if [[ -z "$key" ]]; then
    skipped+=("$ctid (legado): nao reconheci o jogo (nenhuma unit <jogo>.service conhecida)")
    continue
  fi
  ports="$(bash -c 'set -a; source "$1"; echo "${GAME_PORTS:-}"' _ "$GAMES_DIR/$key.env")"
  # Mesma regra do ct-phases.sh: sem presenca quando a consulta divide a porta do jogo.
  presence="$(bash -c 'set -a; source "$1"; [[ "${GAME_PORT:-}" != "${QUERY_PORT:-0}" ]] && echo "${GAME_PORT:-}"' _ "$GAMES_DIR/$key.env" || true)"
  apply_game "$ctid" "$(ct_ip "$ctid")" "$ports" "legado, $key" "${presence:--}"
done

# --- painel (por ultimo: e dele que os outros testes partem) --------------------------------
if selected "$PANEL_CTID"; then
  write_conf "$tmp/panel.env" "FW_ROLE=panel" "FW_ADMIN_SOURCES=\"$ADMIN_FIREWALL_SOURCES\"" \
    "FW_PANEL_PORT=\"$PANEL_PORT\""
  # Do host: ele esta na rede de administracao. Se nao chega, a lista esta errada.
  verify_panel() { timeout 5 bash -c "</dev/tcp/$PANEL_IP/$PANEL_PORT" 2>/dev/null; }
  apply_to "$PANEL_CTID" "painel" "$tmp/panel.env" verify_panel
fi

# ------------------------------------------------------------------------------------ resumo
printf '\n==================== FIREWALL DOS CTs ====================\n'
[[ "$DRY_RUN" == "1" ]] && printf 'Modo so-mostrar: NADA foi aplicado.\n'
printf 'Aplicado e testado: %s CT(s)\n' "$ok_count"
for line in "${skipped[@]}"; do printf 'PULADO  %s\n' "$line"; done
for line in "${failed[@]}"; do printf 'FALHOU  %s\n' "$line"; done
printf '\nDesligar num CT (emergencia): pct exec <CT> -- ct-firewall off\n'
printf 'Ver as regras de um CT:        pct exec <CT> -- ct-firewall status\n'
(( ${#failed[@]} == 0 ))
