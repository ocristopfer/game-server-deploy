"""Cada vez mais jogo publica uma API HTTP de administracao em vez de (ou alem de) uma
query UDP: Palworld (REST em 8212/tcp), Satisfactory (HTTPS em 7777/tcp), Minecraft
com plugin, Factorio... E a melhor fonte de todas, porque devolve os NOMES e nao so
a contagem. Nada aqui e especifico de um jogo: o painel busca uma URL, le o JSON e
acha a lista/contagem sozinho — ou pelo caminho que voce apontar.

A chamada sai de DENTRO do container, por SSH (recebido por injecao - este modulo nao
sabe como falar SSH, so pede pra alguem fazer isso), e nao do painel: essas APIs sao
feitas para escutar em localhost (a documentacao do Palworld pede explicitamente para
NAO expor a porta na internet) e assim continuam fechadas para fora.
"""
from __future__ import annotations

import base64
import json
import re
import shlex
from collections.abc import Callable
from typing import Any

from gamepanel.i18n import Mensagem
from gamepanel.runtime.a2s import AuthError, QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike

HTTP_MAX_BYTES = 256 * 1024
HTTP_URL_MAX = 400
HTTP_ERROR_STATUS = 400
URL_RE = re.compile(r"^https?://[A-Za-z0-9._\-]{1,253}(:\d{1,5})?(/[^\s]*)?$")
STATUS_MARK = "__HTTP_STATUS__"

# curl e a primeira opcao; python3 cobre os containers que so tem o interpretador
# (a imagem de teste do painel, por exemplo, nao traz curl).
HTTP_FETCH_SCRIPT = r"""
set -u
url=$1
auth=$2
corpo=$3
tmo=$4

if command -v curl >/dev/null 2>&1; then
  # -k: essas APIs usam certificado autoassinado (o Satisfactory, por exemplo).
  if [ -n "$corpo" ] && [ -n "$auth" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H "$auth" -H 'Content-Type: application/json' \
      --data-binary "$corpo" "$url"
  elif [ -n "$corpo" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H 'Content-Type: application/json' --data-binary "$corpo" "$url"
  elif [ -n "$auth" ]; then
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" \
      -H "$auth" "$url"
  else
    curl -sS -k -m "$tmo" -w "\n__HTTP_STATUS__%{http_code}" "$url"
  fi
  exit $?
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - "$url" "$auth" "$corpo" "$tmo" <<'PY'
import sys
import urllib.error
import urllib.request

url, auth, corpo, tmo = sys.argv[1:5]
req = urllib.request.Request(url, data=corpo.encode() if corpo else None)
if corpo:
    req.add_header("Content-Type", "application/json")
if auth:
    # Vem 'Nome: valor' pronto (nem toda API autentica por Authorization).
    nome, _, valor = auth.partition(":")
    req.add_header(nome.strip(), valor.strip())
ctx = None
if url.startswith("https"):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
try:
    resp = urllib.request.urlopen(req, timeout=float(tmo), context=ctx)
    dados, codigo = resp.read(), resp.getcode()
except urllib.error.HTTPError as exc:
    # 401/404/500 sao respostas, nao falhas: o painel quer ver o codigo.
    dados, codigo = exc.read(), exc.code
except Exception as exc:
    # Porta fechada, DNS, timeout: uma linha para o painel mostrar, nao um traceback.
    sys.stderr.write("nao consegui chamar %s: %s\n" % (url, exc))
    raise SystemExit(1)
sys.stdout.write(dados.decode("utf-8", "replace"))
sys.stdout.write("\n__HTTP_STATUS__%d" % codigo)
PY
  exit $?
fi

echo "o container nao tem curl nem python3 para falar HTTP" >&2
exit 127
"""


def auth_header(stored: str) -> str:
    """Transforma o que esta no banco no cabecalho HTTP INTEIRO ('Nome: valor').

    Formatos: 'basic:usuario:senha', 'bearer:token', 'header:Nome: valor' e o valor solto.

    Devolve o cabecalho com nome e tudo, e nao so o valor, por causa das APIs que nao
    autenticam por Authorization — o WebQuery do TeamSpeak quer 'x-api-key'. Com so o
    valor na mao, o unico nome possivel seria o fixo no script remoto.

    O valor solto (cadastro antigo, de quando isto devolvia so o valor) continua saindo
    como Authorization: mudar isso calaria a contagem de quem ja tinha um token gravado.
    """
    text = (stored or "").strip()
    if not text:
        return ""
    kind, _, rest = text.partition(":")
    if kind.lower() == "basic":
        return "Authorization: Basic " + base64.b64encode(rest.encode()).decode()
    if kind.lower() == "bearer":
        return "Authorization: Bearer " + rest
    # 'header:' e a saida para o resto do mundo. O que vem depois vai cru, com nome e
    # tudo, porque so quem cadastrou sabe como a API dela chama esse cabecalho.
    if kind.lower() == "header" and ":" in rest:
        return rest.strip()
    return "Authorization: " + text


def _split_status(raw: str) -> tuple[str, int]:
    """Separa o corpo do marcador de status que o script anexa no fim."""
    pos = raw.rfind(STATUS_MARK)
    if pos < 0:
        return raw, 0
    try:
        status = int(raw[pos + len(STATUS_MARK):].strip() or 0)
    except ValueError:
        status = 0
    return raw[:pos].rstrip("\n"), status


SshOutput = Callable[[ServerLike, str, int], str]


def http_json(
    ssh_output: SshOutput,
    server: ServerLike,
    url: str,
    auth: str,
    body: str,
    timeout: float,
    require_json: bool = True,
) -> Any:
    """Chama a URL de dentro do container e devolve o JSON ja interpretado.

    `ssh_output` e quem sabe falar SSH de verdade (injetado por quem chama - este modulo
    so pede pra rodar um comando e devolver a saida). `require_json=False` para quem so
    quer saber se deu certo: expulsar, banir e avisar respondem 200 com o corpo VAZIO, e
    ai "a resposta nao e JSON" seria um erro inventado em cima de uma acao que funcionou.
    """
    url = (url or "").strip()
    if len(url) > HTTP_URL_MAX or not URL_RE.match(url):
        raise QueryError(Mensagem("http.bad_url"))
    remote_cmd = " ".join(shlex.quote(p) for p in (
        "bash", "-lc", HTTP_FETCH_SCRIPT, "gp", url,
        auth_header(auth), (body or "").strip(), f"{timeout:g}",
    ))
    try:
        raw = ssh_output(server, remote_cmd, int(timeout) + 15)
    except RemoteError as exc:
        raise QueryError(str(exc)) from exc

    text, status = _split_status(raw)
    if status in (401, 403):
        # AuthError e uma QueryError especializada: quem tem login configurado usa
        # isso como gatilho para renovar o token em vez de so reportar o erro.
        raise AuthError(Mensagem("http.auth_failed", status=status))
    if status >= HTTP_ERROR_STATUS:
        raise QueryError(Mensagem("http.bad_status", status=status))
    if len(text) > HTTP_MAX_BYTES:
        raise QueryError(Mensagem("http.reply_too_big"))
    try:
        return json.loads(text)
    except ValueError:
        if not require_json:
            return {}
        sample = text.strip()[:120] or "(vazia)"
        raise QueryError(Mensagem("http.not_json", amostra=sample)) from None


# Chaves que os jogos costumam usar. Comparadas sem maiusculas nem separadores, entao
# 'numConnectedPlayers', 'num_connected_players' e 'NUMCONNECTEDPLAYERS' sao a mesma.
LIST_KEYS = {"players", "playerlist", "onlineplayers", "connectedplayers", "clients"}
NAME_KEYS = ("name", "playername", "accountname", "username", "displayname", "nick", "clientnickname")
COUNT_KEYS = {"players", "playercount", "numplayers", "onlineplayers", "currentplayernum",
              "numconnectedplayers", "playersonline", "online"}
MAX_KEYS = {"maxplayers", "maxplayernum", "maxplayercount", "serverplayermaxnum",
            "playerlimit", "slots"}
SERVER_NAME_KEYS = {"servername", "hostname"}
JSON_MAX_DEPTH = 5
PATH_RE = re.compile(r"[^.\[\]]+|\[\d+\]")
_MAX_PLAYERS_IN_LIST = 128


def _slug(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _json_walk(data: Any, path: str) -> Any:
    """Anda um caminho estilo 'a.b[0].c'. Caminho vazio devolve o objeto inteiro."""
    current = data
    for part in PATH_RE.findall(path or ""):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(current, list) or index >= len(current):
                raise QueryError(f"'{path}' nao existe na resposta")
            current = current[index]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise QueryError(f"'{path}' nao existe na resposta")
    return current


def _name_of(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item).strip() if isinstance(item, str) else ""
    by_slug = {_slug(k): v for k, v in item.items()}
    for key in NAME_KEYS:
        value = by_slug.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_query_client(item: Any) -> bool:
    """Conexao de ServerQuery, nao gente no canal.

    O TeamSpeak devolve na MESMA lista quem esta no voz (client_type 0) e as conexoes de
    consulta (client_type 1) — e uma delas e a do proprio painel, que acabou de perguntar.
    Sem tirar essas, o painel se contaria como usuario online e mandaria "entrou no jogo"
    sobre si mesmo a cada volta. Jogo que nao publica client_type nao e afetado.
    """
    if not isinstance(item, dict):
        return False
    kind = {_slug(k): v for k, v in item.items()}.get("clienttype")
    if kind is None:
        return False
    try:
        # O WebQuery manda tudo como string ("client_type": "1").
        return int(kind) != 0
    except (TypeError, ValueError):
        return False


# Kick e ban pedem um identificador, nunca o nome: nome muda, repete e nao e chave.
ID_KEYS = ("userid", "playeruid", "playerid", "steamid", "accountid", "uid")


def _id_of(item: Any) -> str:
    """Identificador do jogador, quando a API publica um. Vazio quando nao publica."""
    if not isinstance(item, dict):
        return ""
    by_slug = {_slug(k): v for k, v in item.items()}
    for key in ID_KEYS:
        value = by_slug.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        if str(value).strip():
            return str(value).strip()
    return ""


def _looks_like_player_list(item: Any) -> bool:
    """Uma lista so vale se for de objetos — e, se tiver alguem, com cara de jogador."""
    if not isinstance(item, list) or not all(isinstance(i, dict) for i in item):
        return False
    return not item or bool(_name_of(item[0]))


def _find_list(data: Any, depth: int = 0) -> list | None:
    """Primeira lista de jogadores da resposta, procurando pelo nome da chave e pela forma."""
    if _looks_like_player_list(data):
        return data
    if not isinstance(data, dict) or depth >= JSON_MAX_DEPTH:
        return None
    # A chave manda: {"players": []} com ninguem online e resposta valida, e pela
    # forma (lista vazia) nao daria para reconhecer.
    for key, value in data.items():
        if _slug(key) in LIST_KEYS and isinstance(value, list):
            return value if all(isinstance(i, dict) for i in value) else None
    for value in data.values():
        found = _find_list(value, depth + 1)
        if found is not None:
            return found
    return None


def _find_value(data: Any, keys: set, types: tuple, depth: int = 0) -> Any:
    """Primeiro valor do tipo pedido guardado em uma das chaves conhecidas."""
    if not isinstance(data, dict) or depth >= JSON_MAX_DEPTH:
        return None
    for key, value in data.items():
        if _slug(key) in keys and isinstance(value, types) and not isinstance(value, bool):
            return value
    for value in data.values():
        found = _find_value(value, keys, types, depth + 1)
        if found is not None:
            return found
    return None


def _list_from_json(data: Any, list_path: str, count_path: str) -> list | None:
    """A lista de jogadores da resposta, ou None quando a API nao publica uma.

    Com o caminho da contagem preenchido e sem o da lista, nem se procura: quem
    informou onde esta o numero esta dizendo que lista nao ha.
    """
    if list_path:
        found_list = _json_walk(data, list_path)
        if not isinstance(found_list, list):
            raise QueryError(f"'{list_path}' nao aponta para uma lista")
    elif count_path:
        return None
    else:
        found_list = _find_list(data)

    if not isinstance(found_list, list):
        return None
    # Antes de contar e de tirar nomes: o que sai daqui nao e jogador, e contaria como um.
    return [item for item in found_list if not _is_query_client(item)]


def _count_from_json(data: Any, count_path: str, player_list: list | None) -> int | None:
    """Quantos estao online, pelo caminho informado ou por chave conhecida.

    Devolve None quando ha lista: nesse caso quem conta e o tamanho dela.
    """
    if count_path:
        raw = _json_walk(data, count_path)
        if isinstance(raw, list):
            return len(raw)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return int(raw)
        raise QueryError(f"'{count_path}' nao e um numero nem uma lista")
    if player_list is not None:
        return None
    found = _find_value(data, COUNT_KEYS, (int, float))
    return int(found) if found is not None else None


def _names_from_json(player_list: list | None) -> list[dict]:
    """A lista no formato que as telas do painel esperam. Teto de 128 por resposta."""
    if player_list is None:
        return []
    out = []
    for item in player_list[:_MAX_PLAYERS_IN_LIST]:
        name = _name_of(item)
        if name:
            out.append({"name": name, "id": _id_of(item), "since": "",
                        "score": 0, "seconds": 0})
    return out


def read_players_json(data: Any, list_path: str = "", count_path: str = "") -> dict[str, Any]:
    """Tira jogadores de um JSON qualquer.

    Sem caminhos preenchidos o painel procura sozinho uma lista de jogadores e, se nao
    houver, um numero em alguma chave conhecida (currentplayernum, numplayers, ...).
    """
    player_list = _list_from_json(data, list_path, count_path)
    count = _count_from_json(data, count_path, player_list)
    names = _names_from_json(player_list)
    if count is None and player_list is not None:
        count = len(player_list)

    if count is None:
        raise QueryError(
            "nao achei jogadores na resposta - preencha o caminho da lista ou da contagem"
        )

    maximum = _find_value(data, MAX_KEYS, (int, float))
    return {
        "players": count,
        "list": names,
        "max_players": int(maximum) if maximum is not None else None,
        "server_name": _find_value(data, SERVER_NAME_KEYS, (str,)) or "",
        "map": "",
        "error": "",
    }
