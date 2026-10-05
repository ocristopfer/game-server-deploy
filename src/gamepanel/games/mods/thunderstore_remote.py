"""Thunderstore mods (BepInEx) - runs INSIDE the game CT, not in the panel.

The panel reads the text of this file and runs it in the container with `python3 -c`, over SSH,
as root. It is this way because the panel does not go to the internet (repository rule: no
SSRF, no third-party dependency in production) and the game CT does: its firewall allows
outbound internet. Stdlib only, and no import of `gamepanel`: the package does not exist in there.

What was MEASURED on a real V Rising server under Proton, and each item here exists because
of one of these:
- BepInEx is all .NET, and the `mscoree=` (disabled) that the Windows .env files use made
  Wine reject each of its DLLs ("IL-only binary ... cannot be loaded"): it comes off the list;
- BepInEx comes in through the doorstop `winhttp.dll`, which is only loaded with `winhttp=n,b`;
- the BepInEx console (on by default) FROZE the server under the virtual X, stuck with no
  CPU and no log: it stays off;
- the first startup generates the code of the whole game and reached 9.4 GB of memory.

Actions (argv): [--scan SCRIPT] status | loader-install [VERSION] | loader-enable | loader-disable |
loader-uninstall | plugin-install NS NAME [VERSION] | plugin-remove NS NAME. Without VERSION the newest
applies; with it, the package and its dependencies come in the versions IT declares (see
`install_plugin`). Every action prints its progress and ends with ONE JSON line, which is what
the panel reads.

Installing requires `--scan` (the panel's `antivirus.SCAN_SCRIPT`): everything that is going to
be installed - the package and ALL dependencies - is downloaded first, checked at once and only
then written into the game folder. A finding or a check that does not run = nothing is installed.
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

API = "https://thunderstore.io/api/experimental/package/{ns}/{name}/"
API_VERSION = "https://thunderstore.io/api/experimental/package/{ns}/{name}/{version}/"
# Thunderstore package namespace and name: letters, digits and underscore. Checked here
# again (the panel already checks): this becomes a folder path and a URL.
PART = re.compile(r"[A-Za-z0-9_]{1,64}")
# The same version shape the panel checks (thunderstore.VERSION): it becomes part of the URL.
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
# What comes in every package zip and does not belong to the game.
SKIP = {"icon.png", "readme.md", "manifest.json", "changelog.md", "license", "license.md",
        "license.txt"}
MARK = ".gamepanel.json"
RUNTIME_ENV = "/etc/game-runtime.env"
DOORSTOP_CONFIG = "doorstop_config.ini"
OWNER = "steam"
MAX_PACKAGES = 25
TIMEOUT = 120


def fetch(url: str) -> bytes:
    # Only thunderstore.io https gets here: the API is fixed (API, above) and the download comes
    # from its response, never from whoever asked in the panel.
    req = urllib.request.Request(url, headers={"User-Agent": "gamepanel"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
        return r.read()


# ------------------------------------------------------------------ antivirus
# IDENTICAL in shroudtopia_remote.py (a test compares them): both run standalone in the CT and
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
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _read_json(path: str) -> dict:
    """The JSON of the file, or empty: a missing or malformed file does not break the status."""
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


def check_part(value: str) -> str:
    if not PART.fullmatch(value or ""):
        raise ValueError(f"nome de pacote invalido: {value!r}")
    return value


def check_version(value: str) -> str:
    if not VERSION.fullmatch(value or ""):
        raise ValueError(f"versao invalida: {value!r}")
    return value


def latest(ns: str, name: str, fetcher=fetch) -> dict:
    data = json.loads(fetcher(API.format(ns=check_part(ns), name=check_part(name))))
    return data["latest"]


def package_meta(ns: str, name: str, version: str = "", fetcher=fetch) -> dict:
    """The data of ONE version of the package; empty version = the newest."""
    if not version:
        return latest(ns, name, fetcher)
    url = API_VERSION.format(ns=check_part(ns), name=check_part(name), version=check_version(version))
    meta = json.loads(fetcher(url))
    # Asked for 1.2.0 and got something else: installing anyway would be lying on the screen.
    if meta.get("version_number") != version:
        raise ValueError(f"o Thunderstore nao tem {ns}-{name}-{version}")
    return meta


def _dependency(dep: str) -> tuple[str, str, str]:
    """`ns-name-1.2.3` as it comes in a package's dependency list."""
    parts = dep.split("-")
    if len(parts) != 3:
        raise ValueError(f"dependencia que nao entendi: {dep!r}")
    return parts[0], parts[1], parts[2]


def _safe_rel(path: str) -> str:
    """A path inside the zip, relative and never going up a folder; empty = rejected."""
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


# ------------------------------------------------------------------ the loader (BepInEx)

def fix_overrides(value: str) -> str:
    """The WINEDLLOVERRIDES BepInEx needs, based on what the game already had.

    `mscoree,mshtml=` becomes `mshtml=;winhttp=n,b`: it removes only mscoree from the DISABLED
    list (the rest stays as the game .env decided) and adds the native winhttp.
    """
    groups = []
    for group in filter(None, (g.strip() for g in value.split(";"))):
        dlls, _, mode = group.partition("=")
        names = [d for d in (x.strip() for x in dlls.split(",")) if d and d != "winhttp"]
        if mode == "":
            names = [d for d in names if d != "mscoree"]
        if names:
            groups.append(f"{','.join(names)}={mode}")
    groups.append("winhttp=n,b")
    return ";".join(groups)


def overrides_ok(value: str) -> bool:
    return fix_overrides(value) == value


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


def _set_ini(path: str, section: str, key: str, value: str) -> None:
    """Replace `key = x` inside `[section]`; create the section if the file does not have it."""
    text = _read_text(path)
    pattern = re.compile(rf"(\[{re.escape(section)}\][^\[]*?\n{re.escape(key)}\s*=\s*)[^\n]*", re.S)
    if pattern.search(text):
        text = pattern.sub(lambda m: m.group(1) + value, text, count=1)
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + f"[{section}]\n{key} = {value}\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def set_enabled(game_dir: str, enabled: bool) -> None:
    _set_ini(os.path.join(game_dir, DOORSTOP_CONFIG), "General", "enabled",
             "true" if enabled else "false")


# ------------------------------------------------------------------ native Linux server
# Valheim (and every Unity Linux game) loads BepInEx through the doorstop .so, via LD_PRELOAD, and
# not through a Wine DLL. The variables are the ones from start_server_bepinex.sh in
# BepInExPack_Valheim 5.4.2351, read from the package; here they go into a systemd drop-in, with
# an ABSOLUTE path (the script uses ./, relative to the game folder), so the game startup wrapper
# does not need to be replaced. Disabling means deleting the drop-in: the server starts without
# any BepInEx code. NOT TESTED on a real server yet.
SYSTEMD_DIR = "/etc/systemd/system"
DROPIN = "gamepanel-bepinex.conf"
UNIT = re.compile(r"[A-Za-z0-9_.@-]{1,120}\.service")


def dropin_path(unit: str, systemd_dir: str = SYSTEMD_DIR) -> str:
    if not UNIT.fullmatch(unit or ""):
        raise ValueError(f"servico invalido: {unit!r}")
    return posixpath.join(systemd_dir, f"{unit}.d", DROPIN)


def dropin_text(game_dir: str) -> str:
    libs = posixpath.join(game_dir, "doorstop_libs")
    preloader = posixpath.join(game_dir, "BepInEx", "core", "BepInEx.Preloader.dll")
    return ("[Service]\n"
            "Environment=DOORSTOP_ENABLED=1\n"
            f"Environment=DOORSTOP_TARGET_ASSEMBLY={preloader}\n"
            f"Environment=LD_LIBRARY_PATH={libs}:{posixpath.join(game_dir, 'linux64')}\n"
            f"Environment=LD_PRELOAD={posixpath.join(libs, 'libdoorstop_x64.so')}\n")


def set_linux_enabled(game_dir: str, unit: str, enabled: bool) -> None:
    # SYSTEMD_DIR and _daemon_reload are read at call time, by the module name: that is what lets
    # the test replace them without an extra parameter in every function along the path.
    path = dropin_path(unit, SYSTEMD_DIR)
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(dropin_text(game_dir))
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    # Without daemon-reload systemd keeps the old environment until the next boot.
    _daemon_reload()


def _daemon_reload() -> None:
    subprocess.run(["systemctl", "daemon-reload"], check=False)  # noqa: S607


def _extract_pack(z: zipfile.ZipFile, prefix: str, game_dir: str, created: set[str]) -> tuple[int, set[str]]:
    """Write to the game root what is under `prefix`; return (files, root names CREATED).

    Only what the package creates is recorded - and only that is deleted on uninstall: what
    already existed before the first install belongs to the game, and what a previous install
    created (`created`) is still ours.
    """
    created = set(created)
    count = 0
    for entry in z.namelist():
        rel = _safe_rel(entry[len(prefix):]) if entry.startswith(prefix) and not entry.endswith("/") else ""
        if not rel:
            continue
        top = rel.split("/", 1)[0]
        if not os.path.exists(os.path.join(game_dir, top)):
            created.add(top)
        dest = os.path.join(game_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count, created


def install_loader(game_dir: str, ns: str, name: str, fetcher=fetch, env_path: str = RUNTIME_ENV,
                   version: str = "", scan=_no_scan, unit: str = "") -> dict:
    meta = package_meta(ns, name, version, fetcher)
    print(f"baixando {meta['full_name']}")
    data = fetcher(meta["download_url"])
    scan([(meta["full_name"], data)])
    z = zipfile.ZipFile(io.BytesIO(data))
    # The package carries a folder (BepInExPack_V_Rising/) with what goes at the game ROOT: it
    # is the one containing BepInEx/core. The rest of the zip (icon, README) is left out.
    core = next((n for n in z.namelist() if "BepInEx/core/" in n), "")
    if not core:
        raise ValueError("o pacote nao tem BepInEx/core: nao e um carregador BepInEx")
    prefix = core[: core.index("BepInEx/core/")]
    previous = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    count, created = _extract_pack(z, prefix, game_dir, set(previous.get("files", [])))
    set_enabled(game_dir, True)
    _set_ini(os.path.join(game_dir, "BepInEx", "config", "BepInEx.cfg"), "Logging.Console", "Enabled", "false")
    # The WINE_DLL_OVERRIDES from before BepInEx, so uninstall can restore it (fix_overrides
    # removes mscoree from the disabled list, and that cannot be undone without knowing how it was).
    overrides_before = previous.get("overrides_before")
    if unit:
        # Native Linux: no Wine; the loader comes in through the systemd drop-in.
        set_linux_enabled(game_dir, unit, True)
    else:
        old = _read_overrides(env_path)
        if os.path.exists(env_path):
            if overrides_before is None:
                overrides_before = old
            _write_overrides(env_path, fix_overrides(old))
    with open(os.path.join(game_dir, "BepInEx", MARK), "w", encoding="utf-8") as f:
        json.dump({"full_name": meta["full_name"], "version": meta["version_number"],
                   "pinned": bool(version), "files": sorted(created),
                   "overrides_before": overrides_before}, f)
    print(f"{count} arquivos do carregador em {game_dir}")
    return {"loader": meta["full_name"], "files": count}


# What a BepInEx package puts at the game root, for installs made before the panel recorded
# the list (a .gamepanel.json without "files"). Only BepInEx/doorstop's own names.
BEPINEX_ROOT = ("BepInEx", DOORSTOP_CONFIG, "winhttp.dll", ".doorstop_version", "doorstop_libs",
                "dotnet", "start_server_bepinex.sh")


def without_winhttp(value: str) -> str:
    return ";".join(g for g in (x.strip() for x in value.split(";")) if g and g != "winhttp=n,b")


def set_loader(game_dir: str, unit: str, enabled: bool) -> None:
    set_enabled(game_dir, enabled)
    if unit:
        set_linux_enabled(game_dir, unit, enabled)


def uninstall_loader(game_dir: str, env_path: str = RUNTIME_ENV, unit: str = "") -> dict:
    """Remove BepInEx and what it changed in the game: the game starts again without any of its code.

    The plugins live inside BepInEx/ and go along (the screen warns first). WINE_DLL_OVERRIDES
    goes back to what it was before the install; without it recorded, only winhttp=n,b is removed
    (the mscoree that BepInEx re-enabled stays - harmless without BepInEx).
    """
    mark = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    names = mark.get("files") or BEPINEX_ROOT
    if unit:
        set_linux_enabled(game_dir, unit, False)
    elif os.path.exists(env_path):
        before = mark.get("overrides_before")
        _write_overrides(env_path, before if isinstance(before, str) else without_winhttp(_read_overrides(env_path)))
    removed = []
    for name in names:
        # Only a root name, never a path: what comes from the mark must not leave the game folder.
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        path = os.path.join(game_dir, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        else:
            continue
        removed.append(name)
    print(f"BepInEx desinstalado de {game_dir}: {', '.join(removed) or 'nada a apagar'}")
    return {"uninstalled": True, "removed": removed}


# ------------------------------------------------------------------ plugins

def _plugins_dir(game_dir: str) -> str:
    return os.path.join(game_dir, "BepInEx", "plugins")


def _plugin_rel(entry: str) -> tuple[str, str]:
    """Where a file from a plugin zip goes: ('plugins'|'config', relative path)."""
    rel = _safe_rel(entry)
    if not rel or posixpath.basename(rel).lower() in SKIP:
        return "", ""
    for head, target in (("BepInEx/plugins/", "plugins"), ("plugins/", "plugins"),
                         ("BepInEx/config/", "config"), ("config/", "config")):
        if rel.startswith(head):
            return target, rel[len(head):]
    return "plugins", rel


def _install_one(game_dir: str, meta: dict, data: bytes, pinned: bool) -> int:
    ns, name = meta["full_name"].split("-")[0], meta["name"]
    target = os.path.join(_plugins_dir(game_dir), f"{check_part(ns)}-{check_part(name)}")
    shutil.rmtree(target, ignore_errors=True)  # the new version replaces the old one entirely
    os.makedirs(target, exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(data))
    count = 0
    for entry in z.namelist():
        if entry.endswith("/"):
            continue
        kind, rel = _plugin_rel(entry)
        if not kind:
            continue
        base = target if kind == "plugins" else os.path.join(game_dir, "BepInEx", "config")
        dest = os.path.join(base, rel)
        # A config that already exists belongs to the server owner: the package only brings the default.
        if kind == "config" and os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with z.open(entry) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    with open(os.path.join(target, MARK), "w", encoding="utf-8") as f:
        json.dump({"full_name": meta["full_name"], "version": meta["version_number"],
                   "dependencies": meta.get("dependencies", []), "pinned": pinned}, f)
    return count


def install_plugin(game_dir: str, ns: str, name: str, fetcher=fetch, loader_ns: str = "BepInEx",
                   version: str = "", scan=_no_scan) -> dict:
    """The package and its dependencies (except BepInEx itself, which has its own button).

    With a pinned version, the dependencies come in the version THAT version declares, and not
    the newest: whoever pins a version wants the set the author tested, and a dependency that is
    too new is exactly the kind of thing that breaks the mod one wanted to hold back. The
    consequence: a dependency shared with another mod may go back to an older version.

    Downloads EVERYTHING before writing anything: there is a single check, and a rejected
    dependency does not leave the main mod half installed.
    """
    pinned = bool(version)
    queue = [(check_part(ns), check_part(name), check_version(version) if pinned else "")]
    done: set[tuple[str, str]] = set()
    downloaded: list[tuple[dict, bytes]] = []
    while queue:
        pns, pname, pversion = queue.pop(0)
        if (pns, pname) in done:
            continue
        done.add((pns, pname))
        if len(done) > MAX_PACKAGES:
            raise ValueError(f"mais de {MAX_PACKAGES} pacotes na arvore de dependencias")
        meta = package_meta(pns, pname, pversion, fetcher)
        print(f"baixando {meta['full_name']}")
        downloaded.append((meta, fetcher(meta["download_url"])))
        for dep in meta.get("dependencies", []):
            dns, dname, dversion = _dependency(dep)
            if dns == loader_ns and dname.startswith("BepInExPack"):
                continue
            queue.append((dns, dname, dversion if pinned else ""))
    scan([(meta["full_name"], data) for meta, data in downloaded])
    installed = []
    for meta, data in downloaded:
        print(f"instalando {meta['full_name']}")
        installed.append({"full_name": meta["full_name"], "files": _install_one(game_dir, meta, data, pinned)})
    return {"installed": installed}


def remove_plugin(game_dir: str, ns: str, name: str) -> dict:
    target = os.path.join(_plugins_dir(game_dir), f"{check_part(ns)}-{check_part(name)}")
    existed = os.path.isdir(target)
    shutil.rmtree(target, ignore_errors=True)
    return {"removed": existed}


def status(game_dir: str, env_path: str = RUNTIME_ENV, unit: str = "") -> dict:
    plugins = []
    pdir = _plugins_dir(game_dir)
    for entry in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        # A folder placed by hand, without the installer mark: it shows up by name.
        # A mark from before pinnable versions has no `pinned`: it was the newest, so False.
        plugins.append({"dir": entry, "full_name": entry, "version": "", "pinned": False,
                        **_read_json(os.path.join(pdir, entry, MARK))})
    loader = _read_json(os.path.join(game_dir, "BepInEx", MARK))
    ini = _read_text(os.path.join(game_dir, DOORSTOP_CONFIG))
    if unit:
        enabled = os.path.exists(dropin_path(unit, SYSTEMD_DIR))
    else:
        enabled = re.search(r"(?m)^enabled\s*=\s*true", ini) is not None
    mem_kb = 0
    for line in _read_text("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:") and line.split()[1].isdigit():
            mem_kb = int(line.split()[1])
    return {
        "loader_installed": os.path.isdir(os.path.join(game_dir, "BepInEx", "core")),
        "loader": loader.get("full_name", ""), "loader_version": loader.get("version", ""),
        "loader_pinned": bool(loader.get("pinned")),
        "enabled": enabled,
        # Native Linux has no Wine: there is no Wine setting to check.
        "overrides_ok": bool(unit) or not os.path.exists(env_path) or overrides_ok(_read_overrides(env_path)),
        "memory_mb": mem_kb // 1024,
        "plugins": plugins,
    }


def _chown(path: str) -> None:
    """The game runs as 'steam' and needs to read (and BepInEx, to write) what came in."""
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, files in os.walk(path):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


INSTALL_ACTIONS = ("loader-install", "plugin-install")


def run(action: str, game_dir: str, loader: tuple[str, str], rest: list[str], unit: str, scan) -> dict:
    """Run one action; `main` only reads argv and turns errors into JSON."""
    loader_ns, loader_name = loader
    if action == "status":
        return status(game_dir, unit=unit)
    if action == "loader-install":
        return install_loader(game_dir, loader_ns, loader_name, version=rest[0] if rest else "", scan=scan,
                              unit=unit)
    if action in ("loader-enable", "loader-disable"):
        set_loader(game_dir, unit, action == "loader-enable")
        return {"enabled": action == "loader-enable"}
    if action == "loader-uninstall":
        return uninstall_loader(game_dir, unit=unit)
    if action == "plugin-install":
        return install_plugin(game_dir, rest[0], rest[1], loader_ns=loader_ns,
                              version=rest[2] if len(rest) > 2 else "", scan=scan)
    if action == "plugin-remove":
        return remove_plugin(game_dir, rest[0], rest[1])
    raise ValueError(f"acao desconhecida: {action}")


def main(argv: list[str]) -> int:
    script = unit = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    # Native Linux server (Valheim): the loader comes in through a systemd drop-in of this service.
    if argv[:1] == ["--unit"]:
        unit, argv = argv[1], argv[2:]
    action, game_dir, loader_ns, loader_name, *rest = argv
    scan = scanner(script) if script else _no_scan
    try:
        if action in INSTALL_ACTIONS and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        result = run(action, game_dir, (loader_ns, loader_name), rest, unit, scan)
        if action not in ("status", "loader-uninstall"):
            _chown(os.path.join(game_dir, "BepInEx"))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
