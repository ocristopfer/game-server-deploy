"""UE4SS (Unreal game mod loader) - runs INSIDE the game CT, not in the panel.

Same design as `shroudtopia_remote.py`: the panel reads this text and runs it in the container
with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel` - the package
does not exist in there -, and whoever goes to the internet is the CT, never the panel.

It applies to Unreal games whose server is the WINDOWS executable running under Proton: UE4SS
gets in by injecting a DLL into that executable. A native Linux server (Dragonwilds, Palworld here)
does not load this - the Linux ports are something else, and none has a trustworthy binary.

Decisions, each with its reason:
- **`experimental-latest`, and not the stable v3.0.1.** MEASURED on the real Icarus (test CT,
  Proton GE 11, 2026-10-03): with v3.0.1 UE4SS loads and runs Lua, but the server's Steam
  starts with `AppId: 0` and "Steam API failed to initialize" - without it the A2S query never
  opens and the server vanishes from the browser. Disabled, `AppId: 1149460` comes back. With
  the experimental one (the loose `dwmapi.dll` and the rest in `ue4ss/`), Steam starts, A2S
  answers and the mods run. The version can still be pinned to a stable one through the screen,
  for whoever knows what they are doing.
- **The normal zip, never zDEV.** `zDEV-UE4SS_*.zip` opens a console and a debug window by
  default; on a headless server that is at the very least wasteful, and on V Rising an open
  console under the virtual X FROZE the server.
- **It comes in through the `dwmapi.dll` next to `*-Win64-Shipping.exe`**, and Wine only uses it
  with `dwmapi=n,b` in WINEDLLOVERRIDES (its default is the built-in dwmapi, and UE4SS never runs).
  Disabling means removing that setting: no UE4SS code runs, without deleting any mod.
- **Console and window off** (`ConsoleEnabled`, `GuiConsoleEnabled`, `GuiConsoleVisible`).
- **Of the mods that come in the zip, only the blueprint mod loaders stay enabled**
  (`BPModLoaderMod`, `BPML_GenericFunctions`): they are what makes logic `.pak` mods run.
  The rest comes enabled out of the box and is client-side or cheats (`CheatManagerEnablerMod`,
  `ConsoleEnablerMod`, `Keybinds`...): installing the loader must not change anyone's game.
- **Reinstalling preserves the owner's `UE4SS-settings.ini` and `mods.txt`** - which is what
  UE4SS itself says to do when updating - and their mods in `Mods/`.
- **The official `mods.txt` comes with a BOM**, which sticks to the first mod's name: it is
  stripped on read.
- **Two layouts**: the experimental one puts everything but the proxy in `ue4ss/`; the stable
  v3.0.x leaves everything loose next to the `.exe`. The installer follows whatever the zip
  brings, and the status finds both.

Actions (argv): [--scan SCRIPT] status | loader-install [VERSION] | loader-enable | loader-disable |
loader-uninstall,
followed by the executable folder (Binaries/Win64). Installing requires `--scan` (the panel's
`antivirus.SCAN_SCRIPT`): the zip is checked before any file reaches the game. Every action
prints its progress and ends with ONE JSON line, which is what the panel reads.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

# The experimental one is rebuilt by the project on every change, always with this tag.
RELEASES = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/experimental-latest"
RELEASE_TAG = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/tags/{tag}"
# The version becomes part of the URL: digits and dots only (the panel checks the same shape).
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
# The normal zip (UE4SS_v3.0.1.zip). zDEV starts with "z" and does not match: it is the debug one.
ASSET = re.compile(r"^UE4SS_v[0-9][0-9A-Za-z.\-]*\.zip$")
PROXY = "dwmapi.dll"
CORE = "UE4SS.dll"
SETTINGS = "UE4SS-settings.ini"
LOG = "UE4SS.log"
MODS = "Mods"
# Loader folder in the experimental layout; empty = loose next to the .exe (v3.0.x).
SUBDIR = "ue4ss"
MODS_TXT = "mods.txt"
MARK = ".gamepanel-ue4ss.json"
RUNTIME_ENV = "/etc/game-runtime.env"
OVERRIDE = "dwmapi=n,b"
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15
# The only out-of-the-box mods that stay enabled: they load logic .pak mods, no cheats.
KEEP_ENABLED = ("BPModLoaderMod", "BPML_GenericFunctions")
HEADLESS = (("Debug", "ConsoleEnabled", "0"), ("Debug", "GuiConsoleEnabled", "0"),
            ("Debug", "GuiConsoleVisible", "0"), ("General", "EnableHotReloadSystem", "0"))
# A zip file that lives under one of these goes to the executable folder; the rest (docs,
# readme) is left out.
SKIP = {"readme.md", "readme.txt", "license", "license.md", "license.txt", "changelog.md"}


def fetch(url: str) -> bytes:
    # Only github.com https gets here: the API is fixed (RELEASES) and the download comes from its
    # response, checked against github.com before downloading.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


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
# IDENTICAL in thunderstore_remote.py and shroudtopia_remote.py (a test compares them): the three
# run standalone in the CT and do not import each other. The rule (what counts as a finding) does
# not live here, but in the script the panel sends; here we only write what was downloaded into a
# folder and call the script.

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


def _read_text(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def _read_json(path: str) -> dict:
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


# ------------------------------------------------------------------ Wine

def _groups(value: str) -> list[str]:
    return [g.strip() for g in value.split(";") if g.strip()]


def with_dwmapi(value: str) -> str:
    """WINEDLLOVERRIDES with the native dwmapi, without touching the rest of what the game decided."""
    return ";".join([g for g in _groups(value) if not g.startswith("dwmapi=")] + [OVERRIDE])


def without_dwmapi(value: str) -> str:
    return ";".join(g for g in _groups(value) if not g.startswith("dwmapi="))


def _read_overrides(env_path: str) -> str:
    for line in _read_text(env_path).splitlines():
        if line.startswith("WINE_DLL_OVERRIDES="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _write_overrides(env_path: str, value: str) -> None:
    lines = _read_text(env_path).splitlines()
    # The file is read with `source`: single quotes, and the value never has a quote (only dll,=;).
    new = f"WINE_DLL_OVERRIDES='{value}'"
    lines = [new if ln.startswith("WINE_DLL_OVERRIDES=") else ln for ln in lines]
    if new not in lines:
        lines.append(new)
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def effective_overrides(env_path: str, overlay: bool = False) -> str:
    """What win-run will use: the overlay's line (helper mode) wins over /etc/game-runtime.env."""
    if overlay:
        value = overlay_get(OVERLAY_RUNTIME, "WINE_DLL_OVERRIDES")
        if value is not None:
            return value
    return _read_overrides(env_path)


def set_enabled(env_path: str, enabled: bool, overlay: bool = False) -> None:
    old = effective_overrides(env_path, overlay)
    value = with_dwmapi(old) if enabled else without_dwmapi(old)
    if not overlay:
        _write_overrides(env_path, value)
        return
    # Helper mode: steam's overlay, and no line at all when the value is the base one - disabling
    # or uninstalling then leaves /etc/game-runtime.env in charge again, exactly as before the loader.
    overlay_set(OVERLAY_RUNTIME, "WINE_DLL_OVERRIDES", None if value == _read_overrides(env_path) else value)


def is_enabled(env_path: str, overlay: bool = False) -> bool:
    return OVERRIDE in _groups(effective_overrides(env_path, overlay))


def overlay_problem(env_path: str = RUNTIME_ENV) -> str:
    """Helper mode: why the Wine setting would not reach the game ('' = it will)."""
    return overlay_wine_problem() if os.path.exists(env_path) else ""


# ------------------------------------------------------------------ configuration

def set_ini(text: str, section: str, key: str, value: str) -> str:
    """`key = value` inside `[section]`, replacing whatever is there or appending."""
    lines = text.splitlines()
    head = re.compile(rf"^\s*\[{re.escape(section)}\]\s*$", re.I)
    entry = re.compile(rf"^\s*{re.escape(key)}\s*=", re.I)
    start = next((i for i, ln in enumerate(lines) if head.match(ln)), None)
    if start is None:
        return "\n".join([*lines, f"[{section}]", f"{key} = {value}"]) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    for i in range(start + 1, end):
        if entry.match(lines[i]):
            lines[i] = f"{key} = {value}"
            return "\n".join(lines) + "\n"
    lines.insert(end, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def server_mods_txt(text: str) -> str:
    """The factory mods.txt with everything off, except the blueprint loaders."""
    out = []
    for line in text.lstrip("\ufeff").splitlines():
        name, sep, _ = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            name = name.strip()
            out.append(f"{name} : {1 if name in KEEP_ENABLED else 0}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def enabled_mods(text: str) -> dict[str, bool]:
    result = {}
    for line in text.lstrip("\ufeff").splitlines():
        name, sep, flag = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            result[name.strip()] = flag.strip() == "1"
    return result


# ------------------------------------------------------------------ the loader

def _asset_url(release: dict) -> tuple[str, str]:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if ASSET.match(asset.get("name", "")) and url.startswith("https://github.com/"):
            return asset["name"], url
    raise ValueError("esta versao do UE4SS nao traz o zip normal (so o de debug?)")


def loader_dir(exe_dir: str) -> str:
    """Where this server's UE4SS.dll lives (and the config, the log and Mods/)."""
    sub = os.path.join(exe_dir, SUBDIR)
    if os.path.exists(os.path.join(sub, CORE)) or not os.path.exists(os.path.join(exe_dir, CORE)):
        return sub
    return exe_dir


def release_for(version: str = "", fetcher=fetch) -> dict:
    """The requested release (empty = the experimental one, the one that works under Proton)."""
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    last: OSError | None = None
    for tag in (f"v{version}", version):
        try:
            return json.loads(fetcher(RELEASE_TAG.format(tag=tag)))
        except OSError as exc:
            last = exc
    raise ValueError(f"o UE4SS nao tem a versao {version}: {last}")


def _safe_rel(path: str) -> str:
    """A path inside the zip, relative and never going up a folder; empty = rejected."""
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def _extract_zip(z: zipfile.ZipFile, names: list[str], prefix: str, exe_dir: str,
                 created: set[str]) -> tuple[int, set[str]]:
    """Write next to the .exe what is under `prefix`; return (files, root names CREATED).

    Only what the zip creates is recorded - and only that is deleted on uninstall: what already
    existed before the first install belongs to the game, and what a previous install created
    (`created`) is still ours.
    """
    keep = {SETTINGS.lower(), MODS_TXT.lower()}
    created = set(created)
    count = 0
    for entry in names:
        rel = _safe_rel(entry[len(prefix):]) if entry.startswith(prefix) else ""
        if not rel or posixpath.basename(rel).lower() in SKIP:
            continue
        top = rel.split("/", 1)[0]
        if not os.path.exists(os.path.join(exe_dir, top)):
            created.add(top)
        dest = os.path.join(exe_dir, rel)
        # A config that already exists belongs to the server owner: only created if missing.
        if posixpath.basename(rel).lower() in keep and os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count, created


def _tidy_config(exe_dir: str, first_install: bool) -> None:
    """BOM out of mods.txt always; console, window and factory mods only on the first install
    (on a reinstall the config belongs to the owner)."""
    base = loader_dir(exe_dir)
    mods_txt = os.path.join(base, MODS, MODS_TXT)
    if os.path.exists(mods_txt):
        text = _read_text(mods_txt)
        if first_install:
            text = server_mods_txt(text)
        with open(mods_txt, "w", encoding="utf-8") as f:
            f.write(text.lstrip("﻿"))
    if first_install:
        settings = os.path.join(base, SETTINGS)
        text = _read_text(settings)
        for section, key, value in HEADLESS:
            text = set_ini(text, section, key, value)
        with open(settings, "w", encoding="utf-8") as f:
            f.write(text)


def install_loader(exe_dir: str, fetcher=fetch, env_path: str = RUNTIME_ENV, version: str = "",
                   scan=_no_scan, overlay: bool = False) -> dict:
    if not os.path.isdir(exe_dir):
        raise ValueError(f"a pasta do executavel nao existe: {exe_dir}")
    release = release_for(version, fetcher)
    name, url = _asset_url(release)
    print(f"baixando {name}")
    data = fetcher(url)
    scan([(name, data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    names = [n for n in z.namelist() if not n.endswith("/")]
    proxy = next((n for n in names if posixpath.basename(n).lower() == PROXY), "")
    if not proxy or not any(posixpath.basename(n) == CORE for n in names):
        raise ValueError(f"o zip nao tem {PROXY} e {CORE}: nao e o UE4SS")
    # Everything is relative to the dwmapi.dll folder inside the zip: that is what goes next to the .exe.
    prefix = proxy[: -len(posixpath.basename(proxy))]
    previous = _read_json(os.path.join(exe_dir, MARK))
    count, created = _extract_zip(z, names, prefix, exe_dir, set(previous.get("files", [])))
    _tidy_config(exe_dir, first_install=not previous)
    if os.path.exists(env_path):
        set_enabled(env_path, True, overlay)
    tag = release.get("tag_name", "")
    with open(os.path.join(exe_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "asset": name, "pinned": bool(version), "files": sorted(created)}, f)
    print(f"UE4SS {tag} em {exe_dir} ({count} arquivos; console e mods de trapaca desligados)")
    return {"loader": "UE4SS", "version": tag, "files": count}


def _fallback_names(exe_dir: str) -> tuple[str, ...]:
    """What UE4SS puts next to the .exe, for installs made before the panel recorded the list:
    the experimental one puts everything in ue4ss/, the stable v3.0.x leaves it loose (Mods/ next to UE4SS.dll)."""
    if os.path.isdir(os.path.join(exe_dir, SUBDIR)):
        return (PROXY, SUBDIR)
    loose = (PROXY, CORE, SETTINGS, LOG, "UE4SS_Signatures", "UE4SS.pdb")
    return (*loose, MODS) if os.path.exists(os.path.join(exe_dir, CORE)) else loose


def uninstall_loader(exe_dir: str, env_path: str = RUNTIME_ENV, overlay: bool = False) -> dict:
    """Remove UE4SS and the Wine setting: the game starts again without any of its code.

    The UE4SS mods live in its folder and go along (the screen warns first); the game's .pak
    files are not its own and stay.
    """
    if os.path.exists(env_path):
        set_enabled(env_path, False, overlay)
    names = _read_json(os.path.join(exe_dir, MARK)).get("files") or _fallback_names(exe_dir)
    removed = []
    for name in (*names, MARK):
        # Only a name inside the folder, never a path: what comes from the mark must not leave it.
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        path = os.path.join(exe_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        else:
            continue
        removed.append(name)
    print(f"UE4SS desinstalado de {exe_dir}: {', '.join(removed) or 'nada a apagar'}")
    return {"uninstalled": True, "removed": removed}


def status(exe_dir: str, env_path: str = RUNTIME_ENV, overlay: bool = False) -> dict:
    base = loader_dir(exe_dir)
    mods_dir = os.path.join(base, MODS)
    flags = enabled_mods(_read_text(os.path.join(mods_dir, MODS_TXT)))
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        if os.path.isdir(os.path.join(mods_dir, entry)):
            enabled = flags.get(entry, os.path.exists(os.path.join(mods_dir, entry, "enabled.txt")))
            mods.append({"name": entry, "enabled": enabled})
    mark = _read_json(os.path.join(exe_dir, MARK))
    return {
        "loader_installed": os.path.exists(os.path.join(exe_dir, PROXY)) and os.path.exists(os.path.join(base, CORE)),
        "loader": "UE4SS", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        "enabled": is_enabled(env_path, overlay) if os.path.exists(env_path) else False,
        "overlay_problem": overlay_problem(env_path) if overlay else "",
        "mods": mods,
        "log": _read_text(os.path.join(base, LOG)).splitlines()[-LOG_TAIL:],
    }


def _chown(exe_dir: str) -> None:
    """The game runs as 'steam': it needs to read the DLL and write the log and the config."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for name in (PROXY, MARK):
        with contextlib.suppress(OSError):
            os.chown(os.path.join(exe_dir, name), pw.pw_uid, pw.pw_gid)
    # The whole loader folder: in the experimental one it is `ue4ss/`; in the loose layout, only what is its own.
    base = loader_dir(exe_dir)
    if base != exe_dir:
        walk_roots = [base]
    else:
        for name in (CORE, SETTINGS):
            with contextlib.suppress(OSError):
                os.chown(os.path.join(exe_dir, name), pw.pw_uid, pw.pw_gid)
        walk_roots = [os.path.join(exe_dir, MODS)]
    for root, dirs, files in (w for r in walk_roots for w in os.walk(r)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    # Helper mode (the panel logs in without root): the Wine setting goes to steam's overlay.
    overlay = argv[:1] == ["--overlay"]
    if overlay:
        argv = argv[1:]
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, exe_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        # Before downloading anything: a setting that would not reach the game is a broken install.
        if overlay and action != "status" and overlay_problem():
            raise ValueError(overlay_problem())
        if action == "status":
            result = status(exe_dir, overlay=overlay)
        elif action == "loader-install":
            result = install_loader(exe_dir, version=rest[0] if rest else "", scan=scanner(script), overlay=overlay)
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(RUNTIME_ENV, action == "loader-enable", overlay)
            result = {"enabled": action == "loader-enable"}
        elif action == "loader-uninstall":
            result = uninstall_loader(exe_dir, overlay=overlay)
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action not in ("status", "loader-uninstall"):
            _chown(exe_dir)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
