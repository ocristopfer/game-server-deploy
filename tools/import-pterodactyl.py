#!/usr/bin/env python3
"""Gera `src/gamepanel/games/catalog/pterodactyl_suggestions.py` a partir dos eggs do Pterodactyl.

Os eggs (MIT, https://github.com/pelican-eggs/games-steamcmd - o sucessor do parkervcp/eggs)
sao a segunda fonte do formulario "Adicionar jogo". Existem por um motivo so: o LinuxGSM so
conhece servidor com build Linux, e os eggs cobrem tambem os que so rodam no Windows (V Rising,
Enshrouded, Abiotic Factor...) por imagens com Wine/Proton.

    python tools/import-pterodactyl.py                  # baixa o repositorio do GitHub
    python tools/import-pterodactyl.py --source PASTA   # usa um clone local

Sai duas coisas, e as duas passam pelo validador do broker AQUI, na geracao: o painel em
producao nao tem o pacote do broker para validar em tempo de uso.

- `SUGGESTIONS`: jogos que o LinuxGSM, a lista manual e os curados NAO tem. Quem ja tem o
  jogo vence: o LinuxGSM diz protocolo de porta, o egg nao; a lista manual foi revisada a mao;
  o curado a busca acha pelo catalogo da pagina.
- `COMPLEMENTS`: por App ID do LinuxGSM, so os campos que la estao VAZIOS e o egg sabe (pasta
  e arquivos de config; portas, quando o LinuxGSM nao achou nenhuma). A busca junta os dois e
  diz de onde veio cada campo.

De onde sai cada dado do egg:

- App ID: a variavel `SRCDS_APPID`. Egg sem ela nao e SteamCMD e fica de fora.
- Portas: a tabela "Server Ports" do README da pasta do egg. A porta principal do egg e a
  ALOCACAO do Pterodactyl, que nao tem numero no JSON; so o README diz o padrao.
- Comando: o `startup`, sem o que e do container do Pterodactyl (`cd`, `export`, `xvfb-run`,
  `proton run`, `wine`) e com `{{SERVER_PORT}}`/a variavel da query trocadas pelos marcadores.
- Windows: `WINDOWS_INSTALL=1`, imagem de wine/proton ou `wine`/`proton` no comando. Sai com
  `proton` (regra do repositorio: Proton primeiro), mais `xvfb` se o egg sobe um X virtual.
- Config: as chaves de `config.files` (os arquivos que o Pterodactyl edita), sob /opt/game.

Regras de seguranca, as mesmas do LinuxGSM (cada uma com teste em test_import_pterodactyl.py):

- O script de instalacao do egg e SHELL e nunca e lido: o broker so aceita dado.
- Porta de RCON, telnet, HTTP e afins NUNCA vira porta exposta.
- Variavel de senha, nome, IP e token NUNCA e resolvida: o argumento sai, com aviso.
- Tudo depois de `; | & $(` e cortado; o que nao cabe no charset do broker sai, nunca e escapado.
- Egg que exige conta Steam fica de fora: jogo dinamico nao tem como levar a senha ao CT.
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
# Os marcadores que o broker troca pela porta alocada (ver catalog._PLACEHOLDERS).
PORT_MARKER, QUERY_MARKER, EXTRA_MARKER = "{PORT}", "{QUERY_PORT}", "{EXTRA_PORT}"

# Nome de linha da tabela de portas que NUNCA vai para o NAT (a porta so fica nos argumentos).
INTERNAL_PORT_WORDS = ("rcon", "telnet", "http", "web", "api", "rest", "admin", "tv", "metric",
                       "console", "mod", "voice")
SECRET_WORDS = ("PASS", "PW", "TOKEN", "KEY", "SECRET", "GSLT", "NAME", "IP", "LOGIN", "USER",
                "RCON", "ADMIN", "PASSWORD", "HOSTNAME", "MOTD", "DESCRIPTION", "WEBHOOK")
# Programas do container do Pterodactyl, e nao do jogo: somem antes de achar o executavel.
LAUNCHERS = ("exec", "stdbuf", "xvfb-run", "wine", "wine64", "proton", "run", "env", "nice")
# Interpretador no lugar do executavel: o START_SCRIPT do broker e um arquivo executado direto,
# entao `java -jar` ou `dotnet X.dll` nao tem como virar comando aqui.
INTERPRETERS = ("java", "dotnet", "mono", "bash", "sh", "python", "python3", "node", "screen")
VARIANT_WORDS = ("bepinex", "modded", "oxide", "umod", "carbon", "experimental", "beta",
                 "mod", "plus", "legacy", "tshock", "unstable", "staging", "sourcemod")
CONFIG_EXTENSIONS = (".ini", ".json", ".properties", ".conf", ".cfg")
# Primeira palavra de trecho que prepara o container e nao sobe o jogo (o X virtual em segundo
# plano, o winetricks, o sed que reescreve config). Escolher um deles como "o servidor" dava
# START_SCRIPT=xvfb na primeira versao deste conversor.
SETUP_WORDS = ("cd", "export", "unset", "rm", "touch", "mkdir", "echo", "chmod", "chown", "cp", "mv",
               "ln", "sed", "cat", "sleep", "if", "then", "else", "fi", "while", "do", "done", "for",
               "trap", "ulimit", "source", ".", "[", "test", "Xvfb", "xvfb", "wineboot", "winetricks", "wait",
               "kill", "true", "false", "printf", "clear", "curl", "wget")
# App ID que nao e o jogo: o 1007 e o Steamworks SDK Redist, que egg de jogo instalado por git
# baixa so pela biblioteca. Com ele o broker instalaria a biblioteca e nenhum servidor.
NOT_GAME_APPIDS = frozenset({1007})

_VAR = re.compile(r"\{\{\s*(?:server\.build\.env\.)?([A-Z0-9_]+)\s*\}\}|\$\{([A-Z0-9_]+)\}")
_ARGS_CHARSET = re.compile(r"[A-Za-z0-9._=:,/+@?{}-]+")
_CHAIN = re.compile(r"&&|\|\||[;|&`<>]|\$\(")
_SCRIPT_RE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
_PATH_PART = re.compile(r"[A-Za-z0-9._-]+")
_PORT_NUMBER = re.compile(r"\b(\d{4,5})\b")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


# ---------------------------------------------------------------- tabela de portas (README)

class PortRow(NamedTuple):
    name: str
    number: int
    protos: tuple[str, ...]


def _protocols(cells: list[str]) -> tuple[str, ...]:
    text = " ".join(cells).lower()
    found = tuple(p for p in ("udp", "tcp") if p in text)
    return found or ("udp",)


def port_rows(readme: str) -> list[PortRow]:
    """As linhas da tabela de portas do README: nome, numero padrao e protocolo. Sem coluna de
    protocolo vale UDP, que e o de todo jogo Steam (e a sugestao avisa que foi presumido)."""
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
        # Query da Steam e UDP em todo jogo, mesmo quando o README diz outra coisa.
        protos = ("udp",) if role == "query" else row.protos
        exposed += [f"{row.number}/{p}" for p in protos if f"{row.number}/{p}" not in exposed]
    if not game:
        return Ports()
    return Ports(game, query, extras[0] if len(extras) == 1 else 0, tuple(exposed),
                 presumed_udp=all(len(r.protos) == 1 and r.protos[0] == "udp" for r in rows))


# ---------------------------------------------------------------- comando de start

def _is_secret(var: str) -> bool:
    return any(w in var for w in SECRET_WORDS)


def _launch_segment(startup: str) -> tuple[str, str]:
    """O trecho do `startup` que sobe o jogo, e a pasta em que ele roda (o `cd` antes dele)."""
    # `&` sozinho tambem separa: `Xvfb :0 & ./server` sobe o X em segundo plano e o jogo depois.
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


# Cara de "e aqui que o jogo sobe", do mais ao menos certo. A porta do jogo no comando e o
# sinal mais forte; um executavel (./x, wine, proton, .exe) vem depois. Sem isso o primeiro
# trecho que sobrava ganhava, e no Space Engineers ele era o pedaco de um `export` com `;`
# dentro das aspas.
_LAUNCH_HINTS = (("SERVER_PORT", 4), ("./", 2), ("wine", 2), ("proton", 2), (".exe", 2),
                 (".x86_64", 2), (".sh", 1))


def _launch_score(segment: str) -> int:
    return 1 + sum(weight for hint, weight in _LAUNCH_HINTS if hint in segment)


def _strip_launchers(tokens: list[str]) -> tuple[list[str], bool]:
    """Tira env inline, `xvfb-run [opcoes]`, `wine`, `proton run`. Devolve (resto, usa xvfb)."""
    xvfb = False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*=.*", t):
            i += 1
        elif t in LAUNCHERS:
            xvfb = xvfb or t == "xvfb-run"
            i += 1
            # As opcoes do xvfb-run (-a, -s "...", --server-args=...) nao sao do jogo.
            while t == "xvfb-run" and i < len(tokens) and tokens[i].startswith("-"):
                i += 2 if tokens[i] in ("-s", "-n", "-e", "-f", "-p") else 1
        else:
            break
    return tokens[i:], xvfb


def _script_path(exe: str, cwd: str) -> str:
    """Caminho do executavel relativo a /opt/game, ou vazio se nao couber no broker."""
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
    markers: dict[str, str]      # variavel -> {PORT}/{QUERY_PORT}/{EXTRA_PORT}


def _is_option(token: str) -> bool:
    """`-port`, `+map` e o `/port` do Bannerlord; `/Game/Maps/X` e caminho, nao opcao."""
    return token[:1] in "-+" or (token[:1] == "/" and "/" not in token[1:])


def _resolve_token(token: str, res: Resolver) -> str | None:
    """Troca as variaveis do token; None = o token (e a opcao que o pede) sai."""
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
    # A pasta do jogo no Pterodactyl e /home/container; aqui e /opt/game.
    out = out.replace(CONTAINER_DIR, GAME_DIR)
    return out if _ARGS_CHARSET.fullmatch(out) else None


def clean_arguments(args: list[str], res: Resolver) -> tuple[str, list[str]]:
    """Fica so com o que o broker aceita. Devolve (argumentos, nomes do que saiu)."""
    resolved = [_resolve_token(t, res) for t in args]
    keep = [r is not None for r in resolved]
    # Sem o valor, a opcao que o pedia ("-name") engoliria a proxima: sai junto.
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


# ---------------------------------------------------------------- o egg inteiro

def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def display_name(name: str) -> str:
    # "Astroneer Dedicated Server" e o nome do EGG; na busca a pessoa procura pelo jogo.
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
    """Os arquivos que o egg edita (`config.files`), sob /opt/game; so os que a tela Config le."""
    raw = (egg.get("config") or {}).get("files") or "{}"
    try:
        files = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for name in files if isinstance(files, dict) else []:
        # normpath, e NAO lstrip("./"): o lstrip comia o "../" e fazia "../../etc/x.ini" virar
        # "etc/x.ini", um arquivo que o egg nunca citou. Com normpath o ".." sobra e e recusado.
        rel = posixpath.normpath(str(name).replace("\\", "/"))
        parts = rel.split("/")
        if rel.lower().endswith(CONFIG_EXTENSIONS) and all(_PATH_PART.fullmatch(p) and p != ".." for p in parts):
            out.append(f"{GAME_DIR}/{rel}")
    return out[:8]


def _markers(defaults: dict[str, str], ports: Ports) -> dict[str, str]:
    """Variavel do egg -> marcador do broker. A porta principal e sempre SERVER_PORT; as outras
    se reconhecem pelo VALOR padrao igual ao da tabela do README."""
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
    # Marcador sem porta correspondente viraria "0" na linha de comando.
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


# ---------------------------------------------------------------- validacao pelo broker

def as_panel_data(s: dict) -> dict:
    """O que o formulario do painel mandaria ao broker. Sem porta (sugestao parcial) o
    validador recebe uma qualquer: o que se confere aqui e o resto."""
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
    """Filtro final: o validador do broker. Campo opcional recusado sai (com aviso); identidade
    ou porta recusada derruba a sugestao inteira."""
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


# ---------------------------------------------------------------- juntar com o LinuxGSM

def complement(linuxgsm: dict, egg: dict) -> dict:
    """Os campos VAZIOS do LinuxGSM que o egg sabe. Portas vao em bloco (e o jogo deixa de andar
    de porta): misturar a porta de um com a consulta do outro nao corresponde a jogo nenhum."""
    extra: dict = {}
    # Campo a campo: o LinuxGSM que ja sabe a PASTA (Sven Co-op) continua com a dele, e o egg so
    # traz os arquivos que ela nao listava.
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


# ---------------------------------------------------------------- leitura e escrita

def _readme_for(egg_path: pathlib.PurePosixPath, readmes: dict[str, str]) -> str:
    """O README da pasta do egg; se ela nao tiver, o da pasta de cima (jogo com variantes)."""
    folder = egg_path.parent
    return readmes.get(str(folder / "README.md")) or readmes.get(str(folder.parent / "README.md"), "")


def _pick(paths: list[pathlib.PurePosixPath]) -> list[pathlib.PurePosixPath]:
    """Um egg por pasta: cada uma traz o mesmo jogo exportado nos formatos do Pterodactyl e do
    Pelican. Fica o do Pterodactyl, que e o formato do resto."""
    by_folder: dict[str, pathlib.PurePosixPath] = {}
    for p in sorted(paths):
        current = by_folder.get(str(p.parent))
        if current is None or p.name.startswith("egg-pterodactyl-"):
            by_folder[str(p.parent)] = p
    return list(by_folder.values())


def load_eggs(files: dict[str, str]) -> list[Egg]:
    """`files`: caminho relativo (com /) -> texto, de um clone ou do tarball."""
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
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL fixa, https
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
    """O que ja existe: LinuxGSM (por App ID), App IDs da lista manual e dos curados, e as chaves."""
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
        # Varias variantes do mesmo jogo (vanilla, BepInEx, oxide): fica a mais simples.
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
        # A anotacao vai no arquivo: sem ela o mypy deduz `dict[int, object]` pelo conteudo e
        # recusa o `**extra` da busca.
        f"COMPLEMENTS: dict[int, dict] = {comp}\n"
    )
    out.write_bytes(text.encode("utf-8"))  # bytes: no Windows o modo texto trocaria \n por \r\n


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
