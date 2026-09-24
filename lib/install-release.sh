#!/usr/bin/env bash
# Instala um release DENTRO do container, a partir de um tar.gz e do sha256 dele.
#
#   bash install-release.sh <pacote> <tarball> <sha256> <app_dir> <servico> [comando_de_saude]
#
# O mesmo arquivo serve aos dois caminhos de publicacao: o envio direto por SSH
# (deploy-*.ps1) e o provisionamento pelo host Proxmox (provision-*-lxc.sh, via pct).
# Ter UMA implementacao e o ponto: quando eram dois, cada um tinha a sua lista escrita a
# mao de quais pastas apagar antes de copiar, e as duas ficaram para tras a cada pasta
# nova do pacote — deixando modulo renomeado vivo no container, importavel, sem ninguem
# ver.
#
# O desenho e release por PASTA, com um symlink apontando para a de hoje:
#
#   /opt/gamepanel/releases/0.1.0+abc1234/gamepanel/...
#   /opt/gamepanel/current -> releases/0.1.0+abc1234
#
# Nada e copiado por cima de nada. Arquivo que sumiu do pacote nao tem como sobreviver, e
# voltar para a versao anterior e mover o symlink de volta — nao repetir um deploy.
set -euo pipefail

KEEP_RELEASES=5
HEALTH_TRIES=10
HEALTH_SLEEP=2

# Falha dentro de $(...) encerra o script antes do `die` que a explicaria: sem este trap
# o deploy para sem dizer uma palavra, e foi assim que o primeiro deploy real terminou.
trap 'echo "ERRO na linha ${LINENO}: ${BASH_COMMAND}" >&2' ERR

die() { echo "ERRO: $*" >&2; exit 1; }
msg() { echo "==> $*"; }

[[ $# -ge 5 ]] || die "uso: install-release.sh <pacote> <tarball> <sha256> <app_dir> <servico> [saude]"

PACKAGE="$1"
TARBALL="$2"
EXPECTED_SHA="$3"
APP_DIR="$4"
SERVICE="$5"
HEALTH_CMD="${6:-}"

RELEASES_DIR="${APP_DIR}/releases"
CURRENT_LINK="${APP_DIR}/current"

[[ -f "$TARBALL" ]] || die "tarball nao encontrado: $TARBALL"

# --- 1. o arquivo e o que o deploy mandou? ------------------------------------
# O hash e determinista (ver tools/build-release.py), entao ele responde "o CT esta com
# ESTE codigo?", e nao so "o arquivo chegou inteiro?".
actual_sha="$(sha256sum "$TARBALL" | cut -d' ' -f1 || true)"
[[ -n "$actual_sha" ]] || die "nao consegui calcular o sha256 de $TARBALL"
[[ "$actual_sha" == "$EXPECTED_SHA" ]] \
  || die "sha256 nao confere: esperado $EXPECTED_SHA, recebido $actual_sha"

# --- 2. abre num lugar temporario e descobre a versao -------------------------
# A versao sai do CARIMBO dentro do pacote, nao do nome do arquivo: nome se renomeia,
# carimbo e o que o processo vai se apresentar como em /health.
staging="$(mktemp -d "${APP_DIR}/.staging.XXXXXX" || true)"
[[ -n "$staging" ]] || die "nao consegui criar pasta temporaria em $APP_DIR"
cleanup() { rm -rf "$staging"; }
trap 'cleanup' EXIT

tar -xzf "$TARBALL" -C "$staging" || die "tar falhou ao extrair $TARBALL"
stamp="${staging}/${PACKAGE}/_build.py"
[[ -f "$stamp" ]] || die "o pacote nao tem ${PACKAGE}/_build.py (foi gerado por tools/build-release.py?)"
version="$(sed -n "s/^VERSION = '\\(.*\\)'$/\\1/p" "$stamp" || true)"
[[ -n "$version" ]] || die "nao consegui ler a VERSION de ${PACKAGE}/_build.py"

target="${RELEASES_DIR}/${version}"
msg "release ${version}"

# --- 3. instala a pasta da versao ---------------------------------------------
install -d -m 0755 "$RELEASES_DIR"
# Reinstalar a MESMA versao e caso normal (redeploy apos um ajuste de configuracao): a
# pasta velha sai inteira para nao virar mistura das duas extracoes.
rm -rf "$target"
install -d -m 0755 "$target"
mv "${staging}/${PACKAGE}" "${target}/${PACKAGE}"
chown -R root:root "$target"
chmod -R a+rX "$target"

# Falhar aqui e melhor do que o servico cair no start com ModuleNotFoundError, ou o
# navegador receber um TemplateNotFound.
( cd "$target" && python3 -c "import ${PACKAGE}, ${PACKAGE}.version" ) \
  || die "o pacote nao importa a partir de ${target}"

# --- 4. vira o symlink (e guarda para onde ele apontava) ----------------------
previous=""
if [[ -L "$CURRENT_LINK" ]]; then
  previous="$(readlink -f "$CURRENT_LINK" || true)"
fi

# ln -sfn num symlink que ja existe cria o link DENTRO da pasta apontada. O caminho
# seguro e criar ao lado e renomear: o `mv -T` e atomico, entao nunca existe um instante
# em que `current` nao aponta para lugar nenhum.
ln -sfn "$target" "${CURRENT_LINK}.new"
mv -T "${CURRENT_LINK}.new" "$CURRENT_LINK"

# --- 5. reinicia e confere; se nao subir, volta para a anterior ---------------
restart_and_check() {
  # No primeiro provisionamento a unit ainda nao existe: ela e escrita depois de o codigo
  # estar no lugar. Nao ha o que reiniciar nem o que sondar, e insistir aqui faria o
  # provisionamento inteiro falhar antes de chegar na parte que cria o servico.
  if ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
    msg "o servico ${SERVICE} ainda nao existe — quem sobe e o provisionamento"
    return 0
  fi
  systemctl restart "$SERVICE" || return 1
  local try
  for try in $(seq 1 "$HEALTH_TRIES"); do
    sleep "$HEALTH_SLEEP"
    systemctl is-active --quiet "$SERVICE" || return 1
    # `[[ ... ]] && return 0` solto derrubaria o script pelo `set -e` quando a condicao
    # fosse falsa: um `&&` que falha e falha do comando inteiro.
    if [[ -z "$HEALTH_CMD" ]] || eval "$HEALTH_CMD" >/dev/null 2>&1; then
      return 0
    fi
    echo "   saude ainda nao respondeu (${try}/${HEALTH_TRIES})"
  done
  return 1
}

if restart_and_check; then
  msg "no ar: ${version}"
else
  if [[ -n "$previous" && -d "$previous" && "$previous" != "$target" ]]; then
    msg "NAO subiu — voltando para $(basename "$previous")"
    ln -sfn "$previous" "${CURRENT_LINK}.new"
    mv -T "${CURRENT_LINK}.new" "$CURRENT_LINK"
    systemctl restart "$SERVICE" || true
  fi
  die "o servico ${SERVICE} nao ficou de pe com o release ${version}"
fi

# --- 6. poda ------------------------------------------------------------------
# Guardar as ultimas e o que faz "voltar uma versao" ser possivel sem reempacotar. A
# atual e a anterior nunca entram na poda, mesmo que a data as coloque no fim da fila.
keep_current="$(readlink -f "$CURRENT_LINK" || true)"
while IFS= read -r old; do
  [[ "$old" == "$keep_current" || "$old" == "$previous" ]] && continue
  rm -rf "$old"
done < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
         | sort -rn | tail -n "+$((KEEP_RELEASES + 1))" | cut -d' ' -f2-)

# Layout antigo: o que existia em ${APP_DIR} antes deste mecanismo. Depois que o symlink
# pegou, ele so confunde -- e o risco nao e cosmetico: e codigo com os NOMES VELHOS ainda
# vivo e importavel no container, sem nada que o atualize. Uma lista do que remover nao
# serve, porque cada versao anterior deixou um layout diferente (o painel deixou 27 .py
# soltos mais templates/ e static/; o broker deixou a pasta broker/, o nome do pacote antes
# do rename), e uma lista escrita a mao ja nasceria incompleta -- foi assim que a lista de
# subpastas a apagar ficou para tras a cada pasta nova, que e a razao de existir o layout
# por versao. Entao a regra e invertida: diz-se o que FICA.
#
# Em ${APP_DIR} so moram o mecanismo de release e os diretorios que o provisionamento
# empurra a parte (lib/ e games/ do broker, que nao sao o pacote Python). Dado e config
# nunca estiveram aqui: vivem em /var/lib e /etc. Por isso remover o resto e seguro.
KEPT_IN_APP_DIR=(releases current lib games)

prune_old_layout() {
  local entry base keep
  for entry in "${APP_DIR}"/* "${APP_DIR}"/.[!.]*; do
    [[ -e "$entry" || -L "$entry" ]] || continue
    base="$(basename "$entry")"
    keep=0
    for name in "${KEPT_IN_APP_DIR[@]}"; do
      [[ "$base" == "$name" ]] && keep=1 && break
    done
    [[ "$keep" -eq 1 ]] && continue
    msg "removendo o layout antigo: ${base}"
    # ${APP_DIR:?} para um APP_DIR vazio virar erro em vez de "rm -rf /nome".
    rm -rf "${APP_DIR:?}/${base}"
  done
}

prune_old_layout
