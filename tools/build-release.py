#!/usr/bin/env python3
"""Packages a release: one tar.gz, one sha256, and nothing else.

    python tools/build-release.py gamepanel
    python tools/build-release.py gamebroker --out dist

The output is what the deploy sends over the network: `dist/gamepanel-0.1.0+abc1234.tar.gz`
plus the `.sha256` next to it. On the other side it becomes `/opt/gamepanel/releases/<version>/`,
and the `current` symlink starts pointing at the new folder -- switching versions (or going
back) is moving a symlink, not copying files over files.

Three decisions that look like details and are not:

- **`tarfile`, from the stdlib, and not a real Python package.** Production only has the
  stdlib and apt's `python3-flask`: there is no pip to install a wheel, and a PyInstaller
  binary would bring its own Python and Flask, throwing away exactly that guarantee.
- **A single file, with a hash.** The old upload copied the whole tree file by file, with
  a hand-written list of which folders to delete first -- a list that fell behind with
  every new folder in the package, leaving renamed modules alive in the container. Here
  there is nothing left over: a new release is a new folder.
- **Byte for byte.** The old upload passed every file through a line-ending normalizer,
  and a PNG caught in that sieve arrived corrupted on the other side (the PWA icon already
  did). A tar does not interpret content.

The content is deterministic: sorted names, zeroed owner/group and the commit date in
place of each file's mtime. Two calls on the same commit give the SAME sha256, which makes
the hash answer "is the CT running this code?" and not just "did the file arrive intact?".
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("gamepanel", "gamebroker")
SKIPPED_DIRS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
SKIPPED_SUFFIXES = (".pyc", ".pyo")
# What does NOT go to production: test doubles and the toy broker that docker compose
# brings up. `dev.py` is the case that matters -- it creates instances against fake
# backends, and on a real CT it would be a way to make the broker lie about what exists.
SKIPPED_NAMES = ("dev.py", "conftest.py", "fakes.py", "fake_http.py")
SKIPPED_PREFIXES = ("test_",)
FILE_MODE = 0o644
READ_BLOCK = 1 << 20

BUILD_TEMPLATE = '''"""GERADO por tools/build-release.py ao empacotar. Nao edite, nao commite."""
VERSION = {version!r}
COMMIT = {commit!r}
BUILT_AT = {built_at!r}
'''


def _git(*args: str) -> str:
    """Runs git at the repository root; returns empty if it fails (tree without .git)."""
    try:
        # Fixed arguments, none come from outside; and `git` from PATH on purpose, because
        # this is a development tool and the path changes on every machine.
        done = subprocess.run(("git", *args), cwd=ROOT, capture_output=True,  # noqa: S603, S607
                              text=True, check=False)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


class Release(NamedTuple):
    """Version, commit and date -- what goes inside the package and into the file name."""

    version: str
    commit: str
    built_at: str
    dirty: bool


def describe() -> Release:
    """`0.1.0+abc1234`, or `0.1.0+abc1234.dirty` if there are uncommitted changes.

    The `.dirty` is visible on purpose in the file name and on screen: a release that
    matches no commit must not be confused with one that does, otherwise "I went back to
    0.1.0" one day brings back different code.
    """
    base = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    commit = _git("rev-parse", "--short=7", "HEAD")
    if not commit:
        # Without git there is no commit and no commit date. Falling back to the clock here
        # would cost determinism -- the date goes into the stamp AND into the mtime of every
        # file in the tar, so two packagings of the same code would give different sha256s
        # and the hash would stop answering "is the CT running this code?". No date is the
        # honest answer.
        return Release(base, "", "", False)
    dirty = bool(_git("status", "--porcelain"))
    built_at = _git("show", "-s", "--format=%cI", "HEAD")
    version = f"{base}+{commit}" + (".dirty" if dirty else "")
    return Release(version, commit, built_at, dirty)


def _keep(path: Path) -> bool:
    return (
        not any(part in SKIPPED_DIRS for part in path.parts)
        and path.suffix not in SKIPPED_SUFFIXES
        and path.name not in SKIPPED_NAMES
        and not path.name.startswith(SKIPPED_PREFIXES)
    )


def _files_of(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and _keep(p))


def _entry(name: str, data: bytes, when: int) -> tarfile.TarInfo:
    """Header with no owner, no group and a fixed date: two equal builds, equal hash."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = when
    info.mode = FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def build(package: str, out_dir: Path, release: Release) -> Path:
    source = ROOT / "src" / package
    if not source.is_dir():
        raise SystemExit(f"pacote nao encontrado: {source}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{package}-{release.version}.tar.gz"
    when = int(datetime.fromisoformat(release.built_at).timestamp()) if release.built_at else 0

    # The gzip is assembled by hand only because of `mtime=0`: tarfile's `mode="w:gz"` stamps
    # the packaging time into the gzip header, and the same commit would give a different
    # sha256 on every call -- the hash would stop answering "is the CT running this code?".
    with target.open("wb") as raw, gzip.GzipFile(
        fileobj=raw, mode="wb", mtime=0, compresslevel=9,
    ) as packed, tarfile.open(
        fileobj=packed, mode="w", format=tarfile.PAX_FORMAT,
    ) as tar:
        for path in _files_of(source):
            name = path.relative_to(source).as_posix()
            data = path.read_bytes()
            tar.addfile(_entry(f"{package}/{name}", data, when), io.BytesIO(data))
        stamp = BUILD_TEMPLATE.format(
            version=release.version, commit=release.commit, built_at=release.built_at,
        ).encode("utf-8")
        tar.addfile(_entry(f"{package}/_build.py", stamp, when), io.BytesIO(stamp))
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(READ_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Empacota um release de gamepanel ou gamebroker.")
    parser.add_argument("package", choices=PACKAGES)
    parser.add_argument("--out", default="dist", help="pasta de saida (padrao: dist/)")
    args = parser.parse_args(argv)

    release = describe()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    target = build(args.package, out_dir, release)
    checksum = _sha256(target)
    # The format is what `sha256sum -c` on the other side expects to read.
    (target.parent / (target.name + ".sha256")).write_text(
        f"{checksum}  {target.name}\n", encoding="utf-8", newline="\n",
    )

    print(f"{target.name}  {target.stat().st_size // 1024} KiB")
    print(f"sha256 {checksum}")
    if release.dirty:
        print("AVISO: a arvore tem mudanca nao commitada; o release saiu marcado .dirty",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
