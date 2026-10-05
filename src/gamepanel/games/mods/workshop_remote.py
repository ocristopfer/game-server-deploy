"""Workshop mods through the game CONFIG - runs INSIDE the game CT.

Same design as the other remote installers: the panel reads this text and runs it in the
container with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel`.

Nobody downloads anything here: the downloader is the game server ITSELF, on startup, from the
list of IDs in its config. The script only reads and writes that list, in each game's format - and
each one was proven on a real server (Docker, 2026-10-05), with the mod downloaded and loaded in the log:

- **dst** (Don't Starve Together): `ServerModSetup("<id>")` in the game folder's
  `mods/dedicated_server_mods_setup.lua` (that is what tells it to DOWNLOAD) and
  `["workshop-<id>"] = { enabled = true }` in each shard's `modoverrides.lua` (that is what tells it
  to LOAD). Without the first the mod never arrives; without the second it arrives and stays off. A
  game update through Steam restores the setup to the original: the status flags it
  (`setup_missing`) and saving again rewrites it.
- **zomboid** (Project Zomboid): `WorkshopItems=` (Workshop IDs, what gets downloaded) and `Mods=`
  (the mod IDs from `mod.info`, what gets loaded) in `<servername>.ini`. They are different lists:
  one Workshop item may bring several mods, and enabling all of them is exactly what breaks a server.
- **unturned**: `File_IDs` in `Servers/<name>/WorkshopDownloadConfig.json`. The server also
  downloads the dependencies (a map and its assets).
- **reforger** (Arma Reforger): `game.mods` in the `-config` JSON, with the GUID from Bohemia's
  workshop (it is not Steam) and a name.
- **ark** (ARK: Survival Ascended): the server downloads from CurseForge by itself, but ONLY
  through `-mods=<id,...>` on its command line - `ActiveMods=` in GameUserSettings.ini is ignored
  ("LoadGameMods with 0 mods", measured), and a mod folder left on disk does not load either. The
  list goes into a systemd drop-in that repeats the unit's ExecStart with `-mods=` appended, so it
  needs root. The drop-in records the command it was built from: a redeploy that changes the
  unit's ExecStart would otherwise be masked by the stale copy, and the status flags it
  (`base_changed`).
- **conan** (Conan Exiles Enhanced): the exception - the server does NOT download mods. The CT
  does, with SteamCMD (anonymous login works for app 440900), into a holding folder the panel's
  antivirus checks before anything reaches the game (`fetch`, then the scan step, then `set`).
  `set` puts the files in `ConanSandbox/Mods` under their ORIGINAL names (a renamed pak fails to
  load in silence), writes `modlist.txt` as `*Name.pak` lines in list order and turns on
  `ServerModList=modlist.txt` in ServerSettings.ini. Measured: a "[Legacy]" (UE4) item is ignored
  without a word, and a mod "too old for this game version" makes the server EXIT at boot - the
  status reads those refusals from the game log (`rejected`).

What applies to all of them, each with its reason:
- **What the person already configured stays.** Each mod's options in `modoverrides.lua` (the
  mod's whole block, copied as text), the other JSON keys and the other .ini lines: the panel only
  replaces the LIST. A mod that left the list loses its block, and that is what "remove" means.
- **Atomic write with a copy of the previous version** (`<file>.gamepanel.bak`): a half-written
  file is a server that does not start, and the copy is the manual way back.
- **The owner stays the file's owner** (or the service `User=`, for a new file): the server runs
  as steam, and a root-owned file it cannot rewrite blocks the next startup.
- **Where the config lives comes from the service ExecStart** (`-servername`, `-cachedir`,
  `-config`, `+InternetServer/`), and not from a guess: it is the same command the game receives.
- **Nothing goes through the antivirus before getting in** (except conan), because the
  downloader is the game, on startup. The panel's "Check installed mods" runs ClamAV over the
  folder where each game keeps them.

Actions (argv): --unit SERVICE FORMAT status|fetch|set GAME_FOLDER [ITEMS...] [--mods LIST]
[--staging DIR]. ITEM is the ID (Steam, CurseForge) or `GUID=Name` (reforger). `fetch` exists
only for conan. Ends with ONE JSON line.
"""
from __future__ import annotations

import contextlib
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

FORMATS = ("dst", "zomboid", "unturned", "reforger", "ark", "conan")
OWNER = "steam"
BACKUP_SUFFIX = ".gamepanel.bak"

STEAM_ID = re.compile(r"^\d{6,20}$", re.ASCII)
GUID = re.compile(r"^[0-9A-F]{16}$", re.ASCII)
# The Reforger mod name goes into the JSON and into the server log: short, printable text.
REFORGER_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,80}$")
# Zomboid Mods=: mod IDs separated by ';'. The backslash is the prefix that Build 42 accepts in
# some guides (`\BB_CommonSense`); it also loads without it (measured).
ZOMBOID_MODS = re.compile(r"^[A-Za-z0-9_.\-\\ ;]{0,4000}$", re.ASCII)

DST_SETUP = "mods/dedicated_server_mods_setup.lua"
DST_SETUP_LINE = re.compile(r'^\s*ServerModSetup\(\s*"(?:workshop-)?(\d+)"\s*\)', re.MULTILINE)
DST_KEY = re.compile(r'\[\s*"([^"]+)"\s*\]\s*=\s*\{')


# --- service and owner ------------------------------------------------------------------------

def unit_text(unit: str) -> str:
    """The unit text (with drop-ins), or empty if systemctl does not answer."""
    if not unit:
        return ""
    # The unit name comes from the panel (the server's own service), and goes as an argument, no shell.
    try:
        proc = subprocess.run(["systemctl", "cat", unit], capture_output=True, text=True,  # noqa: S603, S607
                              timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout or ""


def exec_args(text: str) -> list[str]:
    """The words of the LAST ExecStart (a drop-in that replaces it comes after the original)."""
    lines = [ln.split("=", 1)[1] for ln in text.splitlines() if ln.strip().startswith("ExecStart=")]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return []
    try:
        return shlex.split(lines[-1].lstrip("@-:+!"))
    except ValueError:
        return lines[-1].split()


def unit_value(text: str, key: str) -> str:
    found = [ln.split("=", 1)[1].strip() for ln in text.splitlines() if ln.strip().startswith(key + "=")]
    return found[-1] if found else ""


def arg_after(args: list[str], flag: str) -> str:
    """The value of `-flag value` or `-flag=value`, ignoring case (Zomboid accepts both)."""
    low = flag.lower()
    for i, a in enumerate(args):
        if a.lower() == low and i + 1 < len(args):
            return args[i + 1]
        if a.lower().startswith(low + "="):
            return a.split("=", 1)[1]
    return ""


def home_of(user: str) -> str:
    try:
        import pwd
        return pwd.getpwnam(user).pw_dir
    except (ImportError, KeyError):
        return f"/home/{user}"


def _ids_of(user: str) -> tuple[int, int] | None:
    try:
        import pwd
        pw = pwd.getpwnam(user)
    except (ImportError, KeyError):
        return None
    return pw.pw_uid, pw.pw_gid


def _chown(path: str, owner: tuple[int, int] | None) -> None:
    # Without chown (the Windows the tests run on) or without permission, the file keeps whatever owner it has.
    chown = getattr(os, "chown", None)
    if owner and chown:
        with contextlib.suppress(OSError):
            chown(path, *owner)


def write_atomic(path: str, text: str, user: str) -> None:
    """Write alongside and move over, keeping the previous copy and the previous owner."""
    owner = None
    if os.path.exists(path):
        st = os.stat(path)
        owner = (st.st_uid, st.st_gid)
        shutil.copy2(path, path + BACKUP_SUFFIX)
        _chown(path + BACKUP_SUFFIX, owner)
    else:
        owner = _ids_of(user)
        os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".gamepanel-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        _chown(tmp, owner)
        # World-readable on purpose: the game (steam) reads what root wrote in legacy mode.
        os.chmod(tmp, 0o644)  # NOSONAR - a game config/mod file, readable by the game
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_text(path: str, raw: bool = False) -> str:
    """The file's text, or empty. `raw` keeps the line endings as they are on disk."""
    try:
        with open(path, encoding="utf-8", errors="replace", newline="" if raw else None) as f:
            return f.read()
    except OSError:
        return ""


# --- Don't Starve Together --------------------------------------------------------------------

LUA_LONG = re.compile(r"(--)?\[(=*)\[")


def _lua_skip(text: str, i: int) -> int:
    """If a comment or a string starts at `i`, the position right after it; otherwise `i` itself.

    A brace inside a string (`scale = "1}"`) or a comment does not count: that is how each mod's
    options block comes out whole, and not cut at the first `}` that shows up.
    """
    n = len(text)
    long = LUA_LONG.match(text, i)
    if long:
        close = "]" + long.group(2) + "]"
        j = text.find(close, long.end())
        return n if j < 0 else j + len(close)
    if text.startswith("--", i):
        j = text.find("\n", i)
        return n if j < 0 else j + 1
    if text[i] in "\"'":
        j = i + 1
        while j < n and text[j] != text[i]:
            j += 2 if text[j] == "\\" else 1
        return j + 1
    return i


def _lua_block_end(text: str, start: int) -> int:
    """Position right after the `}` that closes the `{` at `start`."""
    depth, i = 0, start
    while i < len(text):
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("modoverrides.lua com chaves sem fechar")


def lua_entries(text: str) -> dict[str, str]:
    """`["key"] = { ... }` at the top level of the table, as TEXT (the options go whole)."""
    i, start = 0, -1
    while i < len(text):
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "{":
            start = i
            break
        i += 1
    if start < 0:
        return {}
    end = _lua_block_end(text, start)
    entries: dict[str, str] = {}
    i = start + 1
    while i < end - 1:
        j = _lua_skip(text, i)
        if j != i:
            i = j
            continue
        m = DST_KEY.match(text, i)
        if m:
            close = _lua_block_end(text, m.end() - 1)
            entries[m.group(1)] = text[m.end() - 1:close]
            i = close
            continue
        i += 1
    return entries


def render_overrides(entries: dict[str, str]) -> str:
    lines = ["return {"]
    lines += [f'  ["{key}"] = {block},' for key, block in entries.items()]
    lines.append("}")
    return "\n".join(lines) + "\n"


def dst_shards(ctx: dict) -> list[str]:
    """The shard folders (the ones with server.ini) of this server's cluster.

    The cluster comes from the game command (-persistent_storage_root, -conf_dir, -cluster, with
    the DST defaults): cluster.ini only exists after someone configures the cluster, and the first
    start only creates <shard>/server.ini. The scan is the fallback for whoever passes none of that.
    """
    args = ctx["args"]
    root = arg_after(args, "-persistent_storage_root") or os.path.join(ctx["home"], ".klei")
    cluster = os.path.join(root, arg_after(args, "-conf_dir") or "DoNotStarveTogether",
                           arg_after(args, "-cluster") or "Cluster_1")
    found = sorted(os.path.dirname(s) for s in glob.glob(os.path.join(cluster, "*", "server.ini")))
    if found:
        return found
    # Fixed depth, and not `**`: in the game folder that would be gigabytes of files every time the
    # screen opens. The Pterodactyl egg uses /opt/game/DoNotStarveTogether/config/server.
    for base in (os.path.join(ctx["home"], ".klei"), ctx["game_dir"]):
        for depth in range(1, 5):
            for ini in sorted(glob.glob(os.path.join(base, *["*"] * depth, "cluster.ini"))):
                shards = glob.glob(os.path.join(os.path.dirname(ini), "*", "server.ini"))
                found += sorted(os.path.dirname(s) for s in shards)
    return list(dict.fromkeys(found))


def dst_status(ctx: dict) -> dict:
    shards = dst_shards(ctx)
    setup = set(DST_SETUP_LINE.findall(read_text(os.path.join(ctx["game_dir"], DST_SETUP))))
    ids: list[str] = []
    for shard in shards:
        for key in lua_entries(read_text(os.path.join(shard, "modoverrides.lua"))):
            if key.startswith("workshop-") and key[9:] not in ids:
                ids.append(key[9:])
    # Current DST downloads to ugc_mods/<cluster>/<shard>/content/322330/<id>; the old one, mods/workshop-<id>.
    installed = [i for i in ids
                 if glob.glob(os.path.join(ctx["game_dir"], "ugc_mods", "*", "*", "content", "*", i))
                 or os.path.isdir(os.path.join(ctx["game_dir"], "mods", f"workshop-{i}"))]
    return {"config": ", ".join(shards), "ids": ids, "installed": installed,
            "setup_missing": [i for i in ids if i not in setup],
            "problem": "" if shards else "no_cluster"}


def dst_set(ctx: dict, items: list[str]) -> dict:
    shards = dst_shards(ctx)
    if not shards:
        raise ValueError("nenhum cluster do DST com server.ini: suba o servidor uma vez antes")
    setup_path = os.path.join(ctx["game_dir"], DST_SETUP)
    old = read_text(setup_path)
    # Remove the previous ServerModSetup lines and put in the ones from the list; comments and the rest stay.
    kept = [ln for ln in old.splitlines() if not DST_SETUP_LINE.match(ln)]
    new_setup = "\n".join([*kept, *[f'ServerModSetup("{i}")' for i in items]]) + "\n"
    write_atomic(setup_path, new_setup, ctx["user"])
    for shard in shards:
        path = os.path.join(shard, "modoverrides.lua")
        current = lua_entries(read_text(path))
        entries = {k: v for k, v in current.items() if not k.startswith("workshop-")}
        for i in items:
            entries[f"workshop-{i}"] = current.get(f"workshop-{i}", "{ enabled = true }")
        write_atomic(path, render_overrides(entries), ctx["user"])
    return {"ids": items, "shards": shards}


# --- Project Zomboid --------------------------------------------------------------------------

def zomboid_ini(ctx: dict) -> str:
    name = arg_after(ctx["args"], "-servername") or "servertest"
    base = arg_after(ctx["args"], "-cachedir") or os.path.join(ctx["home"], "Zomboid")
    return os.path.join(base, "Server", f"{name}.ini")


def ini_value(text: str, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def ini_set(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


def zomboid_mod_ids(game_dir: str, workshop_id: str) -> list[str]:
    """The `id=` of the mod.info files the Workshop item brought: what may go into `Mods=`."""
    root = os.path.join(game_dir, "steamapps", "workshop", "content", "108600", workshop_id)
    found: list[str] = []
    for info in sorted(glob.glob(os.path.join(root, "mods", "*", "**", "mod.info"), recursive=True)):
        mod_id = ini_value(read_text(info), "id")
        if mod_id and mod_id not in found:
            found.append(mod_id)
    return found


def zomboid_status(ctx: dict) -> dict:
    path = zomboid_ini(ctx)
    text = read_text(path)
    ids = [i for i in re.split(r"[;,\s]+", ini_value(text, "WorkshopItems")) if i]
    available = {i: zomboid_mod_ids(ctx["game_dir"], i) for i in ids}
    return {"config": path, "ids": ids, "mods": ini_value(text, "Mods"),
            "installed": [i for i, mods in available.items() if mods], "available": available,
            "problem": "" if text else "no_config"}


def zomboid_set(ctx: dict, items: list[str], mods: str) -> dict:
    path = zomboid_ini(ctx)
    text = read_text(path)
    if not text:
        raise ValueError(f"{path} nao existe: suba o servidor uma vez antes")
    text = ini_set(text, "WorkshopItems", ";".join(items))
    text = ini_set(text, "Mods", mods)
    write_atomic(path, text, ctx["user"])
    return {"ids": items, "mods": mods, "config": path}


# --- Unturned ---------------------------------------------------------------------------------

def unturned_dir(ctx: dict) -> str:
    """The server folder: the one from `+InternetServer/<name>`, or the only one that exists."""
    for a in ctx["args"]:
        m = re.match(r"^\+(?:Internet|Lan)Server/(.+)$", a, re.IGNORECASE)
        if m:
            return os.path.join(ctx["game_dir"], "Servers", m.group(1))
    configs = glob.glob(os.path.join(ctx["game_dir"], "Servers", "*", "Config.txt"))
    existing = sorted(os.path.dirname(c) for c in configs)
    return existing[0] if len(existing) == 1 else ""


def unturned_status(ctx: dict) -> dict:
    folder = unturned_dir(ctx)
    if not folder:
        return {"config": "", "ids": [], "installed": [], "problem": "no_server_name"}
    path = os.path.join(folder, "WorkshopDownloadConfig.json")
    try:
        ids = [str(i) for i in json.loads(read_text(path) or "{}").get("File_IDs", [])]
    except ValueError:
        return {"config": path, "ids": [], "installed": [], "problem": "bad_json"}
    content = os.path.join(folder, "Workshop", "Steam", "content", "304930")
    return {"config": path, "ids": ids, "installed": [i for i in ids if os.path.isdir(os.path.join(content, i))],
            "problem": ""}


def unturned_set(ctx: dict, items: list[str]) -> dict:
    folder = unturned_dir(ctx)
    if not folder:
        raise ValueError("sem o nome do servidor: ponha +InternetServer/<nome> no comando do jogo")
    path = os.path.join(folder, "WorkshopDownloadConfig.json")
    data = json.loads(read_text(path) or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} nao e um objeto JSON")
    data["File_IDs"] = [int(i) for i in items]
    write_atomic(path, json.dumps(data, indent=2) + "\n", ctx["user"])
    return {"ids": items, "config": path}


# --- Arma Reforger ----------------------------------------------------------------------------

def reforger_config(ctx: dict) -> str:
    path = arg_after(ctx["args"], "-config")
    if path and not os.path.isabs(path):
        path = os.path.join(ctx["workdir"] or ctx["game_dir"], path)
    return path


def reforger_status(ctx: dict) -> dict:
    path = reforger_config(ctx)
    if not path:
        return {"config": "", "ids": [], "installed": [], "problem": "no_config_arg"}
    try:
        data = json.loads(read_text(path) or "null")
    except ValueError:
        return {"config": path, "ids": [], "installed": [], "problem": "bad_json"}
    if not isinstance(data, dict):
        return {"config": path, "ids": [], "installed": [], "problem": "no_config"}
    mods = (data.get("game") or {}).get("mods") or []
    ids = [str(m.get("modId", "")).upper() for m in mods if isinstance(m, dict)]
    names = {str(m.get("modId", "")).upper(): str(m.get("name", "")) for m in mods if isinstance(m, dict)}
    profile = arg_after(ctx["args"], "-profile")
    addons = os.path.join(profile, "addons") if profile else ""
    installed = [i for i in ids if addons and glob.glob(os.path.join(addons, f"*_{i}"))]
    return {"config": path, "ids": ids, "names": names, "installed": installed, "problem": ""}


def reforger_set(ctx: dict, items: list[tuple[str, str]]) -> dict:
    path = reforger_config(ctx)
    if not path:
        raise ValueError("o servidor nao recebe -config no comando: sem ele nao ha onde por os mods")
    data = json.loads(read_text(path) or "null")
    if not isinstance(data, dict) or not isinstance(data.get("game"), dict):
        raise ValueError(f"{path} nao tem o objeto game: crie a config do servidor antes")
    # A pinned version and whatever else the person put in each mod stays; only the list changes.
    before = {str(m.get("modId", "")).upper(): m for m in data["game"].get("mods") or [] if isinstance(m, dict)}
    mods = []
    for guid, name in items:
        entry = dict(before.get(guid, {}))
        entry["modId"] = guid
        entry["name"] = name or entry.get("name") or guid
        mods.append(entry)
    data["game"]["mods"] = mods
    write_atomic(path, json.dumps(data, indent=2) + "\n", ctx["user"])
    return {"ids": [g for g, _ in items], "config": path}


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


# --- ARK: Survival Ascended -------------------------------------------------------------------

ARK_DROPIN = "gamepanel-mods.conf"
ARK_BASE_MARK = "# gamepanel-base: "
# CurseForge unpacks each mod into <Binaries/Win64>/ShooterGame/Mods/<game id>/<mod id>_<file id>.
ARK_MODS_DIR = "ShooterGame/Binaries/Win64/ShooterGame/Mods"


def unit_sections(text: str) -> list[str]:
    """`systemctl cat` prints each file under a `# /path` header: the unit first, then its drop-ins."""
    sections: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith("# /"):
            sections.append([])
        elif sections:
            sections[-1].append(line)
    return ["\n".join(s) for s in sections]


def ark_base(ctx: dict) -> str:
    """The unit file's OWN ExecStart, raw (quotes included), without any `-mods=`.

    Read from the unit and never from a drop-in: ours would otherwise feed its own output back
    in, and a redeploy's new command would never be seen.
    """
    sections = unit_sections(ctx["unit_text"])
    lines = [ln.split("=", 1)[1].strip() for ln in (sections[0] if sections else "").splitlines()
             if ln.strip().startswith("ExecStart=")]
    lines = [ln for ln in lines if ln]
    # Word by word and not a regex: the unit may repeat -mods= from a hand edit, and only the
    # words change - the quoting of the map argument stays exactly as written.
    return " ".join(w for w in lines[-1].split(" ") if not w.startswith("-mods=")) if lines else ""


def ark_dropin(ctx: dict) -> str:
    return os.path.join("/etc/systemd/system", f"{ctx['unit']}.d", ARK_DROPIN)


ARK_ARGS = "GAMEPANEL_EXTRA_ARGS"
WIN_RUN_PREFIX = "/usr/local/bin/win-run "


def ark_overlay_problem(ctx: dict) -> str:
    """Helper mode: why the list could not go through win-run's overlay ('' = it can).

    ExecStart cannot come from an EnvironmentFile, but the game already starts through win-run
    (an .exe under Proton), and win-run appends GAMEPANEL_EXTRA_ARGS from steam's runtime.env to
    the game's arguments - the same place the drop-in's -mods= ended up, at the end.
    """
    if os.path.lexists(ark_dropin(ctx)):
        return "root_dropin"
    base = ark_base(ctx)
    if not base:
        return "no_unit"
    if not base.startswith(WIN_RUN_PREFIX):
        return "no_win_run"
    return "no_overlay" if overlay_wine_problem() else ""


def ark_overlay_status(ctx: dict) -> dict:
    found = re.search(r"-mods=(\S+)", overlay_get(OVERLAY_RUNTIME, ARK_ARGS) or "")
    ids = [i for i in (found.group(1).split(",") if found else []) if i]
    mods_dir = os.path.join(ctx["game_dir"], ARK_MODS_DIR)
    installed = [i for i in ids if glob.glob(os.path.join(mods_dir, "*", f"{i}_*"))]
    return {"config": overlay_path(OVERLAY_RUNTIME), "ids": ids, "installed": installed, "base_changed": False,
            "problem": ark_overlay_problem(ctx)}


def ark_status(ctx: dict) -> dict:
    if ctx.get("overlay") and not os.path.lexists(ark_dropin(ctx)):
        return ark_overlay_status(ctx)
    path = ark_dropin(ctx)
    text = read_text(path)
    stored = next((ln[len(ARK_BASE_MARK):] for ln in text.splitlines() if ln.startswith(ARK_BASE_MARK)), "")
    found = re.search(r"-mods=(\S+)", text)
    ids = [i for i in (found.group(1).split(",") if found else []) if i]
    mods_dir = os.path.join(ctx["game_dir"], ARK_MODS_DIR)
    installed = [i for i in ids if glob.glob(os.path.join(mods_dir, "*", f"{i}_*"))]
    base = ark_base(ctx)
    problem = "" if base else "no_unit"
    # A list a root install left on a server that is now in helper mode: steam cannot change it.
    if not problem and ctx.get("overlay"):
        problem = "root_dropin"
    return {"config": path if text else "", "ids": ids, "installed": installed,
            "base_changed": bool(text) and stored != base,
            "problem": problem}


def ark_set(ctx: dict, items: list[str]) -> dict:
    if ctx.get("overlay"):
        problem = ark_overlay_problem(ctx)
        if problem:
            raise ValueError(f"a lista do ARK nao pode ser gravada sem root aqui ({problem}): {OVERLAY_HINT}")
        overlay_set(OVERLAY_RUNTIME, ARK_ARGS, f"-mods={','.join(items)}" if items else None)
        return {"ids": items, "config": overlay_path(OVERLAY_RUNTIME)}
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise ValueError("the ARK mod list is a systemd drop-in, and only root can write it")
    base = ark_base(ctx)
    if not base:
        raise ValueError(f"no ExecStart found in {ctx['unit']}")
    path = ark_dropin(ctx)
    if items:
        text = (f"# Written by the game panel: the mod list. Remove it to start the server without mods.\n"
                f"{ARK_BASE_MARK}{base}\n[Service]\nExecStart=\nExecStart={base} -mods={','.join(items)}\n")
        write_atomic(path, text, "root")
    elif os.path.exists(path):
        os.unlink(path)
    # Without daemon-reload systemd keeps starting the server with the previous command.
    subprocess.run(["systemctl", "daemon-reload"], check=False)  # noqa: S607
    return {"ids": items, "config": path}


# --- Conan Exiles Enhanced --------------------------------------------------------------------

CONAN_APP = "440900"
STEAMCMD = "/opt/steamcmd/steamcmd.sh"
CONAN_MODS = "ConanSandbox/Mods"
CONAN_SETTINGS = "ConanSandbox/Saved/Config/WindowsServer/ServerSettings.ini"
CONAN_LOG = "ConanSandbox/Saved/Logs/ConanSandbox.log"
CONAN_MARK = ".gamepanel-workshop.json"
# The pak and its UE5 IoStore companions; anything else in a Workshop item is not for the server.
CONAN_FILE = re.compile(r"^[A-Za-z0-9 ._()+-]{1,120}$", re.ASCII)
CONAN_EXTENSIONS = (".pak", ".utoc", ".ucas")
# Same prefix the panel's antivirus agrees to scan and delete (see antivirus.STAGING_PREFIX).
# /var/tmp and not /tmp: on Debian 13 /tmp is tmpfs (memory), and a mod can be hundreds of MB.
STAGING_PREFIX = "/var/tmp/gamepanel-incoming-"  # noqa: S108  # NOSONAR - created 0700 by the panel
CONAN_REJECTED = re.compile(r"Mod pak file: (\S+) failed check and will be excluded[^(\n]*\(Error: ([^)\n]*)")
SETTINGS_SECTION = "[ServerSettings]"
MODLIST_SETTING = "ServerModList=modlist.txt"


def _checked_staging(staging: str) -> str:
    if not staging.startswith(STAGING_PREFIX) or ".." in staging or not os.path.isdir(staging):
        raise ValueError(f"invalid holding folder: {staging!r}")
    return staging


def _conan_mark(ctx: dict) -> dict:
    try:
        data = json.loads(read_text(os.path.join(ctx["game_dir"], CONAN_MODS, CONAN_MARK)) or "{}")
    except ValueError:
        data = {}
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    return {"ids": [str(i) for i in data.get("ids", []) if str(i) in files], "files": files}


def _steamcmd(ctx: dict, items: list[str]) -> subprocess.CompletedProcess:
    """One SteamCMD run for every item, as steam (the panel may be root, in legacy mode)."""
    args = [STEAMCMD, "+@sSteamCmdForcePlatformType", "windows", "+login", "anonymous"]
    for item in items:
        args += ["+workshop_download_item", CONAN_APP, item]
    args.append("+quit")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args = ["runuser", "-u", OWNER, "--", *args]
    # HOME decides where SteamCMD puts the download: steam's, whoever runs the script.
    env = {**os.environ, "HOME": ctx["home"]}
    sys.stdout.flush()
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=3600, check=False)  # noqa: S603


def _conan_file(name: str) -> bool:
    return bool(CONAN_FILE.match(name)) and name.lower().endswith(CONAN_EXTENSIONS)


def _copy_item(content: str, item: str, staging: str, output: str) -> bool:
    """Copy one downloaded item to <staging>/<id>/; False if SteamCMD did not deliver a .pak."""
    src = os.path.join(content, item)
    names = sorted(n for n in (os.listdir(src) if os.path.isdir(src) else []) if _conan_file(n))
    if f"Success. Downloaded item {item}" not in output or not any(n.lower().endswith(".pak") for n in names):
        return False
    dest = os.path.join(staging, item)
    os.makedirs(dest, exist_ok=True)
    for name in names:
        shutil.copyfile(os.path.join(src, name), os.path.join(dest, name))
    return True


def conan_fetch(ctx: dict, items: list[str], staging: str) -> dict:
    """Downloads the items into <staging>/<id>/ - nothing touches the game folder yet."""
    staging = _checked_staging(staging)
    content = os.path.join(ctx["home"], "Steam", "steamapps", "workshop", "content", CONAN_APP)
    failed = list(items)
    # Three tries, like the game install in ct-phases.sh: SteamCMD sometimes updates itself or
    # drops the connection on a run and reports nothing for an item that the next run gets.
    for _attempt in range(3):
        if not failed:
            break
        proc = _steamcmd(ctx, failed)
        print((proc.stdout or "")[-4000:])
        failed = [item for item in failed if not _copy_item(content, item, staging, proc.stdout or "")]
    if failed:
        raise ValueError(f"SteamCMD did not download a .pak for: {', '.join(failed)}")
    return {"fetched": items}


def _settings_with_modlist(text: str) -> str:
    """ServerModList=modlist.txt in [ServerSettings], keeping the file's own line endings."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("ServerModList="):
            lines[i] = MODLIST_SETTING
            return newline.join(lines) + newline
    if SETTINGS_SECTION in lines:
        lines.insert(lines.index(SETTINGS_SECTION) + 1, MODLIST_SETTING)
    else:
        lines = [SETTINGS_SECTION, MODLIST_SETTING, *lines]
    return newline.join(lines) + newline


def _place(src: str, dest: str, owner: tuple[int, int] | None) -> None:
    """Copy next to the target and rename over it: the server may hold the old pak open."""
    tmp = dest + ".gamepanel-new"
    shutil.copyfile(src, tmp)
    _chown(tmp, owner)
    os.chmod(tmp, 0o644)  # NOSONAR - a mod file, readable by the game
    os.replace(tmp, dest)


def _conan_plan(mark: dict, items: list[str], fresh: str) -> dict[str, list[str]]:
    """Which files each mod of the new list ends up with: freshly downloaded, or the ones it has."""
    plan: dict[str, list[str]] = {}
    for item in items:
        new_dir = os.path.join(fresh, item) if fresh else ""
        if new_dir and os.path.isdir(new_dir):
            plan[item] = sorted(os.listdir(new_dir))
        elif item in mark["files"]:
            plan[item] = list(mark["files"][item])
        else:
            raise ValueError(f"mod {item} was not downloaded")
    names = [n.lower() for files in plan.values() for n in files]
    if len(set(names)) != len(names):
        raise ValueError("two mods ship a file with the same name")
    return plan


def _conan_files(ctx: dict, mark: dict, plan: dict[str, list[str]], fresh: str) -> None:
    """Remove what left the list and place what was downloaded."""
    mods_dir = os.path.join(ctx["game_dir"], CONAN_MODS)
    os.makedirs(mods_dir, exist_ok=True)
    keep = {n.lower() for files in plan.values() for n in files}
    # Only what the panel itself placed is removed: a pak someone put there by hand is not ours.
    stale = [n for files in mark["files"].values() for n in files if n.lower() not in keep and _conan_file(n)]
    for name in stale:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(os.path.join(mods_dir, name))
    owner = _ids_of(ctx["user"])
    for item, files in plan.items():
        src = os.path.join(fresh, item) if fresh else ""
        for name in files if src and os.path.isdir(src) else ():
            _place(os.path.join(src, name), os.path.join(mods_dir, name), owner)


def _conan_modlist(ctx: dict, mark: dict, plan: dict[str, list[str]]) -> str:
    path = os.path.join(ctx["game_dir"], CONAN_MODS, "modlist.txt")
    managed = {f"*{n}".lower() for files in mark["files"].values() for n in files}
    # Lines the panel did not write (a hand-installed mod) stay first, in their order.
    hand = [ln for ln in read_text(path).splitlines() if ln.strip() and ln.strip().lower() not in managed]
    ours = [f"*{n}" for files in plan.values() for n in files if n.lower().endswith(".pak")]
    write_atomic(path, "\n".join([*hand, *ours]) + "\n", ctx["user"])
    return path


def conan_set(ctx: dict, items: list[str], staging: str) -> dict:
    mark = _conan_mark(ctx)
    fresh = _checked_staging(staging) if staging else ""
    plan = _conan_plan(mark, items, fresh)
    _conan_files(ctx, mark, plan, fresh)
    modlist = _conan_modlist(ctx, mark, plan)
    settings = os.path.join(ctx["game_dir"], CONAN_SETTINGS)
    # Raw: the server writes this file with CRLF, and text mode would quietly turn it into LF.
    write_atomic(settings, _settings_with_modlist(read_text(settings, raw=True)), ctx["user"])
    mark_path = os.path.join(ctx["game_dir"], CONAN_MODS, CONAN_MARK)
    write_atomic(mark_path, json.dumps({"ids": items, "files": plan}) + "\n", ctx["user"])
    if fresh:
        shutil.rmtree(fresh, ignore_errors=True)
    return {"ids": items, "config": modlist}


def conan_status(ctx: dict) -> dict:
    mods_dir = os.path.join(ctx["game_dir"], CONAN_MODS)
    mark = _conan_mark(ctx)
    present = set(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else set()
    installed = [i for i in mark["ids"] if mark["files"][i] and set(mark["files"][i]) <= present]
    refused = {os.path.basename(p): reason for p, reason in CONAN_REJECTED.findall(
        read_text(os.path.join(ctx["game_dir"], CONAN_LOG)))}
    rejected = {i: refused[n] for i in mark["ids"] for n in mark["files"][i] if n in refused}
    on = MODLIST_SETTING in read_text(os.path.join(ctx["game_dir"], CONAN_SETTINGS))
    return {"config": os.path.join(mods_dir, "modlist.txt"), "ids": mark["ids"], "installed": installed,
            "rejected": rejected, "modlist_off": bool(mark["ids"]) and not on, "problem": ""}


# --- entry point ------------------------------------------------------------------------------

def parse_items(fmt: str, raw: list[str]) -> list:
    """The argv items, checked again here: the panel checks, and the CT does not trust it."""
    if fmt == "reforger":
        out: list[tuple[str, str]] = []
        for item in raw:
            guid, _, name = item.partition("=")
            guid = guid.upper()
            if not GUID.match(guid) or (name and not REFORGER_NAME.match(name)):
                raise ValueError(f"mod do Reforger invalido: {item!r}")
            out.append((guid, name))
        return list({g: (g, n) for g, n in out}.values())
    for item in raw:
        if not STEAM_ID.match(item):
            raise ValueError(f"ID da Workshop invalido: {item!r}")
    return list(dict.fromkeys(raw))


def context(unit: str, game_dir: str, overlay: bool = False) -> dict:
    text = unit_text(unit)
    user = unit_value(text, "User") or OWNER
    return {"game_dir": game_dir, "args": exec_args(text), "user": user, "home": home_of(user),
            "workdir": unit_value(text, "WorkingDirectory"), "unit": unit, "unit_text": text,
            "overlay": overlay}


STATUS = {"dst": dst_status, "zomboid": zomboid_status, "unturned": unturned_status,
          "reforger": reforger_status, "ark": ark_status, "conan": conan_status}


def run(fmt: str, action: str, ctx: dict, raw: list[str], mods: str, staging: str = "") -> dict:
    if fmt not in FORMATS:
        raise ValueError(f"formato desconhecido: {fmt}")
    if action == "status":
        return {"format": fmt, **STATUS[fmt](ctx)}
    if action not in ("set", "fetch") or (action == "fetch" and fmt != "conan"):
        raise ValueError(f"acao desconhecida: {action}")
    items = parse_items(fmt, raw)
    if fmt == "conan":
        return conan_fetch(ctx, items, staging) if action == "fetch" else conan_set(ctx, items, staging)
    if fmt == "ark":
        return ark_set(ctx, items)
    if fmt == "dst":
        return dst_set(ctx, items)
    if fmt == "zomboid":
        if not ZOMBOID_MODS.match(mods):
            raise ValueError("lista Mods= invalida")
        return zomboid_set(ctx, items, mods)
    if fmt == "unturned":
        return unturned_set(ctx, items)
    return reforger_set(ctx, items)


def main(argv: list[str]) -> int:
    unit = ""
    # Helper mode (the panel logs in without root): what needs the game's environment (ARK) goes to
    # steam's overlay. The other formats only write the game's own files, as steam, in both modes.
    overlay = argv[:1] == ["--overlay"]
    if overlay:
        argv = argv[1:]
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    options = {"--mods": "", "--staging": ""}
    for flag in options:
        if flag in argv:
            i = argv.index(flag)
            options[flag], argv = argv[i + 1] if i + 1 < len(argv) else "", argv[:i] + argv[i + 2:]
    try:
        fmt, action, game_dir, *items = argv
        result = run(fmt, action, context(unit, game_dir, overlay), items, options["--mods"], options["--staging"])
    except (ValueError, KeyError, OSError, TypeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
