#!/bin/bash
# Roda DENTRO do sandbox: prova o lib/install-release.sh com systemctl falso e um tarball
# de verdade, gerado pelo tools/build-release.py. Sai com o numero de falhas.
#
#   run-release.sh <repo-montado-em-/repo>
#
# O que esta em jogo: este script troca o codigo de producao. Um erro aqui nao da erro de
# sintaxe nem falha em teste nenhum — ele publica a versao errada, ou publica e nao
# consegue voltar. Como nao existe teste de shell no repositorio, a prova e esta.
set -u
REPO="${1:-/repo}"
APP_DIR=/opt/gamepanel
INSTALL="$REPO/lib/install-release.sh"
falhas=0

ok()  { printf 'OK        %s\n' "$*"; }
nok() { printf 'FALHOU    %s\n' "$*"; falhas=$((falhas + 1)); }
confere() { # descricao, esperado, atual
  if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (esperado '$2', veio '$3')"; fi
}
existe()     { if [ -e "$2" ]; then ok "$1"; else nok "$1 (nao existe: $2)"; fi; }
nao_existe() { if [ -e "$2" ]; then nok "$1 (ainda existe: $2)"; else ok "$1"; fi; }

instala() { # tarball, [comando_de_saude]
  local tar="$1" saude="${2:-}"
  local soma
  soma="$(sha256sum "$tar" | cut -d' ' -f1)"
  bash "$INSTALL" gamepanel "$tar" "$soma" "$APP_DIR" gamepanel.service "$saude"
}

versao_de() { # tarball -> a VERSION do carimbo
  tar -xzOf "$1" gamepanel/_build.py | sed -n "s/^VERSION = '\\(.*\\)'\$/\\1/p"
}

# ----- o artefato, feito pelo empacotador de verdade -----
work=$(mktemp -d)
python3 "$REPO/tools/build-release.py" gamepanel --out "$work/dist" >/dev/null 2>&1 \
  || { nok "build-release.py nao gerou o pacote"; exit 1; }
TAR="$(ls "$work"/dist/gamepanel-*.tar.gz)"
VERSAO="$(versao_de "$TAR")"
ok "empacotou ${VERSAO}"

# Determinismo: o mesmo codigo tem de dar o mesmo arquivo, senao o sha256 so responde
# "chegou inteiro?" em vez de "e este codigo mesmo?".
soma1="$(sha256sum "$TAR" | cut -d' ' -f1)"
python3 "$REPO/tools/build-release.py" gamepanel --out "$work/dist2" >/dev/null 2>&1
soma2="$(sha256sum "$work"/dist2/gamepanel-*.tar.gz | cut -d' ' -f1)"
confere "empacotar duas vezes da o mesmo sha256" "$soma1" "$soma2"

# ----- o CT, com o layout ANTIGO no lugar -----
mkdir -p "$APP_DIR/gamepanel/templates"
echo "# versao anterior a este mecanismo" > "$APP_DIR/gamepanel/app.py"

# ----- 1. sha errado nao instala nada -----
saida="$(bash "$INSTALL" gamepanel "$TAR" "0000000000000000000000000000000000000000000000000000000000000000" \
         "$APP_DIR" gamepanel.service 2>&1)"
confere "sha errado sai com erro" "1" "$?"
case "$saida" in *"sha256 nao confere"*) ok "sha errado diz o motivo";;
                 *) nok "sha errado nao explicou (saida: $saida)";; esac
nao_existe "sha errado nao deixou release" "$APP_DIR/releases"

# ----- 2. instalacao normal -----
instala "$TAR" >/dev/null 2>&1
confere "instalacao normal termina bem" "0" "$?"
existe "a pasta da versao existe"       "$APP_DIR/releases/$VERSAO/gamepanel/app.py"
existe "templates vieram junto"          "$APP_DIR/releases/$VERSAO/gamepanel/templates/base.html"
existe "blueprints vieram junto"         "$APP_DIR/releases/$VERSAO/gamepanel/blueprints/servers.py"
existe "o carimbo esta no lugar"         "$APP_DIR/releases/$VERSAO/gamepanel/_build.py"
confere "current aponta para a versao" "$APP_DIR/releases/$VERSAO" "$(readlink -f $APP_DIR/current)"
nao_existe "o layout antigo foi embora" "$APP_DIR/gamepanel"
nao_existe "nao sobrou pasta temporaria" "$(ls -d $APP_DIR/.staging.* 2>/dev/null | head -1)"
if grep -q "systemctl restart gamepanel.service" /var/log/fake-calls.log 2>/dev/null
  then ok "reiniciou o servico"; else nok "nao reiniciou o servico"; fi

# ----- 3. versao nova: a anterior fica, o symlink anda -----
# Reempacota com outro VERSION para simular o deploy seguinte.
antigo_version="$(cat "$REPO/VERSION")"
novo=$(mktemp -d); cp -r "$REPO"/. "$novo"/ 2>/dev/null
echo "9.9.9" > "$novo/VERSION"
python3 "$novo/tools/build-release.py" gamepanel --out "$work/dist3" >/dev/null 2>&1
TAR2="$(ls "$work"/dist3/gamepanel-*.tar.gz)"
VERSAO2="$(versao_de "$TAR2")"
instala "$TAR2" >/dev/null 2>&1
confere "a versao seguinte instala"      "0" "$?"
confere "current andou para a nova" "$APP_DIR/releases/$VERSAO2" "$(readlink -f $APP_DIR/current)"
existe  "a anterior continua no disco"   "$APP_DIR/releases/$VERSAO/gamepanel/app.py"
case "$antigo_version" in 9.9.9) nok "o VERSION do repo foi alterado";; *) ok "o repo nao foi tocado";; esac

# ----- 4. servico que nao sobe volta para a anterior -----
# systemctl falso que responde "inativo": e o caso de um release que quebra no start.
cat > /usr/local/sbin/systemctl <<'FALSO'
#!/bin/bash
echo "systemctl $*" >> /var/log/fake-calls.log
case "$1" in is-active) exit 3;; esac
FALSO
chmod +x /usr/local/sbin/systemctl
antes="$(readlink -f $APP_DIR/current)"
python3 "$novo/tools/build-release.py" gamepanel --out "$work/dist4" >/dev/null 2>&1
echo "8.8.8" > "$novo/VERSION"
python3 "$novo/tools/build-release.py" gamepanel --out "$work/dist4" >/dev/null 2>&1
TAR3="$(ls "$work"/dist4/gamepanel-8.8.8*.tar.gz 2>/dev/null | head -1)"
saida="$(instala "$TAR3" 2>&1)"
confere "release que nao sobe sai com erro" "1" "$?"
confere "current voltou para a anterior" "$antes" "$(readlink -f $APP_DIR/current)"
case "$saida" in *"voltando para"*) ok "o rollback aparece na saida";;
                 *) nok "o rollback nao foi anunciado (saida: $saida)";; esac

echo
if [ "$falhas" -eq 0 ]; then echo "Tudo certo."; else echo "$falhas verificacao(oes) falharam."; fi
exit "$falhas"
