"""The custom mod setup: for a game with no built-in profile, the admin says where things go.

A built-in profile (profiles.py) is knowledge MEASURED on a real server: which loader, which
Wine DLL, which folder. Most games in the catalog have none, and the person running the server
often knows exactly what their game needs ("download this zip, unpack it next to the .exe, mods
go in BepInEx/plugins"). This module turns that into a profile the Mods screen already knows how
to serve, without giving the form anything that becomes shell:

- **A link, two folders and a list of extensions** - plus, optionally, the two environment
  settings loaders actually use (extra `WINEDLLOVERRIDES` entries and one `LD_PRELOAD` library).
  No free-form command and no arbitrary variable name: the loader is UNPACKED, never run, and
  only those two variables can be set.
- **Folders are RELATIVE to the game folder** (`profiles.GAME_DIR`), each part from a short
  character set, no `.`/`..`, and the CT checks again, after resolving links, that the real path
  is still inside the game folder (custom_remote.py).
- **https only**, checked here and again in the CT (redirects included): the download runs on the
  game server, and a plain http link is one anyone on the way can swap.
- **The built-in profile wins.** The custom setup is only offered (and only applies) when the game
  has none: two managers on the same folder would fight over the same files and the same Wine
  setting, and the built-in one carries what was measured.

The values are validated on save AND rebuilt from the database through the same `parse` on every
read: a row edited by hand cannot reach the container with what the form would have refused.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass

from gamepanel.games.mods import profiles
from gamepanel.i18n import Message

# The same rules live in custom_remote.py, which runs in the CT and cannot import this module; a
# test keeps the two copies equal.
URL_MAX = 500
URL_CHARS = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+", re.ASCII)
# One folder name: what game folders are made of (`~mods`, `Binaries`, `My Mods`, `Mods (1)`).
# Never starting with a dot: that is how `.` and `..` (and hidden folders) stay out.
SEGMENT = re.compile(r"[A-Za-z0-9_~][A-Za-z0-9 _.+()~-]{0,99}", re.ASCII)
REL_MAX = 240
REL_DEPTH = 12
# LD_PRELOAD splits on spaces and colons, and the value goes into steam's overlay (whose character
# set has no parentheses or tilde): a narrower set than a folder name.
PRELOAD_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,99}", re.ASCII)
EXTENSION = re.compile(r"\.[a-z0-9]{1,10}", re.ASCII)
MAX_EXTENSIONS = 16
# What a mod usually IS, across engines: Unreal paks (and the two IoStore companions), .NET/Wine
# plugin DLLs, Java jars, Oxide-style C# plugins, Lua scripts and Bethesda plugin/archive files.
# Left out on purpose: .zip (the panel does not unpack an uploaded mod, and a zip the game does not
# read is a mod that silently does nothing - a game that reads zips gets it added by hand).
DEFAULT_EXTENSIONS = (".pak", ".utoc", ".ucas", ".dll", ".jar", ".cs", ".lua", ".esp", ".esm", ".bsa")
# Never accepted, even when typed: nothing loads these as a "mod" from a folder, and a script or
# a shared library uploaded into the game folder is one step from being run (a start script that
# someone edits, an LD_PRELOAD that points at it) without having come from the loader's package.
BLOCKED_EXTENSIONS = (".sh", ".bash", ".so", ".exe", ".bat", ".cmd", ".ps1", ".py", ".pl", ".service")
# A Wine DLL override as Wine reads it: `name=n,b`, `name=n`, `name=b`, `name=` (disabled).
WINE_ENTRY = re.compile(r"[A-Za-z0-9_.-]{1,64}=(?:n,b|b,n|n|b|)", re.ASCII)
MAX_WINE = 8
SEPARATORS = re.compile(r"[\s,;]+")
WINE_SEPARATORS = re.compile(r"[\s;]+")

FIELDS = ("loader_url", "loader_dir", "mods_dir", "extensions", "wine_overrides", "ld_preload")


@dataclass(frozen=True)
class CustomSetup:
    loader_url: str
    loader_dir: str
    mods_dir: str
    extensions: tuple[str, ...]
    wine: tuple[str, ...] = ()
    preload: str = ""

    @property
    def needs_overlay(self) -> bool:
        """Whether this setup changes the game's environment (only possible in helper mode)."""
        return bool(self.wine or self.preload)

    def as_form(self) -> dict[str, str]:
        """What goes back into the form fields."""
        return {"loader_url": self.loader_url, "loader_dir": self.loader_dir, "mods_dir": self.mods_dir,
                "extensions": " ".join(self.extensions), "wine_overrides": " ".join(self.wine),
                "ld_preload": self.preload}

    def to_json(self) -> str:
        return json.dumps({"loader_url": self.loader_url, "loader_dir": self.loader_dir,
                           "mods_dir": self.mods_dir, "extensions": list(self.extensions),
                           "wine": list(self.wine), "preload": self.preload}, sort_keys=True)


def check_url(text: str) -> str:
    """The loader link, or ValueError. Empty is allowed: a game whose mods need no loader."""
    url = (text or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    if (len(url) > URL_MAX or not URL_CHARS.fullmatch(url) or parts.scheme != "https"
            or not parts.hostname or "@" in parts.netloc):
        raise ValueError(Message("mods.custom_bad_url"))
    return url


def clean_rel(text: str, *, key: str, allow_empty: bool, segment: re.Pattern[str] = SEGMENT) -> str:
    """A folder RELATIVE to the game folder, normalized (`a//b/` -> `a/b`), or ValueError."""
    raw = (text or "").strip().replace("\\", "/")
    if raw.startswith("/"):
        raise ValueError(Message(key))
    parts = [p for p in raw.split("/") if p]
    if not parts:
        if allow_empty:
            return ""
        raise ValueError(Message(key))
    rel = "/".join(parts)
    if len(parts) > REL_DEPTH or len(rel) > REL_MAX or not all(segment.fullmatch(p) for p in parts):
        raise ValueError(Message(key))
    return rel


def parse_extensions(text: str) -> tuple[str, ...]:
    words = [w.lower() for w in SEPARATORS.split((text or "").strip()) if w]
    if not words:
        return DEFAULT_EXTENSIONS
    out: list[str] = []
    for word in words:
        ext = word if word.startswith(".") else "." + word
        if ext in BLOCKED_EXTENSIONS:
            raise ValueError(Message("mods.custom_blocked_ext", ext=ext, blocked=" ".join(BLOCKED_EXTENSIONS)))
        if not EXTENSION.fullmatch(ext):
            raise ValueError(Message("mods.custom_bad_ext"))
        if ext not in out:
            out.append(ext)
    if len(out) > MAX_EXTENSIONS:
        raise ValueError(Message("mods.custom_bad_ext"))
    return tuple(out)


def parse_wine(text: str) -> tuple[str, ...]:
    entries = [w for w in WINE_SEPARATORS.split((text or "").strip()) if w]
    if len(entries) > MAX_WINE or not all(WINE_ENTRY.fullmatch(e) for e in entries):
        raise ValueError(Message("mods.custom_bad_wine"))
    # One entry per DLL: two would leave Wine reading whichever comes last.
    names = [e.split("=", 1)[0].lower() for e in entries]
    if len(set(names)) != len(names):
        raise ValueError(Message("mods.custom_bad_wine"))
    return tuple(entries)


def parse_preload(text: str) -> str:
    rel = clean_rel(text, key="mods.custom_bad_preload", allow_empty=True, segment=PRELOAD_SEGMENT)
    if rel and not rel.endswith(".so"):
        raise ValueError(Message("mods.custom_bad_preload"))
    return rel


def parse(form: Mapping[str, str]) -> tuple[CustomSetup | None, list[Message]]:
    """The setup from the form (or from the stored JSON), with EVERY problem at once."""
    problems: list[Message] = []
    values: dict[str, object] = {}
    checks = (
        ("loader_url", lambda v: check_url(v)),
        ("loader_dir", lambda v: clean_rel(v, key="mods.custom_bad_loader_dir", allow_empty=True)),
        ("mods_dir", lambda v: clean_rel(v, key="mods.custom_bad_mods_dir", allow_empty=False)),
        ("extensions", parse_extensions),
        ("wine_overrides", parse_wine),
        ("ld_preload", parse_preload),
    )
    for field, check in checks:
        try:
            values[field] = check(str(form.get(field, "") or ""))
        except ValueError as exc:
            problems.append(exc.args[0] if isinstance(exc.args[0], Message) else Message("mods.custom_bad_url"))
    if problems:
        return None, problems
    setup = CustomSetup(
        loader_url=str(values["loader_url"]), loader_dir=str(values["loader_dir"]),
        mods_dir=str(values["mods_dir"]), extensions=tuple(values["extensions"]),  # type: ignore[arg-type]
        wine=tuple(values["wine_overrides"]), preload=str(values["ld_preload"]),  # type: ignore[arg-type]
    )
    # The environment is applied when the loader is installed (and taken back when it is
    # uninstalled): with no loader to install there would be no moment to apply it, nor to undo it.
    if setup.needs_overlay and not setup.loader_url:
        return None, [Message("mods.custom_overlay_needs_loader")]
    return setup, []


def from_json(text: str) -> CustomSetup | None:
    """The stored setup, re-validated; None when there is none (or the row no longer passes)."""
    if not (text or "").strip():
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    form = {
        "loader_url": data.get("loader_url", ""), "loader_dir": data.get("loader_dir", ""),
        "mods_dir": data.get("mods_dir", ""),
        "extensions": " ".join(str(e) for e in data.get("extensions", []) or []),
        "wine_overrides": " ".join(str(e) for e in data.get("wine", []) or []),
        "ld_preload": data.get("preload", ""),
    }
    setup, _ = parse({k: str(v) for k, v in form.items()})
    return setup


def profile(setup: CustomSetup) -> profiles.ModProfile:
    """The setup as a profile: the upload, the list, the removal and the audit come for free."""
    folder = f"{profiles.GAME_DIR}/{setup.mods_dir}"
    loader_dir = f"{profiles.GAME_DIR}/{setup.loader_dir}" if setup.loader_dir else profiles.GAME_DIR
    # The antivirus re-check covers the loader only when it has a folder of its own: the game
    # folder as a whole would be gigabytes of the game's own files.
    audit = (folder, loader_dir) if setup.loader_dir and loader_dir != folder else (folder,)
    return profiles.ModProfile(
        key="custom", kind=profiles.KIND_CUSTOM, services=(), folder=folder, help_key="mods.help_custom",
        extensions=setup.extensions, loader_dir=loader_dir, audit_paths=audit,
        sources=(("mods.source_custom_loader", setup.loader_url),) if setup.loader_url else (),
        proven=False, folder_mods=True,
    )
