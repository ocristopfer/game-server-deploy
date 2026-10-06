"""Automatic update of the broker from the GitHub releases.

Run AS ROOT by `gamebroker-update.service` from a daily timer: it reads the latest release of the
repository, compares it with what is running and, when the mode allows, downloads the
`gamebroker-*.tar.gz`, checks its sha256 and hands it to `install-release.sh` - the same installer
the deploy uses. The release carries `lib/` and `games/` next to the package (EXTRA_TREES in
tools/build-release.py), so the game installer scripts and the curated catalog move with the code,
and a rollback takes them back too.

The core is the panel's (`gamepanel/updater.py`), copied between the markers: the CT of the broker
has no `gamepanel` package to import it from. What differs is below the core - the target, the
health probe and where the options come from (the unit's command line: the broker has no screen,
so there is no mode file and no request from anyone).

The health probe that decides the rollback (`gamebroker.healthcheck`) only asks whether the
broker answers; Proxmox or OPNsense being down is not a reason to throw away a release.
"""

# >>> shared updater core: identical in gamepanel/updater.py and gamebroker/updater.py
# (test_updater.py compares them). Change both, or neither.
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from typing import Any, NamedTuple
from urllib.parse import urlsplit

API = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "GamePanel-updater/1.0"
# A release is a few hundred KB; this only stops a wrong asset from filling the disk.
MAX_TARBALL = 64 * 1024 * 1024
MAX_SMALL = 1024 * 1024
TIMEOUT = 30
INSTALL_TIMEOUT = 600
# The installer output kept in the status for the screen: the end is where the reason is.
LOG_TAIL = 4000

MODES = ("off", "notify", "auto")
REQUESTS = ("check", "install")
REQUEST_FILE = "request"
MODE_FILE = "mode"
ALLOWED_DOWNLOAD_HOSTS = ("api.github.com",)
OCTET_STREAM = "application/octet-stream"
SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)", re.ASCII)
SHA256_HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)


class UpdateError(Exception):
    """Something that stops this round. The text goes to the status and the journal."""


class Target(NamedTuple):
    """WHAT is updated: the package, its unit, its folder, and how to tell the new one is alive."""
    package: str
    service: str
    app_dir: str
    # Where `install-release.sh` keeps a copy of itself on every install (see the end of the
    # script): the deploys only send it to /tmp, and the updater needs it after they are gone.
    installer: str
    # Shell command the installer runs after the restart; failing it rolls the release back.
    health: str
    # What to tell whoever reads the status when the installer is missing.
    install_hint: str


class Release(NamedTuple):
    tag: str
    version: tuple[int, int, int]
    page: str
    tarball_name: str
    tarball_url: str
    sha_url: str


# ------------------------------------------------------------------ pure decisions

def parse_version(text: str) -> tuple[int, int, int] | None:
    """`0.2.0`, `v0.2.0` or `0.2.0+abc1234[.dirty]` -> (0, 2, 0). Only the base counts: what it
    is compared against is a RELEASED version, and the build mark says nothing about order."""
    base = (text or "").strip().removeprefix("v").split("+", 1)[0]
    match = SEMVER.fullmatch(base)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def show(version: tuple[int, int, int] | None) -> str:
    return ".".join(map(str, version)) if version else ""


def pick_release(data: Any, package: str) -> Release:
    """The package's tarball and its sha256 among a release's assets."""
    if not isinstance(data, dict):
        raise UpdateError("unexpected answer from the GitHub API")
    tag = str(data.get("tag_name", ""))
    version = parse_version(tag)
    if version is None:
        raise UpdateError(f"tag is not a semver version: {tag!r}")
    if data.get("draft") or data.get("prerelease"):
        raise UpdateError(f"{tag} is a draft or a pre-release")
    # The API URL of each asset (`url`), not the browser one: downloaded with
    # `Accept: application/octet-stream` it is GitHub's documented route, and it answered where
    # the github.com/.../releases/download link gave 404 behind a proxy.
    assets = {str(a.get("name", "")): str(a.get("url", ""))
              for a in data.get("assets") or [] if isinstance(a, dict)}
    prefix = f"{package}-{show(version)}+"
    names = sorted(n for n in assets
                   if n.startswith(prefix) and n.endswith(".tar.gz") and ".dirty" not in n)
    if not names:
        raise UpdateError(f"{tag} has no {prefix}*.tar.gz asset")
    name = names[0]
    if f"{name}.sha256" not in assets:
        raise UpdateError(f"{tag} has no {name}.sha256 asset")
    return Release(tag, version, str(data.get("html_url", "")), name, assets[name],
                   assets[f"{name}.sha256"])


def auto_allowed(current: tuple[int, int, int], latest: tuple[int, int, int]) -> bool:
    """A new MAJOR version is never installed on its own: by semver it is the one allowed to
    need a manual step (a new .env option, a redeploy of the units). It is announced instead."""
    return latest[0] == current[0]


def decide(mode: str, request: str, current: tuple[int, int, int] | None,
           latest: tuple[int, int, int]) -> str:
    """'install', or 'none'. The request button can do what the timer cannot (a major version),
    and nothing installs an OLDER version - a rollback is moving the symlink, not this."""
    if current is not None and latest <= current:
        return "none"
    if request == "install":
        return "install"
    if mode == "auto" and request == "" and (current is None or auto_allowed(current, latest)):
        return "install"
    return "none"


def sha_from_file(text: str, name: str) -> str:
    """`<hash>  <name>` (the `sha256sum` format build-release.py writes), or a bare hash."""
    for line in text.splitlines():
        parts = line.strip().split()
        if parts and SHA256_HEX.fullmatch(parts[0].lower()) and (len(parts) == 1 or parts[-1].lstrip("*") == name):
            return parts[0].lower()
    raise UpdateError(f"the .sha256 file has no hash for {name}")


# ------------------------------------------------------------------ the files between the two sides

def _read_small(path: str) -> str:
    """Read a file the PANEL may have written, without following a link it could have planted."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as fh:
        return fh.read(64).decode("ascii", "replace").strip()


def take_request(update_dir: str) -> str:
    path = os.path.join(update_dir, REQUEST_FILE)
    value = _read_small(path)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    return value if value in REQUESTS else ""


def read_mode(update_dir: str, default: str) -> str:
    value = _read_small(os.path.join(update_dir, MODE_FILE))
    return value if value in MODES else default


def write_status(path: str, status: dict) -> None:
    """Atomic: the panel reads it at any moment, and half a JSON would read as "never checked"."""
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".status.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(status, fh, indent=1, sort_keys=True)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_status(path: str) -> dict | None:
    """The panel's side. None = the updater never ran here (not installed, or dev compose)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def leave_request(update_dir: str, what: str) -> None:
    """The panel's side: ask root to check or install. The path unit wakes the updater."""
    if what not in REQUESTS:
        raise ValueError(what)
    _write_panel_file(update_dir, REQUEST_FILE, what)


def save_mode(update_dir: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(mode)
    _write_panel_file(update_dir, MODE_FILE, mode)


def _write_panel_file(update_dir: str, name: str, value: str) -> None:
    os.makedirs(update_dir, mode=0o755, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=update_dir, prefix=f".{name}.")
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(value + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(update_dir, name))


# ------------------------------------------------------------------ network

Opener = Callable[[urllib.request.Request, float], Any]


def _open(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310  # NOSONAR - _get only lets https GitHub URLs through


def _get(url: str, limit: int, opener: Opener = _open, accept: str = "") -> bytes:
    """GET with a size cap. Only https to the GitHub API: the URLs come from the API's JSON, and
    an asset redirects to GitHub's storage, which urllib follows on its own."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError(f"refusing a URL outside GitHub: {url}")
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    # The scheme and host were checked above: only https to GitHub gets here.
    request = urllib.request.Request(url, headers=headers)  # noqa: S310  # NOSONAR
    try:
        with opener(request, TIMEOUT) as resp:
            data = resp.read(limit + 1)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"download failed for {url}: {exc}") from exc
    if len(data) > limit:
        raise UpdateError(f"{url} is larger than {limit} bytes")
    return data


def latest_release(repo: str, package: str, opener: Opener = _open) -> Release:
    raw = _get(API.format(repo=repo), MAX_SMALL, opener, accept="application/vnd.github+json")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise UpdateError("the GitHub API did not answer JSON") from exc
    return pick_release(data, package)


def download(release: Release, folder: str, opener: Opener = _open) -> tuple[str, str]:
    """(local tarball path, its sha256), already CHECKED here: the installer checks again,
    but a mismatch found here never even reaches it."""
    expected = sha_from_file(
        _get(release.sha_url, MAX_SMALL, opener, accept=OCTET_STREAM).decode("ascii", "replace"),
        release.tarball_name)
    data = _get(release.tarball_url, MAX_TARBALL, opener, accept=OCTET_STREAM)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise UpdateError(f"sha256 mismatch: expected {expected}, got {actual}")
    path = os.path.join(folder, release.tarball_name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path, expected


# ------------------------------------------------------------------ the round

class Deps(NamedTuple):
    """What a round touches outside itself; the tests swap each one."""
    opener: Opener
    run: Callable[..., subprocess.CompletedProcess]
    now: Callable[[], str]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


DEFAULT_DEPS = Deps(_open, subprocess.run, _now)


def install(tarball: str, sha: str, target: Target,
            run: Callable[..., subprocess.CompletedProcess]) -> str:
    """Hand the tarball to install-release.sh. Returns its output; raises when it failed (it has
    already rolled back by then: that is its job, not ours)."""
    if not os.path.isfile(target.installer):
        raise UpdateError(f"installer missing: {target.installer} ({target.install_hint})")
    done = run(["bash", target.installer, target.package, tarball, sha, target.app_dir,
                target.service, target.health],
               capture_output=True, text=True, timeout=INSTALL_TIMEOUT, check=False)
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        raise UpdateError("the installer failed (the previous version stays live):\n" + output[-LOG_TAIL:])
    return output


def run_round(*, target: Target, repo: str, default_mode: str, update_dir: str, status_path: str,
              current_version: str, deps: Deps = DEFAULT_DEPS) -> dict:
    """One pass: read the request and the mode, check, maybe install, write the status."""
    request = take_request(update_dir)
    mode = read_mode(update_dir, default_mode)
    previous = read_status(status_path) or {}
    current = parse_version(current_version)
    status: dict[str, Any] = {
        "mode": mode, "current": current_version, "checked_at": previous.get("checked_at", ""),
        "latest": previous.get("latest", ""), "page": previous.get("page", ""),
        "available": False, "result": "", "message": "", "log": "",
        "installed_at": previous.get("installed_at", ""),
    }
    if mode == "off" and not request:
        status["result"] = "off"
        write_status(status_path, status)
        return status
    try:
        release = latest_release(repo, target.package, deps.opener)
        status.update(checked_at=deps.now(), latest=show(release.version), page=release.page,
                      available=current is None or release.version > current)
        action = decide(mode, request, current, release.version)
        if action == "install":
            with tempfile.TemporaryDirectory(prefix="gamepanel-update-") as folder:
                tarball, sha = download(release, folder, deps.opener)
                status["log"] = install(tarball, sha, target, deps.run)[-LOG_TAIL:]
            installed = release.tarball_name.removeprefix(f"{target.package}-").removesuffix(".tar.gz")
            status.update(result="installed", available=False, current=installed,
                          installed_at=deps.now())
        elif status["available"]:
            # A new major in auto mode lands here too: announced, never installed on its own.
            status["result"] = "available"
        else:
            status["result"] = "up_to_date"
    except UpdateError as exc:
        status.update(result="error", message=str(exc)[-LOG_TAIL:])
    write_status(status_path, status)
    return status


def report(status: dict) -> int:
    """One line in the journal, the reason on stderr, and the exit code systemd records."""
    print(f"updater: {status['result']} (running {status['current']}, latest {status['latest'] or '?'})")
    if status["message"]:
        print(status["message"], file=sys.stderr)
    return 1 if status["result"] == "error" else 0
# <<< shared updater core


BROKER = Target(
    package="gamebroker", service="gamebroker.service", app_dir="/opt/gamebroker",
    installer="/usr/local/lib/gamebroker/install-release.sh",
    health="",  # filled in main(): the port comes from the unit's command line
    install_hint="deploy the broker once with deploy-broker.ps1",
)
# Only root writes here: the status lives where the broker can READ it but never change it.
STATE_DIR = "/var/lib/gamebroker-updater"
STATUS_PATH = f"{STATE_DIR}/status.json"
# The broker's own folder (its BROKER_STATE_DIR in the provisioning), where the API leaves the
# panel's "check"/"install" request and the path unit wakes this updater. It is the panel's
# arrangement: the unprivileged side writes the request, root reads it with O_NOFOLLOW and accepts
# only the fixed values, and the status goes to a folder the broker cannot write.
REQUEST_DIR = "/var/lib/gamebroker/update"
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}", re.ASCII)
MAX_PORT = 65535


def parse_args(args: list[str]) -> tuple[str, str, int] | None:
    """`run --repo owner/name --mode auto --port 8443` -> (repo, mode, port), or None."""
    if not args or args[0] != "run" or len(args) != 7:
        return None
    options = dict(zip(args[1::2], args[2::2], strict=True))
    repo, mode, port = options.get("--repo", ""), options.get("--mode", ""), options.get("--port", "")
    if set(options) != {"--repo", "--mode", "--port"} or not REPO_RE.fullmatch(repo) or mode not in MODES:
        return None
    if not port.isdigit() or not 1 <= int(port) <= MAX_PORT:
        return None
    return repo, mode, int(port)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(sys.argv[1:] if argv is None else argv)
    if parsed is None:
        print("usage: python3 -m gamebroker.updater run --repo OWNER/NAME --mode auto|notify|off --port N",
              file=sys.stderr)
        return 2
    repo, mode, port = parsed
    from gamebroker import version
    # `cd` first: the probe must import the NEW release, which `current` points to by then.
    target = BROKER._replace(
        health=f"cd {BROKER.app_dir}/current && python3 -m gamebroker.healthcheck --port {port}")
    status = run_round(target=target, repo=repo, default_mode=mode, update_dir=REQUEST_DIR,
                       status_path=STATUS_PATH, current_version=version.BUILD.version)
    return report(status)


if __name__ == "__main__":  # pragma: no cover - the systemd unit's entry point
    sys.exit(main())
