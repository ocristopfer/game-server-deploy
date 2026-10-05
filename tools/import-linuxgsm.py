#!/usr/bin/env python3
"""Generates `src/gamepanel/games/catalog/suggestions.py` from the LinuxGSM catalog.

LinuxGSM (MIT, https://github.com/GameServerManagers/LinuxGSM) maintains, for ~140 games, the
dedicated server App ID, the default ports, the executable and the start parameters. The panel
uses this as a SUGGESTION in the "Add game" form: the person picks the game, reviews it and
submits -- the one who decides what is valid is still the broker.

Runs on the development machine (needs internet); the production panel downloads NOTHING:
it reads the generated file, which ships in the repository.

    python tools/import-linuxgsm.py                    # downloads from GitHub
    python tools/import-linuxgsm.py --de PASTA         # uses a local copy (see `coletar`)

Three LinuxGSM sources, and each one answers one question:

- `config-lgsm/<server>/_default.cfg`: App ID, executable, parameters and (almost always) the
  ports. Also the config folder and file and the query type.
- `lgsm/modules/info_game.sh`: for the ~30 games that keep the port in their OWN config file,
  which KEY of it holds the port ("port" in `DefaultPort` of Project Zomboid's server.ini),
  and the derived ports (Valheim's `queryport="$((port + 1))"`).
- `Game-Server-Configs/<game>/<file>`: the default config file, where the VALUE of that key
  comes from. Without the last two, those games came out with no port, and the form showed
  the field's example (7777) as if it were the game's port.

Security rules (each one has a test in broker/test_import_linuxgsm.py):

- Only suggestions the broker would accept come out: the final filter is `validate_dynamic` itself.
- RCON, telnet, HTTP and SourceTV ports NEVER become exposed ports: the default value goes only
  into the arguments, so the game starts, and the port stays behind the firewall.
- Password, server name, IP and token variables are NEVER resolved: the argument that uses one
  is removed and the suggestion warns. No LinuxGSM "CHANGE_ME" ending up on a real server.
- Whatever does not fit the broker's argument charset (quotes, `$`, `;`...) is removed, never escaped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime
import io
import json
import pathlib
import posixpath
import pprint
import re
import shlex
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import NamedTuple

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from gamebroker.domain.exceptions import ValidationError  # noqa: E402
from gamebroker.services.catalog import KEY_RE, NAME_RE, validate_dynamic  # noqa: E402

FONTE_URL = "https://raw.githubusercontent.com/GameServerManagers/LinuxGSM/master/"
GAME_CONFIGS_URL = "https://raw.githubusercontent.com/GameServerManagers/Game-Server-Configs/main/"
GAME_FOLDER = "/opt/game"

# Ports the game announces to the client, and that therefore must exist in the NAT.
EXPOSED_PORTS = ("clientport", "beaconport", "reliableport", "modserverport")
# Administration ports: the number goes into the arguments, but NEVER leaves the container.
INTERNAL_PORTS = ("rconport", "telnetport", "httpport", "sourcetvport", "appport")
# Protocols that are not UDP. The rest is presumed UDP (and the suggestion's warning says so).
VARIABLE_PROTOCOL = {"reliableport": "tcp", "httpport": "tcp"}
# A variable whose name contains any of these fragments is never resolved.
SEGREDOS = ("pass", "gslt", "token", "key", "secret", "servername", "selfname", "ip", "rcon")

_ATRIBUICAO = re.compile(r"""^([a-z_][a-z0-9_]*)=(?:"(.*)"|'(.*)'|([^\s#"']*))\s*(?:#.*)?$""", re.M)
_VARIAVEL = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")
_CHARSET_ARGS = re.compile(r"[A-Za-z0-9._=:,/+@?{}-]+")
_ENCADEAMENTO = re.compile(r"[;|&`<>]|\$\(")


def ler_atribuicoes(texto: str) -> dict[str, str]:
    """`name="value"` from a _default.cfg. The last assignment wins, as in the shell."""
    valores: dict[str, str] = {}
    for m in _ATRIBUICAO.finditer(texto):
        valores[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)
    return valores


def _e_segredo(name: str) -> bool:
    return any(trecho in name for trecho in SEGREDOS)


def resolver(valor: str, variaveis: dict[str, str], extras: dict[str, str] | None = None,
             fundo: int = 6) -> str:
    """Replaces ${name} with whatever it can; what is left stays as is (and later becomes a warning).

    `extras` (ports and folders) wins over `variaveis`. A secret variable is never replaced.
    """
    extras = extras or {}
    for _ in range(fundo):
        def troca(m: re.Match) -> str:
            name = m.group(1)
            if name in extras:
                return extras[name]
            if name in variaveis and not _e_segredo(name):
                # An empty value ("+server.seed ${seed}" with seed="") would leave the option without
                # a value, and it would swallow the next one on the line. It stays marked as
                # unresolved: it is removed along with it.
                return variaveis[name] or "${vazio}"
            return m.group(0)
        novo = _VARIAVEL.sub(troca, valor)
        if novo == valor:
            break
        valor = novo
    return valor


def _numero(texto: str) -> int | None:
    return int(texto) if re.fullmatch(r"\d{1,5}", texto or "") and 1 <= int(texto) <= 65535 else None


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def display_name(gamename: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9 ._-]+", " ", _ascii(gamename))
    limpo = re.sub(r"\s+", " ", limpo).strip(" .-_")
    return limpo[:40].rstrip(" .-_")


def game_key(gamename: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(gamename).lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"g-{slug}"
    return slug[:24].rstrip("-")


def _dividir(args: str) -> list[str]:
    try:
        return shlex.split(args, posix=True)
    except ValueError:
        return args.split()


def _clean_arguments(args: str) -> tuple[str, list[str]]:
    """Keeps only what the broker accepts. Returns (arguments, names of what was removed)."""
    # `;`, `|`, `&`, backtick, `$(` and redirection chain ANOTHER command in the shell: what comes
    # after is not a game argument and does not go in, not even as loose words.
    corte = _ENCADEAMENTO.search(args)
    encadeado = corte is not None
    if corte:
        args = args[:corte.start()]
    tokens = _dividir(args)
    manter = [bool(_CHARSET_ARGS.fullmatch(t)) and "${" not in t for t in tokens]
    # Without the value, the option that asked for it ("-name") would swallow the next option on
    # the line: it is removed too.
    for i, ok in enumerate(manter):
        if not ok and i > 0 and manter[i - 1] and tokens[i - 1][0] in "-+" \
                and "=" not in tokens[i - 1] and tokens[i][:1] not in ("-", "+"):
            manter[i - 1] = False
    fica = [t for t, ok in zip(tokens, manter) if ok]
    saiu = [t.split("=", 1)[0].lstrip("-+") for t, ok in zip(tokens, manter) if not ok and t[:1] in "-+"]
    if encadeado:
        saiu.append("comando encadeado")
    return " ".join(fica), saiu


def _game_port(v: dict[str, str], from_config: dict[str, int], warnings: list[str]) -> int:
    port = _numero(v.get("port", "")) or 0
    if not port and from_config.get("port"):
        port = from_config["port"]
        warnings.append(f"Porta lida do arquivo de configuracao padrao do LinuxGSM "
                        f"({v.get('servercfgdefault', '')}): o jogo a le desse arquivo, e nao do comando.")
    # Even without a port, the App ID (the part nobody knows by heart) makes the suggestion
    # worth it: it goes out with no port and a warning.
    if not port:
        warnings.append("Este jogo guarda as portas no proprio arquivo de configuracao: preencha "
                        "as portas depois de instalar e ver o que ele abre.")
    return port


def _silent_query(port: int, from_config: dict[str, int], warnings: list[str]) -> int:
    """Query port the game opens on its own (Valheim's port+1, the one from the config file).

    It has to be in the firewall, otherwise the server does not show up in the list. With no
    placeholder in the command the broker cannot tell the game about it, so the game stops
    being shiftable.
    """
    query = from_config.get("queryport", port)
    if not port or query == port:
        return 0
    warnings.append(f"Porta de consulta {query} aberta pelo proprio jogo: sem ela o servidor "
                    "nao aparece na lista. Por isso o broker nao sorteia portas para este jogo.")
    return query


def _start_script(v: dict[str, str], warnings: list[str]) -> str:
    executable = resolver(v.get("executable", ""), v, {"serverfiles": GAME_FOLDER})
    folder = resolver(v.get("executabledir", "${serverfiles}"), v, {"serverfiles": GAME_FOLDER})
    path = posixpath.normpath(posixpath.join(folder, executable)) if executable else ""
    if path.startswith(GAME_FOLDER + "/") and "${" not in path:
        warnings.append("O executavel e o do LinuxGSM (binario direto). Se o servidor nao subir, "
                        "use o script .sh que vem na pasta do jogo.")
        return path[len(GAME_FOLDER) + 1:]
    if executable:
        warnings.append("Nao consegui deduzir o executavel: preencha o script de start.")
    return ""


def _no_config(_name: str) -> str | None:
    return None


class GameExtras(NamedTuple):
    """What LinuxGSM says about the game OUTSIDE `_default.cfg`. All optional: without it, what
    comes out is what `_default.cfg` alone says (presumed UDP ports, and no port where it has none)."""

    info_body: str = ""        # body of fn_info_game_<game>, from info_game.sh
    messages_body: str = ""    # body of fn_info_messages_<game>, from info_messages.sh
    read_config: Callable[[str], str | None] = _no_config  # file from Game-Server-Configs


def _port_list(entries: list[tuple[int, str, str]], protocols: dict[str, list[str]],
               warnings: list[str]) -> list[str]:
    """`number/protocol` of each port. The protocol comes from info_messages.sh when it lists
    that variable (Terraria is TCP only); otherwise UDP, and the suggestion warns it presumed."""
    ports: list[str] = []
    presumed = False
    for number, variable, default in entries:
        # The Steam query is UDP, always. info_messages.sh lists "Query ... tcp" for several
        # Unreal games (Pavlov, Hypercharge): opening TCP there would leave the port the server
        # browser queries CLOSED, and one open that nobody uses.
        listed = ["udp"] if variable in STEAM_QUERY_VARIABLES else protocols.get(variable)
        presumed = presumed or not listed
        ports += [f"{number}/{proto}" for proto in listed or [default]]
    if presumed:
        warnings.append("Protocolo UDP presumido em parte das portas: confira (query e TCP em alguns jogos).")
    return list(dict.fromkeys(ports))


def sugerir(gamename: str, texto_do_cfg: str, extras: GameExtras = GameExtras()) -> dict | None:  # noqa: B008
    """One game suggestion, or None if it is not possible to build one the broker accepts."""
    v = ler_atribuicoes(texto_do_cfg)
    appid = int(v["appid"]) if v.get("appid", "").isdigit() else 0
    if not appid:
        return None
    from_config = ports_from_game_config(extras.info_body, v, extras.read_config) if extras.info_body else {}
    avisos: list[str] = []
    porta = _game_port(v, from_config, avisos)
    args_brutos = v.get("startparameters", "")

    var_query = next((n for n in ("queryport", "steamport")
                      if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos), "")
    extras_da_rede = [n for n in EXPOSED_PORTS
                      if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos]

    trocas = {"serverfiles": GAME_FOLDER}
    if porta:
        trocas["port"] = "{PORT}"
    if var_query:
        trocas[var_query] = "{QUERY_PORT}"
    # The broker tells the game about ONE extra port. With two or more (old Satisfactory has beacon
    # and reliable) they keep the default number and the game is not shiftable.
    var_extra = extras_da_rede[0] if len(extras_da_rede) == 1 else ""
    if var_extra:
        trocas[var_extra] = "{EXTRA_PORT}"
    # Every other port becomes the default NUMBER: the game starts with it, and only the exposed
    # ones go to the NAT.
    for name in EXPOSED_PORTS + INTERNAL_PORTS + ("queryport", "steamport", "clientport"):
        if name not in trocas and _numero(v.get(name, "")):
            trocas[name] = v[name]
    argumentos, removidos = _clean_arguments(resolver(args_brutos, v, trocas))
    if removidos:
        avisos.append("Removi do comando o que o painel nao passa (" + ", ".join(dict.fromkeys(removidos))
                      + "): nome do servidor, senha, IP e caminhos de config. Acrescente o que faltar.")

    silent_query = 0 if var_query else _silent_query(porta, from_config, avisos)
    query_port = (_numero(v[var_query]) or 0) if var_query else silent_query
    entries = [(porta, "port", "udp")] if porta else []
    if query_port:
        entries.append((query_port, var_query or "queryport", "udp"))
    entries += [(_numero(v[n]) or 0, n, VARIABLE_PROTOCOL.get(n, "udp")) for n in extras_da_rede]
    ports = _port_list(entries, port_protocols(extras.messages_body), avisos)
    escondidas = [n for n in INTERNAL_PORTS if _numero(v.get(n, "")) and f"${{{n}}}" in args_brutos]
    if escondidas:
        avisos.append("Portas de administracao (" + ", ".join(escondidas)
                      + ") ficam so dentro do container, de proposito: nao entram no firewall.")

    script = _start_script(v, avisos)

    shiftable = (porta and len(extras_da_rede) <= 1 and "{PORT}" in argumentos
                  and not silent_query
                  and (not var_query or "{QUERY_PORT}" in argumentos)
                  and (not var_extra or "{EXTRA_PORT}" in argumentos))
    config_path, config_files = config_location(v)
    source = player_source(v, query_port)
    if source == "a2s":
        avisos.append("Contagem de jogadores pela consulta da Steam (A2S), como o LinuxGSM faz.")
    sugestao = {
        "appid": appid, "name": display_name(gamename), "key": game_key(gamename),
        "ports": " ".join(ports), "game_port": porta,
        "query_port": query_port,
        "extra_port": _numero(v[var_extra]) if var_extra else 0,
        "start_script": script, "start_args": argumentos,
        "shiftable": bool(shiftable),
        "config_path": config_path, "config_files": config_files, "player_source": source,
        "warnings": avisos,
    }
    return _passar_pelo_broker(sugestao)


def _as_panel_data(s: dict) -> dict:
    # Without a port (partial suggestion) the validator gets an arbitrary one: what is checked
    # here is the rest.
    dados: dict = {"key": s["key"], "name": s["name"], "app_id": s["appid"],
                   "ports": s["ports"].split() or ["27015/udp"], "game_port": s["game_port"] or 27015,
                   "recipes": [], "config_files": s.get("config_files", []), "backup_paths": [],
                   "player_source": s.get("player_source", "log"), "shiftable": s["shiftable"]}
    if s.get("config_path"):
        dados["config_path"] = s["config_path"]
    for campo in ("start_script", "start_args"):
        if s[campo]:
            dados[campo] = s[campo]
    if s["query_port"]:
        dados["query_port"] = s["query_port"]
    if s.get("extra_port"):
        dados["extra_port"] = s["extra_port"]
    return dados


# ---------------------------------------------------- ports and data outside _default.cfg

# LinuxGSM query type that is A2S, the one the panel knows how to do.
A2S_QUERY_TYPES = ("protocol-valve",)
# Extensions the panel's Config screen opens field by field (see games/config_format.py). The
# others (.xml, .lua, .sii...) only get the folder: the generic file editor is enough.
CONFIG_EXTENSIONS = (".ini", ".json", ".properties", ".conf", ".cfg")
# Variables LinuxGSM uses for the Steam query (A2S), which is UDP in every game.
STEAM_QUERY_VARIABLES = ("queryport", "steamport")

_INFO_CALL = re.compile(r'fn_info_game_(\w+) "(port|queryport)" "([^"]+)"(?: "([^"]+)")?')
_DERIVED_PORT = re.compile(r'^\s*(queryport)="\$\(\(port \+ (\d{1,3})\)\)"', re.M)


def info_function(info_text: str, shortname: str, prefix: str = "fn_info_game_") -> str:
    """The body of `<prefix><game>` in a LinuxGSM module (empty if the game has none)."""
    m = re.search(rf"^{prefix}{re.escape(shortname)}\(\) \{{\n(.*?)^\}}", info_text, re.M | re.S)
    return m.group(1) if m else ""


_PORT_LINE = re.compile(r'fn_port "[^"]*" (\w+) (tcp|udp)\b')


def port_protocols(messages_body: str) -> dict[str, list[str]]:
    """Variable -> protocols, from `fn_port "Game" port tcp` (info_messages.sh).

    The same variable can appear twice (Assetto Corsa's port is UDP and TCP).
    """
    found: dict[str, list[str]] = {}
    for variable, proto in _PORT_LINE.findall(messages_body):
        found.setdefault(variable, [])
        if proto not in found[variable]:
            found[variable].append(proto)
    return found


def _line_value(text: str, key: str, separator: str, anywhere: bool = False) -> str:
    """The `sed` of LinuxGSM's readers: first line starting with the key, value after the LAST
    separator, without quotes. `anywhere` is quakec's (`set net_port "27960"`)."""
    start = r"(?:^|\s)" if anywhere else r"^\s*"
    for line in text.splitlines():
        if re.match(start + re.escape(key) + r"\b", line) or (anywhere and re.search(
                r"\s" + re.escape(key) + r"\b", line)):
            value = re.split(separator, line)[-1].strip().strip('"').strip()
            return value.split(",")[0].strip().strip('"')
    return ""


def _json_value(text: str, path: str) -> str:
    try:
        node = json.loads(text)
    except ValueError:
        return ""
    for part in path.strip(".").split("."):
        if not isinstance(node, dict) or part not in node:
            return ""
        node = node[part]
    return str(node) if isinstance(node, int | str) and not isinstance(node, bool) else ""


def _xml_value(text: str, xpath: str) -> str:
    """The three xpath formats info_game.sh uses for ports: `/a/@b`, `/a/b` and
    `/a/b[@name='x']/@value`. ElementTree understands the predicate; the final attribute is separate."""
    try:
        # The file is the one from the LinuxGSM repository, read on the machine of whoever generates
        # the suggestions (never on the panel), and the stdlib does not expand external entities
        # since Python 3.7.8.
        root = ET.fromstring(text)  # noqa: S314
    except ET.ParseError:
        return ""
    parts = xpath.strip("/").split("/")
    attribute = parts.pop()[1:] if parts[-1].startswith("@") else ""
    if not parts or parts[0] != root.tag:
        return ""
    node = root.find("/".join(parts[1:])) if len(parts) > 1 else root
    if node is None:
        return ""
    return (node.get(attribute, "") if attribute else (node.text or "")).strip()


def config_value(kind: str, key: str, text: str) -> str:
    """The value of `key` in a config file, read the way `fn_info_game_<kind>` reads it."""
    if kind in ("ini", "keyvalue_pairs_equals", "java_properties", "sqf", "lua"):
        return _line_value(text, key, r"=").rstrip(";")
    if kind in ("keyvalue_pairs_space", "valve_keyvalues"):
        return _line_value(text, key, r"\s+")
    if kind == "quakec":
        return _line_value(text, key, r"\s+", anywhere=True)
    if kind == "pc_config":
        return _line_value(text, key, r":")
    if kind == "json":
        return _json_value(text, key)
    if kind == "xml":
        return _xml_value(text, key)
    return ""


def ports_from_game_config(info_body: str, v: dict[str, str],
                           read_config: Callable[[str], str | None]) -> dict[str, int]:
    """Ports read from the game's DEFAULT config file, where info_game.sh says they are.

    Only the file LinuxGSM publishes (`servercfgdefault`) or the one the call names: it is the
    only one that exists outside an installation. 7 Days to Die uses the one that ships with
    the game itself, which cannot be read from here, and stays without a port.
    """
    found: dict[str, int] = {}
    for kind, name, key, other_file in _INFO_CALL.findall(info_body):
        if name in found:
            continue
        file_name = posixpath.basename(other_file) if other_file else v.get("servercfgdefault", "")
        if not file_name or "$" in file_name:
            continue
        text = read_config(file_name)
        number = _numero(config_value(kind, key, text)) if text else None
        if number:
            found[name] = number
    port = found.get("port") or _numero(v.get("port", ""))
    for name, offset in _DERIVED_PORT.findall(info_body):
        if port and name not in found:
            found[name] = port + int(offset)
    return found


def player_source(v: dict[str, str], query_port: int) -> str:
    """A2S only with its own query port: that is the one the panel queries."""
    return "a2s" if query_port and v.get("querytype") in A2S_QUERY_TYPES else "log"


def config_location(v: dict[str, str]) -> tuple[str, list[str]]:
    """Config folder and file, when both live in the game folder.

    The LinuxGSM folder outside /opt/game (lgsm/config-lgsm, the HOME) does not exist in the
    broker's installation, and neither does a file named after the instance (`${selfname}.xml`).
    """
    folder = resolver(v.get("servercfgdir", ""), v, {"serverfiles": GAME_FOLDER})
    name = resolver(v.get("servercfg", ""), v, {"serverfiles": GAME_FOLDER})
    folder = posixpath.normpath(folder) if folder else ""
    if not (folder == GAME_FOLDER or folder.startswith(GAME_FOLDER + "/")) or "$" in folder:
        return "", []
    if not name or "$" in name or "/" in name or not name.lower().endswith(CONFIG_EXTENSIONS):
        return folder, []
    return folder, [f"{folder}/{name}"]


def _passar_pelo_broker(s: dict) -> dict | None:
    """Final filter: the broker's validator. A rejected optional field is removed (with a warning);
    a rejected identity or port drops the whole suggestion."""
    for _ in range(6):
        try:
            validate_dynamic(_as_panel_data(s))
            return s
        except ValidationError as erro:
            # `field`, not `campo`: with the old name the attribute never existed, and every
            # suggestion with a rejected argument was DISCARDED instead of coming out with the
            # field blank.
            campo = getattr(erro, "field", "")
            if campo in ("start_script", "start_args"):
                s = {**s, campo: "", "shiftable": False,
                     "warnings": s["warnings"] + [f"O broker recusaria {campo}; deixei em branco."]}
            elif campo in ("config_path", "config_files"):
                s = {**s, "config_path": "", "config_files": []}
            elif campo == "shiftable":
                s = {**s, "shiftable": False}
            else:
                return None
    return None


# ---------------------------------------------------------------- download and writing

def _baixar(url: str, tentativas: int = 3) -> str | None:
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "gamepanel-importador"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            time.sleep(1 + i)
    return None


def _read_from_folder(pasta: pathlib.Path, servidor: str) -> str | None:
    arquivo = pasta / f"{servidor}.cfg"
    return arquivo.read_text(encoding="utf-8") if arquivo.exists() else None


def _read_optional(path: pathlib.Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.is_file() else None


class Sources(NamedTuple):
    server_list: str
    default_cfg: Callable[[str], str | None]           # gameservername -> _default.cfg
    info_text: str                                     # lgsm/modules/info_game.sh
    messages_text: str                                 # lgsm/modules/info_messages.sh
    game_config: Callable[[str, str], str | None]      # (shortname, file) -> default config


def _sources(pasta_local: pathlib.Path | None) -> Sources:
    """Local copy: serverlist.csv, <server>.cfg, info_game.sh, info_messages.sh and
    config-game/<shortname>/<file> (the last three optional)."""
    if pasta_local:
        folder = pasta_local
        return Sources(
            (folder / "serverlist.csv").read_text(encoding="utf-8"),
            lambda n: _read_from_folder(folder, n),
            _read_optional(folder / "info_game.sh") or "",
            _read_optional(folder / "info_messages.sh") or "",
            lambda short, name: _read_optional(folder / "config-game" / short / name))
    return Sources(
        _baixar(FONTE_URL + "lgsm/data/serverlist.csv") or "",
        lambda n: _baixar(FONTE_URL + f"lgsm/config-default/config-lgsm/{n}/_default.cfg"),
        _baixar(FONTE_URL + "lgsm/modules/info_game.sh") or "",
        _baixar(FONTE_URL + "lgsm/modules/info_messages.sh") or "",
        lambda short, name: _baixar(GAME_CONFIGS_URL + f"{short}/{name}", tentativas=1))


def _messages_body(messages_text: str, shortname: str, cfg_text: str) -> str:
    """The game's port list; without its own, the engine's (`engine="source"` covers ~30
    games in a single function), which is the dispatch order of info_messages.sh itself."""
    own = info_function(messages_text, shortname, prefix="fn_info_messages_")
    engine = ler_atribuicoes(cfg_text).get("engine", "")
    return own or (info_function(messages_text, engine, prefix="fn_info_messages_") if engine else "")


def coletar(pasta_local: pathlib.Path | None) -> tuple[list[dict], list[str]]:
    src = _sources(pasta_local)
    jogos = list(csv.DictReader(io.StringIO(src.server_list)))
    if not jogos:
        raise SystemExit("serverlist.csv vazio ou inacessivel")
    # Without the modules the suggestion is still valid, just poorer: warn whoever generates it,
    # and do not stop.
    if not src.info_text:
        print("aviso: sem info_game.sh - jogos com porta no proprio config saem sem porta", file=sys.stderr)
    if not src.messages_text:
        print("aviso: sem info_messages.sh - todas as portas saem como UDP presumido", file=sys.stderr)

    def suggest(game: dict) -> dict | None:
        text = src.default_cfg(game["gameservername"])
        if not text:
            return None
        short = game["shortname"]
        return sugerir(game["gamename"], text, GameExtras(
            info_body=info_function(src.info_text, short),
            messages_body=_messages_body(src.messages_text, short, text),
            read_config=lambda name: src.game_config(short, name)))

    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        resultados = list(pool.map(suggest, jogos))
    sugestoes, pulados = [], []
    for j, s in zip(jogos, resultados):
        (sugestoes if s else pulados).append(s or j["gamename"])
    # Two games with the same name (or key) would make the search ambiguous: the first one stays.
    vistos: set[str] = set()
    unicas = []
    for s in sorted(sugestoes, key=lambda s: s["name"].lower()):
        if s["key"] in vistos:
            pulados.append(s["name"])
            continue
        vistos.add(s["key"])
        unicas.append(s)
    return unicas, pulados


def escrever(sugestoes: list[dict], saida: pathlib.Path) -> None:
    corpo = "".join(f"    {pprint.pformat(s, width=110, sort_dicts=False).replace(chr(10), chr(10) + '    ')},\n"
                    for s in sugestoes)
    texto = (
        '"""Sugestoes de jogo para o formulario "Adicionar jogo" — GERADO, NAO EDITE.\n\n'
        "Gerado por tools/import-linuxgsm.py a partir do LinuxGSM (MIT). Para atualizar, rode\n"
        "o script e revise o diff: cada linha aqui e uma sugestao que o broker valida de novo.\n"
        '"""\n'
        f'SOURCE = "LinuxGSM (MIT), gerado em {datetime.date.today().isoformat()}"\n\n'
        f"SUGGESTIONS = (\n{corpo})\n"
    )
    saida.write_bytes(texto.encode("utf-8"))  # bytes: on Windows text mode would turn \n into \r\n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--de", type=pathlib.Path, help="pasta local com serverlist.csv e <servidor>.cfg")
    ap.add_argument(
        "--saida",
        type=pathlib.Path,
        default=RAIZ / "src" / "gamepanel" / "games" / "catalog" / "suggestions.py",
    )
    opts = ap.parse_args()
    sugestoes, pulados = coletar(opts.de)
    escrever(sugestoes, opts.saida)
    print(f"{len(sugestoes)} sugestoes em {opts.saida} ({len(pulados)} jogos sem app id/porta ou repetidos)")


if __name__ == "__main__":
    main()
