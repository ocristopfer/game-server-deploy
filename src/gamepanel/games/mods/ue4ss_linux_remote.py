"""UE4SS for native LINUX Unreal games (our fork of the official one) - runs INSIDE the game CT.

Same design as the other remote installers: the panel reads this text and runs it in the
container with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel`.

The loader is the OFFICIAL UE4SS built for Linux (ocristopfer/RE-UE4SS, branch `linux`), and
no longer a port: the same mechanisms (patternsleuth scan, UE4SS_Signatures, VTableLayout.ini,
Lua mods), with what Linux requires and the layouts of each engine version generated from Epic's
code. Proven on a real server (Docker) with Dragonwilds (UE 5.6.1) and Palworld (UE 5.1.1): Lua,
FindFirstOf, RegisterHook on Blueprint and native, ExecuteInGameThread.
The old "fork" mode (ocristopfer/ue4ss-linux, UE4SS_Addresses.ini) and the XarminaEu port are
gone: both brought Palworld down.

What the install does, each step with its reason:
- **The profile's pinned tag** (`--release`), and each file checked against the release
  SHA256SUMS BEFORE the antivirus.
- **The official layout: `ue4ss/` next to the executable** (libUE4SS.so, UE4SS-settings.ini, Mods/).
  UE4SS finds the config, the mods and the log in its own library's folder.
- **The .so is written alongside and moved over** (`rename`): copying over the file while the
  server is running corrupts the in-memory mapping.
- **Files from the .sym, when the server ships one** (`--symfiles`, the text of the panel's
  ue_sym_layout): VTableLayout.ini and UE4SS_Signatures/*.lua for this executable. An engine
  modified by the studio (Dragonwilds adds virtuals to AActor) only runs right with them. They are
  regenerated on every install: a game update changes the addresses, and the old ones would bring
  the server down.
- **Without a .sym, the version's reference pack** (`--layout`, the text of the panel's
  ue_linux_layout, plus the release's pack-<version>.json): every studio tweaks the engine classes
  (Soulmask has 62 extra virtuals in AGameModeBase, The Front 0x18 extra bytes in
  FUObjectArray), and the per-version built-in layout is not enough. The generator aligns this
  game's exported vtables with those of a reference game of the same version, by the code of each
  function, and finds the signatures by the shortest piece of reference code that matches here.
  With a .sym it runs too, only for the globals (GMalloc, console manager, GUObjectArray) and
  FUObjectArray. A version with no pack in the release and no .sym keeps the built-in layout
  (Palworld, 5.1).
- **The owner's config and mods.txt are preserved**; `Mods/shared` (the Lua libraries many mods
  require, UEHelpers) comes from the release and is replaced entirely.
- **Migrates the old fork's install** (everything next to the executable): the Lua mods go to
  `ue4ss/Mods`, and only the files the old fork wrote are removed.
- **LD_PRELOAD in a systemd drop-in**, without replacing the game startup script. The library
  only starts in a process whose executable has `-Linux-` in its name: the script and whatever it
  calls are left out. Disabling means deleting the drop-in (no UE4SS code runs, without deleting
  any mod).

Actions (argv): [--scan SCRIPT] --unit SERVICE [--release TAG --engine X.Y --symfiles SCRIPT --layout SCRIPT]
status|loader-install|loader-enable|loader-disable|loader-uninstall|mod-remove, followed by the executable
folder (Binaries/Linux) and, for mod-remove, the Lua mod names. Ends with ONE JSON line.
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
import tarfile
import tempfile
import urllib.request

RELEASE = "https://api.github.com/repos/ocristopfer/RE-UE4SS/releases/tags/{tag}"
RELEASE_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
ENGINE = re.compile(r"(\d{1,2})\.(\d{1,2})")
SHA256 = re.compile(r"[0-9a-f]{64}")
SUMS = "SHA256SUMS"
LIB = "libUE4SS.so"
SETTINGS = "UE4SS-settings.ini"
SHARED = "ue4ss-mods-shared.tar.gz"
TEMPLATES = "VTableLayoutTemplates.tar.gz"
PACKS = "LinuxReferencePacks.tar.gz"
RELEASE_FILES = (LIB, SETTINGS, SHARED, TEMPLATES, PACKS)
UE4SS_DIR = "ue4ss"
LOG = "UE4SS.log"
MODS = "Mods"
MODS_TXT = "mods.txt"
SHARED_DIR = "shared"
VTABLE_INI = "VTableLayout.ini"
MEMBER_INI = "MemberVariableLayout.ini"
SIGNATURES_DIR = "UE4SS_Signatures"
# Header ue_sym_layout puts in the ini: only files carrying it are deleted on a reinstall without .sym.
GENERATED_MARK = "; Gerado pelo painel"
SIGNATURE_FILES = ("FName_ToString.lua", "FName_Constructor.lua", "StaticConstructObject.lua", "GNatives.lua",
                   "GMalloc.lua", "ConsoleManager.lua", "GUObjectArray.lua", "GUObjectHashTables.lua")
GENERATED_FILES = frozenset({VTABLE_INI, MEMBER_INI} | {f"{SIGNATURES_DIR}/{n}" for n in SIGNATURE_FILES})
MARK = ".gamepanel-ue4ss-linux.json"
# What the old fork (ocristopfer/ue4ss-linux) left next to the executable.
OLD_FILES = (LIB, SETTINGS, LOG, "UE4SS_Addresses.ini", VTABLE_INI, "MemberVariableLayout.ini", MARK)
SYSTEMD_DIR = "/etc/systemd/system"
DROPIN = "gamepanel-ue4ss.conf"
UNIT = re.compile(r"[A-Za-z0-9_.@-]{1,120}\.service")
EXE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,120}")
OWNER = "steam"
TIMEOUT = 120
# Scanning the .sym (300 MB, ~12 million records) and the executable takes on the order of a minute.
SYMFILES_TIMEOUT = 900
LOG_TAIL = 15


def fetch(url: str) -> bytes:
    # Only github.com https gets here: the API is fixed (RELEASE) and the download comes from its
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


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _read_json(path: str) -> dict:
    with contextlib.suppress(ValueError):
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    return {}


def _write(path: str, data: bytes) -> None:
    staged = path + ".new"
    with open(staged, "wb") as f:
        f.write(data)
    os.replace(staged, path)


# ------------------------------------------------------------------ systemd

def dropin_path(unit: str) -> str:
    if not UNIT.fullmatch(unit or ""):
        raise ValueError(f"servico invalido: {unit!r}")
    return posixpath.join(SYSTEMD_DIR, f"{unit}.d", DROPIN)


def _daemon_reload() -> None:
    subprocess.run(["systemctl", "daemon-reload"], check=False)  # noqa: S607


def loader_env(exe_dir: str, executable: str = "") -> dict[str, str]:
    """The variables that load UE4SS into the game, in the order the drop-in has always had them."""
    if not executable:
        # Re-enabling without reinstalling: the executable is the one the install recorded in the mark.
        executable = _read_json(os.path.join(exe_dir, UE4SS_DIR, MARK)).get("executable", "")
    env = {"LD_PRELOAD": posixpath.join(exe_dir, UE4SS_DIR, LIB)}
    # The library only starts in an executable with -Linux- in its name; TheFrontServer,
    # SquadGameServer and AstroColonyServer do not have it, and without the name here UE4SS never starts in them.
    if executable and "-Linux-" not in executable and EXE_NAME.fullmatch(executable):
        env["UE4SS_TARGET_EXE"] = executable
    return env


def set_enabled(exe_dir: str, unit: str, enabled: bool, executable: str = "", overlay: bool = False) -> None:
    if overlay:
        # Helper mode: steam's service.env, which the game unit reads at every start (no daemon-reload).
        env = loader_env(exe_dir, executable) if enabled else {}
        for key in ("LD_PRELOAD", "UE4SS_TARGET_EXE"):
            overlay_set(OVERLAY_SERVICE, key, env.get(key))
        return
    path = dropin_path(unit)
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = ["[Service]", *(f"Environment={k}={v}" for k, v in loader_env(exe_dir, executable).items())]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
    # Without daemon-reload systemd keeps the old environment until the next boot.
    _daemon_reload()


# ------------------------------------------------------------------ the release

class Release:
    """What the install needs to know from the profile: the release tag, the engine version and
    the generator of the .sym files."""

    def __init__(self, tag: str, engine: str, symfiles_script: str, layout_script: str = "") -> None:
        if not RELEASE_TAG.fullmatch(tag or ""):
            raise ValueError(f"tag do release invalida: {tag!r}")
        if not ENGINE.fullmatch(engine or ""):
            raise ValueError(f"versao do motor invalida: {engine!r}")
        self.tag, self.engine, self.symfiles_script = tag, engine, symfiles_script
        self.layout_script = layout_script

    @property
    def pack_name(self) -> str:
        """pack-4.27.json for engine 4.27 (the release's reference packs)."""
        found = ENGINE.fullmatch(self.engine)
        if not found:
            raise ValueError(f"versao do motor invalida: {self.engine!r}")
        return f"pack-{int(found.group(1))}.{int(found.group(2))}.json"

    @property
    def template_name(self) -> str:
        """VTableLayout_5_06_Template.ini for engine 5.6 (the UE4SS template names)."""
        found = ENGINE.fullmatch(self.engine)
        if not found:
            raise ValueError(f"versao do motor invalida: {self.engine!r}")
        major, minor = found.groups()
        return f"VTableLayout_{int(major)}_{int(minor):02d}_Template.ini"


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum` -> {name: hash}. A malformed line is ignored: a file without a hash is rejected later."""
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and SHA256.fullmatch(parts[0]):
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def release_files(release: Release, fetcher=fetch) -> dict[str, bytes]:
    """The release files, each checked against its SHA256SUMS. The reference packs arrived in
    linux-v2: a release that does not ship them installs as before."""
    data = json.loads(fetcher(RELEASE.format(tag=release.tag)))
    urls = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
    wanted = [n for n in RELEASE_FILES if n != PACKS or n in urls]
    for name in (SUMS, *wanted):
        if not urls.get(name, "").startswith("https://github.com/"):
            raise ValueError(f"o release {release.tag} nao traz {name}")
    sums = parse_sums(fetcher(urls[SUMS]).decode("utf-8", "replace"))
    files = {}
    for name in wanted:
        print(f"baixando {name}")
        blob = fetcher(urls[name])
        if hashlib.sha256(blob).hexdigest() != sums.get(name):
            raise ValueError(f"{name} nao confere com o SHA256SUMS do release: nada foi instalado")
        files[name] = blob
    return files


def _safe_members(tar: tarfile.TarFile, root: str) -> list[tarfile.TarInfo]:
    """Only regular files and folders, inside `root/`: no absolute path, `..` or link."""
    members = []
    for member in tar.getmembers():
        name = posixpath.normpath(member.name)
        if name.startswith(("/", "..")) or not (name == root or name.startswith(root + "/")):
            raise ValueError(f"o pacote traz um caminho inesperado: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise ValueError(f"o pacote traz algo que nao e arquivo: {member.name!r}")
        members.append(member)
    return members


def install_shared(mods_dir: str, data: bytes) -> None:
    """Replace the whole Mods/shared with the release one (the Lua libraries; owner mods do not live there)."""
    target = os.path.join(mods_dir, SHARED_DIR)
    staged = target + ".new"
    shutil.rmtree(staged, ignore_errors=True)
    os.makedirs(staged)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in _safe_members(tar, SHARED_DIR):
            src = tar.extractfile(member) if member.isfile() else None
            if src is None:
                continue
            path = os.path.join(staged, posixpath.relpath(posixpath.normpath(member.name), SHARED_DIR))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with src, open(path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staged, target)


def template_text(release: Release, data: bytes) -> str:
    """The VTableLayout template for this engine version, from inside the release package."""
    wanted = f"VTableLayoutTemplates/{release.template_name}"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in _safe_members(tar, "VTableLayoutTemplates"):
            src = tar.extractfile(member) if member.isfile() else None
            if src is not None and posixpath.normpath(member.name) == wanted:
                return src.read().decode("utf-8", "replace")
    raise ValueError(f"o release nao tem o template {release.template_name}: motor {release.engine} nao suportado")


def pack_text(release: Release, data: bytes | None) -> str:
    """The reference pack for this engine version ('' when the release has none for it)."""
    if not data:
        return ""
    wanted = f"LinuxReferencePacks/{release.pack_name}"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in _safe_members(tar, "LinuxReferencePacks"):
            src = tar.extractfile(member) if member.isfile() else None
            if src is not None and posixpath.normpath(member.name) == wanted:
                return src.read().decode("utf-8", "replace")
    return ""


# ------------------------------------------------------------------ files from the .sym and the pack

def find_executable(exe_dir: str) -> str:
    """The server executable: the one with a `.sym` next to it, otherwise the largest ELF in the folder
    (the startup script, the .so files and the symbol files are left out). '' if there is none."""
    best, size = "", -1
    for name in sorted(os.listdir(exe_dir)):
        path = os.path.join(exe_dir, name)
        if not os.path.isfile(path) or name.endswith((".so", ".sym", ".debug")) or ".so." in name:
            continue
        if os.path.isfile(path + ".sym"):
            return path
        with open(path, "rb") as f:
            if f.read(4) != b"\x7fELF":
                continue
        if os.path.getsize(path) > size:
            best, size = path, os.path.getsize(path)
    return best


def generate_symfiles(executable: str, script: str, template: str) -> dict[str, str]:
    """{path relative to ue4ss/: text} from the panel generator, based on the .sym."""
    print(f"gerando VTableLayout.ini e UE4SS_Signatures a partir de {posixpath.basename(executable)}.sym")
    sys.stdout.flush()
    with tempfile.NamedTemporaryFile("w", suffix=".ini", encoding="utf-8", delete=False) as f:
        f.write(template)
        template_path = f.name
    try:
        # The script is the panel generator (its fixed text); the path was found in this folder.
        proc = subprocess.run(["python3", "-c", script, executable, template_path],  # noqa: S603, S607
                              capture_output=True, text=True, check=False, timeout=SYMFILES_TIMEOUT)
    finally:
        os.remove(template_path)
    if proc.returncode != 0:
        raise ValueError(f"o gerador dos arquivos do .sym falhou: {(proc.stderr or '').strip()[-300:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    for line in result.get("report", []):
        print(f"  {line}")
    files = result.get("files", {})
    if not isinstance(files, dict) or set(files) - GENERATED_FILES:
        raise ValueError("o gerador devolveu arquivos inesperados: nada foi gravado")
    return files


def generate_layout(executable: str, script: str, pack: str, with_sym: bool) -> dict[str, str]:
    """{path relative to ue4ss/: text} from the reference pack generator (ue_linux_layout)."""
    print(f"gerando os arquivos de {posixpath.basename(executable)} a partir do pacote de referencia")
    sys.stdout.flush()
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
        f.write(pack)
        pack_path = f.name
    try:
        args = [executable, pack_path] + (["--com-sym"] if with_sym else [])
        # The script is the panel generator (its fixed text); the executable was found in this folder.
        proc = subprocess.run(["python3", "-c", script, *args],  # noqa: S603, S607
                              capture_output=True, text=True, check=False, timeout=SYMFILES_TIMEOUT)
    finally:
        os.remove(pack_path)
    if proc.returncode != 0:
        raise ValueError(f"o gerador do pacote de referencia falhou: {(proc.stderr or '').strip()[-300:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    for line in result.get("report", []):
        print(f"  {line}")
    files = result.get("files", {})
    if not isinstance(files, dict) or set(files) - GENERATED_FILES:
        raise ValueError("o gerador devolveu arquivos inesperados: nada foi gravado")
    return files


def remove_generated(ue4ss_dir: str) -> None:
    """Delete what a .sym generated before - only the panel files, never a hand-written ini."""
    for name in (VTABLE_INI, MEMBER_INI):
        ini = os.path.join(ue4ss_dir, name)
        if _read_text(ini).startswith(GENERATED_MARK):
            os.remove(ini)
    for name in SIGNATURE_FILES:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(ue4ss_dir, SIGNATURES_DIR, name))


# ------------------------------------------------------------------ installation

def migrate_old_layout(exe_dir: str, ue4ss_dir: str) -> None:
    """The old fork left everything next to the executable: the Lua mods come to ue4ss/Mods and
    its files are removed. Only acts if its mark is there (an install made by the panel itself)."""
    if not os.path.exists(os.path.join(exe_dir, MARK)):
        return
    old_mods, new_mods = os.path.join(exe_dir, MODS), os.path.join(ue4ss_dir, MODS)
    if os.path.isdir(old_mods) and not os.path.exists(new_mods):
        print("movendo os mods Lua da instalacao antiga para ue4ss/Mods")
        os.replace(old_mods, new_mods)
    for name in OLD_FILES:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(exe_dir, name))


def install_loader(exe_dir: str, unit: str, release: Release, fetcher=fetch, scan=_no_scan,
                   overlay: bool = False) -> dict:
    if not os.path.isdir(exe_dir):
        raise ValueError(f"a pasta do executavel nao existe: {exe_dir}")
    dropin_path(unit)  # check the service before downloading anything
    files = release_files(release, fetcher)
    scan(sorted(files.items()))
    executable = find_executable(exe_dir)
    with_sym = bool(executable) and os.path.isfile(executable + ".sym")
    symfiles: dict[str, str] = {}
    # BEFORE touching the folder: a .sym or an executable the generator does not understand stops
    # everything, with no half install.
    if with_sym:
        if not release.symfiles_script:
            raise ValueError("o servidor traz .sym, mas o painel nao mandou o gerador dos arquivos dele")
        symfiles = generate_symfiles(executable, release.symfiles_script, template_text(release, files[TEMPLATES]))
    pack = pack_text(release, files.get(PACKS))
    if executable and pack and release.layout_script:
        layout = generate_layout(executable, release.layout_script, pack, with_sym)
        # What came from this executable's .sym is worth more than what was transposed from the reference.
        symfiles = {**layout, **symfiles}
    elif executable and not with_sym:
        print(f"sem pacote de referencia do motor {release.engine} neste release: layout embutido")
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    os.makedirs(ue4ss_dir, exist_ok=True)
    migrate_old_layout(exe_dir, ue4ss_dir)
    target = os.path.join(ue4ss_dir, LIB)
    staged = target + ".new"
    with open(staged, "wb") as f:
        f.write(files[LIB])
    os.chmod(staged, 0o755)  # noqa: S103
    # Over it with rename: the server may have the old .so mapped in memory.
    os.replace(staged, target)
    settings = os.path.join(ue4ss_dir, SETTINGS)
    if not os.path.exists(settings):
        _write(settings, files[SETTINGS])
    mods_dir = os.path.join(ue4ss_dir, MODS)
    os.makedirs(mods_dir, exist_ok=True)
    install_shared(mods_dir, files[SHARED])
    mods_txt = os.path.join(mods_dir, MODS_TXT)
    if not os.path.exists(mods_txt):
        _write(mods_txt, b"")
    remove_generated(ue4ss_dir)
    for rel, text in symfiles.items():
        path = os.path.join(ue4ss_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write(path, text.encode("utf-8"))
    exe_name = os.path.basename(executable) if executable else ""
    set_enabled(exe_dir, unit, True, exe_name, overlay)
    with open(os.path.join(ue4ss_dir, MARK), "w", encoding="utf-8") as f:
        json.dump({"version": release.tag, "sym_files": sorted(symfiles), "executable": exe_name}, f)
    extra = f", {len(symfiles)} arquivo(s) gerado(s)" if symfiles else ", layouts embutidos"
    print(f"UE4SS {release.tag} em {ue4ss_dir} (LD_PRELOAD no {unit}{extra})")
    return {"loader": "UE4SS Linux", "version": release.tag}


def uninstall_loader(exe_dir: str, unit: str, overlay: bool = False) -> dict:
    """Remove UE4SS: the drop-in (the game starts again without LD_PRELOAD) and the whole ue4ss/ folder.

    The Lua mods live in ue4ss/Mods and go along (the screen warns first); the game's .pak files
    are not UE4SS's and stay. Leftovers from the old fork's install (next to the executable, with
    its mark) are removed too, with its Mods/ - only the names the fork used to write.
    """
    set_enabled(exe_dir, unit, False, overlay=overlay)
    removed = []
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    if os.path.isdir(ue4ss_dir) and not os.path.islink(ue4ss_dir):
        shutil.rmtree(ue4ss_dir)
        removed.append(UE4SS_DIR)
    if os.path.exists(os.path.join(exe_dir, MARK)):
        for name in (*OLD_FILES, MODS):
            path = os.path.join(exe_dir, name)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.remove(path)
            else:
                continue
            removed.append(name)
    print(f"UE4SS desinstalado de {exe_dir}: {', '.join(removed) or 'nada a apagar'} (sem LD_PRELOAD no {unit})")
    return {"uninstalled": True, "removed": removed}


# ------------------------------------------------------------------ Lua mod removal
# IDENTICAL in ue4ss_remote.py and ue4ss_linux_remote.py (a test compares them): both run
# standalone in the CT and do not import each other. A Lua mod is a FOLDER in Mods/ plus its
# `Name : 1` line in mods.txt. Deleting only the folder leaves UE4SS looking for a mod that is gone
# on every start; rewriting the whole mods.txt would lose the owner's comments, order and line
# endings - so only the lines of the removed names go, and every other byte stays.
LUA_MOD_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+ -]{0,127}")
# The Lua libraries other mods `require` (UEHelpers): not a mod, and removing it breaks the rest.
LUA_PROTECTED = ("shared",)


def under_link(path: str) -> bool:
    """True when `path` or any folder above it is a symbolic link.

    realpath() against abspath() would say the same on Linux, but also flags Windows 8.3 short names
    (PROGRA~1) in the tests. What matters is the link: the game can plant one in a folder it
    writes, and an rmtree run as root through it deletes wherever it points.
    """
    path = os.path.abspath(path)
    while True:
        if os.path.islink(path):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def without_mod_lines(text: str, names: set[str]) -> str:
    """mods.txt without the lines of `names`; the BOM, CRLF and comments stay as they were."""
    out = []
    for line in text.splitlines(keepends=True):
        body = line.lstrip("﻿")
        name, sep, _ = body.partition(":")
        if sep and not body.lstrip().startswith(";") and name.strip() in names:
            # The BOM belongs to the FILE, not to the first line: it stays even when that line goes.
            out.append(line[: len(line) - len(body)])
            continue
        out.append(line)
    return "".join(out)


def remove_lua_mods(mods_dir: str, names: list[str]) -> dict:
    """Remove Lua mods from Mods/ by NAME (never a path), and their mods.txt lines."""
    for name in names:
        if not LUA_MOD_NAME.fullmatch(name) or name.lower() in LUA_PROTECTED:
            raise ValueError(f"invalid mod name: {name!r}")
    # Mods/ being a link (or living under one) would make rmtree delete wherever it points: in
    # legacy mode this runs as root, and the folder is one the game itself can write.
    if under_link(mods_dir):
        raise ValueError(f"the mods folder is (or is under) a link: {mods_dir}")
    removed = []
    for name in names:
        path = os.path.join(mods_dir, name)
        if os.path.islink(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            # A loose file is not a Lua mod (mods.txt itself would match the name rule).
            raise ValueError(f"{name} is not a mod folder")
        else:
            print(f"{name}: no such folder (only its mods.txt line goes)")
            continue
        removed.append(name)
    mods_txt = os.path.join(mods_dir, "mods.txt")
    if os.path.isfile(mods_txt) and not os.path.islink(mods_txt):
        # newline="" and surrogateescape: the file comes back byte for byte, CRLF and odd bytes included.
        with open(mods_txt, encoding="utf-8", errors="surrogateescape", newline="") as f:
            text = f.read()
        new = without_mod_lines(text, set(names))
        if new != text:
            # In place (same inode): the owner and the mode stay the ones the game expects.
            with open(mods_txt, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                f.write(new)
    print(f"Lua mods removed from {mods_dir}: {', '.join(removed) or 'no folder'}")
    return {"removed": removed}
# ------------------------------------------------------------------ end of the Lua mod removal


def enabled_mods(text: str) -> dict[str, bool]:
    result = {}
    for line in text.lstrip("﻿").splitlines():
        name, sep, flag = line.partition(":")
        if sep and not line.lstrip().startswith(";"):
            result[name.strip()] = flag.strip() == "1"
    return result


def overlay_problem(unit: str) -> str:
    """Helper mode: why LD_PRELOAD would not reach the game ('' = it will)."""
    return overlay_unit_problem(unit, dropin_path(unit))


def status(exe_dir: str, unit: str, overlay: bool = False) -> dict:
    ue4ss_dir = os.path.join(exe_dir, UE4SS_DIR)
    mods_dir = os.path.join(ue4ss_dir, MODS)
    flags = enabled_mods(_read_text(os.path.join(mods_dir, MODS_TXT)))
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        # `shared` is a library, not a mod: it is not listed and has no on/off switch.
        if entry != SHARED_DIR and os.path.isdir(os.path.join(mods_dir, entry)):
            mods.append({"name": entry, "enabled": flags.get(
                entry, os.path.exists(os.path.join(mods_dir, entry, "enabled.txt")))})
    mark = _read_json(os.path.join(ue4ss_dir, MARK))
    return {
        "loader_installed": os.path.exists(os.path.join(ue4ss_dir, LIB)),
        "loader": "UE4SS Linux", "loader_version": mark.get("version", ""),
        "loader_pinned": False,
        "sym_files": mark.get("sym_files", []),
        "enabled": os.path.exists(dropin_path(unit)) or (
            overlay and overlay_get(OVERLAY_SERVICE, "LD_PRELOAD") == posixpath.join(exe_dir, UE4SS_DIR, LIB)),
        "overlay_problem": overlay_problem(unit) if overlay else "",
        # The old fork's install is still in place: reinstalling migrates it.
        "old_layout": os.path.exists(os.path.join(exe_dir, MARK)),
        "mods": mods,
        "log": _read_text(os.path.join(ue4ss_dir, LOG)).splitlines()[-LOG_TAIL:],
    }


def _chown(exe_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    # The game runs as steam and UE4SS writes the log and the configs inside ue4ss/.
    for root, dirs, files in os.walk(os.path.join(exe_dir, UE4SS_DIR)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def parse_options(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """The leading options, in the order the panel sends them; the rest is the action and the folder.

    `--overlay` (helper mode: LD_PRELOAD goes to steam's overlay) takes no value.
    """
    options: dict[str, str] = {}
    if argv[:1] == ["--overlay"]:
        options["overlay"], argv = "1", argv[1:]
    for flag in ("--scan", "--unit"):
        if argv[:1] == [flag]:
            options[flag[2:]], argv = argv[1], argv[2:]
    while argv[:1] and argv[0] in ("--release", "--engine", "--symfiles", "--layout"):
        options[argv[0][2:]], argv = argv[1], argv[2:]
    return options, argv


def main(argv: list[str]) -> int:
    options, argv = parse_options(argv)
    script, unit, overlay = options.get("scan", ""), options.get("unit", ""), "overlay" in options
    action, exe_dir, *rest = argv
    try:
        if action == "loader-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        # Before downloading anything: a setting that would not reach the game is a broken install.
        # Removing a Lua mod touches no environment, so a CT without the overlay can still do it.
        if overlay and action not in ("status", "mod-remove") and overlay_problem(unit):
            raise ValueError(overlay_problem(unit))
        if action == "status":
            result = status(exe_dir, unit, overlay)
        elif action == "mod-remove":
            result = remove_lua_mods(os.path.join(exe_dir, UE4SS_DIR, MODS), rest)
        elif action == "loader-install":
            release = Release(options.get("release", ""), options.get("engine", ""),
                              options.get("symfiles", ""), options.get("layout", ""))
            result = install_loader(exe_dir, unit, release, scan=scanner(script), overlay=overlay)
        elif action in ("loader-enable", "loader-disable"):
            set_enabled(exe_dir, unit, action == "loader-enable", overlay=overlay)
            result = {"enabled": action == "loader-enable"}
        elif action == "loader-uninstall":
            result = uninstall_loader(exe_dir, unit, overlay)
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action not in ("status", "loader-uninstall", "mod-remove"):
            _chown(exe_dir)
    except (ValueError, KeyError, OSError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
