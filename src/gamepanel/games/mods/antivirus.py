"""Antivirus (ClamAV) for mods, running INSIDE the game CT, before the mod reaches the game.

The scripts here are text: the panel sends them over SSH, like everything else that runs in
the CT. The security rule lives in a single place - the upload through the screen and the
remote installers (Thunderstore, Shroudtopia) call the SAME `SCAN_SCRIPT`; the installers get
it as an argument, since the panel package does not exist in there.

Decisions, each with its reason:
- **ClamAV only enters the CT with the first mod** (`apt-get`, on the spot): a server without
  mods pays neither the disk (~300 MB) nor the update daemon, and a server that is already
  running gains the check without a redeploy. The game CT goes to the internet; the panel does not.
- **Fail CLOSED.** Without ClamAV, without recent signatures or with a read error, the mod does
  NOT get in: an "I could not check" that lets it through is the same as having no check,
  except that it looks like one.
- **A file that is too large or a password-protected zip counts as a finding**
  (`--alert-exceeds-max`, `--alert-encrypted`): without that ClamAV SKIPS whatever is over the
  limit, silently, and a password-protected zip would be the obvious way to sneak anything in.
- **ClamAV finds what is already known.** A tailor-made malicious mod gets through. This is one
  more layer, not the barrier: the game still runs as 'steam' and the CT firewall still
  isolates the internal network.
- **The scan loads the signature database into memory (~1 GB for a few seconds)**, next to
  the running server. In a CT at its limit, that can bring the game down for lack of memory:
  the same memory warning from the screen applies here.
"""
from __future__ import annotations

from collections.abc import Sequence

from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import ServerLike

# Everything the antivirus checks or deletes lives under this prefix. The script REFUSES any
# other path: it deletes the folder when it finds something, and a wrong path coming from a bug
# must not turn into `rm -rf` on the game folder. In /var/tmp because Debian 13's /tmp is tmpfs
# (memory); each upload's folder carries a random 128-bit token and is created 0700.
STAGING_PREFIX = "/var/tmp/gamepanel-"  # noqa: S108
# The upload holding folder: it only goes to the mods folder after being checked.
INCOMING_PREFIX = STAGING_PREFIX + "incoming-"
# Signatures less than a day old need no update; up to seven, a failed update (mirror down,
# ClamAV CDN rate limit) still allows checking. Older than that, the mod is refused: signatures
# from weeks ago do not know what circulates today.
FRESH_DAYS = 1
MAX_AGE_DAYS = 7

# Install ClamAV if missing and ensure recent signatures. COMMON part of the two scripts
# below: the includer defines `refuse MESSAGE CODE`, which states the consequence and exits.
_ENSURE = r"""
if ! command -v clamscan >/dev/null 2>&1; then
  echo "antivirus: instalando o ClamAV (so na primeira vez neste servidor)..."
  export DEBIAN_FRONTEND=noninteractive
  { apt-get update -qq && apt-get install -y -qq --no-install-recommends clamav clamav-freshclam; } >/dev/null 2>&1 \
    || refuse "nao consegui instalar o ClamAV (apt)" 2
fi

# Overridable only for the script test; in the CT it is always the Debian package default.
db=${CLAMAV_DB_DIR:-/var/lib/clamav}
newest() { find "$db" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) -mtime "-$1" 2>/dev/null | head -n 1; }
if [ -z "$(newest __FRESH_DAYS__)" ]; then
  echo "antivirus: atualizando as assinaturas..."
  # The freshclam daemon holds the log lock: running freshclam while it is up fails.
  systemctl stop clamav-freshclam >/dev/null 2>&1 || true
  freshclam --quiet >/dev/null 2>&1 || echo "antivirus: a atualizacao falhou; usando as assinaturas que ja havia"
  systemctl start clamav-freshclam >/dev/null 2>&1 || true
  [ -n "$(newest __MAX_AGE_DAYS__)" ] || refuse "sem assinaturas dos ultimos __MAX_AGE_DAYS__ dias" 2
fi
CLAMSCAN_OPTS="--recursive --infected --stdout --alert-exceeds-max=yes --alert-encrypted=yes"
CLAMSCAN_OPTS="$CLAMSCAN_OPTS --max-filesize=512M --max-scansize=1024M"
""".replace("__FRESH_DAYS__", str(FRESH_DAYS)).replace("__MAX_AGE_DAYS__", str(MAX_AGE_DAYS))

# Before installing: check the holding folder and, if it does not pass, DELETE it.
SCAN_SCRIPT = r"""
set -u
target=${1:?}
case "$target" in
  /var/tmp/gamepanel-*) ;;
  *) echo "ANTIVIRUS: caminho fora da area de verificacao: $target" >&2; exit 2 ;;
esac
case "$target" in *..*) echo "ANTIVIRUS: caminho invalido: $target" >&2; exit 2 ;; esac
# Found something or could not check: what is in the holding folder is useless, and it goes.
refuse() { rm -rf -- "$target"; echo "ANTIVIRUS: $1; o mod NAO foi instalado" >&2; exit "$2"; }
""" + _ENSURE + r"""
echo "antivirus: verificando..."
# shellcheck disable=SC2086 # the options are a word list on purpose
out=$(clamscan $CLAMSCAN_OPTS --no-summary -- "$target" 2>&1)
rc=$?
case $rc in
  0) echo "antivirus: nada encontrado" ;;
  1) printf '%s\n' "$out" >&2; refuse "o ClamAV encontrou algo" 1 ;;
  *) printf '%s\n' "$out" >&2; refuse "a verificacao nao rodou (codigo $rc)" 2 ;;
esac
"""

# After installing: check what is ALREADY on the server (what got in before the antivirus).
# It only READS - nothing is deleted or moved. A mod on a running server is the call of whoever
# looks after it: deleting on its own over a false positive would break a mod the server depends on.
AUDIT_SCRIPT = r"""
set -u
refuse() { echo "ANTIVIRUS: $1; nada foi verificado" >&2; exit "$2"; }
present=()
for p in "$@"; do
  case "$p" in *..*) refuse "caminho invalido: $p" 2 ;; esac
  if [ -e "$p" ]; then present+=("$p"); else echo "antivirus: nao existe (pulado): $p"; fi
done
if [ ${#present[@]} -eq 0 ]; then
  echo "antivirus: nenhum mod instalado para verificar"
  exit 0
fi
""" + _ENSURE + r"""
echo "antivirus: verificando ${present[*]}"
# shellcheck disable=SC2086 # the options are a word list on purpose
clamscan $CLAMSCAN_OPTS -- "${present[@]}" 2>&1
rc=$?
case $rc in
  0) echo "antivirus: nada encontrado" ;;
  1) echo "ANTIVIRUS: o ClamAV encontrou algo (linhas FOUND acima)." >&2
     echo "Nada foi apagado: remova pela tela Mods e reinicie o servidor." >&2
     exit 1 ;;
  *) echo "ANTIVIRUS: a verificacao nao rodou (codigo $rc)" >&2; exit 2 ;;
esac
"""

# Helper mode: the scan runs as steam, which can neither `apt-get` nor stop the freshclam
# daemon. Installing and refreshing become the step BEFORE it, through the fixed root helper
# (`remote_cmd.clamav_ensure`, which runs the same steps as `_ENSURE`), and the scan itself
# only CHECKS that what that step left is usable. Still fail closed: no ClamAV or signatures
# older than the limit = no mod.
_CHECK = r"""
command -v clamscan >/dev/null 2>&1 || refuse "o ClamAV nao esta instalado neste servidor" 2
db=${CLAMAV_DB_DIR:-/var/lib/clamav}
newest() { find "$db" -maxdepth 1 \( -name '*.cvd' -o -name '*.cld' \) -mtime "-$1" 2>/dev/null | head -n 1; }
[ -n "$(newest __MAX_AGE_DAYS__)" ] || refuse "sem assinaturas dos ultimos __MAX_AGE_DAYS__ dias" 2
CLAMSCAN_OPTS="--recursive --infected --stdout --alert-exceeds-max=yes --alert-encrypted=yes"
CLAMSCAN_OPTS="$CLAMSCAN_OPTS --max-filesize=512M --max-scansize=1024M"
""".replace("__MAX_AGE_DAYS__", str(MAX_AGE_DAYS))


def _as_steam_variant(script: str) -> str:
    """The same script with the inline install swapped for the check-only block.

    Derived, not written twice: the scan rule (what counts as a finding, what is deleted) has to
    stay ONE text for both modes. `raise` if the swap did not happen - a variant that still
    carries the apt-get would fail as steam on every mod, and one without any block would scan
    with no options at all.
    """
    if script.count(_ENSURE) != 1:
        raise RuntimeError("o bloco de instalacao do ClamAV nao esta no script")
    return script.replace(_ENSURE, _CHECK)


SCAN_SCRIPT_AS_STEAM = _as_steam_variant(SCAN_SCRIPT)
AUDIT_SCRIPT_AS_STEAM = _as_steam_variant(AUDIT_SCRIPT)

# Create the upload holding folder (only root reads it) and sweep the ones left over from an
# upload that never became a job - a browser closed halfway, for example.
INCOMING_SCRIPT = r"""
set -e
d=${1:?}
case "$d" in /var/tmp/gamepanel-incoming-*) ;; *) echo "pasta de espera invalida: $d" >&2; exit 2 ;; esac
find /var/tmp -maxdepth 1 -name 'gamepanel-incoming-*' -mmin +1440 -exec rm -rf -- {} + 2>/dev/null || true
mkdir -p -m 0700 -- "$d"
"""

# Move what has already been checked from the holding folder to the mods folder, with the same
# rules as the regular upload (UPLOAD_SCRIPT): an existing file gets a .bak copy and keeps owner
# and permissions; a new one inherits the folder owner, because the game runs as 'steam' and needs to read it.
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
    """The holding folder of ONE upload. The token comes from the panel (hex), never from the form."""
    if not token or not all(c in "0123456789abcdef" for c in token):
        raise ValueError("token de envio invalido")
    return INCOMING_PREFIX + token


# ------------------------------------------------- commands, per access mode
#
# Every script above deals with mod CONTENT, so it goes through `remote_cmd.as_steam`: in
# helper mode the holding folder belongs to steam, and the move into the game folder never
# writes through a link with more rights than the game has. Only the ClamAV install needs
# root, and in helper mode it is a separate step through the fixed helper.

def incoming_command(server: ServerLike, incoming: str) -> str:
    return remote_cmd.as_steam(server, "bash", "-c", INCOMING_SCRIPT, "gp", incoming)


def place_command(server: ServerLike, incoming: str, folder: str) -> str:
    return remote_cmd.as_steam(server, "bash", "-c", PLACE_SCRIPT, "gp", incoming, folder)


def scan_steps(server: ServerLike, incoming: str) -> list[str]:
    """Job steps that scan the holding folder (and delete it if it does not pass)."""
    if remote_cmd.privileged(server):
        return [remote_cmd.as_steam(server, "bash", "-c", SCAN_SCRIPT, "gp", incoming)]
    return [remote_cmd.clamav_ensure(),
            remote_cmd.as_steam(server, "bash", "-c", SCAN_SCRIPT_AS_STEAM, "gp", incoming)]


def audit_steps(server: ServerLike, paths: Sequence[str]) -> list[str]:
    """Job steps that scan what is already installed (read-only).

    In helper mode ClamAV is ensured even when nothing turns out to be installed: knowing what
    exists means reading the game folders, which only steam may do, and steam cannot install
    anything. The cost is an install on a server with no mods, on an explicit click.
    """
    if remote_cmd.privileged(server):
        return [remote_cmd.as_steam(server, "bash", "-c", AUDIT_SCRIPT, "gp", *paths)]
    return [remote_cmd.clamav_ensure(),
            remote_cmd.as_steam(server, "bash", "-c", AUDIT_SCRIPT_AS_STEAM, "gp", *paths)]
