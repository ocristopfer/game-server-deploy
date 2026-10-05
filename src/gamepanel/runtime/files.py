"""File editor and upload/download for the game container - all over SSH.

There is no SFTP and no transfer library: each operation is a small POSIX script
(`bash -lc`) run on the target, with the content going back and forth over standard
input/output (base64 text so it fits in a command; raw bytes, streamed, for upload
and download - see `ssh_stream_in`/`stream_remote_file`).

Every script goes through `remote_cmd.as_steam`: in helper mode it runs as `steam`, so the
editor and the upload never write through a link the game planted with more rights than the
game itself has.
"""
from __future__ import annotations

import base64
import contextlib
import shlex
import subprocess
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import RemoteError, ServerLike

SshRun = Callable[..., subprocess.CompletedProcess]
SshArgv = Callable[..., list[str]]

# ---------------------------------------------------------------- path

FILE_PATH_MAX = 400


def _resolve_segments(path: str) -> str:
    """Resolve '..' and '.' without touching the target (follows no link, reads no disk)."""
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/" + "/".join(parts)


def _check_roots(path: str, roots: tuple[str, ...]) -> None:
    if not roots or "/" in roots:  # "/" configured = no restriction
        return
    # rstrip + "/" so that /opt/game does not accidentally allow /opt/gamex.
    if any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots):
        return
    raise ValueError(Message("path.outside_roots", folders=", ".join(roots)))


def clean_path(raw: str, roots: tuple[str, ...]) -> str:
    """Normalize an absolute path coming from the screen (resolves '..' lexically)."""
    path = (raw or "").strip()
    if not path.startswith("/"):
        raise ValueError(Message("path.not_absolute"))
    if "\x00" in path or "\n" in path or "\r" in path:
        raise ValueError(Message("path.bad_character"))
    if len(path) > FILE_PATH_MAX:
        raise ValueError(Message("path.too_long"))
    cleaned = _resolve_segments(path)
    _check_roots(cleaned, roots)
    return cleaned


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"


# -------------------------------------------------------- remote scripts

LIST_SCRIPT = r"""
set -e
d=$1
[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }
find "$d" -maxdepth 1 -mindepth 1 -printf '%y\t%Y\t%s\t%TY-%Tm-%Td %TH:%TM\t%M\t%f\n' \
  2>/dev/null | head -n "$2"
"""

# $2 = edit limit, $3 = how much to bring from the end when the file is over the limit.
# A large file is no longer an error: only its end comes back, marked as 'tail'.
READ_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
sz=$(stat -Lc %s -- "$f")
if [ "$sz" -le "$2" ]; then kind=full; else kind=tail; fi
stat -Lc "META|%s|%y|%a|%U|%G|$kind" -- "$f"
if [ "$kind" = full ]; then
  base64 -w0 -- "$f"
else
  tail -c "$3" -- "$f" | base64 -w0
fi
"""

# Used before a download: checks that it can be downloaded and how much is coming.
STAT_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
[ -f "$f" ] || { echo "nao e um arquivo comum (pastas nao sao baixaveis)" >&2; exit 4; }
[ -r "$f" ] || { echo "sem permissao de leitura" >&2; exit 5; }
stat -Lc 'META|%s|%y|%a|%U|%G' -- "$f"
"""

# Writes over the existing file (cat >) instead of swapping the inode: that way owner,
# group and permissions stay the game's - the server runs as 'steam', not root.
WRITE_SCRIPT = r"""
set -e
f=$1
d=$(dirname "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
base64 -d > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 "$f"
  # A new file inherits the folder owner: the game runs as 'steam' and must still be
  # able to rewrite its own config.
  chown --reference="$d" "$f" 2>/dev/null || true
fi
echo "gravado: $(stat -Lc %s -- "$f") bytes"
"""

# Deleting has no .bak: a multi-GB save does not fit in a safety copy, and whoever
# deletes wants the space back. That is why the scope is narrow: regular file, link,
# or EMPTY folder (rmdir) - no recursive removal from the screen.
DELETE_SCRIPT = r"""
set -e
f=$1
[ -e "$f" ] || [ -L "$f" ] || { echo "arquivo nao encontrado" >&2; exit 3; }
if [ -d "$f" ] && [ ! -L "$f" ]; then
  rmdir -- "$f" 2>/dev/null || { echo "a pasta nao esta vazia (esvazie antes de apagar)" >&2; exit 4; }
  echo "pasta apagada: $f"
else
  sz=$(stat -Lc %s -- "$f" 2>/dev/null || echo 0)
  # -f so rm never stops to ask about a write-protected file; the error
  # that matters (read-only folder) still comes through.
  rm -f -- "$f"
  echo "apagado: $f ($sz bytes)"
fi
"""

# $1 = final destination. The content arrives RAW on standard input (no base64: the file
# may be gigabytes, and encoding would inflate it by 33% for nothing).
UPLOAD_SCRIPT = r"""
set -e
f=$1
d=$(dirname -- "$f")
[ -d "$d" ] || { echo "pasta nao existe: $d" >&2; exit 3; }
[ -d "$f" ] && { echo "ja existe uma PASTA com esse nome" >&2; exit 4; }
t=$(mktemp "$d/.gamepanel-XXXXXX")
trap 'rm -f "$t"' EXIT
cat > "$t"
if [ -e "$f" ]; then
  [ -f "$f" ] || { echo "o destino nao e um arquivo comum" >&2; exit 4; }
  cp -a -- "$f" "$f.$(date +%Y%m%d-%H%M%S).bak"
  # cat > over it instead of mv: keeps the owner and mode of the file that was already there.
  cat "$t" > "$f"
else
  cat "$t" > "$f"
  chmod 0644 -- "$f"
  # A new file inherits the folder owner: the game runs as 'steam' and must be able to read it.
  chown --reference="$d" -- "$f" 2>/dev/null || true
fi
echo "enviado: $f ($(stat -Lc %s -- "$f") bytes)"
"""


# ----------------------------------------------------------------- list

_LIST_LINE_FIELDS = 6


def list_dir(ssh_run: SshRun, server: ServerLike, path: str, limit: int) -> tuple[list[dict], bool]:
    proc = ssh_run(server, remote_cmd.as_steam(server, "bash", "-lc", LIST_SCRIPT, "gp", path, str(limit)), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao listar a pasta")
    entries: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 5)
        if len(parts) != _LIST_LINE_FIELDS:
            continue
        kind, target_kind, size, mtime, mode, name = parts
        real = target_kind if kind == "l" else kind
        entries.append({
            "name": name,
            "dir": real == "d",
            "link": kind == "l",
            "size": int(size) if size.isdigit() else 0,
            "mtime": mtime,
            "mode": mode,
            "path": (path.rstrip("/") + "/" + name) if path != "/" else "/" + name,
        })
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return entries, len(entries) >= limit


_FIND_LINE_FIELDS = 3


def find_config_files(ssh_run: SshRun, server: ServerLike, root: str, globs: Iterable[str]) -> list[dict]:
    """Scan the game folder for the most likely configuration files."""
    names = " -o ".join(f"-name {shlex.quote(g)}" for g in globs)
    script = (
        "set -e\n"
        'd=$1\n'
        '[ -d "$d" ] || { echo "pasta nao encontrada: $d" >&2; exit 3; }\n'
        f'find "$d" -maxdepth 5 -type f \\( {names} \\) '
        r"-printf '%s\t%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | LC_ALL=C sort -k3 | head -n 300"
        "\n"
    )
    proc = ssh_run(server, remote_cmd.as_steam(server, "bash", "-lc", script, "gp", root), timeout=90)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha na busca")
    found: list[dict] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != _FIND_LINE_FIELDS:
            continue
        found.append({
            "size": int(parts[0]) if parts[0].isdigit() else 0,
            "mtime": parts[1],
            "path": parts[2],
        })
    return found


# ----------------------------------------------------------- read/write

def _parse_meta(head: str, fields: int) -> list[str]:
    meta = head.split("|")
    if meta[0] != "META" or len(meta) < fields:
        raise RemoteError(Message("file.unexpected_reply"))
    return meta


def stat_file(ssh_run: SshRun, server: ServerLike, path: str) -> dict:
    """Metadata without fetching the content - used before starting a download."""
    proc = ssh_run(server, remote_cmd.as_steam(server, "bash", "-lc", STAT_SCRIPT, "gp", path), timeout=40)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    meta = _parse_meta(proc.stdout.strip(), 6)
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else 0,
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
    }


def read_file(
    ssh_run: SshRun, server: ServerLike, path: str, max_bytes: int, preview_bytes: int,
) -> dict:
    """Read the file for the editor.

    A file within the limit comes whole and editable. Above the limit only the end
    comes (read-only) - whoever needs the complete file uses the download.
    """
    proc = ssh_run(
        server,
        remote_cmd.as_steam(server, "bash", "-lc", READ_SCRIPT, "gp", path, str(max_bytes), str(preview_bytes)),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao ler o arquivo")
    head, _, payload = proc.stdout.partition("\n")
    meta = _parse_meta(head, 7)
    try:
        raw = base64.b64decode(payload.strip() or "", validate=True)
    except ValueError as exc:  # binascii.Error is a subclass of ValueError
        raise RemoteError(Message("file.corrupted")) from exc
    binary = b"\x00" in raw
    truncated = meta[6] == "tail"
    text = "" if binary else raw.decode("utf-8", "replace")
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1] or "arquivo",
        "size": int(meta[1]) if meta[1].isdigit() else len(raw),
        "mtime": meta[2][:19],
        "mode": meta[3],
        "owner": f"{meta[4]}:{meta[5]}",
        "binary": binary,
        # Only the end of the file: editing and saving from here would wipe everything else.
        "truncated": truncated,
        "shown": len(raw),
        "editable": not binary and not truncated,
        "text": text,
        # \r\n becomes \n in the textarea; we keep this to write the file back as it was.
        "crlf": b"\r\n" in raw,
    }


def write_file(ssh_run: SshRun, server: ServerLike, path: str, data: bytes) -> str:
    """Write the file in the container (with .bak, owner and permissions preserved)."""
    proc = ssh_run(
        server, remote_cmd.as_steam(server, "bash", "-lc", WRITE_SCRIPT, "gp", path), timeout=120,
        stdin_data=base64.b64encode(data),
    )
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao gravar")
    return proc.stdout.strip()


def delete_file(ssh_run: SshRun, server: ServerLike, path: str) -> str:
    """Delete a file (or empty folder) in the container. There is no undo."""
    proc = ssh_run(server, remote_cmd.as_steam(server, "bash", "-lc", DELETE_SCRIPT, "gp", path), timeout=60)
    if proc.returncode != 0:
        raise RemoteError((proc.stderr or proc.stdout).strip() or "falha ao apagar")
    return proc.stdout.strip()


# --------------------------------------------------------- streaming

def ssh_stream_in(
    ssh_argv: SshArgv, server: ServerLike, command: str, source: Any, timeout: int, chunk_size: int,
) -> str:
    """Run a remote command, feeding its input from `source`.

    Unlike running with the whole content in memory: here the bytes pass in chunks,
    from the file the browser sent straight to the `cat` on the other side. That is
    what makes it possible to upload a multi-GB mod or save.
    """
    argv = [*ssh_argv(server, connect_timeout=10), command]
    try:
        proc = subprocess.Popen(  # noqa: S603  # NOSONAR - argv comes from SshClient, never raw from a form
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise RemoteError(Message("ssh.failed_to_run", reason=exc)) from exc

    # In a local variable because `Popen.stdin` is Optional in the type (Popen without PIPE
    # has no input) and because it is cleared in the `finally` below - the `close()` there
    # must refer to the SAME object the loop used.
    entry = proc.stdin
    if entry is None:
        raise RemoteError(Message("ssh.no_stdin"))

    try:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            entry.write(chunk)
    except OSError:
        # The other side gave up (no space, no permission): the reason is in stderr, so
        # complaining about the broken pipe here is pointless. BrokenPipeError - the
        # typical case - is already an OSError, so listing both caught nothing extra.
        pass
    finally:
        # Closing the input is what makes the remote `cat` finish. The reference must go
        # too: communicate() below would flush an already closed file and raise ValueError
        # with the file ALREADY written on the other side - error on screen, upload done.
        with contextlib.suppress(OSError):
            entry.close()
        proc.stdin = None

    try:
        out_text, failure = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RemoteError(Message("ssh.upload_timeout", seconds=timeout,
                                   host=server["host"])) from None
    if proc.returncode != 0:
        detail = (failure or out_text or b"").decode("utf-8", "replace").strip()
        raise RemoteError(detail or f"falha ao enviar (exit {proc.returncode})")
    return out_text.decode("utf-8", "replace").strip()


def stream_remote_file(
    ssh_argv: SshArgv, server: ServerLike, path: str, chunk_size: int,
) -> Iterator[bytes]:
    """Send the container's file straight to the browser, without touching disk.

    It is `cat` on the other end read in chunks: a multi-GB save comes down without the
    panel holding anything in memory.
    """
    argv = [*ssh_argv(server), remote_cmd.as_steam(server, "cat", "--", path)]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603  # NOSONAR - argv comes from SshClient
    # `Popen.stdout` is Optional in the type; here it exists because PIPE was requested above.
    out_text = proc.stdout
    if out_text is None:
        raise RemoteError(Message("ssh.no_stdout"))

    def generate() -> Iterator[bytes]:
        try:
            while True:
                chunk = out_text.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            # A browser that cancels midway must not leave an orphan ssh holding an fd.
            if proc.poll() is None:
                proc.kill()
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    pipe.close()
            proc.wait()

    return generate()
