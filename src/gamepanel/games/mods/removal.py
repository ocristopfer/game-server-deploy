"""Removing mod FILES (and mod folders) from a profile's mods folder, by name only.

The Mods screen lists what is in the folder and the person ticks what goes. What travels from
the form is a NAME, never a path: the folder is the profile's (or the custom setup's), fixed on
the panel side, and the remote script refuses a name with a slash. Decisions, each with its reason:

- **The folder must be the real path, with no link anywhere in it** (`realpath -e` equal to the
  folder). In legacy mode this runs as root, in a folder the game itself can write: a link the
  game planted would turn `rm -rf` into a delete wherever it points.
- **A file and a folder are told apart by the PANEL** (`f NAME` / `d NAME`): a profile that only
  takes `.dll` files cannot have a folder deleted through a name that happens to end in `.dll`,
  and a folder mod (Shroudtopia's `mod.json` folders) is only removable where the profile says
  folder mods exist.
- **Unreal 5 mods are three files with the same stem** (`.pak` + `.utoc` + `.ucas`, IoStore):
  removing the `.pak` alone leaves the other two in `~mods`, and the engine then logs a broken
  container on every start (or, with only the `.pak` gone, mounts nothing and says nothing). So
  removing any of the three removes the siblings the profile also accepts; a sibling that is not
  there is skipped, because plenty of mods ship a `.pak` only.
- **It runs as a JOB**, like the upload and the installers: the restart (when asked) is the step
  after it, so a removal that failed does not restart the server for nothing.
"""
from __future__ import annotations

import posixpath
from collections.abc import Iterable

from gamepanel.games.mods.profiles import ModProfile
from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.ssh import ServerLike

# The three files of an Unreal 5 (IoStore) mod.
IOSTORE = (".pak", ".utoc", ".ucas")
# A file name long enough for any mod, short enough not to become a way to send a blob.
NAME_MAX = 200
# How many names one removal takes: a full mods folder, not an unbounded form.
MAX_NAMES = 200

# $1 = mods folder; then pairs "f NAME" (a file or a link) / "d NAME" (a folder).
REMOVE_SCRIPT = r"""
set -u
dir=${1:?}
shift
case "$dir" in /*) ;; *) echo "invalid mods folder: $dir" >&2; exit 2 ;; esac
real=$(realpath -e -- "$dir" 2>/dev/null) || { echo "the mods folder does not exist: $dir" >&2; exit 3; }
[ "$real" = "$dir" ] || { echo "the mods folder is (or is under) a link: $dir -> $real" >&2; exit 3; }
removed=0
while [ $# -ge 2 ]; do
  kind=$1; name=$2; shift 2
  case "$name" in ''|.|..|*/*) echo "invalid name: $name" >&2; exit 2 ;; esac
  p="$dir/$name"
  if [ -L "$p" ]; then
    rm -f -- "$p"
  elif [ "$kind" = d ] && [ -d "$p" ]; then
    rm -rf -- "$p"
  elif [ "$kind" = f ] && [ -f "$p" ]; then
    rm -f -- "$p"
  elif [ -e "$p" ]; then
    echo "$name: not what the screen listed (file vs folder); nothing was deleted" >&2; exit 4
  else
    echo "not there (skipped): $p"
    continue
  fi
  [ -e "$p" ] || [ -L "$p" ] || { echo "removed: $p"; removed=$((removed + 1)); continue; }
  echo "could not delete: $p" >&2; exit 5
done
echo "$removed item(s) removed from $dir"
"""


def valid_name(name: str) -> bool:
    """One entry of a folder: no path, no control character, not '.' or '..'."""
    return (0 < len(name) <= NAME_MAX and name not in (".", "..") and "/" not in name and "\\" not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name))


def _siblings(profile: ModProfile, name: str) -> list[str]:
    stem, ext = posixpath.splitext(name)
    if ext.lower() not in IOSTORE:
        return [name]
    # Only the extensions THIS profile takes: a 4.x Unreal game accepts .pak alone, and its
    # folder may hold a .utoc that is the game's, not the mod's.
    return [name, *(stem + e for e in IOSTORE if e != ext.lower() and profile.accepts(stem + e))]


def targets(profile: ModProfile, names: Iterable[str], folders: Iterable[str] = ()) -> list[tuple[str, str]]:
    """The ("f"|"d", name) pairs to remove, or ValueError (a Message) if any name is not acceptable.

    All or nothing: one bad name refuses the whole removal, before anything reaches the container.
    `folders` are the names the person ticked as FOLDER mods (the screen knows which rows are
    folders); they only count on a profile that has folder mods.
    """
    out: list[tuple[str, str]] = []
    for name in (n.strip() for n in names):
        if not valid_name(name) or not profile.accepts(name):
            raise ValueError(Message("mods.bad_name", name=name or "?",
                                     allowed=", ".join(profile.upload_names or profile.extensions)))
        out.extend(("f", n) for n in _siblings(profile, name))
    for name in (n.strip() for n in folders):
        if not profile.folder_mods or not valid_name(name):
            raise ValueError(Message("mods.bad_name", name=name or "?",
                                     allowed=", ".join(profile.upload_names or profile.extensions)))
        out.append(("d", name))
    unique = list(dict.fromkeys(out))
    if not unique:
        raise ValueError(Message("mods.remove_none_selected"))
    if len(unique) > MAX_NAMES:
        raise ValueError(Message("mods.remove_too_many", n=MAX_NAMES))
    return unique


def remove_command(server: ServerLike, folder: str, pairs: list[tuple[str, str]]) -> str:
    """The removal as steam (helper mode) or root (legacy mode, exactly how every content command runs)."""
    flat = [part for pair in pairs for part in pair]
    return remote_cmd.as_steam(server, "bash", "-c", REMOVE_SCRIPT, "gp", folder, *flat)
