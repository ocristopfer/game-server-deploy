"""Catalog of games the broker knows how to create.

Two sources, a single type (`Game`):

- **curated**: the repository's `games/*.env`. You reviewed it in git, so it may carry
  `PRE/POST_INSTALL_CMD`. It is the same list `deploy-game.ps1` uses - there is no second
  catalog to keep in parallel.
- **dynamic**: registered via the API. It is only data: each field has its own regex and none
  becomes a command. A field the broker does not know is refused, otherwise `pre_install_cmd`
  would be smuggled in.

The `.env` NEVER goes through `source` here. It is read by its own parser that does not expand
`$VAR`, `$(...)` or backticks: what is in the file is the text, period.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from gamebroker.domain.exceptions import Conflict, NotFound, ValidationError

SOURCE_CURATED = "curado"
SOURCE_DYNAMIC = "dinamico"

# Recipes: a CLOSED list in the code. A dynamic game picks from here, never writes shell.
RECIPES = ("wine", "proton", "xvfb", "vulkan", "steamclient-sdk64")
RECIPES_WINDOWS = ("wine", "proton")
# Virtual X for the .exe that creates a window even headless (Icarus, V Rising). It is a recipe,
# not a field, because it only makes sense together with a Windows runtime: on its own it would
# install xvfb on a CT that never calls it.
RECIPE_XVFB = "xvfb"
# Software Vulkan driver (Mesa's lavapipe), for the .exe that creates a Direct3D 12 device even
# headless (ARK: Survival Ascended): Proton turns D3D12 into Vulkan, and with no driver the server
# dies at boot. Same reasoning as xvfb: it only means anything next to a Windows runtime.
RECIPE_VULKAN = "vulkan"
# Recipes that need a Windows runtime next to them.
RECIPES_NEED_RUNTIME = (RECIPE_XVFB, RECIPE_VULKAN)

# Ports no game may ever expose: panel, Proxmox, REST API and RCON
# (see PORT_NOTES in palworld.env - the panel talks to them from inside the container).
FORBIDDEN_PORTS = frozenset({22, 80, 443, 8006, 8080, 8212, 25575})

KEY_RE = re.compile(r"[a-z][a-z0-9-]{1,23}", re.ASCII)
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}", re.ASCII)
# A GAME name, not an instance name: "RuneScape: Dragonwilds" has a colon, and with NAME_RE
# editing the curated game was refused ("name: formato invalido"). The name goes into
# install.env (via shlex.quote) and into the systemd unit's `Description=`, so `%` (systemd
# specifier), double quotes, `$`, backtick, backslash and line break stay out. The instance
# name still uses NAME_RE: it becomes a CT name.
GAME_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:'&()!+-]{0,39}", re.ASCII)
_PORT_RE = re.compile(r"(\d{1,5})/(tcp|udp)", re.ASCII)
_SCRIPT_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", re.ASCII)
_PATH_RE = re.compile(r"/(opt/game|home/steam)(/[A-Za-z0-9._-]+)*", re.ASCII)
# No ; | & $ ` ( ) < > \ quotes or line breaks: START_ARGS ends up in a command line inside
# the CT. {PORT} and {QUERY_PORT} are the only placeholders: braces are in the charset, and
# `_args_de_start` rejects any brace left over after removing those two.
_ARGS_RE = re.compile(r"[A-Za-z0-9 ._=:,/+@?{}-]{0,300}", re.ASCII)
_PLACEHOLDERS = ("{PORT}", "{QUERY_PORT}", "{EXTRA_PORT}")
_REGEX_MAX_LEN = 200
# (a+)+ , (.*)* , (a|b*)+ : repetition inside a repeating group. Python's `re` has no
# timeout, so this shape is refused before it exists. The search only runs on text of up to
# _REGEX_TAMANHO_MAX characters (checked beforehand), which bounds the backtracking cost.
_NESTED_REPETITION = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]")  # NOSONAR
_ASSIGN_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)=(.*)$", re.ASCII)

# 'net' = active conversations on the game port, counted by the firewall the broker itself puts
# in the CT (FW_PRESENCE_PORTS in ct-phases.sh); it needs nothing from the game.
PLAYER_SOURCES_DYNAMIC = ("a2s", "net", "log")
PLATFORMS = ("", "linux", "windows")


@dataclass(frozen=True)
class Port:
    number: int
    proto: str

    def __str__(self) -> str:
        return f"{self.number}/{self.proto}"


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    app_id: int
    platform: str
    ports: tuple[Port, ...]
    game_port: int
    query_port: int
    memory_mb: int
    cores: int
    disk_gb: int
    start_script: str
    start_args: str
    config_path: str
    config_files: tuple[str, ...]
    backup_paths: tuple[str, ...]
    player_source: str
    join_re: str
    leave_re: str
    log_path: str
    recipes: tuple[str, ...]
    shiftable: bool
    source: str
    creatable: bool
    reason: str
    # Shell reviewed by you (only the curated catalog has it). Never leaves through the API.
    pre_install: str = ""
    post_install: str = ""
    # Third port the game accepts through its arguments ({EXTRA_PORT}): Satisfactory's
    # "reliable" one (-ReliablePort), for example. 0 = the game has none.
    extra_port: int = 0
    # Curated game with its DATA edited via the API (see `Catalog.update`). The shell stays the
    # one from the .env: that is what allows editing a curated game without opening a door to commands.
    edited: bool = False
    # The server does not download with anonymous login (DayZ): it only exists in the curated
    # catalog, and the installer takes the broker's Steam account to the CT. An API game never
    # asks for it (`validate_dynamic`).
    needs_account: bool = False
    # WINE_DLL_OVERRIDES from the curated .env. Empty = the installer's default (ct-phases.sh).
    # It used not to go into the broker's install.env: V Rising needed mscoree enabled (it is what
    # lets BepInEx, .NET, load) and the CT created by the panel was born with the default, which
    # disables it. It only exists in the curated catalog, like the shell: an API game does not pick Wine DLLs.
    wine_overrides: str = ""
    # Server slots (MAX_PLAYERS from the .env). The panel only uses it when the count does not
    # bring the total - log or active connections; A2S brings its own. 0 = unknown.
    max_players: int = 0
    # The CLIENT's Steam appid, for a Windows .exe without a steam_appid.txt next to it (Conan
    # Exiles: 440900, while the server app is 443030). win-run hands it to Proton; without it the
    # server reports appid 0 and the game's server browser never lists it. 0 = not needed.
    client_app_id: int = 0

    @property
    def has_hooks(self) -> bool:
        return bool(self.pre_install or self.post_install)

    def as_public(self) -> dict:
        """What the API shows: no command, no installer path."""
        return {
            "key": self.key, "name": self.name, "app_id": self.app_id,
            "ports": [str(p) for p in self.ports], "game_port": self.game_port,
            "query_port": self.query_port, "extra_port": self.extra_port,
            "memory_mb": self.memory_mb,
            "cores": self.cores, "disk_gb": self.disk_gb,
            "recipes": list(self.recipes), "shiftable": self.shiftable,
            "source": self.source, "creatable": self.creatable, "reason": self.reason,
            "edited": self.edited, "client_app_id": self.client_app_id,
        }

    def as_stored(self) -> dict:
        """Form written to disk; `validate_dynamic` accepts it back."""
        return {
            "key": self.key, "name": self.name, "app_id": self.app_id,
            "platform": self.platform, "start_script": self.start_script,
            "start_args": self.start_args, "ports": [str(p) for p in self.ports],
            "game_port": self.game_port, "query_port": self.query_port,
            "extra_port": self.extra_port,
            "memory_mb": self.memory_mb, "cores": self.cores, "disk_gb": self.disk_gb,
            "config_path": self.config_path, "config_files": list(self.config_files),
            "backup_paths": list(self.backup_paths), "player_source": self.player_source,
            "join_re": self.join_re, "leave_re": self.leave_re, "log_path": self.log_path,
            "recipes": list(self.recipes), "shiftable": self.shiftable,
            "max_players": self.max_players, "client_app_id": self.client_app_id,
        }


# ----------------------------------------------------------------------------
# Safe reading of the .env (no shell)
# ----------------------------------------------------------------------------

def read_env(text: str) -> dict[str, str]:
    """Reads `CHAVE=valor` without executing anything. Single/double quotes may span several lines."""
    lines = text.splitlines()
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _ASSIGN_RE.match(lines[i])
        i += 1
        if not m:
            continue
        key, rest = m.group(1), m.group(2).lstrip()
        if rest[:1] in ("'", '"'):
            value, i = _quoted_value(key, rest, lines, i)
        else:
            value = re.split(r"\s#", rest, maxsplit=1)[0].strip()
        out[key] = value
    return out


def _quoted_value(key: str, rest: str, lines: list[str], start: int) -> tuple[str, int]:
    quote = rest[0]
    body = "\n".join([rest[1:], *lines[start:]])
    pieces: list[str] = []
    k = 0
    while k < len(body):
        c = body[k]
        if quote == '"' and c == "\\" and k + 1 < len(body):
            nxt = body[k + 1]
            pieces.append(nxt if nxt in '"\\$`' else c + nxt)
            k += 2
        elif c == quote and quote == "'" and body.startswith("\\''", k + 1):
            # 'abc'\''def' : the shell's way of writing an apostrophe inside single quotes.
            pieces.append("'")
            k += 4
        elif c == quote:
            return "".join(pieces), start + body[:k].count("\n")
        else:
            pieces.append(c)
            k += 1
    raise ValueError(f"{key}: aspas sem fechar")


# ----------------------------------------------------------------------------
# Curated game (games/*.env)
# ----------------------------------------------------------------------------

def _port(text: str) -> Port:
    m = _PORT_RE.fullmatch(text.strip())
    if not m or not 1 <= int(m.group(1)) <= MAX_PORT:
        raise ValueError(f"porta invalida: {text!r}")
    return Port(int(m.group(1)), m.group(2))


def _parts(value: str, separator: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in re.split(separator, value) if p.strip())


# The largest port that exists in TCP/UDP: the field has 16 bits. It shows up in four broker
# checks, and the constant says what the number IS - a bare `65535` looks like an arbitrary
# limit. It lives HERE, and not in `allocator`, because the allocator imports `Game` from here:
# the other way around would be a cycle.
MAX_PORT = 65535


def _env_int(data: dict[str, str], key: str, default: int) -> int:
    raw = data.get(key, "").strip()
    return int(raw) if raw else default


def shiftable_problem(ports: tuple[Port, ...], game_port: int, query_port: int,
                           start_args: str, extra_port: int = 0) -> str:
    """A game only moves ports if the broker can TELL the game about all of them.

    The broker hands the game up to three ports ({PORT}, {QUERY_PORT} and {EXTRA_PORT}). A
    fourth (DayZ has 2303/2304) would be open in the firewall on a number the game does not
    listen on, and the client would connect to nothing. Without the placeholder in START_ARGS
    the game ignores the drawn number.
    """
    tellable = {game_port, query_port, extra_port} - {0}
    if any(p.number not in tellable for p in ports):
        return ("so aceita as portas do jogo, da query e uma extra "
                "(o broker nao avisa mais portas ao jogo)")
    if "{PORT}" not in start_args:
        return "start_args precisa de {PORT}: e por ele que o jogo recebe a porta sorteada"
    if query_port and "{QUERY_PORT}" not in start_args:
        return "start_args precisa de {QUERY_PORT}: e por ele que o jogo recebe a porta de consulta"
    if extra_port and "{EXTRA_PORT}" not in start_args:
        return "start_args precisa de {EXTRA_PORT}: e por ele que o jogo recebe a porta extra"
    return ""


def extra_port_problem(start_args: str, extra_port: int) -> str:
    """{EXTRA_PORT} without an extra port would become "0" on the game's command line."""
    if "{EXTRA_PORT}" in start_args and not extra_port:
        return "start_args usa {EXTRA_PORT}, mas o jogo nao tem porta extra (EXTRA_PORT / porta_extra)"
    return ""


def _reason_not_creatable(data: dict[str, str], app_id: int, ports: tuple[Port, ...],
                          steam_account: bool) -> str:
    if data.get("PROVISION_SCRIPT"):
        return "instalador proprio (nao e Steam); use o deploy-game.ps1"
    if data.get("STEAM_ANONYMOUS", "1") == "0" and not steam_account:
        return ("exige conta Steam: configure STEAM_USER/STEAM_PASS no broker.secrets.env "
                "(ou use o deploy-game.ps1)")
    if app_id <= 0:
        return "sem STEAM_APP_ID"
    if not ports:
        return "sem portas em GAME_PORTS"
    return ""


def game_from_env(file_name: str, data: dict[str, str], steam_account: bool = False) -> Game:
    key = data.get("GAME_KEY", file_name)
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"GAME_KEY invalida: {key!r}")
    app_id = _env_int(data, "STEAM_APP_ID", 0)
    ports = tuple(_port(p) for p in _parts(data.get("GAME_PORTS", ""), r"\s+"))
    runtime = data.get("WINDOWS_RUNTIME", "")
    reason = _reason_not_creatable(data, app_id, ports, steam_account)
    shiftable = data.get("PORTS_SHIFTABLE", "0") == "1"
    extra_port = _env_int(data, "EXTRA_PORT", 0)
    problem = extra_port_problem(data.get("START_ARGS", ""), extra_port)
    if problem:
        raise ValueError(problem)
    if shiftable:
        problem = shiftable_problem(ports, _env_int(data, "GAME_PORT", 0),
                                          _env_int(data, "QUERY_PORT", 0), data.get("START_ARGS", ""),
                                          extra_port)
        if problem:
            raise ValueError(f"PORTS_SHIFTABLE=1 invalido: {problem}")
    return Game(
        key=key, name=data.get("GAME_DISPLAY_NAME", key), app_id=app_id,
        platform=data.get("STEAM_PLATFORM", ""), ports=ports,
        game_port=_env_int(data, "GAME_PORT", 0),
        query_port=_env_int(data, "QUERY_PORT", 0), extra_port=extra_port,
        memory_mb=_env_int(data, "RECOMMENDED_MEMORY", 4096),
        cores=_env_int(data, "RECOMMENDED_CORES", 2),
        disk_gb=_env_int(data, "RECOMMENDED_DISK_GB", 20),
        start_script=data.get("START_SCRIPT", ""), start_args=data.get("START_ARGS", ""),
        config_path=data.get("CONFIG_PATH", ""),
        config_files=_parts(data.get("CONFIG_FILES", ""), ","),
        backup_paths=_parts(data.get("BACKUP_PATHS", ""), ","),
        player_source=data.get("PLAYER_SOURCE", "log"),
        join_re=data.get("JOIN_RE", ""), leave_re=data.get("LEAVE_RE", ""),
        log_path=data.get("LOG_PATH", ""),
        recipes=_curated_recipes(runtime, data.get("WINDOWS_RUNTIME_XVFB", "0") == "1"),
        shiftable=shiftable,
        source=SOURCE_CURATED, creatable=not reason, reason=reason,
        needs_account=data.get("STEAM_ANONYMOUS", "1") == "0",
        wine_overrides=data.get("WINE_DLL_OVERRIDES", ""),
        pre_install=data.get("PRE_INSTALL_CMD", ""),
        max_players=_env_int(data, "MAX_PLAYERS", 0),
        client_app_id=_env_int(data, "CLIENT_APP_ID", 0),
        post_install=data.get("POST_INSTALL_CMD", ""),
    )


def _curated_recipes(runtime: str, xvfb: bool) -> tuple[str, ...]:
    """The runtime and virtual X of a curated game, in the same shape as a dynamic game's
    recipes: that is how the broker's `install.env` reaches the CT. It used to be only the
    runtime, and an Icarus created by the panel came up WITHOUT the virtual X the .env asks for
    (deploy-game.ps1, which reads the raw file, never had the problem)."""
    if runtime not in RECIPES_WINDOWS:
        return ()
    return (runtime, RECIPE_XVFB) if xvfb else (runtime,)


def load_curated(directory: Path, steam_account: bool = False) -> tuple[dict[str, Game], list[str]]:
    """Reads `games/*.env` (except those starting with `_`). A bad file becomes an error, not an exception."""
    games: dict[str, Game] = {}
    errors: list[str] = []
    for file in sorted(Path(directory).glob("*.env")):
        if file.name.startswith("_"):
            continue
        try:
            game = game_from_env(file.stem, read_env(file.read_text(encoding="utf-8")), steam_account)
        except (ValueError, OSError) as error:
            errors.append(f"{file.name}: {error}")
            continue
        games[game.key] = game
    return games, errors


# ----------------------------------------------------------------------------
# Dynamic game (API)
# ----------------------------------------------------------------------------

_DYNAMIC_FIELDS = frozenset({
    "key", "name", "app_id", "platform", "start_script", "start_args", "ports",
    "game_port", "query_port", "extra_port", "memory_mb", "cores", "disk_gb", "config_path",
    "config_files", "backup_paths", "player_source", "join_re", "leave_re", "log_path",
    "recipes", "shiftable", "max_players", "client_app_id",
})
_REQUIRED_FIELDS = ("key", "name", "app_id", "ports", "game_port")


def _int_field(data: dict, field: str, minimum: int, maximum: int, default: int | None = None) -> int:
    if field not in data:
        if default is None:
            raise ValidationError(field, "obrigatorio")
        return default
    value = data[field]
    # bool is a subclass of int in Python: `true` must not pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(field, "deve ser um numero inteiro")
    if not minimum <= value <= maximum:
        raise ValidationError(field, f"deve estar entre {minimum} e {maximum}")
    return value


def _text_field(data: dict, field: str, regex: re.Pattern[str], default: str = "",
           required: bool = False) -> str:
    value = data.get(field, default)
    if not isinstance(value, str):
        raise ValidationError(field, "deve ser texto")
    # Empty only counts for an optional field: an empty key/name would pass as "absent".
    if (value or required) and not regex.fullmatch(value):
        raise ValidationError(field, "formato invalido")
    return value


def _text_list(data: dict, field: str, maximum: int) -> list[str]:
    value = data.get(field, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValidationError(field, "deve ser uma lista de textos")
    if len(value) > maximum:
        raise ValidationError(field, f"no maximo {maximum} itens")
    return value


def _no_dot_dot(path: str, field: str) -> str:
    if ".." in path.split("/"):
        raise ValidationError(field, "'..' nao e permitido")
    return path


def _path_list(data: dict, field: str, maximum: int) -> tuple[str, ...]:
    items = _text_list(data, field, maximum)
    for item in items:
        if not _PATH_RE.fullmatch(item):
            raise ValidationError(field, "so caminhos absolutos sob /opt/game ou /home/steam")
        _no_dot_dot(item, field)
    return tuple(items)


def _ports_field(data: dict) -> tuple[Port, ...]:
    items = _text_list(data, "ports", 8)
    ports: list[Port] = []
    for item in items:
        try:
            port = _port(item)
        except ValueError as error:
            raise ValidationError("ports", str(error)) from None
        if port.number < 1024:
            raise ValidationError("ports", f"{port}: portas abaixo de 1024 nao sao permitidas")
        if port.number in FORBIDDEN_PORTS:
            raise ValidationError("ports", f"{port}: porta reservada (painel, Proxmox, REST ou RCON)")
        ports.append(port)
    if not ports or len(set(ports)) != len(ports):
        raise ValidationError("ports", "informe ao menos uma porta, sem repetir")
    return tuple(ports)


def _log_regex(data: dict, field: str) -> str:
    default = data.get(field, "")
    if not isinstance(default, str):
        raise ValidationError(field, "deve ser texto")
    if not default:
        return ""
    if len(default) > _REGEX_MAX_LEN:
        raise ValidationError(field, f"no maximo {_REGEX_MAX_LEN} caracteres")
    if _NESTED_REPETITION.search(default):
        raise ValidationError(field, "repeticao dentro de repeticao (risco de travar o painel)")
    try:
        re.compile(default)
    except re.error as error:
        raise ValidationError(field, f"regex invalida: {error}") from None
    return default


def _start_args_field(data: dict) -> str:
    args = _text_field(data, "start_args", _ARGS_RE)
    leftover = args
    for placeholder in _PLACEHOLDERS:
        leftover = leftover.replace(placeholder, "")
    if "{" in leftover or "}" in leftover:
        raise ValidationError("start_args", "so {PORT}, {QUERY_PORT} e {EXTRA_PORT} sao marcadores validos")
    return args


def _start_script_field(data: dict) -> str:
    script = _text_field(data, "start_script", _SCRIPT_RE)
    return _no_dot_dot(script, "start_script")


def _recipes_field(data: dict, platform: str) -> tuple[str, ...]:
    items = _text_list(data, "recipes", len(RECIPES))
    unknown = next((r for r in items if r not in RECIPES), None)
    if unknown is not None:
        raise ValidationError("recipes", f"receita desconhecida: {unknown!r}")
    if platform == "windows" and not set(items) & set(RECIPES_WINDOWS):
        raise ValidationError("recipes", "jogo de Windows precisa da receita 'proton' ou 'wine'")
    for recipe in RECIPES_NEED_RUNTIME:
        if recipe in items and not set(items) & set(RECIPES_WINDOWS):
            raise ValidationError("recipes", f"'{recipe}' only works together with 'proton' or 'wine'")
    return tuple(dict.fromkeys(items))


# The field names this API used before it spoke English. It exists only for the game that was
# already SAVED in `<estado>/dinamico/*.json` when the broker was updated: without this it
# would become an "unknown field" on the first reload and vanish from the catalog, taking with
# it the instance that depended on it. The file is rewritten in the new format on the next
# save; the table is closed, so a smuggled field is still refused.
_LEGACY_FIELDS = {
    "chave": "key", "nome": "name", "plataforma": "platform", "portas": "ports",
    "porta_jogo": "game_port", "porta_query": "query_port", "porta_extra": "extra_port",
    "memoria_mb": "memory_mb", "disco_gb": "disk_gb", "receitas": "recipes",
    "deslocavel": "shiftable",
}


def _without_legacy_names(data: dict) -> dict:
    """Translates the old names; a field given BOTH ways is refused."""
    repeated = sorted(v for k, v in _LEGACY_FIELDS.items() if k in data and v in data)
    if repeated:
        raise ValidationError(repeated[0], "informado duas vezes (nome antigo e novo)")
    return {_LEGACY_FIELDS.get(k, k): v for k, v in data.items()}


def validate_dynamic(data: object) -> Game:
    """Validates a game coming from the API. Any doubt means refusal: nothing here becomes a command."""
    if not isinstance(data, dict):
        raise ValidationError("corpo", "esperado um objeto JSON")
    data = _without_legacy_names(data)
    unknown_field = sorted(set(data) - _DYNAMIC_FIELDS)
    if unknown_field:
        raise ValidationError(unknown_field[0], "campo desconhecido (a API so aceita dados, nunca comandos)")
    missing = [c for c in _REQUIRED_FIELDS if c not in data]
    if missing:
        raise ValidationError(missing[0], "obrigatorio")

    ports = _ports_field(data)
    game_port = _int_field(data, "game_port", 1024, MAX_PORT)
    if game_port not in {p.number for p in ports}:
        raise ValidationError("game_port", "deve estar entre as portas expostas")
    query_port = _int_field(data, "query_port", 0, MAX_PORT, default=0)
    if query_port and query_port not in {p.number for p in ports}:
        raise ValidationError("query_port", "deve estar entre as portas expostas (ou 0)")
    extra_port = _int_field(data, "extra_port", 0, MAX_PORT, default=0)
    if extra_port and extra_port not in {p.number for p in ports}:
        raise ValidationError("extra_port", "deve estar entre as portas expostas (ou 0)")
    if extra_port and extra_port in (game_port, query_port):
        raise ValidationError("extra_port", "deve ser diferente da porta do jogo e da de consulta")

    platform = _text_field(data, "platform", re.compile(r"linux|windows"))
    player_source_raw = data.get("player_source", "log")
    if player_source_raw not in PLAYER_SOURCES_DYNAMIC:
        raise ValidationError("player_source", f"use {' ou '.join(PLAYER_SOURCES_DYNAMIC)}")
    shiftable = data.get("shiftable", False)
    if not isinstance(shiftable, bool):
        raise ValidationError("shiftable", "deve ser verdadeiro ou falso")
    start_args = _start_args_field(data)
    problem = extra_port_problem(start_args, extra_port)
    if problem:
        raise ValidationError("start_args", problem)
    if shiftable:
        problem = shiftable_problem(ports, game_port, query_port, start_args, extra_port)
        if problem:
            raise ValidationError("shiftable", problem)

    return Game(
        key=_text_field(data, "key", KEY_RE, required=True),
        name=_text_field(data, "name", GAME_NAME_RE, required=True),
        app_id=_int_field(data, "app_id", 1, 2**31 - 1),
        platform=platform, ports=ports, game_port=game_port, query_port=query_port,
        extra_port=extra_port,
        memory_mb=_int_field(data, "memory_mb", 512, 65536, default=4096),
        cores=_int_field(data, "cores", 1, 16, default=2),
        disk_gb=_int_field(data, "disk_gb", 4, 500, default=20),
        start_script=_start_script_field(data), start_args=start_args,
        config_path=_single_path(data, "config_path"),
        config_files=_path_list(data, "config_files", 8),
        backup_paths=_path_list(data, "backup_paths", 8),
        player_source=player_source_raw,
        join_re=_log_regex(data, "join_re"), leave_re=_log_regex(data, "leave_re"),
        log_path=_single_path(data, "log_path"),
        recipes=_recipes_field(data, platform), shiftable=shiftable,
        source=SOURCE_DYNAMIC, creatable=True, reason="",
        max_players=_int_field(data, "max_players", 0, 1000, default=0),
        client_app_id=_int_field(data, "client_app_id", 0, 2**31 - 1, default=0),
    )


def _single_path(data: dict, field: str) -> str:
    value = _text_field(data, field, _PATH_RE)
    return _no_dot_dot(value, field)


# ----------------------------------------------------------------------------
# Curated catalog, plus the dynamic one
# ----------------------------------------------------------------------------

def _as_override(curated: Game, edited: Game) -> Game:
    """The DATA comes from the edit; what only git can say comes from the .env.

    The shell (`pre_install`/`post_install`) and the reason the game is creatable or not stay
    those of the file: the edit went through `validate_dynamic`, which never accepts a command,
    and it cannot turn into creatable a game that requires a Steam account or its own installer.
    """
    return dataclasses.replace(
        edited, source=SOURCE_CURATED, creatable=curated.creatable, reason=curated.reason,
        pre_install=curated.pre_install, post_install=curated.post_install,
        needs_account=curated.needs_account, wine_overrides=curated.wine_overrides, edited=True,
        # The catalog edit screen does not have this field: without this, editing Dragonwilds
        # would zero the 6 slots that only the .env knows.
        max_players=edited.max_players or curated.max_players,
        client_app_id=edited.client_app_id or curated.client_app_id)


def _checked_key(key: str) -> str:
    # The key becomes a FILE name in `_dynamic_dir`: without the regex, `../x` would leave the folder.
    if not KEY_RE.fullmatch(key or ""):
        raise ValidationError("key", "formato invalido")
    return key


class Catalog:
    def __init__(self, curated_dir: Path, dynamic_dir: Path, steam_account: bool = False):
        self._curated_dir = Path(curated_dir)
        self._dynamic_dir = Path(dynamic_dir)
        # Does the broker have a Steam account configured? Decides whether the curated game that needs one is creatable.
        self._steam_account = steam_account
        self._lock = threading.Lock()
        self._games: dict[str, Game] = {}
        # The curated game as git describes it, to undo an edit without rereading the folder.
        self._curated: dict[str, Game] = {}
        self.errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        curated, errors = load_curated(self._curated_dir, self._steam_account)
        games = dict(curated)
        self._dynamic_dir.mkdir(parents=True, exist_ok=True)
        for file in sorted(self._dynamic_dir.glob("*.json")):
            try:
                # Revalidate on read: a file tampered with on disk does not become a creatable game.
                game = validate_dynamic(json.loads(file.read_text(encoding="utf-8")))
            except (ValueError, OSError, ValidationError) as error:
                errors.append(f"{file.name}: {error}")
                continue
            if file.stem != game.key:
                errors.append(f"{file.name}: chave diferente do nome do arquivo")
                continue
            base = curated.get(game.key)
            if base is None:
                games[game.key] = game
            elif base.creatable:
                # Same key as a curated game = its edit (see `update`).
                games[game.key] = _as_override(base, game)
            else:
                errors.append(f"{file.name}: edita um jogo curado que nao pode ser editado pela API")
        with self._lock:
            self._games, self._curated, self.errors = games, curated, errors

    def list_all(self) -> list[Game]:
        with self._lock:
            return sorted(self._games.values(), key=lambda j: j.key)

    def get(self, key: str) -> Game:
        with self._lock:
            game = self._games.get(key)
        if game is None:
            raise NotFound(f"jogo desconhecido: {key!r}")
        return game

    def add_dynamic(self, data: object) -> Game:
        game = validate_dynamic(data)
        with self._lock:
            if game.key in self._games:
                raise Conflict(f"ja existe um jogo com a chave {game.key!r}")
            self._store(game)
            self._games[game.key] = game
        return game

    def stored(self, key: str) -> dict:
        """The whole game, for the edit form. Never the curated game's shell."""
        game = self.get(key)
        return {**game.as_stored(), "source": game.source, "edited": game.edited,
                "creatable": game.creatable, "reason": game.reason}

    def update(self, key: str, data: object) -> Game:
        """Replaces a game's data. On a curated game, writes the edit ON TOP of the .env.

        The edit lives in the same place as the dynamic games (`<chave>.json`) and the git file is
        not touched: the broker cannot even write to the repository, and the next deploy would
        overwrite it. That is why `remove` exists, which on a curated game UNDOES the edit.
        """
        game = validate_dynamic(data)
        if game.key != _checked_key(key):
            raise ValidationError("key", "nao pode mudar ao editar (apague e adicione de novo)")
        with self._lock:
            if key not in self._games:
                raise NotFound(f"jogo desconhecido: {key!r}")
            base = self._curated.get(key)
            if base is not None and not base.creatable:
                raise Conflict(f"{key} nao sai pelo broker ({base.reason}): edite games/{key}.env")
            self._store(game)
            self._games[key] = _as_override(base, game) if base is not None else game
            return self._games[key]

    def remove(self, key: str) -> Game | None:
        """Deletes a dynamic game, or undoes the edit of a curated one (restores the curated game).

        An instance already created does not depend on the catalog: it stores what it needs at creation.
        """
        _checked_key(key)
        with self._lock:
            current = self._games.get(key)
            if current is None:
                raise NotFound(f"jogo desconhecido: {key!r}")
            base = self._curated.get(key)
            if base is not None and not current.edited:
                raise Conflict(f"{key} vem de games/{key}.env, no repositorio: tire o arquivo "
                               "de la e publique o broker")
            (self._dynamic_dir / f"{key}.json").unlink(missing_ok=True)
            if base is not None:
                self._games[key] = base
                return base
            del self._games[key]
            return None

    def _store(self, game: Game) -> None:
        self._dynamic_dir.mkdir(parents=True, exist_ok=True)
        target = self._dynamic_dir / f"{game.key}.json"
        # Write to a temp file and swap: a power cut does not leave half-written JSON.
        fd, temporary = tempfile.mkstemp(dir=self._dynamic_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                json.dump(game.as_stored(), out, ensure_ascii=True, indent=2)
            os.replace(temporary, target)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            raise
