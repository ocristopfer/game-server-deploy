"""Game container backup: a tar.gz of the folders worth keeping, over SSH.

The backup lives INSIDE the game container, not on the panel - which is why creating,
listing and deleting are just one remote script each. Download and restore reuse,
respectively, `runtime.files.stream_remote_file` and the command that `backup_command`
builds here (the panel chains the safety copy, `restore_command` and the pull to the panel -
that is job orchestration, it stays in the backups blueprint).
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import RemoteError, ServerLike

SshRun = Callable[..., subprocess.CompletedProcess]

# $1 = backups folder, $2 = server prefix, $3 = how many copies to keep,
# $4 = name suffix (the restore's safety copy uses this), $5.. = what to back up.
BACKUP_SCRIPT = r"""
set -e
dir=$1
nome=$2
manter=$3
sufixo=$4
shift 4
[ $# -gt 0 ] || { echo "nenhuma pasta para guardar" >&2; exit 3; }

# A path that does not exist yet is NOT an error: the save folder only appears when someone
# joins the server for the first time, and the game record already points to it. Each missing
# one becomes a warning and the others still go in; it only stops if none is left.
# (Rotates the arguments: takes the first and, if it exists, puts it back at the end.)
n=$#
i=0
while [ "$i" -lt "$n" ]; do
  p=$1
  shift
  i=$((i + 1))
  if [ -e "$p" ]; then
    set -- "$@" "$p"
  else
    echo "ignorado (ainda nao existe): $p"
  fi
done
[ $# -gt 0 ] || { echo "nada a guardar: nenhum dos caminhos existe no container" >&2; exit 3; }
mkdir -p -- "$dir"

# Free space vs target size. The .tar.gz is much smaller than the original, so this
# margin is generous on purpose: filling the container disk takes the game down with it.
precisa=$(du -sk -- "$@" 2>/dev/null | awk '{ t += $1 } END { print t+0 }')
livre=$(df -Pk -- "$dir" | awk 'NR>1 { print $4; exit }')
if [ "${livre:-0}" -lt "${precisa:-0}" ]; then
  echo "sem espaco em $dir: o alvo ocupa ${precisa}KB e sobram ${livre}KB" >&2
  exit 4
fi

alvo="$dir/$nome-$(date +%Y%m%d-%H%M%S)$sufixo.tar.gz"
tmp="$alvo.parcial"
lista=$(mktemp)
trap 'rm -f "$tmp" "$lista"' EXIT
# An absolute path becomes relative inside the tar (-C /): that is what makes restore put
# each file back exactly where it came from.
for p in "$@"; do printf '%s\n' "${p#/}" >> "$lista"; done

# tar exits with 1 when a file changes while being read - normal with the server running,
# and it does not invalidate the backup. Only exit code 2 (a real error) aborts.
set +e
tar -czf "$tmp" --warning=no-file-changed -C / -T "$lista"
rc=$?
set -e
[ "$rc" -le 1 ] || { echo "tar falhou (codigo $rc)" >&2; exit 5; }
[ "$rc" -eq 1 ] && echo "aviso: arquivo mudou durante a copia; pare o servidor para uma copia mais fiel"

mv -- "$tmp" "$alvo"
echo "backup pronto: $alvo ($(stat -Lc %s -- "$alvo") bytes)"

# Retention: keeps the N newest copies of THIS server and deletes the rest.
if [ "$manter" -gt 0 ]; then
  ls -1t -- "$dir/$nome-"*.tar.gz 2>/dev/null | tail -n +$((manter + 1)) | while IFS= read -r velho; do
    rm -f -- "$velho" && echo "retencao: apagado $(basename -- "$velho")"
  done
fi
"""

# $1 = backups folder, $2 = server prefix.
BACKUP_LIST_SCRIPT = r"""
set -e
dir=$1
nome=$2
[ -d "$dir" ] || exit 0
# Name first: since it starts with the date, a reverse sort puts the newest on top.
find "$dir" -maxdepth 1 -type f -name "$nome-*.tar.gz" \
  -printf '%f\t%s\t%TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | LC_ALL=C sort -r | head -n "$3"
"""

# The member check of the restore, in awk (every CT has it; python3 only comes with Proton).
# Input: `tar --numeric-owner --quoting-style=c -tvzf`, one member per line. The C quoting is
# what makes the line parseable: the name is the first double-quoted string (with
# --numeric-owner nothing before it can hold a quote), and a symlink/hardlink target is the
# second. The escapes stay as they are - an escaped byte is never a slash or a dot, so the
# path checks are exact without decoding anything.
#
# ENVIRON["GP_ALLOWED"] = the server's backup paths, one per line. Output: the backup paths
# that have members in the archive (the tar operands); the reason for a refusal on stderr.
_RESTORE_CHECK_AWK = r"""
function fail(msg) {
  if (!bad) print "restauracao recusada: " msg > "/dev/stderr"
  bad = 1
  exit 1
}
function cstr(s,   i, n, c, out) {
  OK = 0
  n = length(s)
  for (i = 1; i <= n && substr(s, i, 1) != "\""; i++) ;
  out = ""
  for (i++; i <= n; i++) {
    c = substr(s, i, 1)
    if (c == "\\") { out = out c substr(s, i + 1, 1); i++; continue }
    if (c == "\"") { OK = 1; POS = i + 1; return out }
    out = out c
  }
  return ""
}
function norm(p,   n, parts, out, k, i, r) {
  ESC = 0
  n = split(p, parts, "/")
  k = 0
  for (i = 1; i <= n; i++) {
    if (parts[i] == "" || parts[i] == ".") continue
    if (parts[i] == "..") { if (k == 0) { ESC = 1; return "" } k--; continue }
    out[++k] = parts[i]
  }
  r = ""
  for (i = 1; i <= k; i++) r = (i == 1) ? out[i] : r "/" out[i]
  return r
}
function parent(p) {
  if (p !~ /\//) return ""
  sub(/\/[^\/]*$/, "", p)
  return p
}
function root_of(p,   i) {
  for (i = 1; i <= na; i++)
    if (p == allowed[i] || substr(p, 1, length(allowed[i]) + 1) == allowed[i] "/") return i
  return 0
}
BEGIN {
  n = split(ENVIRON["GP_ALLOWED"], raw, "\n")
  na = 0
  for (i = 1; i <= n; i++) {
    if (raw[i] == "") continue
    if (raw[i] ~ /[^ -~]/ || index(raw[i], "\"") || index(raw[i], "\\"))
      fail("a pasta de backup " raw[i] " tem um caractere que a conferencia nao compara; corrija o cadastro")
    p = norm(raw[i])
    if (p == "" || ESC) fail("pasta de backup invalida: " raw[i])
    allowed[++na] = p
  }
  if (na == 0) fail("o servidor nao tem pastas de backup cadastradas, entao nada pode voltar")
}
{
  type = substr($0, 1, 1)
  name = cstr($0)
  if (!OK) fail("linha que nao entendi na lista do arquivo: " $0)
  rest = substr($0, POS)
  if (substr(name, 1, 1) == "/") fail("caminho absoluto no arquivo: " name)
  if (("/" name "/") ~ /\/\.\.\//) fail("caminho com .. no arquivo: " name)
  if (type != "-" && type != "d" && type != "l" && type != "h")
    fail("tipo de arquivo que a restauracao nao aceita (" type "): " name)
  if (substr($0, 4, 1) ~ /[sS]/ || substr($0, 7, 1) ~ /[sS]/) fail("arquivo com setuid/setgid: " name)
  path = norm(name)
  if (type == "l" || type == "h") {
    target = cstr(rest)
    if (!OK) fail("linha que nao entendi na lista do arquivo: " $0)
    if (type == "h" && (substr(target, 1, 1) == "/" || ("/" target "/") ~ /\/\.\.\//))
      fail("link fisico para fora das pastas de backup: " name)
    if (type == "h" || substr(target, 1, 1) == "/") resolved = norm(target)
    else resolved = norm(parent(path) "/" target)
    if (ESC || !root_of(resolved)) fail("link para fora das pastas de backup: " name " -> " target)
  }
  r = root_of(path)
  # Outside every backup path: never extracted (it is not among the tar operands).
  if (!r) next
  # The entry of each folder comes before its content (tar -c always writes it so). Without it
  # tar would create the file THROUGH whatever already sits at that path - a link the game
  # planted included; with it, tar replaces that link with a real folder first.
  # (No single quote anywhere in this program: it travels inside a single-quoted bash string.)
  if (path != allowed[r] && !(parent(path) in dirs))
    fail("o arquivo traz " name " sem a pasta dele antes; foi montado a mao")
  if (type == "d") dirs[path] = 1
  present[r] = 1
}
END {
  if (bad) exit 1
  for (i = 1; i <= na; i++) if (present[i]) print allowed[i]
}
"""

# $1 = backups folder, $2 = file name, $3 = the game's systemd unit, $4 = `root` (legacy mode:
# the script already runs as root) or `steam` (helper mode: it runs as the login user and
# reaches steam and the service only through the fixed sudo lines), $5.. = the server's
# backup paths. Only what is under them is extracted; anything strange refuses the WHOLE restore.
#
# Why each tar option is (or is not) there, measured on GNU tar 1.35 (Debian 13):
# - default "old files" behavior: tar REPLACES a symlink found at a member's own path (it
#   unlinks it and creates the folder or file). That is what keeps a planted
#   `Saved/sub -> /etc` from being followed - so NO --keep-directory-symlink (it would keep
#   and follow the link) and NO --overwrite (it writes through the existing file);
# - NO --unlink-first: it refuses to remove a non-empty folder and the restore fails;
# - --delay-directory-restore and --no-overwrite-dir only change WHEN/WHETHER folder modes
#   are set, nothing about links, so they stay out;
# - what tar DOES follow is a link in a component it does not extract itself: the folders
#   ABOVE a backup path, and a folder with no entry of its own in the archive. The script
#   refuses the first (root mode; as steam a link only reaches what steam writes anyway) and
#   the awk check refuses the second;
# - helper mode extracts as steam with --no-same-owner --no-same-permissions, so nothing in
#   the archive chooses an owner or a mode bit. Legacy mode keeps ownership (as before), and
#   the check refuses setuid/setgid members: as root, keeping them would plant a setuid file
#   wherever the archive says.
RESTORE_SCRIPT = r"""
set -e
dir=$1
arq=$2
unit=$3
mode=$4
shift 4
# The name comes from the screen: a slash here would allow picking any .tar.gz in the container.
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
case "$mode" in
  root|steam) ;;
  *) echo "modo de acesso invalido: $mode" >&2; exit 3 ;;
esac
# Every path below is absolute. In helper mode the session starts in the login user's home
# (0700), which steam cannot enter: without this tar and gzip fail on the working folder.
cd /
f="$dir/$arq"

# Content (the archive, the extraction) as its owner; root only through the fixed helper.
content() {
  if [ "$mode" = steam ]; then sudo -n -u steam -- "$@"; else "$@"; fi
}
game_service() {
  if [ "$mode" = steam ]; then sudo -n /usr/local/sbin/gp-service "$1"; else systemctl "$1" "$unit"; fi
}

content test -f "$f" || { echo "backup nao encontrado: $arq" >&2; exit 3; }
# Checks BEFORE stopping the server: finding out the archive is corrupt (or refused) with
# the game already stopped is the worst possible moment.
content gzip -t -- "$f" 2>/dev/null || { echo "arquivo corrompido (gzip nao le): $arq" >&2; exit 4; }

check='__CHECK__'
plan=$(mktemp)
trap 'rm -f "$plan"' EXIT
set +e
content env LC_ALL=C tar --numeric-owner --quoting-style=c -tvzf "$f" 2>/dev/null \
  | GP_ALLOWED="$(printf '%s\n' "$@")" LC_ALL=C awk "$check" > "$plan"
rc=("${PIPESTATUS[@]}")
set -e
# awk first: when it refuses it stops reading, and tar then dies of a broken pipe - that is
# not a corrupt archive, and the reason is already on stderr.
[ "${rc[1]}" -eq 0 ] || exit 4
[ "${rc[0]}" -eq 0 ] || { echo "arquivo corrompido (tar nao le): $arq" >&2; exit 4; }
mapfile -t members < "$plan"
if [ "${#members[@]}" -eq 0 ]; then
  echo "nada neste backup esta nas pastas de backup do servidor ($*)" >&2
  exit 4
fi

if [ "$mode" = root ]; then
  for m in "${members[@]}"; do
    [ "${m%/*}" != "$m" ] || continue
    IFS=/ read -r -a parts <<< "${m%/*}"
    p=""
    for part in "${parts[@]}"; do
      p="$p/$part"
      if [ -L "$p" ]; then
        echo "restauracao recusada: $p e um link simbolico, e como root o tar o seguiria" >&2
        exit 4
      fi
    done
  done
fi

estava=$(systemctl is-active "$unit" 2>/dev/null || true)
if [ "$estava" = active ]; then
  game_service stop
  echo "servidor parado para a restauracao"
fi

if [ "$mode" = steam ]; then
  content tar -xzf "$f" -C / --no-same-owner --no-same-permissions -- "${members[@]}"
else
  tar -xzf "$f" -C / -- "${members[@]}"
fi
echo "restaurado: $arq"
printf 'pasta restaurada: /%s\n' "${members[@]}"

# A server that was already stopped stays stopped: restoring is not starting.
if [ "$estava" = active ]; then
  game_service start
  echo "servidor religado"
fi
""".replace("__CHECK__", _RESTORE_CHECK_AWK)

# The awk program goes into the script between single quotes: one apostrophe in it (a comment
# is enough) ends the string early and the restore dies with a bash syntax error - on the
# day someone needs a backup back. `raise`, not `assert`, so `python -O` keeps the check.
if "'" in _RESTORE_CHECK_AWK:
    raise RuntimeError("_RESTORE_CHECK_AWK nao pode ter aspas simples")

# $1 = backups folder, $2 = file name.
BACKUP_DELETE_SCRIPT = r"""
set -e
dir=$1
arq=$2
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
f="$dir/$arq"
[ -f "$f" ] || { echo "backup nao encontrado: $arq" >&2; exit 3; }
sz=$(stat -Lc %s -- "$f")
rm -f -- "$f"
echo "backup apagado: $arq ($sz bytes)"
"""

# $1 = backups folder, $2 = file name. The content arrives on standard input: it is the
# copy kept on the PANEL going back to the container, for `RESTORE_SCRIPT` to extract there.
BACKUP_RECEIVE_SCRIPT = r"""
set -e
dir=$1
arq=$2
case "$arq" in
  ''|*/*|*..*) echo "nome de backup invalido" >&2; exit 3 ;;
esac
mkdir -p -- "$dir"
tmp="$dir/.$arq.parcial"
trap 'rm -f "$tmp"' EXIT
cat > "$tmp"
# The real integrity test is the RESTORE_SCRIPT one, right after; this one only avoids
# replacing a good copy in the container with a file that arrived broken.
gzip -t -- "$tmp" 2>/dev/null || { echo "a copia chegou corrompida: $arq" >&2; exit 4; }
mv -f -- "$tmp" "$dir/$arq"
echo "copia do painel enviada ao container: $arq ($(stat -Lc %s -- "$dir/$arq") bytes)"
"""

# `\Z`, not `$`: `$` also matches before a trailing newline, and the name becomes a path.
BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.tar\.gz\Z")


def validate_backup_name(raw: str) -> str:
    """Check the name that came back from the screen before it goes into a remote command."""
    name = (raw or "").strip()
    if not BACKUP_NAME_RE.match(name) or ".." in name:
        raise ValueError(Message("backup.bad_name"))
    return name


def backup_paths(server: ServerLike, max_paths: int) -> list[str]:
    """What goes into this server's backup.

    With nothing configured, the config folder is used, which is where the save usually
    lives - the default that spares configuring any server just to get a backup.
    """
    chosen_ones = [ln.strip() for ln in (server["backup_paths"] or "").splitlines() if ln.strip()]
    if chosen_ones:
        return chosen_ones[:max_paths]
    fallback = (server["config_path"] or "").strip()
    return [fallback] if fallback else []


def backup_prefix(server: ServerLike) -> str:
    """Prefix of this server's files: it is what separates (and limits) the copies.

    It comes from the systemd unit name, which is already unique per container. The
    sanitizing matters because the prefix goes into a shell glob on the other side.
    """
    raw_text = (server["service"] or "jogo").rsplit(".service", 1)[0]
    clean = re.sub(r"[^A-Za-z0-9_-]", "-", raw_text).strip("-")
    return clean or "jogo"


def backup_command(
    server: ServerLike, backup_dir: str, keep: int, paths: list[str], suffix: str = "",
) -> str:
    """Build the remote backup command. Used by the screen, the restore and the scheduler."""
    return remote_cmd.as_steam(
        server, "bash", "-lc", BACKUP_SCRIPT, "gp", backup_dir, backup_prefix(server), str(keep), suffix, *paths,
    )


def restore_command(server: ServerLike, backup_dir: str, name: str, paths: list[str]) -> str:
    """Build the remote restore command: check every member, stop, extract, start.

    The only content command that is NOT wrapped in `as_steam`: it needs both identities in
    the same script - steam for the archive and the extraction, and the root helper for the
    service stop/start (steam itself has no sudo at all). So it runs as the login user, and
    the mode argument tells it which way to reach each one.
    """
    mode = "root" if remote_cmd.privileged(server) else remote_cmd.GAME_USER
    return remote_cmd.unprivileged(
        "bash", "-lc", RESTORE_SCRIPT, "gp", backup_dir, name, server["service"], mode, *paths,
    )


def receive_command(server: ServerLike, backup_dir: str, name: str) -> str:
    """Build the command that takes a panel copy back into the container (content on stdin)."""
    return remote_cmd.as_steam(server, "bash", "-lc", BACKUP_RECEIVE_SCRIPT, "gp", backup_dir, name)


_LIST_LINE_FIELDS = 3


def list_backups(ssh_run: SshRun, server: ServerLike, backup_dir: str, limit: int) -> list[dict]:
    proc = ssh_run(
        server,
        remote_cmd.as_steam(
            server, "bash", "-lc", BACKUP_LIST_SCRIPT, "gp", backup_dir, backup_prefix(server), str(limit)),
        timeout=40,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or Message("backup.list_failed"))
    copies: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != _LIST_LINE_FIELDS:
            continue
        copies.append({
            "name": parts[0],
            "size": int(parts[1]) if parts[1].isdigit() else 0,
            "mtime": parts[2],
            # The copy the panel itself takes before restoring: it gets lost among the
            # others if not marked, and it is exactly the one that saves a wrong restore.
            "seguranca": parts[0].endswith("-antes-de-restaurar.tar.gz"),
        })
    return copies


def delete_backup(ssh_run: SshRun, server: ServerLike, backup_dir: str, name: str) -> str:
    proc = ssh_run(
        server, remote_cmd.as_steam(server, "bash", "-lc", BACKUP_DELETE_SCRIPT, "gp", backup_dir, name), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or Message("backup.delete_failed"))
    return proc.stdout.strip()
