"""Satisfactory mods (SML and what runs on it) - runs INSIDE the game CT, not in the panel.

Same design as the other remote installers: the panel reads this text and runs it in the
container with `python3 -c`, over SSH, as root. Stdlib only and no import of `gamepanel`.

Why the ficsit.app API, and not ficsit-cli: ficsit-cli (v0.7.1, checked) has no command to ADD
a mod - only the interactive UI or editing its profiles.json by hand. The API is the same one
it uses underneath, public and without login, and for each version it gives the package of
each target (Windows, WindowsServer, LinuxServer), the sha256 and the dependencies.

Decisions, each with its reason:
- **Only the `LinuxServer` target.** The server here is native Linux; a version without that
  target does not run on it and is skipped.
- **The API sha256 is checked BEFORE the antivirus.** A package swapped along the way does not
  even get to be scanned.
- **Dependencies come along, in the version the mod's condition asks for** (`^3.12.0`, `>=1.2.0`):
  the newest that satisfies it. Everything is downloaded and checked at once before any file
  goes in, as with Thunderstore: a rejected dependency does not leave the mod half installed.
- **Each mod in its own folder, replaced entirely** (`FactoryGame/Mods/<reference>`): the new
  version does not inherit a file the old one had and the new one does not.
- **SML is a mod like the others** (the `SML` reference): installing any mod brings it as a
  dependency, and the loader button just installs it on its own.

NOT TESTED on a real server yet: the package layout (the zip root is the plugin folder, with
`SML.uplugin`) was checked by downloading SML 3.12.0 through the API, and nothing else.

Actions (argv): [--scan SCRIPT] status | mod-install REF [VERSION] | mod-remove REF, followed by the
game folder (where FactoryServer.sh lives). Every action ends with ONE JSON line.
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

API = "https://api.ficsit.app"
QUERY = API + "/v2/query"
TARGET = "LinuxServer"
# A ficsit.app mod reference: it becomes a folder name and part of a query.
REF = re.compile(r"[A-Za-z0-9_]{1,64}")
VERSION = re.compile(r"\d{1,9}\.\d{1,9}\.\d{1,9}")
MODS = os.path.join("FactoryGame", "Mods")
MARK = ".gamepanel.json"
OWNER = "steam"
TIMEOUT = 120
MAX_PACKAGES = 25
VERSIONS_PER_MOD = 50
GRAPHQL = """query($ref: ModReference!, $limit: Int!) {
  getModByReference(modReference: $ref) {
    mod_reference
    name
    versions(filter: {limit: $limit, order_by: created_at, order: desc}) {
      id version game_version
      targets { targetName link hash }
      dependencies { mod_reference condition optional }
    }
  }
}"""


def fetch(url: str, body: bytes | None = None) -> bytes:
    # Only ficsit.app: the query is fixed (QUERY) and the package link comes from its response,
    # always relative to the same host.
    headers = {"User-Agent": "gamepanel"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)  # noqa: S310
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


def check_ref(value: str) -> str:
    if not REF.fullmatch(value or ""):
        raise ValueError(f"referencia de mod invalida: {value!r}")
    return value


# ------------------------------------------------------------------ versions

def _parse(version: str) -> tuple[int, int, int] | None:
    found = re.match(r"^\s*v?(\d+)\.(\d+)\.(\d+)", version or "")
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


_COMPARE = {
    ">=": lambda have, want: have >= want,
    "<=": lambda have, want: have <= want,
    ">": lambda have, want: have > want,
    "<": lambda have, want: have < want,
    "=": lambda have, want: have == want,
    # ^ pins the first non-zero number (semver): ^3.1.0 accepts 3.x, ^0.4.0 accepts 0.4.x.
    "^": lambda have, want: have >= want and (have[0] == want[0] if want[0] else have[:2] == want[:2]),
    "~": lambda have, want: have >= want and have[:2] == want[:2],
}


def _meets(have: tuple[int, int, int], part: str) -> bool:
    """One part of the condition (`^3.12.0`, `>=1.2.0`, `1.0.0`)."""
    # The group is optional: the match never fails, and without an operator the exact version applies.
    found_op = re.match(r"^(\^|~|>=|<=|>|<|=)?", part)
    written = found_op.group(0) if found_op else ""
    # Cut what was WRITTEN: with the implicit "=", cutting len("=") ate the first digit.
    op = written or "="
    want = _parse(part[len(written):])
    return want is not None and _COMPARE[op](have, want)


def satisfies(version: str, condition: str) -> bool:
    """Does the version meet the dependency condition? (`^x.y.z`, `>=x.y.z`, `~x.y.z`, exact, empty)."""
    have = _parse(version)
    if have is None:
        return False
    cond = (condition or "").strip()
    if cond in ("", "*"):
        return True
    return all(_meets(have, part) for part in cond.split())


def mod_versions(ref: str, fetcher=fetch) -> list[dict]:
    body = json.dumps({"query": GRAPHQL, "variables": {"ref": check_ref(ref), "limit": VERSIONS_PER_MOD}})
    data = json.loads(fetcher(QUERY, body.encode()))
    mod = (data.get("data") or {}).get("getModByReference")
    if not mod:
        raise ValueError(f"o ficsit.app nao conhece o mod {ref}")
    return mod.get("versions") or []


def _target(version: dict) -> dict | None:
    return next((t for t in version.get("targets") or [] if t.get("targetName") == TARGET), None)


def pick(versions: list[dict], condition: str = "", exact: str = "") -> dict:
    """The newest version with a Linux server package that meets the request."""
    for v in versions:
        if not _target(v):
            continue
        if exact and v.get("version") != exact:
            continue
        if satisfies(v.get("version", ""), condition):
            return v
    wanted = exact or condition or "qualquer"
    raise ValueError(f"nenhuma versao ({wanted}) com pacote de servidor Linux")


def resolve(ref: str, version: str = "", fetcher=fetch) -> list[tuple[str, dict]]:
    """The mod and its mandatory dependencies: [(reference, chosen version)]."""
    if version and not VERSION.fullmatch(version):
        raise ValueError(f"versao invalida: {version!r}")
    queue: list[tuple[str, str, str]] = [(check_ref(ref), "", version)]
    chosen: dict[str, dict] = {}
    while queue:
        name, condition, exact = queue.pop(0)
        if name in chosen:
            continue
        if len(chosen) >= MAX_PACKAGES:
            raise ValueError(f"mais de {MAX_PACKAGES} pacotes na arvore de dependencias")
        picked = pick(mod_versions(name, fetcher), condition, exact)
        chosen[name] = picked
        for dep in picked.get("dependencies") or []:
            if not dep.get("optional"):
                queue.append((check_ref(dep.get("mod_reference", "")), dep.get("condition", ""), ""))
    return list(chosen.items())


# ------------------------------------------------------------------ install

def _safe_rel(path: str) -> str:
    rel = posixpath.normpath(path.replace("\\", "/")).lstrip("/")
    if rel in (".", "") or rel.startswith("..") or "/../" in f"/{rel}/":
        return ""
    return rel


def _download(plan: list[tuple[str, dict]], fetcher) -> list[tuple[str, bytes]]:
    """Each mod package in the plan, checked against the sha256 the API published."""
    blobs: list[tuple[str, bytes]] = []
    for name, picked in plan:
        target = _target(picked) or {}
        link = target.get("link", "")
        if not link.startswith("/v1/version/"):
            raise ValueError(f"link de pacote inesperado para {name}")
        print(f"baixando {name} {picked.get('version')}")
        data = fetcher(API + link)
        if hashlib.sha256(data).hexdigest() != (target.get("hash") or "").lower():
            raise ValueError(f"o pacote de {name} nao confere com o sha256 do ficsit.app")
        blobs.append((f"{name}-{picked.get('version')}", data))
    return blobs


def _extract(dest: str, data: bytes) -> int:
    """Replace the mod folder entirely with the package contents. Return how many files."""
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    count = 0
    z = zipfile.ZipFile(io.BytesIO(data))
    for entry in z.namelist():
        rel = _safe_rel(entry)
        if not rel or entry.endswith("/"):
            continue
        out_path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with z.open(entry) as src, open(out_path, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def install(game_dir: str, ref: str, version: str = "", fetcher=fetch, scan=_no_scan) -> dict:
    if not os.path.isdir(game_dir):
        raise ValueError(f"a pasta do jogo nao existe: {game_dir}")
    plan = resolve(ref, version, fetcher)
    blobs = _download(plan, fetcher)
    # Everything checked at once: a rejected dependency does not leave the main mod half installed.
    scan(blobs)
    installed = []
    for (name, picked), (_, data) in zip(plan, blobs, strict=True):
        dest = os.path.join(game_dir, MODS, name)
        count = _extract(dest, data)
        with open(os.path.join(dest, MARK), "w", encoding="utf-8") as f:
            json.dump({"version": picked.get("version", ""), "pinned": bool(version) and name == ref,
                       "game_version": picked.get("game_version", "")}, f)
        installed.append({"mod": name, "version": picked.get("version", ""), "files": count})
        print(f"{name} {picked.get('version')} ({count} arquivos)")
    return {"installed": installed}


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


def remove(game_dir: str, ref: str) -> dict:
    mods_dir = os.path.join(game_dir, MODS)
    dest = os.path.join(mods_dir, check_ref(ref))
    # FactoryGame/Mods being a link (or under one) would make rmtree delete wherever it points.
    if under_link(mods_dir):
        raise ValueError(f"the mods folder is (or is under) a link: {mods_dir}")
    if os.path.islink(dest):
        os.remove(dest)
        return {"removed": True}
    existed = os.path.isdir(dest)
    # No ignore_errors: a folder this user cannot delete used to come back as "removed" while
    # the mod stayed and kept loading.
    if existed:
        shutil.rmtree(dest)
    return {"removed": existed}


def _read_json(path: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def status(game_dir: str) -> dict:
    mods_dir = os.path.join(game_dir, MODS)
    mods = []
    for entry in sorted(os.listdir(mods_dir)) if os.path.isdir(mods_dir) else []:
        path = os.path.join(mods_dir, entry)
        if not os.path.isdir(path):
            continue
        mark = _read_json(os.path.join(path, MARK))
        # A mod placed by hand (without the mark): the version comes from the .uplugin, which every plugin has.
        version = mark.get("version") or _read_json(os.path.join(path, f"{entry}.uplugin")).get("VersionName", "")
        mods.append({"name": entry, "version": version, "pinned": bool(mark.get("pinned"))})
    sml = next((m for m in mods if m["name"] == "SML"), None)
    return {"loader_installed": sml is not None, "loader": "SML",
            "loader_version": sml["version"] if sml else "", "loader_pinned": bool(sml and sml["pinned"]),
            "enabled": sml is not None, "mods": [m for m in mods if m["name"] != "SML"]}


def _chown(game_dir: str) -> None:
    try:
        import pwd
        pw = pwd.getpwnam(OWNER)
    except (ImportError, KeyError):
        return
    for root, dirs, files in os.walk(os.path.join(game_dir, MODS)):
        for n in (root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]):
            with contextlib.suppress(OSError):
                os.chown(n, pw.pw_uid, pw.pw_gid)


def main(argv: list[str]) -> int:
    script = ""
    if argv[:1] == ["--scan"]:
        script, argv = argv[1], argv[2:]
    action, game_dir, *rest = argv
    try:
        if action == "mod-install" and not script:
            raise ValueError("instalar sem a verificacao do antivirus nao e caminho do painel")
        if action == "status":
            result = status(game_dir)
        elif action == "mod-install":
            result = install(game_dir, rest[0], rest[1] if len(rest) > 1 else "", scan=scanner(script))
        elif action == "mod-remove":
            result = remove(game_dir, rest[0])
        else:
            raise ValueError(f"acao desconhecida: {action}")
        if action != "status":
            _chown(game_dir)
    except (ValueError, KeyError, OSError, IndexError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
