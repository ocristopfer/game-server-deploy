"""The second backup copy, kept on the PANEL in addition to the one in the game container.

The copy inside the container dies with it: removing an instance through the broker
deletes the CT with its disks (`purge=1`), and the save went along. The one here
survives that.

It is organized by the backup PREFIX (the service name: `valheim`), not by the server's
id on the panel. The recreated server gets another id, but the catalog game comes up
with the same service - and that is the only reason the new Valheim sees the save of the
Valheim that was removed. Paths inside the tar are absolute (`-C /`), and the game
recreated from the same catalog uses the same ones, so restoring here is the usual
`RESTORE_SCRIPT`.

Only local disk and stdlib: nothing here speaks SSH. Fetching and sending back is done by
`app.py`, which passes the chunks (`stream_remote_file`) or reads the file from here into
ssh's input.
"""
from __future__ import annotations

import os
import posixpath
import re
import time
from collections.abc import Iterable

from gamepanel.runtime.backups import validate_backup_name

# The line `BACKUP_SCRIPT` writes when it finishes. It is what tells the panel WHICH file
# to fetch: the name carries the container's time, which the panel cannot guess. Changing
# the sentence there without changing it here leaves the backup without a second copy -
# the test compares the two.
DONE_RE = re.compile(r"^backup pronto: (.+) \((\d+) bytes\)$", re.MULTILINE)
# `\Z`, not `$`: the prefix comes from the URL, and `$` would also accept it with a trailing newline.
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}\Z", re.ASCII)
PARTIAL_SUFFIX = ".parcial"
SAFETY_SUFFIX = "-antes-de-restaurar.tar.gz"
_CHMOD_PRIVATE = 0o700
_CHMOD_FILE = 0o600


def created_file(output: str, backup_dir: str) -> tuple[str, int] | None:
    """Path and size of the LAST backup the output announces, if it lives in the right folder.

    The folder is checked because the path comes from a remote command's text: without
    this, a forged line in the output would make the panel fetch any file in the container.
    """
    found = DONE_RE.findall(output or "")
    if not found:
        return None
    path, size = found[-1]
    if posixpath.dirname(path) != backup_dir.rstrip("/"):
        return None
    validate_backup_name(posixpath.basename(path))
    return path, int(size)


def _folder(root: str, prefix: str) -> str:
    if not PREFIX_RE.match(prefix or ""):
        raise ValueError(f"prefixo de backup invalido: {prefix!r}")
    return os.path.join(root, prefix)


def path_of(root: str, prefix: str, name: str) -> str:
    """The stored file, checked. `FileNotFoundError` when it does not exist."""
    path = os.path.join(_folder(root, prefix), validate_backup_name(name))
    if not os.path.isfile(path):
        raise FileNotFoundError(name)
    return path


def store(root: str, prefix: str, name: str, chunks: Iterable[bytes],
          expected_size: int | None, keep: int) -> tuple[int, list[str]]:
    """Write the copy and apply retention. Returns (bytes written, names deleted).

    Writes to a `.parcial` and only renames at the end, with the size checked: a remote
    `cat` that dies midway does NOT raise for whoever reads the chunks, it just stops
    sending - and a truncated copy with the right name would be worse than none, because
    nobody would suspect it.
    """
    folder = _folder(root, prefix)
    os.makedirs(folder, mode=_CHMOD_PRIVATE, exist_ok=True)
    final = os.path.join(folder, validate_backup_name(name))
    partial = final + PARTIAL_SUFFIX
    written = 0
    try:
        with open(partial, "wb") as out:
            for chunk in chunks:
                out.write(chunk)
                written += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        if expected_size is not None and written != expected_size:
            raise OSError(f"copia incompleta: chegaram {written} de {expected_size} bytes")
        # A save is the players' data, and the panel is not the only service on the machine.
        os.chmod(partial, _CHMOD_FILE)
        os.replace(partial, final)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    return written, prune(root, prefix, keep)


def prune(root: str, prefix: str, keep: int) -> list[str]:
    """Keep the `keep` newest copies of this prefix. 0 = never delete."""
    if keep <= 0:
        return []
    removed = []
    for item in list_copies(root, prefix)[keep:]:
        os.remove(os.path.join(_folder(root, prefix), item["name"]))
        removed.append(item["name"])
    return removed


def list_copies(root: str, prefix: str) -> list[dict]:
    """This prefix's copies, newest first (same format as the container's list)."""
    folder = _folder(root, prefix)
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return []
    copies = []
    for entry in entries:
        if not entry.is_file() or not entry.name.startswith(prefix + "-") or not entry.name.endswith(".tar.gz"):
            continue
        info = entry.stat()
        copies.append({
            "name": entry.name,
            "size": info.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime)),
            "seguranca": entry.name.endswith(SAFETY_SUFFIX),
            "_ts": info.st_mtime,
        })
    # A mtime tie (two copies in the same second) falls back to the name, which starts with the date.
    copies.sort(key=lambda c: (c["_ts"], c["name"]), reverse=True)
    for c in copies:
        del c["_ts"]
    return copies


def delete(root: str, prefix: str, name: str) -> int:
    """Delete a copy. Returns the size it had."""
    path = path_of(root, prefix, name)
    size = os.path.getsize(path)
    os.remove(path)
    return size


def list_games(root: str) -> list[str]:
    """The prefixes (games) that have a copy on the panel, with or without a registered server.

    It is the missing list: a server's Backups tab only shows ITS prefix, so the copy of a
    removed game stayed stored with no screen at all to show it.
    """
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return []
    return sorted(
        e.name for e in entries
        if e.is_dir() and PREFIX_RE.match(e.name) and list_copies(root, e.name)
    )
