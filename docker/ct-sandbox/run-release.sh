#!/bin/bash
# Roda DENTRO do sandbox: prova o lib/install-release.sh com systemctl falso e um tarball
# de verdade, gerado pelo tools/build-release.py. Sai com o numero de falhas.
#
#   run-release.sh <repo-montado-em-/repo>
#
# O que esta em jogo: este script troca o codigo de producao. Um erro ali nao da erro de
# sintaxe nem falha em teste nenhum — ele publica a versao errada, ou publica e nao
# consegue voltar. Como nao existe teste de shell no repositorio, a prova e esta.
set -u
REPO="${1:-/repo}"
APP_DIR=/opt/gamepanel
INSTALLER="$REPO/lib/install-release.sh"
failures=0

ok()   { printf 'OK        %s\n' "$*"; }
fail() { printf 'FALHOU    %s\n' "$*"; failures=$((failures + 1)); }
check() { # descricao, esperado, atual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1 (esperado '$2', veio '$3')"; fi
}
has()     { if [ -e "$2" ]; then ok "$1"; else fail "$1 (nao existe: $2)"; fi; }
has_not() { if [ -e "$2" ]; then fail "$1 (ainda existe: $2)"; else ok "$1"; fi; }

install_release() { # tarball, [comando de saude]
  local tarball="$1" health="${2:-}"
  local checksum
  checksum="$(sha256sum "$tarball" | cut -d' ' -f1)"
  bash "$INSTALLER" gamepanel "$tarball" "$checksum" "$APP_DIR" gamepanel.service "$health"
}

version_of() { # tarball -> a VERSION do carimbo
  tar -xzOf "$1" gamepanel/_build.py | sed -n "s/^VERSION = '\\(.*\\)'\$/\\1/p"
}

# ----- o artefato, feito pelo empacotador de verdade -----
work=$(mktemp -d)
python3 "$REPO/tools/build-release.py" gamepanel --out "$work/dist" >/dev/null 2>&1 \
  || { fail "build-release.py nao gerou o pacote"; exit 1; }
tarball="$(ls "$work"/dist/gamepanel-*.tar.gz)"
version="$(version_of "$tarball")"
ok "empacotou ${version}"

# Determinismo: o mesmo codigo tem de dar o mesmo arquivo, senao o sha256 so responde
# "chegou inteiro?" em vez de "e este codigo mesmo?".
first_sum="$(sha256sum "$tarball" | cut -d' ' -f1)"
python3 "$REPO/tools/build-release.py" gamepanel --out "$work/dist2" >/dev/null 2>&1
second_sum="$(sha256sum "$work"/dist2/gamepanel-*.tar.gz | cut -d' ' -f1)"
check "empacotar duas vezes da o mesmo sha256" "$first_sum" "$second_sum"

# ----- o CT, com o layout ANTIGO no lugar -----
mkdir -p "$APP_DIR/gamepanel/templates"
echo "# versao anterior a este mecanismo" > "$APP_DIR/gamepanel/app.py"

# ----- 1. sha errado nao publica nada -----
out="$(bash "$INSTALLER" gamepanel "$tarball" \
       "0000000000000000000000000000000000000000000000000000000000000000" \
       "$APP_DIR" gamepanel.service 2>&1)"
check "sha errado sai com erro" "1" "$?"
case "$out" in *"sha256 nao confere"*) ok "sha errado diz o motivo";;
               *) fail "sha errado nao explicou (saida: $out)";; esac
has_not "sha errado nao deixou release" "$APP_DIR/releases"

# ----- 2. instalacao normal -----
install_release "$tarball" >/dev/null 2>&1
check "instalacao normal termina bem" "0" "$?"
has "a pasta da versao existe"   "$APP_DIR/releases/$version/gamepanel/app.py"
has "templates vieram junto"     "$APP_DIR/releases/$version/gamepanel/templates/base.html"
has "blueprints vieram junto"    "$APP_DIR/releases/$version/gamepanel/blueprints/servers.py"
has "o carimbo esta no lugar"    "$APP_DIR/releases/$version/gamepanel/_build.py"
check "current aponta para a versao" "$APP_DIR/releases/$version" "$(readlink -f $APP_DIR/current)"
has_not "o layout antigo foi embora"  "$APP_DIR/gamepanel"
has_not "nao sobrou pasta temporaria" "$(ls -d $APP_DIR/.staging.* 2>/dev/null | head -1)"
if grep -q "systemctl restart gamepanel.service" /var/log/fake-calls.log 2>/dev/null
  then ok "reiniciou o servico"; else fail "nao reiniciou o servico"; fi

# ----- 3. versao nova: a anterior fica, o symlink anda -----
# Copia do repo com outro VERSION, para simular o deploy seguinte sem tocar no original.
declared_version="$(cat "$REPO/VERSION")"
fake_repo=$(mktemp -d); cp -r "$REPO"/. "$fake_repo"/ 2>/dev/null
echo "9.9.9" > "$fake_repo/VERSION"
python3 "$fake_repo/tools/build-release.py" gamepanel --out "$work/dist3" >/dev/null 2>&1
next_tarball="$(ls "$work"/dist3/gamepanel-*.tar.gz)"
next_version="$(version_of "$next_tarball")"
install_release "$next_tarball" >/dev/null 2>&1
check "a versao seguinte instala" "0" "$?"
check "current andou para a nova" "$APP_DIR/releases/$next_version" "$(readlink -f $APP_DIR/current)"
has "a anterior continua no disco" "$APP_DIR/releases/$version/gamepanel/app.py"
case "$declared_version" in 9.9.9) fail "o VERSION do repo foi alterado";;
                            *) ok "o repo nao foi tocado";; esac

# ----- 4. servico que nao sobe volta para a anterior -----
# systemctl falso que responde "inativo": e o caso de um release que quebra no start.
cat > /usr/local/sbin/systemctl <<'FALSO'
#!/bin/bash
echo "systemctl $*" >> /var/log/fake-calls.log
case "$1" in is-active) exit 3;; esac
FALSO
chmod +x /usr/local/sbin/systemctl
before="$(readlink -f $APP_DIR/current)"
echo "8.8.8" > "$fake_repo/VERSION"
python3 "$fake_repo/tools/build-release.py" gamepanel --out "$work/dist4" >/dev/null 2>&1
broken_tarball="$(ls "$work"/dist4/gamepanel-8.8.8*.tar.gz 2>/dev/null | head -1)"
out="$(install_release "$broken_tarball" 2>&1)"
check "release que nao sobe sai com erro" "1" "$?"
check "current voltou para a anterior" "$before" "$(readlink -f $APP_DIR/current)"
case "$out" in *"voltando para"*) ok "o rollback aparece na saida";;
               *) fail "o rollback nao foi anunciado (saida: $out)";; esac

echo
if [ "$failures" -eq 0 ]; then echo "Tudo certo."; else echo "$failures verificacao(oes) falharam."; fi
exit "$failures"
