"""Oxide (uMod), the Rust plugin loader - runs INSIDE the game CT, not in the panel.

Same design as the other remote installers: the panel reads this text and runs it in the
container with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel`.

The package (`Oxide.Rust-linux.zip`, GitHub release of OxideMod/Oxide.Rust) is only the
`RustDedicated_Data/Managed/` folder - checked by downloading 2.0.7801 -, and it OVERWRITES DLLs
of the game itself. The decisions follow from that:
- **What is going to be overwritten is saved first** (`.gamepanel-oxide/original/`). Disabling
  restores the original; re-enabling puts Oxide back, without downloading anything. Without the
  copy, "disabling" would only be possible by validating the whole game through Steam.
- **A Rust update through Steam WIPES Oxide** (SteamCMD restores the game DLLs), and Rust
  updates every first Thursday of the month, plus hotfixes. The status compares what is in the
  folder with what the installer put there, and the screen asks to reinstall when they do not
  match. The copy of the original also goes stale at that point: reinstalling redoes it.
- **Plugins are `.cs` files in `oxide/plugins`**, uploaded through the screen (the upload goes
  through the antivirus). Oxide compiles and loads a new plugin without restarting the server.

NOT TESTED on a real server yet.

Actions (argv): [--scan SCRIPT] status | loader-install [VERSION] | loader-enable | loader-disable |
loader-uninstall,
followed by the game folder (where RustDedicated lives). Every action ends with ONE JSON line.
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
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

RELEASES = "https://api.github.com/repos/OxideMod/Oxide.Rust/releases/latest"
RELEASE_TAG = "https://api.github.com/repos/OxideMod/Oxide.Rust/releases/tags/{tag}"
# Oxide versions are x.y.zzzz (2.0.7801).
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
ASSET = "Oxide.Rust-linux.zip"
PREFIX = "RustDedicated_Data/Managed/"
STATE_DIR = ".gamepanel-oxide"
ORIGINAL = "original"
PACKAGE = "package"
MARK = "install.json"
PLUGINS = posixpath.join("oxide", "plugins")
OWNER = "steam"
TIMEOUT = 120
LOG_TAIL = 15


def fetch(url: str) -> bytes:
    # Only github.com https gets here: the API is fixed (RELEASES) and the download comes from its
    # response, checked against github.com before downloading.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


# ------------------------------------------------------------------ antivirus
# IDENTICAL in the other remote installers (a test compares them): they run standalone in the CT
# and do not import each other. The rule (what counts as a finding) does not live here, but in the
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


def _read_json(path: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _safe_rel(path: str) -> str:
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def release_for(version: str = "", fetcher=fetch) -> dict:
    if not version:
        return json.loads(fetcher(RELEASES))
    if not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    return json.loads(fetcher(RELEASE_TAG.format(tag=version)))


def _asset_url(release: dict) -> str:
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        if asset.get("name") == ASSET and url.startswith("https://github.com/"):
            return url
    raise ValueError(f"esta versao do Oxide nao traz o {ASSET}")


def install_loader(game_dir: str, version: str = "", fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(os.path.join(game_dir, "RustDedicated_Data")):
        raise ValueError(f"nao parece um servidor de Rust: falta RustDedicated_Data em {game_dir}")
    release = release_for(version, fetcher)
    data = fetcher(_asset_url(release))
    scan([(f"Oxide.Rust-{release.get('tag_name', '')}", data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    files = [n for n in z.namelist() if n.startswith(PREFIX) and not n.endswith("/") and _safe_rel(n)]
    if not files:
        raise ValueError(f"o zip nao tem {PREFIX}: nao e o Oxide do Rust")
    state = os.path.join(game_dir, STATE_DIR)
    original = os.path.join(state, ORIGINAL)
    package = os.path.join(state, PACKAGE)
    ours = _read_json(os.path.join(state, MARK)).get("files", {})
    shutil.rmtree(package, ignore_errors=True)
    hashes = {}
    for entry in files:
        rel = _safe_rel(entry)
        dest = os.path.join(game_dir, rel)
        # What goes into the backup is the file that is NOT what the installer put there: the
        # game's. With Oxide enabled, what is in the folder is Oxide, and the earlier backup still
        # holds; after a Rust update, what is in the folder is the NEW game, and it replaces the old one.
        if os.path.exists(dest) and _sha(dest) != ours.get(rel):
            os.makedirs(os.path.dirname(os.path.join(original, rel)), exist_ok=True)
            shutil.copy2(dest, os.path.join(original, rel))
        body = z.read(entry)
        for base in (game_dir, package):
            out = os.path.join(base, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(body)
        hashes[rel] = hashlib.sha256(body).hexdigest()
    os.makedirs(os.path.join(game_dir, PLUGINS), exist_ok=True)
    tag = release.get("tag_name", "")
    with open(os.path.join(state, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": tag, "pinned": bool(version), "files": hashes}, f)
    print(f"Oxide {tag}: {len(files)} arquivos em {game_dir}/{PREFIX}")
    return {"loader": "Oxide", "version": tag, "files": len(files)}


def _copy_tree(src: str, dest: str) -> int:
    count = 0
    for root, _, names in os.walk(src):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), src)
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(os.path.join(root, name), out)
            count += 1
    return count


def set_enabled(game_dir: str, enabled: bool) -> dict:
    state = os.path.join(game_dir, STATE_DIR)
    mark = _read_json(os.path.join(state, MARK))
    if not mark:
        raise ValueError("o Oxide nao foi instalado pelo painel neste servidor")
    if enabled:
        count = _copy_tree(os.path.join(state, PACKAGE), game_dir)
    else:
        # A file Oxide brought and the game did not have is removed; what the game had comes back.
        for rel in mark.get("files", {}):
            if not os.path.exists(os.path.join(state, ORIGINAL, rel)):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(game_dir, rel))
        count = _copy_tree(os.path.join(state, ORIGINAL), game_dir)
    return {"enabled": enabled, "files": count}


def uninstall_loader(game_dir: str) -> dict:
    """Remove Oxide: restore the game DLLs and delete oxide/ (plugins, data, logs) and the state.

    File by file, and not by copying the whole backup back: after a Rust update the folder
    already has the game's NEW DLLs and the backup is from the old version - restoring it would
    break the server. Only what is still the Oxide file (same sha256) goes back to the original
    (or is removed, if the game did not have it); what Steam has already replaced stays.
    """
    state = os.path.join(game_dir, STATE_DIR)
    files = _read_json(os.path.join(state, MARK)).get("files", {})
    restored = removed = kept = 0
    for rel, sha in files.items():
        if not _safe_rel(rel):
            continue
        path = os.path.join(game_dir, rel)
        if _sha(path) != sha:
            kept += 1
            continue
        original = os.path.join(state, ORIGINAL, rel)
        if os.path.exists(original):
            shutil.copy2(original, path)
            restored += 1
        else:
            os.remove(path)
            removed += 1
    for folder in (os.path.join(game_dir, "oxide"), state):
        shutil.rmtree(folder, ignore_errors=True)
    print(f"Oxide desinstalado de {game_dir}: {restored} arquivo(s) do jogo devolvido(s), {removed} apagado(s), "
          f"{kept} ja trocado(s) pela Steam")
    return {"uninstalled": True, "restored": restored, "removed": removed, "kept": kept}


def status(game_dir: str) -> dict:
    mark = _read_json(os.path.join(game_dir, STATE_DIR, MARK))
    files = mark.get("files", {})
    matching = sum(1 for rel, sha in files.items() if _sha(os.path.join(game_dir, rel)) == sha)
    plugins_dir = os.path.join(game_dir, PLUGINS)
    plugins = [{"name": n, "size": os.path.getsize(os.path.join(plugins_dir, n))}
               for n in sorted(os.listdir(plugins_dir)) if n.endswith(".cs")] if os.path.isdir(plugins_dir) else []
    log_dir = os.path.join(game_dir, "oxide", "logs")
    logs = sorted(n for n in os.listdir(log_dir) if n.endswith(".txt")) if os.path.isdir(log_dir) else []
    log: list[str] = []
    if logs:
        newest = os.path.join(log_dir, logs[-1])
        with contextlib.suppress(OSError), open(newest, encoding="utf-8", errors="replace") as f:
            log = f.read().splitlines()[-LOG_TAIL:]
    return {
        "loader_installed": bool(files),
        "loader": "Oxide", "loader_version": mark.get("version", ""),
        "loader_pinned": bool(mark.get("pinned")),
        # Everything in place = enabled; nothing = disabled (or the game was updated); some = broken.
        "enabled": bool(files) and matching == len(files),
        "wiped": bool(files) and 0 < matching < len(files),
        "mods": plugins, "log": log,
    }


def _chown(game_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, names in os.walk(os.path.join(game_dir, "oxide")):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in names]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)
    for rel in _read_json(os.path.join(game_dir, STATE_DIR, MARK)).get("files", {}):
        with contextlib.suppress(OSError):
            os.chown(os.path.join(game_dir, rel), pw.pw_uid, pw.pw_gid)


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
            result = install_loader(game_dir, rest[0] if rest else "", scan=scanner(script))
        elif action in ("loader-enable", "loader-disable"):
            result = set_enabled(game_dir, action == "loader-enable")
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
