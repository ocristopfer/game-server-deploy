#!/bin/bash
# Runs INSIDE the sandbox: runs the real provision-broker-lxc.sh (with fake pct/systemctl/apt)
# and checks what it left in the "CT". Exits with the number of failures.
#
#   run-broker.sh <repo-mounted-at-/repo>
set -u
REPO="${1:-/repo}"
failures=0
ok()  { printf 'OK        %s\n' "$*"; }
fail() { printf 'FALHOU    %s\n' "$*"; failures=$((failures + 1)); }
check() { # description, expected, actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (esperado '$2', veio '$3')"; fi
}

# ----- bundle identical to what deploy-broker.ps1 builds -----
# The CODE goes in a release tarball (no longer file by file); lib/ and games/
# stay loose, which is what the deploy does.
work=$(mktemp -d)
mkdir -p "$work/lib" "$work/games"
python3 "$REPO/tools/build-release.py" gamebroker --out "$work/dist" >/dev/null 2>&1   || { echo "FALHOU    build-release.py nao gerou o pacote do broker"; exit 1; }
release_tar="$(basename "$(ls "$work"/dist/gamebroker-*.tar.gz)")"
cp "$work/dist/$release_tar" "$work/"
printf "RELEASE_TARBALL='%s'
RELEASE_SHA256='%s'
" "$release_tar"   "$(sha256sum "$work/$release_tar" | cut -d' ' -f1)" > "$work/release.env"
cp "$REPO"/lib/*.sh "$work/lib/"
cp "$REPO/lib/install-release.sh" "$work/install-release.sh"
cp "$REPO"/games/*.env "$work/games/"
cp "$REPO/deploy/broker/provision-broker-lxc.sh" "$work/"
cat > "$work/broker.conf.env" <<'CONF'
BROKER_CTID='208'
BROKER_HOSTNAME='gamebroker'
BROKER_IP_CIDR='10.20.1.18/24'
BROKER_GATEWAY='10.20.1.1'
STORAGE='fake'
TEMPLATE_STORAGE='fake'
BRIDGE='vmbr0'
BROKER_IP_PREFIX='10.20.1'
BROKER_ALLOW_IPS='10.20.1.19'
ADMIN_CTID='209'
CONF
# Secret with EVERYTHING that usually breaks: double quotes, backslash, dollar, backtick, space.
cat > "$work/secrets.modelo" <<'SEC'
PROXMOX_URL='https://10.20.0.2:8006'
PROXMOX_TOKEN='broker@pve!broker=segredo-do-proxmox-0123456789'
PROXMOX_NODE='pve'
PROXMOX_POOL='games'
PROXMOX_STORAGE='local-lvm'
PROXMOX_TEMPLATE_STORAGE='local'
PROXMOX_BRIDGE='vmbr0'
PROXMOX_CERT_SHA256='AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA'
OPNSENSE_URL='https://10.20.0.1:8443/'
OPNSENSE_KEY='qSNu/chave+de=teste'
OPNSENSE_SECRET='a"b\c$d`e f'
OPNSENSE_CERT_SHA256='BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB:BB'
OPNSENSE_WAN='wan'
SEC

# ----- the "panel CT" (pct exec 209 runs right here) -----
useradd --system gamepanel 2>/dev/null
mkdir -p /etc/gamepanel
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelPainelPainelPainelPainel painel@gp' > /etc/gamepanel/id_ed25519.pub
printf 'GAMEPANEL_PORT=8080\nGAMEPANEL_ALLOW_SHELL=1\n' > /etc/gamepanel/panel.env

provision() { # log, [VAR=value ...]
  local log="$1"; shift
  cp "$work/secrets.modelo" "$work/broker.secrets.env"
  ( cd "$work" && env BROKER_SKIP_HEALTHCHECK=1 BROKER_CONFIGURE_PANEL=1 "$@" bash ./provision-broker-lxc.sh ) > "$log" 2>&1
}
token() { cat /etc/gamebroker/token; }
cert()  { openssl x509 -in /etc/gamebroker/tls/cert.pem -noout -fingerprint -sha256 | cut -d= -f2; }

echo "== 1o deploy =="
provision /tmp/deploy1.log
check "deploy terminou sem erro" 0 "$?"
T1="$(token)"; C1="$(cert)"; K1="$(cat /etc/gamebroker/ssh/id_ed25519.pub)"

check "broker.env: modo/dono"           "640 root:gamebroker"        "$(stat -c '%a %U:%G' /etc/gamebroker/broker.env)"
check "token: modo/dono"                "600 root:root"              "$(stat -c '%a %U:%G' /etc/gamebroker/token)"
check "chave ssh do broker: modo/dono"  "600 gamebroker:gamebroker"  "$(stat -c '%a %U:%G' /etc/gamebroker/ssh/id_ed25519)"
check "chave privada TLS: modo/dono"    "600 gamebroker:gamebroker"  "$(stat -c '%a %U:%G' /etc/gamebroker/tls/key.pem)"
check "codigo do broker e de root"      "root:root"                  "$(stat -c '%U:%G' /opt/gamebroker/current/gamebroker/wsgi.py)"
[ "${#T1}" -ge 32 ] && ok "token com ${#T1} caracteres" || fail "token curto: ${#T1}"
openssl x509 -in /etc/gamebroker/tls/cert.pem -noout -ext subjectAltName | grep -q '10.20.1.18' \
  && ok "SAN = 10.20.1.18" || fail "SAN sem o IP do broker"

# What goes to production does NOT carry test doubles nor the toy broker.
enviados="$(ls /opt/gamebroker/current/gamebroker)"
if echo "$enviados" | grep -Eq '^(test_|conftest|fakes|fake_http|dev\.py)'; then fail "dobles de teste foram para o CT: $(echo "$enviados" | tr '\n' ' ')"; else ok "sem dobles de teste no CT ($(echo "$enviados" | wc -l) modulos)"; fi
[ -L /opt/gamebroker/current ] && ok "current e um symlink" || fail "current nao e symlink"
[ -f /opt/gamebroker/current/gamebroker/_build.py ] && ok "o carimbo de versao chegou"   || fail "_build.py ausente no CT"
[ -f /opt/gamebroker/lib/ct-install.sh ] && [ -f /opt/gamebroker/lib/ct-phases.sh ] && ok "lib/ enviada" || fail "lib/ ausente"
[ "$(ls /opt/gamebroker/games/*.env | wc -l)" -ge 8 ] && ok "games/*.env enviados" || fail "games/ incompleto"
[ -f /opt/gamebroker/lib/ct-firewall.sh ] && ok "lib/ct-firewall.sh enviada (vai para cada CT de jogo)" || fail "lib/ct-firewall.sh ausente"
[ -f /opt/gamebroker/lib/ct-panel-access.sh ] && ok "lib/ct-panel-access.sh enviada (usuario gamepanel em cada CT de jogo)" || fail "lib/ct-panel-access.sh ausente"

echo "== firewall de dentro do CT do broker =="
check "papel do firewall" "FW_ROLE=broker" "$(grep '^FW_ROLE=' /etc/ct-firewall.env)"
# The API only serves the panel; output only goes to Proxmox and OPNsense (from the URL, with the port).
grep -q 'ip saddr { 10.20.1.19 } tcp dport 8443 accept' /etc/nftables.conf \
  && ok "API do broker so para o painel" || fail "regra de entrada da API ausente"
grep -q '10.20.0.2 . 8006, 10.20.0.1 . 8443' /etc/nftables.conf \
  && ok "saida para Proxmox e OPNsense tirada das URLs" || fail "destinos da API errados: $(grep 'ip daddr . tcp dport' /etc/nftables.conf)"
grep -q 'ip daddr { 10.20.1.102-10.20.1.199 } tcp dport 22 accept' /etc/nftables.conf \
  && ok "SSH so para a faixa dos jogos" || fail "faixa dos jogos errada"
grep -q '^nft -f /etc/nftables.conf' /var/log/fake-calls.log && ok "regras carregadas (nft -f)" || fail "nft -f nao foi chamado"
# And the games the broker creates: the panel and the broker itself may open SSH to them.
grep -q '^BROKER_FIREWALL_SOURCES="10.20.1.19,10.20.1.18"$' /etc/gamebroker/broker.env \
  && ok "broker.env leva quem administra os jogos" || fail "BROKER_FIREWALL_SOURCES ausente ou errado"

echo "== o broker.env gerado e ACEITO pelo carregador de configuracao real =="
python3 - > /tmp/config-load.out 2>&1 <<'PY'
import re, sys
sys.path.insert(0, '/opt/gamebroker/current')
def valor_systemd(texto):
    """How systemd reads NAME="value": the FIRST unescaped quote closes the value, and whatever is
    left after it must be only whitespace. (A greedy regex would swallow an unescaped quote and hide
    exactly the defect this test exists to catch.)"""
    assert texto[0] == '"', texto
    saida, i = [], 1
    while i < len(texto):
        c = texto[i]
        if c == '\\':
            saida.append(texto[i + 1]); i += 2; continue
        if c == '"':
            assert texto[i + 1:].strip() == '', 'lixo depois da aspa que fecha: ' + texto[i + 1:]
            return ''.join(saida)
        saida.append(c); i += 1
    raise AssertionError('aspas sem fechar')

env = {}
for linha in open('/etc/gamebroker/broker.env', encoding='utf-8'):
    m = re.fullmatch(r'([A-Z_0-9]+)=(".*)\n?', linha)
    if m:
        env[m.group(1)] = valor_systemd(m.group(2))
from gamebroker.config import load
cfg = load(env)
print('token_ok', cfg.token == open('/etc/gamebroker/token').read().strip())
print('segredo', cfg.opnsense_secret == 'a"b\\c$d`e f')
print('chave_opn', cfg.opnsense_key == 'qSNu/chave+de=teste')
print('ips', cfg.ips[0], cfg.ips[-1], cfg.allowed_ips)
print('enderecos', cfg.ctid_base, cfg.ports.start, cfg.ports.stop - 1)
print('chaves', len(cfg.proxmox.ssh_keys), cfg.proxmox.ssh_keys[0] == open('/etc/gamebroker/ssh/id_ed25519.pub').read().strip(), 'painel@gp' in cfg.ssh.panel_public_key)
print('template', cfg.proxmox.template)
print('impressoes', cfg.proxmox_fingerprint[:8], cfg.opnsense_fingerprint[:8])
print('prefixo', cfg.proxmox.prefix)
PY
cat /tmp/config-load.out | sed 's/^/          /'
grep -q '^token_ok True' /tmp/config-load.out && ok "token do env = token do arquivo" || fail "token divergente"
grep -q '^segredo True' /tmp/config-load.out && ok "segredo com aspas, barra, cifrao e crase sobrevive ao env do systemd" || fail "segredo corrompido no env"
grep -q '^chave_opn True' /tmp/config-load.out && ok "chave com / + = intacta" || fail "chave do OPNsense corrompida"
grep -q "^ips 10.20.1.102 10.20.1.199 ('10.20.1.19', '127.0.0.1')" /tmp/config-load.out && ok "faixa de IPs e origens: painel + loopback (teste de saude)" || fail "faixa/origens erradas"
grep -q '^enderecos 200 31000 31999' /tmp/config-load.out && ok "CTID = 200 + ultimo numero do IP; portas dos jogos em 31000-31999" || fail "base do CTID ou faixa de portas erradas"
grep -q '^chaves 1 True True' /tmp/config-load.out && ok "CT novo recebe so a chave do broker no root; a do painel vai para o gamepanel" || fail "chaves do CT novo erradas"
grep -q 'template local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst' /tmp/config-load.out && ok "template dos jogos = o Debian 13 mais novo do storage" || fail "template errado"
grep -q '^prefixo 24' /tmp/config-load.out && ok "mascara vem do BROKER_IP_CIDR" || fail "mascara errada"
grep -q '^impressoes aaaaaaaa bbbbbbbb' /tmp/config-load.out && ok "impressoes do Proxmox e do OPNsense normalizadas" || fail "impressoes erradas"

echo "== servico systemd =="
U=/etc/systemd/system/gamebroker.service
grep -q "^User=gamebroker" $U && ok "roda como gamebroker, nao root" || fail "unit roda como root?"
grep -q -- "--workers 1" $U && ok "UM worker (a trava de IP vive na memoria)" || fail "workers != 1"
grep -q -- "--certfile /etc/gamebroker/tls/cert.pem" $U && grep -q -- "--keyfile /etc/gamebroker/tls/key.pem" $U && ok "gunicorn com TLS" || fail "sem TLS na unit"
# The unit's entry point is checked against the CODE, not against a literal copy of the
# name here. The previous check was `grep -q "...:criar_app_de_ambiente()"`: it compared
# the script with a second copy of the same old name, so the two agreed and the suite
# stayed green while the function in the package was already called something else. It was
# gunicorn that found out, in production, with `Failed to find attribute` and exit 4 -- taking
# down a broker that was live, because the unit is rewritten before any health check.
ENTRY="$(sed -n "s/.*'gamebroker\.wsgi:\([A-Za-z_][A-Za-z_0-9]*\)()'.*/\1/p" $U)"
if [ -z "$ENTRY" ]; then
  fail "a unit nao declara um gamebroker.wsgi:<funcao>()"
elif grep -q "^def ${ENTRY}(" /opt/gamebroker/current/gamebroker/wsgi.py; then
  ok "entrada gamebroker.wsgi:${ENTRY} existe no pacote"
else
  fail "a unit chama gamebroker.wsgi:${ENTRY}(), que nao existe no pacote publicado"
fi
grep -q "^EnvironmentFile=/etc/gamebroker/broker.env" $U && ok "segredos vem do EnvironmentFile (nao da unit)" || fail "EnvironmentFile ausente"
grep -q "ProtectSystem=strict" $U && grep -q "NoNewPrivileges=true" $U && ok "endurecimento do systemd" || fail "sem endurecimento"
! grep -q "segredo-do-proxmox" $U && ok "nenhum segredo dentro da unit" || fail "SEGREDO NA UNIT"
grep -q "gamebroker.service" /var/log/fake-calls.log && grep -q "systemctl restart gamebroker.service" /var/log/fake-calls.log && ok "servico reiniciado" || fail "servico nao reiniciado"
! grep -q -E "features|--tags gamepanel" /var/log/fake-calls.log && ok "CT do broker sem features especiais" || fail "features no CT do broker"

echo "== painel configurado (BROKER_CONFIGURE_PANEL=1) =="
check "token no painel" "$T1" "$(cat /etc/gamepanel/broker.token)"
check "token no painel: modo/dono" "640 root:gamepanel" "$(stat -c '%a %U:%G' /etc/gamepanel/broker.token)"
grep -q '^GAMEPANEL_BROKER_URL=https://10.20.1.18:8443$' /etc/gamepanel/panel.env && ok "URL do broker no painel" || fail "URL ausente no painel"
grep -q "^GAMEPANEL_BROKER_CERT_SHA256=$C1\$" /etc/gamepanel/panel.env && ok "impressao do broker no painel" || fail "impressao ausente no painel"
grep -q '^GAMEPANEL_ALLOW_BROKER=0$' /etc/gamepanel/panel.env && ok "recurso continua DESLIGADO no painel" || fail "recurso ligado sem pedir"
grep -q '^GAMEPANEL_PORT=8080$' /etc/gamepanel/panel.env && ok "config anterior do painel preservada" || fail "config do painel perdida"

echo "== segredos no log do deploy =="
for s in "$T1" 'segredo-do-proxmox' 'chave+de=teste' 'a"b'; do
  grep -qF -- "$s" /tmp/deploy1.log && fail "segredo '${s:0:8}...' apareceu no log do deploy" || ok "segredo '${s:0:8}...' fora do log"
done
grep -q "REGRAS DE FIREWALL" /tmp/deploy1.log && ok "resumo traz as regras de firewall" || fail "resumo sem firewall"
grep -q "1. 10.20.1.19 -> 10.20.1.18:8443/tcp" /tmp/deploy1.log && ok "regra 1 do resumo traz o IP do painel" || fail "resumo sem o IP do painel"
grep -q "3. 10.20.1.18 -> 10.20.0.1:8443 " /tmp/deploy1.log && ok "resumo sem barra sobrando nas URLs" || fail "resumo com URL suja: $(grep '3. 10.20.1.18' /tmp/deploy1.log)"
[ ! -f "$work/broker.secrets.env" ] && ok "copia dos segredos apagada do bundle" || fail "segredos ficaram no bundle"

echo "== 2o deploy (idempotencia) =="
provision /tmp/deploy2.log
check "deploy terminou sem erro" 0 "$?"
check "token estavel"          "$T1" "$(token)"
check "certificado estavel"    "$C1" "$(cert)"
check "chave ssh estavel"      "$K1" "$(cat /etc/gamebroker/ssh/id_ed25519.pub)"
check "sem linhas duplicadas no painel" 1 "$(grep -c '^GAMEPANEL_BROKER_URL=' /etc/gamepanel/panel.env)"

echo "== rotacao =="
provision /tmp/deploy3.log BROKER_ROTATE_TOKEN=1
T3="$(token)"
[ "$T3" != "$T1" ] && ok "BROKER_ROTATE_TOKEN gera token novo" || fail "token nao rodou"
check "certificado nao mudou na rotacao do token" "$C1" "$(cert)"
check "painel recebeu o token novo" "$T3" "$(cat /etc/gamepanel/broker.token)"
provision /tmp/deploy4.log BROKER_ROTATE_CERT=1
C4="$(cert)"
[ "$C4" != "$C1" ] && ok "BROKER_ROTATE_CERT gera certificado novo" || fail "certificado nao rodou"
check "token nao mudou na rotacao do certificado" "$T3" "$(token)"
grep -q "^GAMEPANEL_BROKER_CERT_SHA256=$C4\$" /etc/gamepanel/panel.env && ok "painel recebeu a impressao nova" || fail "painel com impressao velha"

echo "== falhas claras =="
cp "$work/secrets.modelo" "$work/broker.secrets.env"; sed -i '/^PROXMOX_TOKEN=/d' "$work/broker.secrets.env"
( cd "$work" && BROKER_SKIP_HEALTHCHECK=1 bash ./provision-broker-lxc.sh ) > /tmp/deploy5.log 2>&1
[ $? -ne 0 ] && grep -q "PROXMOX_TOKEN nao definido" /tmp/deploy5.log && ok "falta de PROXMOX_TOKEN derruba o deploy nomeando a variavel" || fail "deploy nao reclamou do PROXMOX_TOKEN"
# Fingerprint not given + server unreachable from the host (what really happened with
# OPNsense): it must fail LOUDLY, saying what to do. It used to exit silently (set -e + pipefail).
cp "$work/secrets.modelo" "$work/broker.secrets.env"
sed -i "/^OPNSENSE_CERT_SHA256=/d;s#^OPNSENSE_URL=.*#OPNSENSE_URL='https://127.0.0.1:1/'#" "$work/broker.secrets.env"
( cd "$work" && BROKER_SKIP_HEALTHCHECK=1 bash ./provision-broker-lxc.sh ) > /tmp/deploy7.log 2>&1
rc=$?
[ $rc -ne 0 ] && grep -q "nao conseguiu ler o certificado de https://127.0.0.1:1/" /tmp/deploy7.log && grep -q "OPNSENSE_CERT_SHA256 no broker.secrets.env" /tmp/deploy7.log \
  && ok "servidor inalcancavel: o deploy falha DIZENDO o que fazer (nao sai calado)" || fail "deploy saiu sem explicar (rc=$rc): $(tail -3 /tmp/deploy7.log | tr '\n' ' ')"
# Any unexpected failure shows the line and the command (trap ERR), with no secret value.
cp "$work/secrets.modelo" "$work/broker.secrets.env"
# The line replaced by `false` must EXIST in the script: if its text changes, the sed
# does not match, nothing breaks and the test passes without having tested anything. Hence
# the check below, before running.
target_line='^  run_ct "chown -R root:root ${APP_DIR}/lib ${APP_DIR}/games"$'
grep -q "$target_line" "$work/provision-broker-lxc.sh"   || fail "a linha que este teste derruba de proposito sumiu do provision-broker-lxc.sh"
sed "s#${target_line}#  false#" "$work/provision-broker-lxc.sh" > "$work/quebrado.sh"
( cd "$work" && BROKER_SKIP_HEALTHCHECK=1 bash ./quebrado.sh ) > /tmp/deploy8.log 2>&1
rc=$?
if [ $rc -ne 0 ] && grep -q "falhou na linha .* executando: false" /tmp/deploy8.log && ! grep -qF "segredo-do-proxmox" /tmp/deploy8.log; then
  ok "falha inesperada mostra linha e comando (sem segredo)"
else
  fail "trap ERR nao explicou a falha (rc=$rc): $(tail -3 /tmp/deploy8.log | tr '
' ' ')"
fi
# dhcp IP: the certificate and the firewall rule depend on the IP; the script reloads
# broker.conf.env, so IT is what must change (an outside variable would be overwritten).
cp "$work/secrets.modelo" "$work/broker.secrets.env"
sed -i "s#^BROKER_IP_CIDR=.*#BROKER_IP_CIDR='dhcp'#" "$work/broker.conf.env"
( cd "$work" && BROKER_SKIP_HEALTHCHECK=1 bash ./provision-broker-lxc.sh ) > /tmp/deploy6.log 2>&1
rc=$?
[ $rc -ne 0 ] && grep -q "BROKER_IP_CIDR precisa ser um IP fixo" /tmp/deploy6.log && ok "IP dhcp e recusado, com a explicacao" || fail "IP dhcp aceito ou recusado sem explicar (rc=$rc)"

echo
echo "falhas: $failures"
exit "$failures"
