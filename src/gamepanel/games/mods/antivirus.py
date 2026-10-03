"""Antivirus (ClamAV) para mod, rodando DENTRO do CT do jogo, antes de o mod chegar ao jogo.

Os scripts aqui sao texto: o painel os manda por SSH, como o resto do que roda no CT. A
regra de seguranca mora num lugar so - o upload pela tela e os instaladores remotos
(Thunderstore, Shroudtopia) chamam o MESMO `SCAN_SCRIPT`; os instaladores o recebem por
argumento, ja que la dentro o pacote do painel nao existe.

Decisoes, cada uma com o motivo:
- **O ClamAV so entra no CT no primeiro mod** (`apt-get`, na hora): servidor sem mod nao paga
  o disco (~300 MB) nem o daemon de atualizacao, e servidor que ja roda ganha a verificacao
  sem redeploy. O CT de jogo vai a internet; o painel, nao.
- **Falha FECHADA.** Sem ClamAV, sem assinatura recente ou com erro de leitura, o mod NAO
  entra: um "nao consegui verificar" que deixa passar e o mesmo que nao ter verificacao,
  so que com cara de ter.
- **Arquivo grande demais ou zip com senha conta como achado** (`--alert-exceeds-max`,
  `--alert-encrypted`): sem isso o ClamAV PULA o que passa do limite, calado, e um zip com
  senha seria o jeito obvio de passar qualquer coisa.
- **O ClamAV acha o que ja e conhecido.** Mod malicioso feito sob medida passa. Isto e uma
  camada a mais, nao a barreira: o jogo continua rodando como 'steam' e o firewall do CT
  continua isolando a rede interna.
- **A varredura carrega o banco de assinaturas na memoria (~1 GB por uns segundos)**, ao lado
  do servidor que esta rodando. Num CT no limite, isso pode derrubar o jogo por falta de
  memoria: e o mesmo aviso de memoria da tela vale aqui.
"""
from __future__ import annotations

# Tudo o que o antivirus verifica ou apaga mora debaixo deste prefixo. O script RECUSA outro
# caminho: ele apaga a pasta quando acha algo, e um caminho errado vindo de um bug nao pode
# virar `rm -rf` na pasta do jogo. Em /var/tmp porque o /tmp do Debian 13 e tmpfs (memoria);
# a pasta de cada envio leva um token aleatorio de 128 bits e nasce 0700.
STAGING_PREFIX = "/var/tmp/gamepanel-"  # noqa: S108
# A pasta de espera do upload: so vai para a pasta de mods depois de verificada.
INCOMING_PREFIX = STAGING_PREFIX + "incoming-"
# Assinatura com menos de um dia nao pede atualizacao; ate sete, uma atualizacao que falha
# (espelho fora do ar, limite de pedidos do CDN do ClamAV) ainda deixa verificar. Mais velha
# que isso, o mod e recusado: assinatura de semanas atras nao conhece o que circula hoje.
FRESH_DAYS = 1
MAX_AGE_DAYS = 7

SCAN_SCRIPT = r"""
set -u
target=${1:?}
case "$target" in
  /var/tmp/gamepanel-*) ;;
  *) echo "ANTIVIRUS: caminho fora da area de verificacao: $target" >&2; exit 2 ;;
esac
case "$target" in *..*) echo "ANTIVIRUS: caminho invalido: $target" >&2; exit 2 ;; esac
# Achou algo ou nao conseguiu verificar: o que esta na espera nao serve para nada, e sai.
refuse() { rm -rf -- "$target"; echo "ANTIVIRUS: $1" >&2; exit "$2"; }

if ! command -v clamscan >/dev/null 2>&1; then
  echo "antivirus: instalando o ClamAV (so na primeira vez neste servidor)..."
  export DEBIAN_FRONTEND=noninteractive
  { apt-get update -qq && apt-get install -y -qq --no-install-recommends clamav clamav-freshclam; } >/dev/null 2>&1 \
    || refuse "nao consegui instalar o ClamAV (apt); o mod NAO foi instalado" 2
fi

# Trocavel so para o teste do script; no CT e sempre o padrao do pacote do Debian.
db=${CLAMAV_DB_DIR:-/var/lib/clamav}
newest() { find "$db" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) -mtime "-$1" 2>/dev/null | head -n 1; }
if [ -z "$(newest __FRESH_DAYS__)" ]; then
  echo "antivirus: atualizando as assinaturas..."
  # O daemon do freshclam segura a trava do log: rodar o freshclam com ele de pe falha.
  systemctl stop clamav-freshclam >/dev/null 2>&1 || true
  freshclam --quiet >/dev/null 2>&1 || echo "antivirus: a atualizacao falhou; usando as assinaturas que ja havia"
  systemctl start clamav-freshclam >/dev/null 2>&1 || true
  [ -n "$(newest __MAX_AGE_DAYS__)" ] \
    || refuse "sem assinaturas dos ultimos __MAX_AGE_DAYS__ dias; o mod NAO foi instalado" 2
fi

echo "antivirus: verificando..."
out=$(clamscan --recursive --infected --no-summary --stdout \
        --alert-exceeds-max=yes --alert-encrypted=yes \
        --max-filesize=512M --max-scansize=1024M -- "$target" 2>&1)
rc=$?
case $rc in
  0) echo "antivirus: nada encontrado" ;;
  1) printf '%s\n' "$out" >&2; refuse "o ClamAV encontrou algo; o mod NAO foi instalado" 1 ;;
  *) printf '%s\n' "$out" >&2; refuse "a verificacao nao rodou (codigo $rc); o mod NAO foi instalado" 2 ;;
esac
""".replace("__FRESH_DAYS__", str(FRESH_DAYS)).replace("__MAX_AGE_DAYS__", str(MAX_AGE_DAYS))

# Cria a pasta de espera do upload (so root le) e varre as que sobraram de um envio que nao
# chegou a virar job - o navegador fechado no meio, por exemplo.
INCOMING_SCRIPT = r"""
set -e
d=${1:?}
case "$d" in /var/tmp/gamepanel-incoming-*) ;; *) echo "pasta de espera invalida: $d" >&2; exit 2 ;; esac
find /var/tmp -maxdepth 1 -name 'gamepanel-incoming-*' -mmin +1440 -exec rm -rf -- {} + 2>/dev/null || true
mkdir -p -m 0700 -- "$d"
"""

# Leva o que ja foi verificado da espera para a pasta de mods, com as mesmas regras do envio
# comum (UPLOAD_SCRIPT): arquivo que ja existe ganha copia .bak e mantem dono e permissao; o
# novo herda o dono da pasta, porque o jogo roda como 'steam' e precisa ler.
PLACE_SCRIPT = r"""
set -e
src=${1:?}
dest=${2:?}
case "$src" in /var/tmp/gamepanel-incoming-*) ;; *) echo "pasta de espera invalida: $src" >&2; exit 2 ;; esac
trap 'rm -rf -- "$src"' EXIT
mkdir -p -- "$dest"
chown --reference="$(dirname -- "$dest")" -- "$dest" 2>/dev/null || true
for f in "$src"/*; do
  [ -f "$f" ] || continue
  name=$(basename -- "$f")
  t="$dest/$name"
  if [ -e "$t" ]; then
    [ -f "$t" ] || { echo "o destino nao e um arquivo comum: $t" >&2; exit 4; }
    cp -a -- "$t" "$t.$(date +%Y%m%d-%H%M%S).bak"
    cat "$f" > "$t"
  else
    cat "$f" > "$t"
    chmod 0644 -- "$t"
    chown --reference="$dest" -- "$t" 2>/dev/null || true
  fi
  echo "instalado: $t ($(stat -Lc %s -- "$t") bytes)"
done
"""


def incoming_dir(token: str) -> str:
    """A pasta de espera de UM envio. O token vem do painel (hex), nunca do formulario."""
    if not token or not all(c in "0123456789abcdef" for c in token):
        raise ValueError("token de envio invalido")
    return INCOMING_PREFIX + token
