#!/usr/bin/env python3
"""Gera `src/gamepanel/games/catalog/suggestions.py` a partir do catalogo do LinuxGSM.

O LinuxGSM (MIT, https://github.com/GameServerManagers/LinuxGSM) mantem, para ~140 jogos, o
App ID do servidor dedicado, as portas padrao, o executavel e os parametros de start. O painel
usa isso como SUGESTAO no formulario "Adicionar jogo": a pessoa escolhe o jogo, confere e
envia — quem decide o que e valido continua sendo o broker.

Roda na maquina de desenvolvimento (precisa de internet); o painel em producao NAO baixa nada:
le o arquivo gerado, que vai no repositorio.

    python tools/import-linuxgsm.py                    # baixa do GitHub
    python tools/import-linuxgsm.py --de PASTA         # usa uma copia local (ver `coletar`)

Tres fontes do LinuxGSM, e cada uma responde uma pergunta:

- `config-lgsm/<servidor>/_default.cfg`: App ID, executavel, parametros e (quase sempre) as
  portas. Tambem a pasta e o arquivo de config e o tipo de consulta.
- `lgsm/modules/info_game.sh`: para os ~30 jogos que guardam a porta no PROPRIO arquivo de
  configuracao, em que CHAVE dele ela mora ("port" em `DefaultPort` do server.ini do Project
  Zomboid), e as portas derivadas (`queryport="$((port + 1))"` do Valheim).
- `Game-Server-Configs/<jogo>/<arquivo>`: o arquivo de config padrao, de onde sai o VALOR
  daquela chave. Sem as duas ultimas, esses jogos saiam sem porta, e o formulario mostrava o
  exemplo do campo (7777) como se fosse a porta do jogo.

Regras de seguranca (cada uma tem teste em broker/test_import_linuxgsm.py):

- So sai sugestao que o broker aceitaria: o filtro final e o proprio `validate_dynamic`.
- Porta de RCON, telnet, HTTP e SourceTV NUNCA vira porta exposta: o valor padrao vai so nos
  argumentos, para o jogo subir, e ela continua atras do firewall.
- Variavel de senha, nome do servidor, IP e token NUNCA e resolvida: o argumento que a usa e
  removido e a sugestao avisa. Nada de "CHANGE_ME" do LinuxGSM indo parar num servidor real.
- O que nao cabe no charset de argumentos do broker (aspas, `$`, `;`...) e removido, nunca escapado.
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

# Portas que o jogo anuncia para o cliente e por isso precisam existir no NAT.
EXPOSED_PORTS = ("clientport", "beaconport", "reliableport", "modserverport")
# Portas de administracao: o numero vai nos argumentos, mas NUNCA sai do container.
INTERNAL_PORTS = ("rconport", "telnetport", "httpport", "sourcetvport", "appport")
# Protocolo que nao e UDP. O resto e presumido UDP (e o aviso da sugestao diz isso).
VARIABLE_PROTOCOL = {"reliableport": "tcp", "httpport": "tcp"}
# Variavel cujo nome contem qualquer um destes trechos nunca e resolvida.
SEGREDOS = ("pass", "gslt", "token", "key", "secret", "servername", "selfname", "ip", "rcon")

_ATRIBUICAO = re.compile(r"""^([a-z_][a-z0-9_]*)=(?:"(.*)"|'(.*)'|([^\s#"']*))\s*(?:#.*)?$""", re.M)
_VARIAVEL = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")
_CHARSET_ARGS = re.compile(r"[A-Za-z0-9._=:,/+@?{}-]+")
_ENCADEAMENTO = re.compile(r"[;|&`<>]|\$\(")


def ler_atribuicoes(texto: str) -> dict[str, str]:
    """`nome="valor"` de um _default.cfg. A ultima atribuicao vence, como no shell."""
    valores: dict[str, str] = {}
    for m in _ATRIBUICAO.finditer(texto):
        valores[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)
    return valores


def _e_segredo(name: str) -> bool:
    return any(trecho in name for trecho in SEGREDOS)


def resolver(valor: str, variaveis: dict[str, str], extras: dict[str, str] | None = None,
             fundo: int = 6) -> str:
    """Troca ${nome} pelo que der; o que sobra fica como esta (e depois vira aviso).

    `extras` (portas e pastas) vence `variaveis`. Variavel de segredo nunca e trocada.
    """
    extras = extras or {}
    for _ in range(fundo):
        def troca(m: re.Match) -> str:
            name = m.group(1)
            if name in extras:
                return extras[name]
            if name in variaveis and not _e_segredo(name):
                # Valor vazio ("+server.seed ${seed}" com seed="") deixaria a opcao sem valor, e
                # ela engoliria a proxima da linha. Fica marcado como nao resolvido: sai junto.
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
    """Fica so com o que o broker aceita. Devolve (argumentos, nomes do que foi removido)."""
    # `;`, `|`, `&`, crase, `$(` e redirecionamento encadeiam OUTRO comando no shell: o que vem
    # depois nao e argumento do jogo e nao entra, nem como palavras soltas.
    corte = _ENCADEAMENTO.search(args)
    encadeado = corte is not None
    if corte:
        args = args[:corte.start()]
    tokens = _dividir(args)
    manter = [bool(_CHARSET_ARGS.fullmatch(t)) and "${" not in t for t in tokens]
    # Sem o valor, a opcao que o pedia ("-name") engoliria a proxima opcao da linha: sai junto.
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
    # Mesmo sem porta o App ID (a parte que ninguem sabe de cor) vale a sugestao: fica sem
    # porta e avisa.
    if not port:
        warnings.append("Este jogo guarda as portas no proprio arquivo de configuracao: preencha "
                        "as portas depois de instalar e ver o que ele abre.")
    return port


def _silent_query(port: int, from_config: dict[str, int], warnings: list[str]) -> int:
    """Consulta que o jogo abre sozinho (porta+1 do Valheim, a do arquivo de config).

    Ela tem de estar no firewall, senao o servidor nao aparece na lista. Sem marcador no
    comando o broker nao consegue avisa-la ao jogo, entao o jogo deixa de andar de porta.
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
    """O que o LinuxGSM diz sobre o jogo FORA do `_default.cfg`. Tudo opcional: sem isto sai o
    que o `_default.cfg` sozinho diz (portas UDP presumidas, e sem porta onde ele nao tem)."""

    info_body: str = ""        # corpo de fn_info_game_<jogo>, do info_game.sh
    messages_body: str = ""    # corpo de fn_info_messages_<jogo>, do info_messages.sh
    read_config: Callable[[str], str | None] = _no_config  # arquivo do Game-Server-Configs


def _port_list(entries: list[tuple[int, str, str]], protocols: dict[str, list[str]],
               warnings: list[str]) -> list[str]:
    """`numero/protocolo` de cada porta. O protocolo vem do info_messages.sh quando ele lista
    aquela variavel (o Terraria e so TCP); senao, UDP, e a sugestao avisa que presumiu."""
    ports: list[str] = []
    presumed = False
    for number, variable, default in entries:
        # A consulta da Steam e UDP, sempre. O info_messages.sh lista "Query ... tcp" em
        # varios jogos Unreal (Pavlov, Hypercharge): abrir TCP ali deixaria a porta que o
        # navegador de servidores consulta FECHADA, e uma aberta que ninguem usa.
        listed = ["udp"] if variable in STEAM_QUERY_VARIABLES else protocols.get(variable)
        presumed = presumed or not listed
        ports += [f"{number}/{proto}" for proto in listed or [default]]
    if presumed:
        warnings.append("Protocolo UDP presumido em parte das portas: confira (query e TCP em alguns jogos).")
    return list(dict.fromkeys(ports))


def sugerir(gamename: str, texto_do_cfg: str, extras: GameExtras = GameExtras()) -> dict | None:  # noqa: B008
    """Uma sugestao de jogo, ou None se nao da para montar uma que o broker aceite."""
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
    # O broker avisa ao jogo UMA porta extra. Com duas ou mais (Satisfactory antigo tem beacon e
    # confiavel) elas ficam com o numero padrao e o jogo nao anda de porta.
    var_extra = extras_da_rede[0] if len(extras_da_rede) == 1 else ""
    if var_extra:
        trocas[var_extra] = "{EXTRA_PORT}"
    # Toda outra porta vira o NUMERO padrao: o jogo sobe com ela, e so as expostas vao ao NAT.
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
    # Sem porta (sugestao parcial) o validador recebe uma qualquer: o que se confere aqui e o resto.
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


# ---------------------------------------------------- porta e dados fora do _default.cfg

# Tipo de consulta do LinuxGSM que e A2S, a que o painel sabe fazer.
A2S_QUERY_TYPES = ("protocol-valve",)
# Extensoes que a tela Config do painel abre campo a campo (ver games/config_format.py). As
# outras (.xml, .lua, .sii...) ficam so na pasta: o editor de arquivo generico serve.
CONFIG_EXTENSIONS = (".ini", ".json", ".properties", ".conf", ".cfg")
# Variaveis que o LinuxGSM usa para a consulta da Steam (A2S), que e UDP em todo jogo.
STEAM_QUERY_VARIABLES = ("queryport", "steamport")

_INFO_CALL = re.compile(r'fn_info_game_(\w+) "(port|queryport)" "([^"]+)"(?: "([^"]+)")?')
_DERIVED_PORT = re.compile(r'^\s*(queryport)="\$\(\(port \+ (\d{1,3})\)\)"', re.M)


def info_function(info_text: str, shortname: str, prefix: str = "fn_info_game_") -> str:
    """O corpo de `<prefixo><jogo>` num modulo do LinuxGSM (vazio se o jogo nao tem)."""
    m = re.search(rf"^{prefix}{re.escape(shortname)}\(\) \{{\n(.*?)^\}}", info_text, re.M | re.S)
    return m.group(1) if m else ""


_PORT_LINE = re.compile(r'fn_port "[^"]*" (\w+) (tcp|udp)\b')


def port_protocols(messages_body: str) -> dict[str, list[str]]:
    """Variavel -> protocolos, de `fn_port "Game" port tcp` (info_messages.sh).

    Uma mesma variavel pode aparecer duas vezes (a porta do Assetto Corsa e UDP e TCP).
    """
    found: dict[str, list[str]] = {}
    for variable, proto in _PORT_LINE.findall(messages_body):
        found.setdefault(variable, [])
        if proto not in found[variable]:
            found[variable].append(proto)
    return found


def _line_value(text: str, key: str, separator: str, anywhere: bool = False) -> str:
    """O `sed` dos leitores do LinuxGSM: primeira linha que comeca pela chave, valor depois do
    ULTIMO separador, sem aspas. `anywhere` e o do quakec (`set net_port "27960"`)."""
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
    """Os tres formatos de xpath que o info_game.sh usa para porta: `/a/@b`, `/a/b` e
    `/a/b[@name='x']/@value`. O ElementTree entende o predicado; o atributo final e a parte."""
    try:
        # O arquivo e o do repositorio do LinuxGSM, lido na maquina de quem gera as sugestoes
        # (nunca no painel), e a stdlib nao expande entidade externa desde o Python 3.7.8.
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
    """O valor de `key` num arquivo de config, lido como o `fn_info_game_<kind>` le."""
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
    """Portas lidas do arquivo de config PADRAO do jogo, onde o info_game.sh diz que elas estao.

    So o arquivo que o LinuxGSM publica (`servercfgdefault`) ou o que a chamada nomeia: e o
    unico que existe fora de uma instalacao. 7 Days to Die usa o que vem com o proprio jogo,
    que nao da para ler daqui, e continua sem porta.
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
    """A2S so com porta de consulta propria: e ela que o painel consulta."""
    return "a2s" if query_port and v.get("querytype") in A2S_QUERY_TYPES else "log"


def config_location(v: dict[str, str]) -> tuple[str, list[str]]:
    """Pasta e arquivo de config, quando os dois moram na pasta do jogo.

    A pasta do LinuxGSM fora de /opt/game (lgsm/config-lgsm, o HOME) nao existe na instalacao
    do broker, e um arquivo com o nome da instancia (`${selfname}.xml`) tampouco.
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
    """Filtro final: o validador do broker. Campo opcional recusado e removido (com aviso);
    identidade ou porta recusada derruba a sugestao inteira."""
    for _ in range(6):
        try:
            validate_dynamic(_as_panel_data(s))
            return s
        except ValidationError as erro:
            # `field`, e nao `campo`: com o nome antigo o atributo nunca existia, e toda sugestao
            # com argumento recusado era DESCARTADA em vez de sair com o campo em branco.
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


# ---------------------------------------------------------------- download e escrita

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
    game_config: Callable[[str, str], str | None]      # (shortname, arquivo) -> config padrao


def _sources(pasta_local: pathlib.Path | None) -> Sources:
    """Copia local: serverlist.csv, <servidor>.cfg, info_game.sh, info_messages.sh e
    config-game/<shortname>/<arquivo> (os tres ultimos opcionais)."""
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
    """A lista de portas do jogo; sem uma propria, a do motor (`engine="source"` cobre ~30
    jogos numa funcao so), que e a ordem do despacho do proprio info_messages.sh."""
    own = info_function(messages_text, shortname, prefix="fn_info_messages_")
    engine = ler_atribuicoes(cfg_text).get("engine", "")
    return own or (info_function(messages_text, engine, prefix="fn_info_messages_") if engine else "")


def coletar(pasta_local: pathlib.Path | None) -> tuple[list[dict], list[str]]:
    src = _sources(pasta_local)
    jogos = list(csv.DictReader(io.StringIO(src.server_list)))
    if not jogos:
        raise SystemExit("serverlist.csv vazio ou inacessivel")
    # Sem os modulos a sugestao continua valendo, so mais pobre: avisa quem gera, e nao para.
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
    # Dois jogos com o mesmo nome (ou chave) tornariam a busca ambigua: fica o primeiro.
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
    saida.write_bytes(texto.encode("utf-8"))  # bytes: no Windows o modo texto trocaria \n por \r\n


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
