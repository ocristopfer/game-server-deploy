"""Custom mod setup (a loader from a link the admin gave) - runs INSIDE the game CT, not in the panel.

Same design as the other remote installers: the panel reads this text and runs it in the
container with `python3 -c`, over SSH - as steam in helper mode, as root in legacy mode. Stdlib
only and no import of `gamepanel`: the package does not exist in there, and whoever goes to the
internet is the CT, never the panel.

The setup (`--setup`, the JSON games/mods/custom.py stored) is checked AGAIN here with the same
rules: this script is the last stop before the files, and a row edited by hand in the panel's
database must not reach them. What each step does, with its reason:

- **Every folder is resolved and must stay inside the game folder** (`confined`): the setup only
  holds relative folders, but the game can write in its own folder and plant a link there; after
  `realpath` the target must still be under the game folder, or nothing is touched.
- **https only, redirects included, and a size cap** (`MAX_DOWNLOAD`): a plain http hop anywhere
  is a download anyone on the way can swap.
- **The antivirus sees the download BEFORE anything is unpacked** (`--scan`, the panel's script),
  and installing without it is refused - same rule as every other installer.
- **Unpacking refuses** absolute names, `..`, links, devices and archives that unpack to more than
  `MAX_UNPACKED` bytes or `MAX_MEMBERS` entries (zip slip and zip bombs), all checked before the
  first byte is written.
- **The package may not overwrite a file it did not create**: that would be a game file, and the
  panel could not give it back on uninstall (Oxide keeps a copy of each DLL for exactly that; a
  loader the panel knows nothing about gets no such promise). A reinstall may overwrite its own.
- **A marker records what the install CREATED** (files and folders), and uninstall removes only
  that, plus the environment lines it set. What already existed belongs to the game.
- **The environment only in helper mode**, through steam's overlay (`WINE_DLL_OVERRIDES` in
  runtime.env, `LD_PRELOAD` in service.env). In legacy mode the setup with environment settings is
  refused: writing root's drop-ins for a loader nobody measured is the wrong place to start.

Actions (argv): [--overlay] [--scan SCRIPT] [--unit SERVICE] --setup JSON
status | loader-install | loader-uninstall | mod-place INCOMING | mod-remove (f|d NAME)...,
followed by the game folder (and the action's own arguments). Ends with ONE JSON line.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

# ------------------------------------------------------------------ the setup rules
# The SAME values as games/mods/custom.py (a test compares them): the panel checks on save, this
# script checks again before touching anything.
URL_MAX = 500
URL_CHARS = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+", re.ASCII)
SEGMENT = re.compile(r"[A-Za-z0-9_~][A-Za-z0-9 _.+()~-]{0,99}", re.ASCII)
REL_MAX = 240
REL_DEPTH = 12
PRELOAD_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,99}", re.ASCII)
EXTENSION = re.compile(r"\.[a-z0-9]{1,10}", re.ASCII)
MAX_EXTENSIONS = 16
BLOCKED_EXTENSIONS = (".sh", ".bash", ".so", ".exe", ".bat", ".cmd", ".ps1", ".py", ".pl", ".service")
WINE_ENTRY = re.compile(r"[A-Za-z0-9_.-]{1,64}=(?:n,b|b,n|n|b|)", re.ASCII)
MAX_WINE = 8

# What one loader may weigh: BepInEx is ~33 MB and UE4SS ~10 MB; ClamAV's own per-file limit
# is 512 MB, and a download that big would be held in memory next to the running game.
MAX_DOWNLOAD = 256 * 1024 * 1024
# What the package may unpack to, and how many entries: a 1 MB zip of zeros can claim gigabytes.
MAX_UNPACKED = 1024 * 1024 * 1024
MAX_MEMBERS = 20000
# The download's own name, when it is a single file and not an archive.
FILE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,99}", re.ASCII)
# The upload holding folder (games/mods/antivirus.py, INCOMING_PREFIX + a hex token): a pattern to
# CHECK the argument against, not a temporary file this script creates.
INCOMING = re.compile(r"/var/tmp/gamepanel-incoming-[0-9a-f]{8,64}")  # noqa: S108
# A mod's name in the mods folder: no path, no control character, not '.' or '..'.
NAME_MAX = 200
MARK = ".gamepanel-custom.json"
RUNTIME_ENV = "/etc/game-runtime.env"
OWNER = "steam"
TIMEOUT = 120


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if (not url or len(url) > URL_MAX or not URL_CHARS.fullmatch(url) or parts.scheme != "https"
            or not parts.hostname or "@" in parts.netloc):
        raise ValueError("the loader link must be an https:// address")
    return url


def check_rel(rel: str, *, allow_empty: bool, segment: re.Pattern[str] = SEGMENT) -> str:
    parts = rel.split("/") if rel else []
    if not parts and allow_empty:
        return ""
    if (not parts or len(parts) > REL_DEPTH or len(rel) > REL_MAX
            or not all(segment.fullmatch(p) for p in parts)):
        raise ValueError(f"invalid folder in the setup: {rel!r}")
    return rel


def load_setup(text: str) -> dict:
    """The panel's setup, checked with the same rules it was saved with."""
    data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise ValueError("invalid setup")
    url = str(data.get("loader_url", ""))
    exts = [str(e) for e in data.get("extensions", [])]
    wine = [str(e) for e in data.get("wine", [])]
    preload = str(data.get("preload", ""))
    if (len(exts) > MAX_EXTENSIONS or not all(EXTENSION.fullmatch(e) for e in exts)
            or any(e in BLOCKED_EXTENSIONS for e in exts)):
        raise ValueError("invalid extension list in the setup")
    if len(wine) > MAX_WINE or not all(WINE_ENTRY.fullmatch(e) for e in wine):
        raise ValueError("invalid Wine overrides in the setup")
    if preload and not preload.endswith(".so"):
        raise ValueError("LD_PRELOAD must name a .so library")
    return {
        "loader_url": check_url(url) if url else "",
        "loader_dir": check_rel(str(data.get("loader_dir", "")), allow_empty=True),
        "mods_dir": check_rel(str(data.get("mods_dir", "")), allow_empty=False),
        "extensions": tuple(exts),
        "wine": wine,
        "preload": check_rel(preload, allow_empty=True, segment=PRELOAD_SEGMENT),
    }


def confined(game_dir: str, rel: str) -> str:
    """The REAL path of `rel` under the game folder, or ValueError when a link takes it outside.

    From here on every operation uses the resolved path: a link swapped in afterwards would have
    to win a race against a single call, instead of being followed by every one of them.
    """
    root = os.path.realpath(game_dir)
    real = os.path.realpath(os.path.join(root, rel) if rel else root)
    if real != root and not real.startswith(root + os.sep):
        raise ValueError(f"{rel} leaves the game folder (through a link)")
    return real


def _makedirs(game_dir: str, rel: str) -> str:
    path = confined(game_dir, rel)
    os.makedirs(path, exist_ok=True)
    # Again after creating: a component created by someone else in between is resolved now.
    return confined(game_dir, rel)


def valid_name(name: str) -> bool:
    return (0 < len(name) <= NAME_MAX and name not in (".", "..") and "/" not in name and "\\" not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name))


def accepts(setup: dict, name: str) -> bool:
    return valid_name(name) and name.lower().endswith(setup["extensions"])


# ------------------------------------------------------------------ steam overlay (helper mode)
# IDENTICAL in every installer that touches the game's environment (a test compares them): they
# run standalone in the CT and do not import each other. On a server in helper mode the installer
# runs as steam, which can write neither a systemd drop-in nor /etc/game-runtime.env. It writes
# these two files instead - steam's, inside a folder root owns (lib/ct-panel-access.sh prepares
# them once): service.env reaches the game unit through EnvironmentFile=, runtime.env reaches
# win-run after /etc/game-runtime.env. No daemon-reload: systemd reads the file at every start,
# and the restart that follows the install (a step of the same job) is what applies it.
OVERLAY_DIR = "/etc/gamepanel/game-env"
OVERLAY_SERVICE = "service.env"
OVERLAY_RUNTIME = "runtime.env"
OVERLAY_SYSTEMD_DIR = "/etc/systemd/system"
OVERLAY_DROPIN = "gamepanel-env.conf"
OVERLAY_WIN_RUN = "/usr/local/bin/win-run"
OVERLAY_HOOK = "gamepanel-overlay"
OVERLAY_KEY = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")
# It goes between single quotes in a file bash sources: never a quote, $ or backtick.
OVERLAY_VALUE = re.compile(r"[A-Za-z0-9_./:,;=@+ -]{0,4096}")
OVERLAY_HINT = "rode deploy/game/migrate-ct.ps1 de novo neste CT (ele prepara o ambiente dos mods)"


def overlay_path(name: str) -> str:
    return os.path.join(OVERLAY_DIR, name)


def _overlay_lines(name: str) -> list[str]:
    try:
        with open(overlay_path(name), encoding="utf-8") as f:
            return f.read().splitlines()
    except OSError:
        return []


def overlay_get(name: str, key: str) -> str | None:
    """KEY's value in the overlay file, without quotes; None when the line is not there."""
    for line in _overlay_lines(name):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def overlay_set(name: str, key: str, value: str | None) -> None:
    """KEY='value' in the overlay file, replaced where it is; None removes the line.

    The file has to exist: steam cannot create anything in the folder, and that is precisely what
    keeps it from being swapped for a link. Written in place (same inode, still steam's).
    """
    if not OVERLAY_KEY.fullmatch(key) or (value is not None and not OVERLAY_VALUE.fullmatch(value)):
        raise ValueError(f"valor invalido para o ambiente do jogo: {key}")
    path = overlay_path(name)
    if not os.path.isfile(path):
        raise ValueError(f"{path} nao existe: {OVERLAY_HINT}")
    new = None if value is None else f"{key}='{value}'"
    lines, placed = [], False
    for line in _overlay_lines(name):
        if line.startswith(key + "="):
            if new is not None and not placed:
                lines.append(new)
            placed = True
            continue
        lines.append(line)
    if new is not None and not placed:
        lines.append(new)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def overlay_wine_problem() -> str:
    """Why runtime.env would not reach the game ('' = it will)."""
    if not os.path.isfile(overlay_path(OVERLAY_RUNTIME)):
        return f"{overlay_path(OVERLAY_RUNTIME)} nao existe: {OVERLAY_HINT}"
    try:
        with open(OVERLAY_WIN_RUN, encoding="utf-8", errors="replace") as f:
            hooked = OVERLAY_HOOK in f.read()
    except OSError:
        hooked = False
    return "" if hooked else f"o win-run deste CT nao le o ambiente dos mods: {OVERLAY_HINT}"


def overlay_unit_problem(unit: str, root_dropin: str = "") -> str:
    """Why service.env would not reach this unit ('' = it will).

    A drop-in a ROOT installer wrote before the CT was migrated is a problem too: steam cannot
    remove it, so "disable" would only look like it worked.
    """
    if not os.path.isfile(overlay_path(OVERLAY_SERVICE)):
        return f"{overlay_path(OVERLAY_SERVICE)} nao existe: {OVERLAY_HINT}"
    if not os.path.isfile(os.path.join(OVERLAY_SYSTEMD_DIR, f"{unit}.d", OVERLAY_DROPIN)):
        return f"o servico {unit} nao le o ambiente dos mods: {OVERLAY_HINT}"
    if root_dropin and os.path.lexists(root_dropin):
        return f"o carregador foi instalado como root antes da migracao ({root_dropin}): {OVERLAY_HINT}"
    return ""
# ------------------------------------------------------------------ end of the steam overlay


# ------------------------------------------------------------------ antivirus
# IDENTICAL in thunderstore_remote.py (a test compares them): both run standalone in the CT and
# do not import each other. The rule (what counts as a finding) does not live here, but in the
# script the panel sends; here we only write what was downloaded into a folder and call the script.

def scanner(script: str):
    """Function that checks [(name, bytes)] with the panel's script; ValueError = rejected."""
    def scan(blobs: list[tuple[str, bytes]]) -> None:
        # /var/tmp and not /tmp: on Debian 13 /tmp is tmpfs (memory), and the package can be
        # tens of MB. The prefix is what the antivirus script agrees to delete. mkdtemp:
        # unpredictable name and 0700.
        os.makedirs("/var/tmp", exist_ok=True)  # noqa: S108
        work = tempfile.mkdtemp(prefix="gamepanel-scan-", dir="/var/tmp")
        try:
            for i, (name, data) in enumerate(blobs):
                safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]
                with open(os.path.join(work, f"{i:02d}-{safe}.zip"), "wb") as f:
                    f.write(data)
            sys.stdout.flush()
            proc = subprocess.run(["bash", "-c", script, "gp", work],  # noqa: S603, S607
                                  capture_output=True, text=True, check=False)
            sys.stdout.write((proc.stdout or "") + (proc.stderr or ""))
            if proc.returncode != 0:
                raise ValueError("o antivirus recusou o pacote: nada foi instalado")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return scan


def _no_scan(blobs: list[tuple[str, bytes]]) -> None:
    """Only for tests and status: `main` refuses to install without `--scan`."""


# ------------------------------------------------------------------ download

class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https address (GitHub releases redirect to a CDN)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise ValueError("the loader link redirected to a non-https address: refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, limit: int = MAX_DOWNLOAD) -> bytes:
    check_url(url)
    opener = urllib.request.build_opener(_HttpsOnly)
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with opener.open(req, timeout=TIMEOUT) as r:
        if not str(r.geturl()).lower().startswith("https://"):
            raise ValueError("the loader link ended on a non-https address: refused")
        chunks, total = [], 0
        while True:
            block = r.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError(f"the download is larger than {limit // (1024 * 1024)} MB: refused")
            chunks.append(block)
    return b"".join(chunks)


def download_name(url: str) -> str:
    return posixpath.basename(urllib.parse.unquote(urllib.parse.urlsplit(url).path))


# ------------------------------------------------------------------ unpacking

def safe_rel(name: str) -> str:
    """A path inside the archive, relative and never going up; empty = refused."""
    raw = name.replace("\\", "/")
    rel = posixpath.normpath(raw)
    if (raw.startswith("/") or re.match(r"^[A-Za-z]:", raw) or rel in (".", "")
            or rel == ".." or rel.startswith("../") or "/../" in f"/{rel}/"):
        return ""
    return rel


Entry = tuple[str, int, object]


def _zip_entries(data: bytes) -> list[Entry]:
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError(f"the package has more than {MAX_MEMBERS} entries: refused")
    entries: list[Entry] = []
    for info in infos:
        rel = safe_rel(info.filename)
        if not rel:
            raise ValueError(f"the package has an unsafe path: {info.filename!r}")
        # A zip carries the Unix mode in the high bits: zipfile would write a link entry as a file
        # holding the target's name, but the archive still SAYS link, and that is not a loader.
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"the package has a link: {info.filename!r}")
        if info.is_dir():
            entries.append((rel, -1, None))
        else:
            entries.append((rel, info.file_size, (lambda i=info: z.open(i))))
    return entries


def _tar_entries(tar: tarfile.TarFile) -> list[Entry]:
    members = tar.getmembers()
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"the package has more than {MAX_MEMBERS} entries: refused")
    entries: list[Entry] = []
    for member in members:
        rel = safe_rel(member.name)
        if not rel:
            raise ValueError(f"the package has an unsafe path: {member.name!r}")
        # Links (soft and hard) and devices: a link inside the package is how an archive writes
        # outside the folder it is unpacked into.
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"the package has something that is not a file or folder: {member.name!r}")
        if member.isdir():
            entries.append((rel, -1, None))
        else:
            entries.append((rel, member.size, (lambda m=member: tar.extractfile(m))))
    return entries


def _open_tar(data: bytes) -> tarfile.TarFile | None:
    try:
        # It stays open for the readers plan() hands out; it is in memory, there is nothing to leak.
        return tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        return None


def plan(data: bytes, name: str) -> list[Entry]:
    """Every entry of the package as (relative path, -1 for a folder or the size, reader).

    All the refusals happen HERE, before anything is written: a package with one bad entry
    installs nothing at all. Not an archive = a single file (a loader that is one DLL), named
    after the link.
    """
    if zipfile.is_zipfile(io.BytesIO(data)):
        entries = _zip_entries(data)
    else:
        tar = _open_tar(data)
        if tar is None:
            if not FILE_NAME.fullmatch(name):
                raise ValueError("the link is neither a zip/tar archive nor a plain file name")
            return [(name, len(data), (lambda: io.BytesIO(data)))]
        entries = _tar_entries(tar)
    if sum(size for _, size, _ in entries if size > 0) > MAX_UNPACKED:
        raise ValueError(f"the package unpacks to more than {MAX_UNPACKED // (1024 * 1024)} MB: refused")
    return entries


def _write_entry(dest: str, reader, size: int) -> None:
    staged = dest + ".gamepanel-new"
    written = 0
    with contextlib.closing(reader()) as src, open(staged, "wb") as out:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            written += len(block)
            # The declared size is what the cap was computed from: more than that is a lying archive.
            if written > size:
                out.close()
                os.remove(staged)
                raise ValueError(f"{dest}: more data than the package declared")
            out.write(block)
    # Over it with rename: a library the running game has mapped must not be written in place.
    os.replace(staged, dest)


def unpack(game_dir: str, loader_rel: str, entries, previous: set[str], files: list[str],
           folders: list[str]) -> None:
    """Write the package under the loader folder, appending to `files`/`folders` what it CREATED.

    The lists are the caller's so that a failure halfway still leaves them filled: the marker is
    written with whatever got in, and uninstall can take it out again.
    """
    base = _makedirs(game_dir, loader_rel)
    clashes = [rel for rel, size, _ in entries
               if size >= 0 and os.path.lexists(os.path.join(base, rel)) and rel not in previous]
    if clashes:
        shown = ", ".join(clashes[:5]) + (" ..." if len(clashes) > 5 else "")
        raise ValueError(f"the package would overwrite {len(clashes)} file(s) it did not create ({shown}): "
                         "the panel could not give them back on uninstall, so nothing was installed")
    for rel, size, reader in entries:
        parts = rel.split("/")
        # Every folder on the way, recorded only when THIS install created it.
        for depth in range(1, len(parts) if size >= 0 else len(parts) + 1):
            sub = "/".join(parts[:depth])
            path = confined(base, sub)
            if not os.path.isdir(path):
                if os.path.lexists(path):
                    raise ValueError(f"{sub} exists and is not a folder")
                os.mkdir(path)
                folders.append(sub)
        if size < 0:
            continue
        dest = os.path.join(confined(base, posixpath.dirname(rel)), parts[-1])
        if os.path.islink(dest) or os.path.isdir(dest):
            raise ValueError(f"{rel} exists as a link or folder")
        _write_entry(dest, reader, size)
        files.append(rel)


# ------------------------------------------------------------------ Wine (helper mode only)

def _groups(value: str) -> list[str]:
    return [g.strip() for g in value.split(";") if g.strip()]


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _read_overrides(env_path: str) -> str:
    for line in _read_text(env_path).splitlines():
        if line.startswith("WINE_DLL_OVERRIDES="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def with_entries(value: str, entries: list[str]) -> str:
    """WINEDLLOVERRIDES with ours, replacing only the same DLLs: the rest is what the game decided."""
    ours = {e.split("=", 1)[0].lower() for e in entries}
    return ";".join([g for g in _groups(value) if g.split("=", 1)[0].lower() not in ours] + list(entries))


def without_entries(value: str, entries: list[str], replaced: list[str]) -> str:
    """Ours out and what ours had replaced back: the game's `mscoree=` must not vanish with the loader."""
    ours = set(entries)
    back = {e.split("=", 1)[0].lower() for e in replaced}
    kept = [g for g in _groups(value) if g not in ours and g.split("=", 1)[0].lower() not in back]
    return ";".join(kept + list(replaced))


def set_wine(entries: list[str], enabled: bool, env_path: str = RUNTIME_ENV, replaced: list[str] | None = None,
             ) -> list[str]:
    """Add (or take out) our entries in steam's overlay. Adding returns the game's entries it replaced."""
    base = _read_overrides(env_path)
    current = overlay_get(OVERLAY_RUNTIME, "WINE_DLL_OVERRIDES")
    current = base if current is None else current
    ours = {e.split("=", 1)[0].lower() for e in entries}
    if enabled:
        replaced = [g for g in _groups(current) if g.split("=", 1)[0].lower() in ours and g not in entries]
        value = with_entries(current, entries)
    else:
        value = without_entries(current, entries, replaced or [])
    # No line at all when the value is the base one (order aside: Wine does not care about it):
    # /etc/game-runtime.env is in charge again, exactly as before the loader.
    same = sorted(_groups(value)) == sorted(_groups(base))
    overlay_set(OVERLAY_RUNTIME, "WINE_DLL_OVERRIDES", None if same else value)
    return replaced or []


def apply_env(game_dir: str, setup: dict, applied: dict, env_path: str = RUNTIME_ENV) -> None:
    """Bring the overlay to what THIS setup says, undoing first what `applied` (the last install) set.

    A reinstall after the setup changed must not stack the old entries on the new ones, and must
    not record ours as "the game's" (which uninstall would then put back). `applied` is updated
    step by step, so a failure halfway still leaves the marker telling the truth.
    """
    if applied.get("wine"):
        set_wine(list(applied["wine"]), False, env_path, list(applied.get("wine_replaced", [])))
        applied.update(wine=[], wine_replaced=[])
    if applied.get("preload"):
        if overlay_get(OVERLAY_SERVICE, "LD_PRELOAD") == applied["preload"]:
            overlay_set(OVERLAY_SERVICE, "LD_PRELOAD", None)
        applied["preload"] = ""
    if setup["preload"]:
        preload = confined(game_dir, setup["preload"])
        if not os.path.isfile(preload):
            raise ValueError(f"LD_PRELOAD {setup['preload']} is not a file after the install")
        overlay_set(OVERLAY_SERVICE, "LD_PRELOAD", preload)
        applied["preload"] = preload
    if setup["wine"]:
        applied["wine_replaced"] = set_wine(setup["wine"], True, env_path)
        applied["wine"] = list(setup["wine"])


def env_problem(setup: dict, unit: str, overlay: bool, env_path: str = RUNTIME_ENV) -> str:
    """Why the setup's environment could not be applied ('' = it can, or there is none)."""
    if not (setup["wine"] or setup["preload"]):
        return ""
    if not overlay:
        return "environment settings need the CT in helper mode (gamepanel login): nothing was installed"
    if setup["wine"]:
        if not os.path.exists(env_path):
            return "this server does not run through Wine/Proton: the Wine overrides cannot apply"
        problem = overlay_wine_problem()
        if problem:
            return problem
    if setup["preload"]:
        return overlay_unit_problem(unit)
    return ""


# ------------------------------------------------------------------ actions

def _read_json(path: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def _mark_path(game_dir: str, setup: dict) -> str:
    return os.path.join(confined(game_dir, setup["loader_dir"]), MARK)


def install_loader(game_dir: str, setup: dict, unit: str = "", fetcher=fetch, scan=None,
                   overlay: bool = False, env_path: str = RUNTIME_ENV) -> dict:
    if not setup["loader_url"]:
        raise ValueError("the setup has no loader link")
    problem = env_problem(setup, unit, overlay, env_path)
    if problem:
        raise ValueError(problem)
    if scan is None:
        raise ValueError("installing without the antivirus check is not a panel path")
    url = setup["loader_url"]
    name = download_name(url)
    print(f"downloading {url}")
    data = fetcher(url)
    digest = hashlib.sha256(data).hexdigest()
    print(f"{len(data)} bytes, sha256 {digest}")
    scan([(name or "loader", data)])
    entries = plan(data, name)
    mark_path = _mark_path(game_dir, setup)
    previous = _read_json(mark_path)
    old_files = set(previous.get("files", []))
    files: list[str] = []
    folders: list[str] = []
    applied = {key: previous.get(key, default) for key, default in
               (("wine", []), ("wine_replaced", []), ("preload", ""))}
    complete = False
    try:
        unpack(game_dir, setup["loader_dir"], entries, old_files, files, folders)
        _makedirs(game_dir, setup["mods_dir"])
        # Only when there is something to set or to undo: a legacy-mode CT has no overlay at all.
        if setup["wine"] or setup["preload"] or applied["wine"] or applied["preload"]:
            apply_env(game_dir, setup, applied, env_path)
        complete = True
    finally:
        # Even (above all) when it failed halfway: what got in is recorded, so uninstall can take
        # it out. Nothing written and nothing recorded before = no marker at all.
        if files or folders or previous:
            mark = {
                "url": url, "sha256": digest, "complete": complete,
                # A reinstall keeps what the first one created: it is still ours to remove.
                "files": sorted(old_files | set(files)),
                "dirs": sorted(set(previous.get("dirs", [])) | set(folders)),
                **applied,
            }
            with open(mark_path, "w", encoding="utf-8") as f:
                json.dump(mark, f)
    print(f"loader in {confined(game_dir, setup['loader_dir'])}: {len(files)} file(s), {len(folders)} new folder(s)")
    return {"installed": True, "files": len(files)}


def uninstall_loader(game_dir: str, setup: dict, overlay: bool = False, env_path: str = RUNTIME_ENV) -> dict:
    """Remove what the install CREATED (files, then its folders) and the environment it set."""
    mark_path = _mark_path(game_dir, setup)
    mark = _read_json(mark_path)
    if not mark:
        return {"uninstalled": False, "removed": 0}
    base = confined(game_dir, setup["loader_dir"])
    removed = 0
    for rel in mark.get("files", []):
        if not safe_rel(rel):
            continue
        path = confined(base, posixpath.dirname(rel))
        path = os.path.join(path, posixpath.basename(rel))
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
            removed += 1
    # Deepest first; a folder this install created goes with what is inside (the mods that live
    # in a loader folder go with the loader - the screen asks first).
    for rel in sorted(mark.get("dirs", []), key=lambda r: r.count("/"), reverse=True):
        if not safe_rel(rel):
            continue
        path = os.path.join(confined(base, posixpath.dirname(rel)), posixpath.basename(rel))
        if os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            continue
        removed += 1
    if overlay:
        if mark.get("preload") and overlay_get(OVERLAY_SERVICE, "LD_PRELOAD") == mark["preload"]:
            overlay_set(OVERLAY_SERVICE, "LD_PRELOAD", None)
        if mark.get("wine") and os.path.exists(env_path):
            set_wine(list(mark["wine"]), False, env_path, list(mark.get("wine_replaced", [])))
    os.remove(mark_path)
    print(f"loader removed from {base}: {removed} item(s)")
    return {"uninstalled": True, "removed": removed}


def list_mods(game_dir: str, setup: dict) -> list[dict]:
    mods_dir = confined(game_dir, setup["mods_dir"])
    if not os.path.isdir(mods_dir):
        return []
    mods = []
    for entry in sorted(os.listdir(mods_dir)):
        path = os.path.join(mods_dir, entry)
        if entry.startswith(".") or os.path.islink(path) or not valid_name(entry):
            continue
        if os.path.isdir(path):
            mods.append({"name": entry, "dir": True, "size": 0})
        elif accepts(setup, entry):
            mods.append({"name": entry, "dir": False, "size": os.path.getsize(path)})
    return mods


def place(game_dir: str, setup: dict, incoming: str) -> dict:
    """Move the checked upload from the holding folder into the mods folder (and delete the holding folder)."""
    if not INCOMING.fullmatch(incoming):
        raise ValueError(f"invalid holding folder: {incoming}")
    try:
        mods_dir = _makedirs(game_dir, setup["mods_dir"])
        placed = []
        for name in sorted(os.listdir(incoming)):
            src = os.path.join(incoming, name)
            if os.path.islink(src) or not os.path.isfile(src) or not accepts(setup, name):
                raise ValueError(f"{name}: not a file this setup accepts")
            dest = os.path.join(mods_dir, name)
            if os.path.islink(dest) or os.path.isdir(dest):
                raise ValueError(f"{dest} exists as a link or folder")
            if os.path.exists(dest):
                # The same rule as the upload on the Files screen: the old one is kept as a .bak.
                shutil.copy2(dest, f"{dest}.{int(os.path.getmtime(dest))}.bak")
            shutil.copyfile(src, dest + ".gamepanel-new")
            os.replace(dest + ".gamepanel-new", dest)
            placed.append(name)
            print(f"installed: {dest} ({os.path.getsize(dest)} bytes)")
    finally:
        shutil.rmtree(incoming, ignore_errors=True)
    return {"placed": placed}


def remove_mods(game_dir: str, setup: dict, pairs: list[str]) -> dict:
    """Remove by NAME: `f NAME` for a file the setup accepts, `d NAME` for a folder mod."""
    if len(pairs) % 2 or not pairs:
        raise ValueError("nothing to remove")
    mods_dir = confined(game_dir, setup["mods_dir"])
    removed = []
    for kind, name in zip(pairs[::2], pairs[1::2], strict=True):
        if kind not in ("f", "d") or not valid_name(name) or (kind == "f" and not accepts(setup, name)):
            raise ValueError(f"invalid name: {name!r}")
        path = os.path.join(mods_dir, name)
        if os.path.islink(path) or (kind == "f" and os.path.isfile(path)):
            os.remove(path)
        elif kind == "d" and os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            raise ValueError(f"{name}: not what the screen listed (file vs folder); nothing was deleted")
        else:
            print(f"not there (skipped): {path}")
            continue
        removed.append(name)
        print(f"removed: {path}")
    return {"removed": removed}


def status(game_dir: str, setup: dict, unit: str = "", overlay: bool = False, env_path: str = RUNTIME_ENV) -> dict:
    mark = _read_json(_mark_path(game_dir, setup))
    enabled = bool(mark)
    if mark and overlay and mark.get("preload"):
        enabled = enabled and overlay_get(OVERLAY_SERVICE, "LD_PRELOAD") == mark["preload"]
    return {
        "loader_installed": bool(mark), "loader_url": mark.get("url", ""), "loader_sha256": mark.get("sha256", ""),
        # A marker from an install that stopped halfway: what got in is recorded, the rest is not there.
        "loader_complete": bool(mark.get("complete")),
        "loader_files": len(mark.get("files", [])),
        "enabled": enabled,
        "overlay_problem": env_problem(setup, unit, True, env_path) if overlay else "",
        "legacy_env": bool(setup["wine"] or setup["preload"]) and not overlay,
        "mods_dir": confined(game_dir, setup["mods_dir"]),
        "mods": list_mods(game_dir, setup),
    }


def _chown(game_dir: str, setup: dict) -> None:
    """Legacy mode runs as root: what it wrote must still be the game's (steam) to read and update.

    Only what the marker says this install created, plus the mods folder - never the whole game
    folder, which with an empty loader folder would be gigabytes walked for nothing.
    """
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    base = confined(game_dir, setup["loader_dir"])
    mark = _read_json(os.path.join(base, MARK))
    paths = [os.path.join(base, r) for r in (*mark.get("files", []), *mark.get("dirs", [])) if safe_rel(r)]
    paths.append(os.path.join(base, MARK))
    for root, dirs, files in os.walk(confined(game_dir, setup["mods_dir"])):
        paths.extend([root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]])
    for path in paths:
        with contextlib.suppress(OSError):
            os.chown(path, pw.pw_uid, pw.pw_gid, follow_symlinks=False)


def parse_options(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    if argv[:1] == ["--overlay"]:
        options["overlay"], argv = "1", argv[1:]
    for flag in ("--scan", "--unit", "--setup"):
        if argv[:1] == [flag]:
            options[flag[2:]], argv = argv[1], argv[2:]
    return options, argv


def run(action: str, game_dir: str, setup: dict, rest: list[str], options: dict[str, str]) -> dict:
    overlay, unit, script = "overlay" in options, options.get("unit", ""), options.get("scan", "")
    if action == "status":
        return status(game_dir, setup, unit, overlay)
    if action == "loader-install":
        return install_loader(game_dir, setup, unit, scan=scanner(script) if script else None, overlay=overlay)
    if action == "loader-uninstall":
        return uninstall_loader(game_dir, setup, overlay)
    if action == "mod-place":
        return place(game_dir, setup, rest[0])
    if action == "mod-remove":
        return remove_mods(game_dir, setup, rest)
    raise ValueError(f"unknown action: {action}")


def main(argv: list[str]) -> int:
    options, argv = parse_options(argv)
    try:
        action, game_dir, *rest = argv
        setup = load_setup(options.get("setup", ""))
        result = run(action, game_dir, setup, rest, options)
        if action != "status" and getattr(os, "geteuid", lambda: -1)() == 0:
            _chown(game_dir, setup)
    except (ValueError, KeyError, OSError, IndexError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
