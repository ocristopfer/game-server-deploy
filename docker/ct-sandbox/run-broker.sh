#!/bin/bash
# Roda DENTRO do sandbox: executa o provision-broker-lxc.sh de verdade (com pct/systemctl/apt
# falsos) e confere o que ele deixou no "CT". Sai com o numero de falhas.
#
#   run-broker.sh <repo-montado-em-/repo>
set -u
REPO="${1:-/repo}"
falhas=0
ok()  { printf 'OK        %s\n' "$*"; }
nok() { printf 'FALHOU    %s\n' "$*"; falhas=$((falhas + 1)); }
confere() { # descricao, esperado, atual
  if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (esperado '$2', veio '$3')"; fi
}

# ----- bundle igual ao que o deploy-broker.ps1 monta -----
work=$(mktemp -d)
mkdir -p "$work/broker" "$work/lib" "$work/games"
cp "$REPO"/broker/*.py "$work/broker/"
cp "$REPO"/lib/*.sh "$work/lib/"
cp "$REPO"/games/*.env "$work/games/"
cp "$REPO/provision-broker-lxc.sh" "$work/"
cat > "$work/broker.conf.env" <<'CONF'
BROKER_CTID='208'
BROKER_HOSTNAME='gamebroker'
BROKER_IP_CIDR='192.168.2.18/24'
BROKER_GATEWAY='192.168.2.1'
STORAGE='fake'
TEMPLATE_STORAGE='fake'
BRIDGE='vmbr0'
BROKER_IP_PREFIX='192.168.2'
BROKER_ALLOW_IPS='192.168.2.19'
ADMIN_CTID='209'
CONF
# Segredo com TUDO que costuma quebrar: aspas duplas, barra, cifrao, crase, espaco.
cat > "$work/secrets.modelo" <<'SEC'
PROXMOX_URL='https://192.168.1.254:8006'
PROXMOX_TOKEN='broker@pve!broker=segredo-do-proxmox-0123456789'
PROXMOX_NODE='pve'
PROXMOX_POOL='games'
PROXMOX_STORAGE='vm-pool'
PROXMOX_TEMPLATE_STORAGE='vm-pool-data'
PROXMOX_BRIDGE='vmbr1'
PROXMOX_CERT_SHA256='9F:92:67:F5:41:F2:19:60:C6:1C:48:BA:CD:4A:3A:A7:2C:A4:02:23:09:A1:ED:74:E5:3F:20:EF:19:DE:2F:E4'
OPNSENSE_URL='https://192.168.1.1:8443/'
OPNSENSE_KEY='qSNu/chave+de=teste'
OPNSENSE_SECRET='a"b\c$d`e f'
OPNSENSE_CERT_SHA256='96:86:5B:E9:63:5F:7C:9C:EF:F7:69:A9:BB:AF:22:A1:CC:83:3C:90:B0:A5:B2:C2:B3:64:AC:16:2A:82:CE:C2'
OPNSENSE_WAN='wan'
SEC

# ----- o "CT do painel" (pct exec 209 roda aqui mesmo) -----
useradd --system gamepanel 2>/dev/null
mkdir -p /etc/gamepanel
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPainelPainelPainelPainelPainel painel@gp' > /etc/gamepanel/id_ed25519.pub
printf 'GAMEPANEL_PORT=8080\nGAMEPANEL_ALLOW_SHELL=1\n' > /etc/gamepanel/panel.env

provisionar() { # log, [VAR=valor ...]
  local log="$1"; shift
  cp "$work/secrets.modelo" "$work/broker.secrets.env"
  ( cd "$work" && env BROKER_SKIP_HEALTHCHECK=1 BROKER_CONFIGURE_PANEL=1 "$@" bash ./provision-broker-lxc.sh ) > "$log" 2>&1
}
token() { cat /etc/gamebroker/token; }
cert()  { openssl x509 -in /etc/gamebroker/tls/cert.pem -noout -fingerprint -sha256 | cut -d= -f2; }

echo "== 1o deploy =="
provisionar /tmp/deploy1.log
confere "deploy terminou sem erro" 0 "$?"
T1="$(token)"; C1="$(cert)"; K1="$(cat /etc/gamebroker/ssh/id_ed25519.pub)"

confere "broker.env: modo/dono"           "640 root:gamebroker"        "$(stat -c '%a %U:%G' /etc/gamebroker/broker.env)"
confere "token: modo/dono"                "600 root:root"              "$(stat -c '%a %U:%G' /etc/gamebroker/token)"
confere "chave ssh do broker: modo/dono"  "600 gamebroker:gamebroker"  "$(stat -c '%a %U:%G' /etc/gamebroker/ssh/id_ed25519)"
confere "chave privada TLS: modo/dono"    "600 gamebroker:gamebroker"  "$(stat -c '%a %U:%G' /etc/gamebroker/tls/key.pem)"
confere "codigo do broker e de root"      "root:root"                  "$(stat -c '%U:%G' /opt/gamebroker/broker/prod.py)"
[ "${#T1}" -ge 32 ] && ok "token com ${#T1} caracteres" || nok "token curto: ${#T1}"
openssl x509 -in /etc/gamebroker/tls/cert.pem -noout -ext subjectAltName | grep -q '192.168.2.18' \
  && ok "SAN = 192.168.2.18" || nok "SAN sem o IP do broker"

# O que vai para producao NAO leva dobles de teste nem o broker de brinquedo.
enviados="$(ls /opt/gamebroker/broker)"
if echo "$enviados" | grep -Eq '^(test_|conftest|fakes|http_falso|dev\.py)'; then nok "dobles de teste foram para o CT: $(echo "$enviados" | tr '\n' ' ')"; else ok "sem dobles de teste no CT ($(echo "$enviados" | wc -l) modulos)"; fi
[ -f /opt/gamebroker/lib/ct-install.sh ] && [ -f /opt/gamebroker/lib/ct-fases.sh ] && ok "lib/ enviada" || nok "lib/ ausente"
[ "$(ls /opt/gamebroker/games/*.env | wc -l)" -ge 8 ] && ok "games/*.env enviados" || nok "games/ incompleto"

echo "== o broker.env gerado e ACEITO pelo carregador de configuracao real =="
python3 - > /tmp/carregar.out 2>&1 <<'PY'
import re, sys
sys.path.insert(0, '/opt/gamebroker')
def valor_systemd(texto):
    """Como o systemd le NOME="valor": a PRIMEIRA aspas sem escape fecha o valor, e o que sobra
    depois dela tem de ser so espaco. (Um regex guloso engoliria uma aspa sem escape e esconderia
    exatamente o defeito que este teste existe para pegar.)"""
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
from broker.config import carregar
cfg = carregar(env)
print('token_ok', cfg.token == open('/etc/gamebroker/token').read().strip())
print('segredo', cfg.opnsense_secret == 'a"b\\c$d`e f')
print('chave_opn', cfg.opnsense_key == 'qSNu/chave+de=teste')
print('ips', cfg.ips[0], cfg.ips[-1], cfg.ips_permitidos)
print('chaves', len(cfg.proxmox.chaves_ssh), cfg.proxmox.chaves_ssh[0] == open('/etc/gamebroker/ssh/id_ed25519.pub').read().strip(), 'painel@gp' in cfg.proxmox.chaves_ssh[1])
print('template', cfg.proxmox.template)
print('impressoes', cfg.proxmox_impressao[:8], cfg.opnsense_impressao[:8])
print('prefixo', cfg.proxmox.prefixo)
PY
cat /tmp/carregar.out | sed 's/^/          /'
grep -q '^token_ok True' /tmp/carregar.out && ok "token do env = token do arquivo" || nok "token divergente"
grep -q '^segredo True' /tmp/carregar.out && ok "segredo com aspas, barra, cifrao e crase sobrevive ao env do systemd" || nok "segredo corrompido no env"
grep -q '^chave_opn True' /tmp/carregar.out && ok "chave com / + = intacta" || nok "chave do OPNsense corrompida"
grep -q '^ips 192.168.2.30 192.168.2.99 (.192.168.2.19.,)' /tmp/carregar.out && ok "faixa de IPs e lista de origens" || nok "faixa/origens erradas"
grep -q '^chaves 2 True True' /tmp/carregar.out && ok "CT novo recebe a chave do broker E a do painel" || nok "chaves do CT novo erradas"
grep -q 'template vm-pool-data:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst' /tmp/carregar.out && ok "template dos jogos = o Debian 13 mais novo do storage" || nok "template errado"
grep -q '^prefixo 24' /tmp/carregar.out && ok "mascara vem do BROKER_IP_CIDR" || nok "mascara errada"
grep -q '^impressoes 9f9267f5 96865be9' /tmp/carregar.out && ok "impressoes do Proxmox e do OPNsense normalizadas" || nok "impressoes erradas"

echo "== servico systemd =="
U=/etc/systemd/system/gamebroker.service
grep -q "^User=gamebroker" $U && ok "roda como gamebroker, nao root" || nok "unit roda como root?"
grep -q -- "--workers 1" $U && ok "UM worker (a trava de IP vive na memoria)" || nok "workers != 1"
grep -q -- "--certfile /etc/gamebroker/tls/cert.pem" $U && grep -q -- "--keyfile /etc/gamebroker/tls/key.pem" $U && ok "gunicorn com TLS" || nok "sem TLS na unit"
grep -q "broker.prod:criar_app_de_ambiente()" $U && ok "entrada broker.prod" || nok "entrada errada"
grep -q "^EnvironmentFile=/etc/gamebroker/broker.env" $U && ok "segredos vem do EnvironmentFile (nao da unit)" || nok "EnvironmentFile ausente"
grep -q "ProtectSystem=strict" $U && grep -q "NoNewPrivileges=true" $U && ok "endurecimento do systemd" || nok "sem endurecimento"
! grep -q "segredo-do-proxmox" $U && ok "nenhum segredo dentro da unit" || nok "SEGREDO NA UNIT"
grep -q "gamebroker.service" /var/log/fake-calls.log && grep -q "systemctl restart gamebroker.service" /var/log/fake-calls.log && ok "servico reiniciado" || nok "servico nao reiniciado"
! grep -q -E "features|--tags gamepanel" /var/log/fake-calls.log && ok "CT do broker sem features especiais" || nok "features no CT do broker"

echo "== painel configurado (BROKER_CONFIGURE_PANEL=1) =="
confere "token no painel" "$T1" "$(cat /etc/gamepanel/broker.token)"
confere "token no painel: modo/dono" "640 root:gamepanel" "$(stat -c '%a %U:%G' /etc/gamepanel/broker.token)"
grep -q '^GAMEPANEL_BROKER_URL=https://192.168.2.18:8443$' /etc/gamepanel/panel.env && ok "URL do broker no painel" || nok "URL ausente no painel"
grep -q "^GAMEPANEL_BROKER_CERT_SHA256=$C1\$" /etc/gamepanel/panel.env && ok "impressao do broker no painel" || nok "impressao ausente no painel"
grep -q '^GAMEPANEL_ALLOW_BROKER=0$' /etc/gamepanel/panel.env && ok "recurso continua DESLIGADO no painel" || nok "recurso ligado sem pedir"
grep -q '^GAMEPANEL_PORT=8080$' /etc/gamepanel/panel.env && ok "config anterior do painel preservada" || nok "config do painel perdida"

echo "== segredos no log do deploy =="
for s in "$T1" 'segredo-do-proxmox' 'chave+de=teste' 'a"b'; do
  grep -qF -- "$s" /tmp/deploy1.log && nok "segredo '${s:0:8}...' apareceu no log do deploy" || ok "segredo '${s:0:8}...' fora do log"
done
grep -q "REGRAS DE FIREWALL" /tmp/deploy1.log && ok "resumo traz as regras de firewall" || nok "resumo sem firewall"
[ ! -f "$work/broker.secrets.env" ] && ok "copia dos segredos apagada do bundle" || nok "segredos ficaram no bundle"

echo "== 2o deploy (idempotencia) =="
provisionar /tmp/deploy2.log
confere "deploy terminou sem erro" 0 "$?"
confere "token estavel"          "$T1" "$(token)"
confere "certificado estavel"    "$C1" "$(cert)"
confere "chave ssh estavel"      "$K1" "$(cat /etc/gamebroker/ssh/id_ed25519.pub)"
confere "sem linhas duplicadas no painel" 1 "$(grep -c '^GAMEPANEL_BROKER_URL=' /etc/gamepanel/panel.env)"

echo "== rotacao =="
provisionar /tmp/deploy3.log BROKER_ROTATE_TOKEN=1
T3="$(token)"
[ "$T3" != "$T1" ] && ok "BROKER_ROTATE_TOKEN gera token novo" || nok "token nao rodou"
confere "certificado nao mudou na rotacao do token" "$C1" "$(cert)"
confere "painel recebeu o token novo" "$T3" "$(cat /etc/gamepanel/broker.token)"
provisionar /tmp/deploy4.log BROKER_ROTATE_CERT=1
C4="$(cert)"
[ "$C4" != "$C1" ] && ok "BROKER_ROTATE_CERT gera certificado novo" || nok "certificado nao rodou"
confere "token nao mudou na rotacao do certificado" "$T3" "$(token)"
grep -q "^GAMEPANEL_BROKER_CERT_SHA256=$C4\$" /etc/gamepanel/panel.env && ok "painel recebeu a impressao nova" || nok "painel com impressao velha"

echo "== falhas claras =="
cp "$work/secrets.modelo" "$work/broker.secrets.env"; sed -i '/^PROXMOX_TOKEN=/d' "$work/broker.secrets.env"
( cd "$work" && BROKER_SKIP_HEALTHCHECK=1 bash ./provision-broker-lxc.sh ) > /tmp/deploy5.log 2>&1
[ $? -ne 0 ] && grep -q "PROXMOX_TOKEN nao definido" /tmp/deploy5.log && ok "falta de PROXMOX_TOKEN derruba o deploy nomeando a variavel" || nok "deploy nao reclamou do PROXMOX_TOKEN"
( cd "$work" && BROKER_IP_CIDR='dhcp' BROKER_SKIP_HEALTHCHECK=1 bash -c 'source ./broker.conf.env; BROKER_IP_CIDR=dhcp; export BROKER_IP_CIDR; source ./broker.secrets.env; exec bash ./provision-broker-lxc.sh' ) >/tmp/deploy6.log 2>&1
[ $? -ne 0 ] && ok "IP dhcp e recusado" || nok "IP dhcp aceito"

echo
echo "falhas: $falhas"
exit "$falhas"
