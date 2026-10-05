#!/usr/bin/env python3
"""Generates `src/gamepanel/games/catalog/pterodactyl_suggestions.py` from the Pterodactyl eggs.

The eggs (MIT, https://github.com/pelican-eggs/games-steamcmd - the successor of parkervcp/eggs)
are the second source of the "Add game" form. They exist for a single reason: LinuxGSM only
knows servers with a Linux build, and the eggs also cover the ones that only run on Windows
(V Rising, Enshrouded, Abiotic Factor...) through images with Wine/Proton.

    python tools/import-pterodactyl.py                  # downloads the repository from GitHub
    python tools/import-pterodactyl.py --source PASTA   # uses a local clone

Two things come out, and both go through the broker's validator HERE, at generation time: the
production panel does not have the broker package to validate at use time.

- `SUGGESTIONS`: games that LinuxGSM, the manual list and the curated ones do NOT have. Whoever
  already has the game wins: LinuxGSM states the port protocol, the egg does not; the manual list
  was reviewed by hand; the curated ones the search finds through the page's catalog.
- `COMPLEMENTS`: per LinuxGSM App ID, only the fields that are EMPTY there and the egg knows
  (config folder and files; ports, when LinuxGSM found none). The search merges the two and
  says where each field came from.

Where each piece of egg data comes from:

- App ID: the `SRCDS_APPID` variable. An egg without it is not SteamCMD and is left out.
- Ports: the "Server Ports" table in the README of the egg's folder. The egg's main port is the
  Pterodactyl ALLOCATION, which has no number in the JSON; only the README states the default.
- Command: the `startup`, without what belongs to the Pterodactyl container (`cd`, `export`,
  `xvfb-run`, `proton run`, `wine`) and with `{{SERVER_PORT}}`/the query variable replaced by
  the placeholders.
- Windows: `WINDOWS_INSTALL=1`, a wine/proton image or `wine`/`proton` in the command. Comes out
  with `proton` (repository rule: Proton first), plus `xvfb` if the egg starts a virtual X.
- Config: the keys of `config.files` (the files Pterodactyl edits), under /opt/game.

Security rules, the same as LinuxGSM's (each with a test in test_import_pterodactyl.py):

- The egg's install script is SHELL and is never read: the broker only accepts data.
- RCON, telnet, HTTP and similar ports NEVER become exposed ports.
- Password, name, IP and token variables are NEVER resolved: the argument goes, with a warning.
- Everything after `; | & $(` is cut; what does not fit the broker's charset goes, never escaped.
- An egg that requires a Steam account is left out: a dynamic game has no way to carry the
  password to the CT.
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import pathlib
import posixpath
import pprint
import re
import shlex
import sys
import tarfile
import unicodedata
import urllib.request
from typing import NamedTuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gamebroker.domain.exceptions import ValidationError  # noqa: E402
from gamebroker.services.catalog import KEY_RE, read_env, validate_dynamic  # noqa: E402

TARBALL_URL = "https://codeload.github.com/pelican-eggs/games-steamcmd/tar.gz/refs/heads/main"
SOURCE_NAME = "Pterodactyl eggs (MIT)"
GAME_DIR = "/opt/game"
CONTAINER_DIR = "/home/container"
# The placeholders the broker replaces with the allocated port (see catalog._PLACEHOLDERS).
PORT_MARKER, QUERY_MARKER, EXTRA_MARKER = "{PORT}", "{QUERY_PORT}", "{EXTRA_PORT}"

# Port table row names that NEVER go to the NAT (the port only stays in the arguments).
INTERNAL_PORT_WORDS = ("rcon", "telnet", "http", "web", "api", "rest", "admin", "tv", "metric",
                       "console", "mod", "voice")
SECRET_WORDS = ("PASS", "PW", "TOKEN", "KEY", "SECRET", "GSLT", "NAME", "IP", "LOGIN", "USER",
                "RCON", "ADMIN", "PASSWORD", "HOSTNAME", "MOTD", "DESCRIPTION", "WEBHOOK")
# Programs of the Pterodactyl container, not of the game: dropped before finding the executable.
LAUNCHERS = ("exec", "stdbuf", "xvfb-run", "wine", "wine64", "proton", "run", "env", "nice")
# An interpreter in place of the executable: the broker's START_SCRIPT is a file executed directly,
# so `java -jar` or `dotnet X.dll` has no way to become a command here.
INTERPRETERS = ("java", "dotnet", "mono", "bash", "sh", "python", "python3", "node", "screen")
VARIANT_WORDS = ("bepinex", "modded", "oxide", "umod", "carbon", "experimental", "beta",
                 "mod", "plus", "legacy", "tshock", "unstable", "staging", "sourcemod")
CONFIG_EXTENSIONS = (".ini", ".json", ".properties", ".conf", ".cfg")
# First word of a segment that prepares the container and does not start the game (the virtual X
# in the background, winetricks, the sed that rewrites config). Picking one of them as "the server"
# gave START_SCRIPT=xvfb in the first version of this converter.
SETUP_WORDS = ("cd", "export", "unset", "rm", "touch", "mkdir", "echo", "chmod", "chown", "cp", "mv",
               "ln", "sed", "cat", "sleep", "if", "then", "else", "fi", "while", "do", "done", "for",
               "trap", "ulimit", "source", ".", "[", "test", "Xvfb", "xvfb", "wineboot", "winetricks", "wait",
               "kill", "true", "false", "printf", "clear", "curl", "wget")
# App ID that is not the game: 1007 is the Steamworks SDK Redist, which an egg for a game installed
# via git downloads only for the library. With it the broker would install the library and no server.
NOT_GAME_APPIDS = frozenset({1007})

_VAR = re.compile(r"\{\{\s*(?:server\.build\.env\.)?([A-Z0-9_]+)\s*\}\}|\$\{([A-Z0-9_]+)\}")
_ARGS_CHARSET = re.compile(r"[A-Za-z0-9._=:,/+@?{}-]+")
_CHAIN = re.compile(r"&&|\|\||[;|&`<>]|\$\(")
_SCRIPT_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
_PATH_PART = re.compile(r"[A-Za-z0-9._-]+")
_PORT_NUMBER = re.compile(r"\b(\d{4,5})\b")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


# ---------------------------------------------------------------- port table (README)

class PortRow(NamedTuple):
    name: str
    number: int
    protos: tuple[str, ...]


def _protocols(cells: list[str]) -> tuple[str, ...]:
    text = " ".join(cells).lower()
    found = tuple(p for p in ("udp", "tcp") if p in text)
    return found or ("udp",)


def port_rows(readme: str) -> list[PortRow]:
    """The rows of the README's port table: name, default number and protocol. With no protocol
    column it is UDP, which is that of every Steam game (and the suggestion warns it was presumed)."""
    rows: list[PortRow] = []
    in_ports = False
    for line in readme.splitlines():
        if line.lstrip().startswith("#"):
            in_ports = "port" in line.lower()
            continue
        match = _TABLE_ROW.match(line)
        if not (in_ports and match):
            continue
        cells = [c.strip().strip("*` ") for c in match.group(1).split("|")]
        number = next((int(m.group(1)) for c in cells[1:] for m in [_PORT_NUMBER.search(c)] if m), 0)
        if cells and 1024 <= number <= 65535:
            rows.append(PortRow(cells[0], number, _protocols(cells[1:])))
    return rows


def _role(name: str) -> str:
    low = name.lower()
    if "query" in low:
        return "query"
    if any(w in low for w in INTERNAL_PORT_WORDS):
        return "internal"
    if any(w in low for w in ("game", "primary", "server", "main", "default", "port")) and "+" not in low:
        return "game"
    return "extra"


class Ports(NamedTuple):
    game: int = 0
    query: int = 0
    extra: int = 0
    exposed: tuple[str, ...] = ()
    presumed_udp: bool = False


def classify_ports(rows: list[PortRow]) -> Ports:
    game = query = 0
    extras: list[int] = []
    exposed: list[str] = []
    for row in rows:
        role = _role(row.name)
        if role == "internal":
            continue
        if role == "game" and not game:
            game = row.number
        elif role == "query" and not query:
            query = row.number
        else:
            extras.append(row.number)
        # The Steam query is UDP in every game, even when the README says otherwise.
        protos = ("udp",) if role == "query" else row.protos
        exposed += [f"{row.number}/{p}" for p in protos if f"{row.number}/{p}" not in exposed]
    if not game:
        return Ports()
    return Ports(game, query, extras[0] if len(extras) == 1 else 0, tuple(exposed),
                 presumed_udp=all(len(r.protos) == 1 and r.protos[0] == "udp" for r in rows))


# ---------------------------------------------------------------- start command

def _is_secret(var: str) -> bool:
    return any(w in var for w in SECRET_WORDS)


def _launch_segment(startup: str) -> tuple[str, str]:
    """The segment of `startup` that starts the game, and the folder it runs in (the `cd` before it)."""
    # A lone `&` also separates: `Xvfb :0 & ./server` starts X in the background and the game after.
    segments = [s.strip() for s in re.split(r";|&&|\|\||&|\||\n", startup) if s.strip()]
    cwd = chosen_cwd = chosen = ""
    best = 0
    for seg in segments:
        words = seg.split()
        if words and words[0] == "cd" and len(words) > 1:
            cwd = words[1].strip("\"'")
            continue
        if not words or words[0] in SETUP_WORDS or words[0].startswith("("):
            continue
        score = _launch_score(seg)
        if score > best:
            chosen, chosen_cwd, best = seg, cwd, score
    return chosen, chosen_cwd


# Signs of "this is where the game starts", from most to least certain. The game port in the
# command is the strongest signal; an executable (./x, wine, proton, .exe) comes next. Without
# this the first leftover segment won, and in Space Engineers that was a piece of an `export`
# with a `;` inside the quotes.
_LAUNCH_HINTS = (("SERVER_PORT", 4), ("./", 2), ("wine", 2), ("proton", 2), (".exe", 2),
                 (".x86_64", 2), (".sh", 1))


def _launch_score(segment: str) -> int:
    return 1 + sum(weight for hint, weight in _LAUNCH_HINTS if hint in segment)


def _strip_launchers(tokens: list[str]) -> tuple[list[str], bool]:
    """Strips inline env, `xvfb-run [options]`, `wine`, `proton run`. Returns (rest, uses xvfb)."""
    xvfb = False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*=.*", t):
            i += 1
        elif t in LAUNCHERS:
            xvfb = xvfb or t == "xvfb-run"
            i += 1
            # The xvfb-run options (-a, -s "...", --server-args=...) are not the game's.
            while t == "xvfb-run" and i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in ("-s", "-n", "-e", "-f", "-p") else 1
        else:
            break
    return tokens[i:], xvfb


def _script_path(exe: str, cwd: str) -> str:
    """Executable path relative to /opt/game, or empty if it does not fit the broker."""
    path = exe
    if cwd and not exe.startswith("/"):
        path = posixpath.join(cwd, exe)
    path = posixpath.normpath(path)
    if path.startswith(CONTAINER_DIR + "/"):
        path = path[len(CONTAINER_DIR) + 1:]
    elif path.startswith("/"):
        return ""
    return path if _SCRIPT_RE.fullmatch(path) else ""


class Resolver(NamedTuple):
    defaults: dict[str, str]
    markers: dict[str, str]      # variable -> {PORT}/{QUERY_PORT}/{EXTRA_PORT}


def _is_option(token: str) -> bool:
    """`-port`, `+map` and Bannerlord's `/port`; `/Game/Maps/X` is a path, not an option."""
    return token[:1] in "-+" or (token[:1] == "/" and "/" not in token[1:])


def _resolve_token(token: str, res: Resolver) -> str | None:
    """Replaces the token's variables; None = the token (and the option that asks for it) goes."""
    def swap(m: re.Match[str]) -> str:
        var = m.group(1) or m.group(2)
        if var in res.markers:
            return res.markers[var]
        value = res.defaults.get(var, "")
        if _is_secret(var) or not value or not _ARGS_CHARSET.fullmatch(value):
            raise LookupError(var)
        return value
    try:
        out = _VAR.sub(swap, token)
    except LookupError:
        return None
    # The game folder in Pterodactyl is /home/container; here it is /opt/game.
    out = out.replace(CONTAINER_DIR, GAME_DIR)
    return out if _ARGS_CHARSET.fullmatch(out) else None


def clean_arguments(args: list[str], res: Resolver) -> tuple[str, list[str]]:
    """Keeps only what the broker accepts. Returns (arguments, names of what was dropped)."""
    resolved = [_resolve_token(t, res) for t in args]
    keep = [r is not None for r in resolved]
    # Without the value, the option that asked for it ("-name") would swallow the next one: it goes too.
    for i in range(1, len(args)):
        if not keep[i] and keep[i - 1] and _is_option(args[i - 1]) and "=" not in args[i - 1] \
                and not _is_option(args[i]):
            keep[i - 1] = False
    kept = [r for r, ok in zip(resolved, keep, strict=True) if ok and r is not None]
    dropped = [a.split("=", 1)[0].lstrip("-+/") for a, ok in zip(args, keep, strict=True)
               if not ok and _is_option(a)]
    return " ".join(kept), dropped


class Command(NamedTuple):
    script: str
    args: str
    xvfb: bool
    warnings: tuple[str, ...]


def parse_startup(startup: str, res: Resolver) -> Command:
    segment, cwd = _launch_segment(startup)
    chain = _CHAIN.search(segment)
    if chain:
        segment = segment[:chain.start()]
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    tokens, xvfb = _strip_launchers(tokens)
    xvfb = xvfb or "xvfb-run" in startup
    if not tokens:
        return Command("", "", xvfb, ("O egg nao diz qual e o executavel: preencha o script de start.",))
    exe, rest = tokens[0], tokens[1:]
    if posixpath.basename(exe) in INTERPRETERS:
        return Command("", "", xvfb, (f"O egg sobe o jogo por '{posixpath.basename(exe)}', que o broker "
                                      "nao chama: preencha o script de start e os argumentos a mao.",))
    warnings: list[str] = []
    script = _script_path(exe, cwd)
    if not script:
        warnings.append(f"O executavel do egg ({exe}) nao cabe no broker: preencha o script de start.")
    args, dropped = clean_arguments(rest, res)
    if dropped:
        warnings.append(f"Removi do comando o que o painel nao passa ({', '.join(sorted(set(dropped)))}): "
                        "nome, senha, IP e afins. Acrescente o que faltar.")
    if chain:
        warnings.append("O comando do egg encadeava outros comandos (;, |, &&): so o do jogo ficou.")
    return Command(script, args, xvfb, tuple(warnings))


# ---------------------------------------------------------------- the whole egg

def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def display_name(name: str) -> str:
    # "Astroneer Dedicated Server" is the EGG's name; in the search the person looks for the game.
    name = re.sub(r"\s+(dedicated\s+)?server$", "", name.strip(), flags=re.IGNORECASE)
    clean =re.sub(r"[^A-Za-z0-9 ._:'&()!+-]", "", _ascii(name)).strip(" .-")
    return clean[:40].rstrip() or "Jogo"


def game_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(name).lower()).strip("-")
    if not slug[:1].isalpha():
        slug = f"g-{slug}"
    slug = slug[:24].rstrip("-")
    return slug if KEY_RE.fullmatch(slug) else ""


def _variables(egg: dict) -> dict[str, str]:
    return {v.get("env_variable", ""): str(v.get("default_value") or "") for v in egg.get("variables", [])}


def _needs_account(defaults: dict[str, str], egg: dict) -> bool:
    for v in egg.get("variables", []):
        var = v.get("env_variable", "")
        if var in ("STEAM_USER", "STEAM_PASS", "SRCDS_LOGIN", "STEAM_USERNAME") and "required" in str(v.get("rules")):
            return defaults.get(var, "").lower() not in ("anonymous", "")
    return False


def is_windows(egg: dict, defaults: dict[str, str]) -> bool:
    images = " ".join(str(i) for i in (egg.get("docker_images") or {}).values()).lower()
    startup = str(egg.get("startup", "")).lower()
    return (defaults.get("WINDOWS_INSTALL") == "1" or "wine" in images or "proton" in images
            or re.search(r"\b(wine|wine64|proton)\b", startup) is not None)


def config_files(egg: dict) -> list[str]:
    """The files the egg edits (`config.files`), under /opt/game; only the ones the Config screen reads."""
    raw = (egg.get("config") or {}).get("files") or "{}"
    try:
        files = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for name in files if isinstance(files, dict) else []:
        # normpath, and NOT lstrip("./"): lstrip ate the "../" and turned "../../etc/x.ini" into
        # "etc/x.ini", a file the egg never mentioned. With normpath the ".." remains and is rejected.
        rel = posixpath.normpath(str(name).replace("\\", "/"))
        parts = rel.split("/")
        if rel.lower().endswith(CONFIG_EXTENSIONS) and all(_PATH_PART.fullmatch(p) and p != ".." for p in parts):
            out.append(f"{GAME_DIR}/{rel}")
    return out[:8]


def _markers(defaults: dict[str, str], ports: Ports) -> dict[str, str]:
    """Egg variable -> broker placeholder. The main port is always SERVER_PORT; the others are
    recognized by a default VALUE equal to the one in the README table."""
    markers = {"SERVER_PORT": PORT_MARKER}
    for var, value in defaults.items():
        if not value.isdigit():
            continue
        if ports.query and int(value) == ports.query and "QUERY" in var:
            markers[var] = QUERY_MARKER
        elif ports.extra and int(value) == ports.extra:
            markers[var] = EXTRA_MARKER
    return markers


class Egg(NamedTuple):
    data: dict
    readme: str
    folder: str


def suggest(egg: Egg) -> dict | None:
    data = egg.data
    defaults = _variables(data)
    appid = defaults.get("SRCDS_APPID", "")
    if not appid.isdigit() or int(appid) <= 0 or int(appid) in NOT_GAME_APPIDS \
            or _needs_account(defaults, data):
        return None
    name = display_name(str(data.get("name", "")))
    key = game_key(name)
    if not key:
        return None
    ports = classify_ports(port_rows(egg.readme))
    windows = is_windows(data, defaults)
    cmd = parse_startup(str(data.get("startup", "")), Resolver(defaults, _markers(defaults, ports)))
    warnings = [f"Tirado do egg '{egg.folder}' do Pterodactyl: confira antes de enviar."]
    if not ports.game:
        warnings.append("O README do egg nao lista a porta padrao: preencha as portas.")
    elif ports.presumed_udp:
        warnings.append("O egg nao diz o protocolo das portas: presumi UDP, o de todo jogo Steam.")
    if windows:
        warnings.append("Servidor so de Windows: roda pelo Proton (receita proton). Se nao subir, "
                        "troque para wine.")
    warnings += cmd.warnings
    files = config_files(data)
    args = cmd.args
    # A placeholder without a matching port would become "0" on the command line.
    if (QUERY_MARKER in args and not ports.query) or (EXTRA_MARKER in args and not ports.extra):
        args = ""
    return {
        "appid": int(appid), "name": name, "key": key,
        "ports": " ".join(ports.exposed), "game_port": ports.game, "query_port": ports.query,
        "extra_port": ports.extra,
        "start_script": cmd.script, "start_args": args,
        "shiftable": _shiftable(args, ports),
        "platform": "windows" if windows else "",
        "recipes": (["proton", "xvfb"] if cmd.xvfb else ["proton"]) if windows else [],
        "config_path": posixpath.dirname(files[0]) if files else "",
        "config_files": files, "backup_paths": [],
        "player_source": "a2s" if ports.query else "log",
        "warnings": warnings,
    }


def _shiftable(args: str, ports: Ports) -> bool:
    if not ports.game or PORT_MARKER not in args:
        return False
    if ports.query and QUERY_MARKER not in args:
        return False
    if ports.extra and EXTRA_MARKER not in args:
        return False
    numbers = {int(p.split("/")[0]) for p in ports.exposed}
    return numbers <= {ports.game, ports.query, ports.extra} - {0}


# ---------------------------------------------------------------- validation by the broker

def as_panel_data(s: dict) -> dict:
    """What the panel's form would send to the broker. Without a port (partial suggestion) the
    validator gets an arbitrary one: what is checked here is the rest."""
    data: dict = {"key": s["key"], "name": s["name"], "app_id": s["appid"],
                  "ports": s["ports"].split() or ["27015/udp"], "game_port": s["game_port"] or 27015,
                  "recipes": list(s.get("recipes") or []), "config_files": list(s.get("config_files") or []),
                  "backup_paths": [], "player_source": s.get("player_source", "log"),
                  "shiftable": s["shiftable"]}
    for field in ("start_script", "start_args", "config_path", "platform"):
        if s.get(field):
            data[field] = s[field]
    if not s["ports"]:
        data["player_source"] = "log"
    for field in ("query_port", "extra_port"):
        if s.get(field) and s["ports"]:
            data[field] = s[field]
    return data


def through_broker(s: dict) -> dict | None:
    """Final filter: the broker's validator. A rejected optional field goes (with a warning); a
    rejected identity or port drops the whole suggestion."""
    for _ in range(8):
        try:
            validate_dynamic(as_panel_data(s))
            return s
        except ValidationError as error:
            field = getattr(error, "field", "")
            if field in ("start_script", "start_args"):
                s = {**s, field: "", "shiftable": False,
                     "warnings": [*s["warnings"], f"O broker recusaria {field}; deixei em branco."]}
            elif field in ("config_path", "config_files"):
                s = {**s, "config_path": "", "config_files": []}
            elif field == "shiftable":
                s = {**s, "shiftable": False}
            elif field == "extra_port":
                s = {**s, "extra_port": 0, "shiftable": False}
            else:
                return None
    return None


# ---------------------------------------------------------------- merging with LinuxGSM

def complement(linuxgsm: dict, egg: dict) -> dict:
    """The EMPTY LinuxGSM fields that the egg knows. Ports go as a block (and the game stops being
    shiftable): mixing one's port with the other's query matches no game at all."""
    extra: dict = {}
    # Field by field: a LinuxGSM entry that already knows the FOLDER (Sven Co-op) keeps its own,
    # and the egg only brings the files it did not list.
    if not linuxgsm.get("config_files") and egg.get("config_files"):
        extra["config_files"] = egg["config_files"]
        if not linuxgsm.get("config_path"):
            extra["config_path"] = egg["config_path"]
    if not linuxgsm.get("ports") and egg.get("ports"):
        extra.update(ports=egg["ports"], game_port=egg["game_port"], query_port=egg["query_port"],
                     extra_port=egg["extra_port"], shiftable=False,
                     player_source=egg["player_source"])
    if not extra:
        return {}
    merged = {**linuxgsm, **extra, "warnings": []}
    return extra if through_broker(merged) is merged else {}


# ---------------------------------------------------------------- reading and writing

def _readme_for(egg_path: pathlib.PurePosixPath, readmes: dict[str, str]) -> str:
    """The README of the egg's folder; if it has none, the parent folder's (game with variants)."""
    folder = egg_path.parent
    return readmes.get(str(folder / "README.md")) or readmes.get(str(folder.parent / "README.md"), "")


def _pick(paths: list[pathlib.PurePosixPath]) -> list[pathlib.PurePosixPath]:
    """One egg per folder: each one carries the same game exported in the Pterodactyl and Pelican
    formats. The Pterodactyl one stays, which is the format of the rest."""
    by_folder: dict[str, pathlib.PurePosixPath] = {}
    for p in sorted(paths):
        current = by_folder.get(str(p.parent))
        if current is None or p.name.startswith("egg-pterodactyl-"):
            by_folder[str(p.parent)] = p
    return list(by_folder.values())


def load_eggs(files: dict[str, str]) -> list[Egg]:
    """`files`: relative path (with /) -> text, from a clone or from the tarball."""
    readmes = {k: v for k, v in files.items() if k.endswith("/README.md")}
    paths = [pathlib.PurePosixPath(k) for k in files
             if pathlib.PurePosixPath(k).name.startswith("egg-") and k.endswith(".json")]
    eggs = []
    for p in _pick(paths):
        try:
            data = json.loads(files[str(p)])
        except ValueError:
            continue
        eggs.append(Egg(data, _readme_for(p, readmes), str(p.parent)))
    return eggs


def _from_folder(folder: pathlib.Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in folder.rglob("*") if p.is_file() and p.suffix in (".json", ".md")}


def _from_github() -> dict[str, str]:
    req = urllib.request.Request(TARBALL_URL, headers={"User-Agent": "gamepanel-importer"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed URL, https
        raw = r.read()
    out = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and member.name.endswith((".json", ".md")):
                rel = member.name.split("/", 1)[1] if "/" in member.name else member.name
                handle = tar.extractfile(member)
                if handle is not None:
                    out[rel] = handle.read().decode("utf-8", "replace")
    return out


def _variant_rank(s: dict) -> tuple[int, int]:
    low = s["name"].lower()
    return (sum(w in low for w in VARIANT_WORDS), len(low))


def _known() -> tuple[dict[int, dict], set[int], set[str]]:
    """What already exists: LinuxGSM (by App ID), App IDs of the manual list and the curated ones, and the keys."""
    catalog = ROOT / "src" / "gamepanel" / "games" / "catalog"
    ns: dict = {}
    exec(compile((catalog / "suggestions.py").read_text(encoding="utf-8"), "suggestions", "exec"), ns)  # noqa: S102
    manual: dict = {}
    exec(compile((catalog / "manual_suggestions.py").read_text(encoding="utf-8"), "manual", "exec"), manual)  # noqa: S102
    linuxgsm = {s["appid"]: s for s in ns["SUGGESTIONS"]}
    taken_appids = {s["appid"] for s in manual["SUGGESTIONS"]}
    keys = {s["key"] for s in ns["SUGGESTIONS"]} | {s["key"] for s in manual["SUGGESTIONS"]}
    for env in (ROOT / "games").glob("[!_]*.env"):
        values = read_env(env.read_text(encoding="utf-8"))
        keys.add(values.get("GAME_KEY", env.stem))
        if values.get("STEAM_APP_ID", "").isdigit():
            taken_appids.add(int(values["STEAM_APP_ID"]))
    return linuxgsm, taken_appids, keys


def collect(files: dict[str, str]) -> tuple[list[dict], dict[int, dict], list[str]]:
    linuxgsm, taken_appids, keys = _known()
    by_appid: dict[int, dict] = {}
    skipped: list[str] = []
    for egg in load_eggs(files):
        s = suggest(egg)
        if s is None:
            skipped.append(egg.folder)
            continue
        # Several variants of the same game (vanilla, BepInEx, oxide): the simplest one stays.
        current = by_appid.get(s["appid"])
        if current is None or _variant_rank(s) < _variant_rank(current):
            by_appid[s["appid"]] = s
    new, complements = [], {}
    for appid, s in sorted(by_appid.items(), key=lambda kv: kv[1]["name"].lower()):
        if appid in linuxgsm:
            extra = complement(linuxgsm[appid], s)
            if extra:
                complements[appid] = extra
            continue
        if appid in taken_appids or s["key"] in keys:
            continue
        valid = through_broker(s)
        if valid is None:
            skipped.append(s["name"])
            continue
        keys.add(valid["key"])
        new.append(valid)
    return new, complements, skipped


def write(new: list[dict], complements: dict[int, dict], out: pathlib.Path) -> None:
    body = "".join(f"    {pprint.pformat(s, width=110, sort_dicts=False).replace(chr(10), chr(10) + '    ')},\n"
                   for s in new)
    comp = pprint.pformat(complements, width=110, sort_dicts=True)
    text = (
        '"""Sugestoes de jogo tiradas dos eggs do Pterodactyl — GERADO, NAO EDITE.\n\n'
        "Gerado por tools/import-pterodactyl.py (pelican-eggs/games-steamcmd, MIT). Para atualizar,\n"
        "rode o script e revise o diff. SUGGESTIONS sao jogos que o LinuxGSM, a lista manual e os\n"
        "curados nao tem; COMPLEMENTS sao os campos vazios de uma sugestao do LinuxGSM que o egg\n"
        "preenche (por App ID). Tudo aqui ja passou pelo validador do broker na geracao.\n"
        '"""\n'
        f'SOURCE = "{SOURCE_NAME}, gerado em {datetime.date.today().isoformat()}"\n\n'
        f"SUGGESTIONS = (\n{body})\n\n"
        # The annotation goes into the file: without it mypy infers `dict[int, object]` from the
        # content and rejects the search's `**extra`.
        f"COMPLEMENTS: dict[int, dict] = {comp}\n"
    )
    out.write_bytes(text.encode("utf-8"))  # bytes: on Windows text mode would turn \n into \r\n


def main() -> None:
    doc = __doc__ or ""
    ap = argparse.ArgumentParser(description=doc.split("\n")[0])
    ap.add_argument("--source", type=pathlib.Path, help="clone local de pelican-eggs/games-steamcmd")
    ap.add_argument("--out", type=pathlib.Path,
                    default=ROOT / "src" / "gamepanel" / "games" / "catalog" / "pterodactyl_suggestions.py")
    opts = ap.parse_args()
    files = _from_folder(opts.source) if opts.source else _from_github()
    new, complements, skipped = collect(files)
    write(new, complements, opts.out)
    print(f"{len(new)} jogos novos e {len(complements)} complementos do LinuxGSM em {opts.out} "
          f"({len(skipped)} eggs sem App ID, com conta Steam ou recusados)")


if __name__ == "__main__":
    main()
