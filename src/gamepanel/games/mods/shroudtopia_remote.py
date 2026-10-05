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


def set_enabled(env_path: str, enabled: bool) -> None:
    old = _read_overrides(env_path)
    _write_overrides(env_path, with_winmm(old) if enabled else without_winmm(old))


def is_enabled(env_path: str) -> bool:
    return OVERRIDE in _groups(_read_overrides(env_path))


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
                   scan=_no_scan) -> dict:
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
        set_enabled(env_path, True)
    tag = release.get("tag_name", "")
    with open(os.path.join(game_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "asset": name, "pinned": bool(version)}, f)
    print(f"Shroudtopia {tag} em {game_dir} (sem os mods de exemplo)")
    return {"loader": "Shroudtopia", "version": tag}


def uninstall_loader(game_dir: str, env_path: str = RUNTIME_ENV) -> dict:
    """Remove Shroudtopia and winmm=n,b: Enshrouded starts again without any of its code.

    The mods (DLLs in mods/) depend on it and go along (the screen warns first). These are the
    loader's fixed names next to the executable, never the whole game folder.
    """
    if os.path.exists(env_path):
        set_enabled(env_path, False)
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


def status(game_dir: str, env_path: str = RUNTIME_ENV) -> dict:
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
        "enabled": is_enabled(env_path) if os.path.exists(env_path) else False,
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
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, game_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(game_dir)
        elif action == "loader-install":
            result = install_loader(game_dir, version=rest[0] if rest else "", scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(RUNTIME_ENV, action == "loader-enable")
            result = {"enabled": action == "loader-enable"}
        elif action == "loader-uninstall":
            result = uninstall_loader(game_dir)
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
