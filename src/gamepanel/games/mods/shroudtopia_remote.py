"""Shroudtopia (Enshrouded mod loader) - runs INSIDE the game CT, not in the panel.

Same design as `thunderstore_remote.py`: the panel reads this text and runs it in the container
with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel` - the package
does not exist in there -, and whoever goes to the internet is the CT, never the panel.

What was MEASURED on the real Enshrouded (CT 303, Proton GE 11), and each item here exists
because of one of these:
- the loader comes in through the `winmm.dll` next to `enshrouded_server.exe`, and Wine only
  loads it with `winmm=n,b` in WINEDLLOVERRIDES (without it Wine uses its own winmm and nothing happens);
- with that it starts (`Running on server: 1`), reads `shroudtopia.json` and loads the DLLs from
  `mods/`; the server keeps answering A2S;
- the official package ships EXAMPLE mods with cheats on (no fall damage, no resource cost).
  They do NOT go in: installing the loader must not change anyone's game;
- a mod made for another game version does not bring the server down, but silently loses
  functionality (`... not found` in the log): that is why the status returns the tail of `shroudtopia.log`.

Disabling means removing `winmm=n,b`: Wine goes back to its own winmm and no loader code
runs. Safer than trusting `"active": false` in the json, which still loads the DLL.

Actions (argv): [--scan SCRIPT] status | loader-install [VERSION] | loader-enable | loader-disable |
loader-uninstall. Without VERSION
the latest GitHub release applies; with it, the release of that tag. Installing requires
`--scan` (the panel's `antivirus.SCAN_SCRIPT`): the zip is checked before any file
reaches the game folder. Every action prints its
progress and ends with ONE JSON line, which is what the panel reads.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

RELEASES = "https://api.github.com/repos/s0t7x/shroudtopia/releases/latest"
RELEASE_TAG = "https://api.github.com/repos/s0t7x/shroudtopia/releases/tags/{tag}"
# The version becomes part of the URL: digits and dots only (the panel checks the same shape).
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
# The release zip: Shroudtopia-0.1.1.zip. An asset with another name is not the loader.
ASSET = re.compile(r"^Shroudtopia-[0-9][0-9A-Za-z.\-]*\.zip$")
# What comes out of the zip. The rest (example mods/) is left out on purpose.
LOADER_FILES = ("winmm.dll", "shroudtopia.dll")
CONFIG = "shroudtopia.json"
LOG = "shroudtopia.log"
MODS = "mods"
MARK = ".gamepanel-shroudtopia.json"
RUNTIME_ENV = "/etc/game-runtime.env"
OVERRIDE = "winmm=n,b"
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15
# The config only turns on the log and the loader: mods start empty, each comes in through the screen.
DEFAULT_CONFIG = {"active": True, "bootDelay": 3000, "enableLogging": True,
                  "logLevel": "INFO", "mods": {}, "updateDelay": 500}


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


def with_winmm(value: str) -> str:
    """WINEDLLOVERRIDES with the native winmm, without touching the rest of what the game decided."""
    return ";".join([g for g in _groups(value) if not g.startswith("winmm=")] + [OVERRIDE])


def without_winmm(value: str) -> str:
    return ";".join(g for g in _groups(value) if not g.startswith("winmm="))


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
    value = with_winmm(old) if enabled else without_winmm(old)
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


# ------------------------------------------------------------------ the loader

def _asset_url(release: dict) -> tuple[str, str]:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if ASSET.match(asset.get("name", "")) and url.startswith("https://github.com/"):
            return asset["name"], url
    raise ValueError("esta versao do Shroudtopia nao traz o zip do carregador")


def release_for(version: str = "", fetcher=fetch) -> dict:
    """The requested release (empty = the latest)."""
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    # The tag may have been created with or without the leading "v": the panel only receives the
    # number, and whoever types it has no way of knowing which of the two the author used.
    last: OSError | None = None
    for tag in (f"v{version}", version):
        try:
            return json.loads(fetcher(RELEASE_TAG.format(tag=tag)))
        except OSError as exc:
            last = exc
    raise ValueError(f"o Shroudtopia nao tem a versao {version}: {last}")


def install_loader(game_dir: str, fetcher=fetch, env_path: str = RUNTIME_ENV, version: str = "",
                   scan=_no_scan, overlay: bool = False) -> dict:
    release = release_for(version, fetcher)
    name, url = _asset_url(release)
    print(f"baixando {name}")
    data = fetcher(url)
    # The whole zip, example mods included: that is what came from the internet.
    scan([(name, data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    by_base = {n.rsplit("/", 1)[-1].lower(): n for n in z.namelist() if not n.endswith("/")}
    missing = [f for f in LOADER_FILES if f not in by_base]
    if missing:
        raise ValueError(f"o zip nao tem {', '.join(missing)}: nao e o carregador")
    for wanted in LOADER_FILES:
        with z.open(by_base[wanted]) as src, open(os.path.join(game_dir, wanted), "wb") as out:
            out.write(src.read())
    config_path = os.path.join(game_dir, CONFIG)
    # A config that already exists belongs to the server owner (their mods are there): only created if missing.
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
    os.makedirs(os.path.join(game_dir, MODS), exist_ok=True)
    if os.path.exists(env_path):
        set_enabled(env_path, True, overlay)
    tag = release.get("tag_name", "")
    with open(os.path.join(game_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "asset": name, "pinned": bool(version)}, f)
    print(f"Shroudtopia {tag} em {game_dir} (sem os mods de exemplo)")
    return {"loader": "Shroudtopia", "version": tag}


def uninstall_loader(game_dir: str, env_path: str = RUNTIME_ENV, overlay: bool = False) -> dict:
    """Remove Shroudtopia and winmm=n,b: Enshrouded starts again without any of its code.

    The mods (DLLs in mods/) depend on it and go along (the screen warns first). These are the
    loader's fixed names next to the executable, never the whole game folder.
    """
    if os.path.exists(env_path):
        set_enabled(env_path, False, overlay)
    removed = []
    for name in (*LOADER_FILES, CONFIG, LOG, MODS, MARK):
        path = os.path.join(game_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        else:
            continue
        removed.append(name)
    print(f"Shroudtopia desinstalado de {game_dir}: {', '.join(removed) or 'nada a apagar'}")
    return {"uninstalled": True, "removed": removed}


def status(game_dir: str, env_path: str = RUNTIME_ENV, overlay: bool = False) -> dict:
    mods_dir = os.path.join(game_dir, MODS)
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        path = os.path.join(mods_dir, entry)
        if entry.lower().endswith(".dll") or os.path.isdir(path):
            mods.append({"name": entry, "dir": os.path.isdir(path),
                         "size": 0 if os.path.isdir(path) else os.path.getsize(path)})
    log = _read_text(os.path.join(game_dir, LOG)).splitlines()[-LOG_TAIL:]
    mark = _read_json(os.path.join(game_dir, MARK))
    return {
        "loader_installed": all(os.path.exists(os.path.join(game_dir, f)) for f in LOADER_FILES),
        "loader": "Shroudtopia", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        "enabled": is_enabled(env_path, overlay) if os.path.exists(env_path) else False,
        "overlay_problem": overlay_problem(env_path) if overlay else "",
        "mods": mods, "log": log,
    }


def _chown(game_dir: str) -> None:
    """The game runs as 'steam' and needs to read the loader and write the log and the config."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    paths = [os.path.join(game_dir, n) for n in (*LOADER_FILES, CONFIG, MARK, MODS)]
    for path in paths:
        with contextlib.suppress(OSError):
            os.chown(path, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    # Helper mode (the panel logs in without root): the Wine setting goes to steam's overlay.
    overlay = argv[:1] == ["--overlay"]
    if overlay:
        argv = argv[1:]
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, game_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        # Before downloading anything: a setting that would not reach the game is a broken install.
        if overlay and action != "status" and overlay_problem():
            raise ValueError(overlay_problem())
        if action == "status":
            result = status(game_dir, overlay=overlay)
        elif action == "loader-install":
            result = install_loader(game_dir, version=rest[0] if rest else "", scan=scanner(script), overlay=overlay)
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(RUNTIME_ENV, action == "loader-enable", overlay)
            result = {"enabled": action == "loader-enable"}
        elif action == "loader-uninstall":
            result = uninstall_loader(game_dir, overlay=overlay)
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action not in ("status", "loader-uninstall"):
            _chown(game_dir)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
