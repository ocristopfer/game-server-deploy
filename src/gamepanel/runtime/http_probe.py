"""More and more games publish an HTTP admin API instead of (or alongside) a UDP query:
Palworld (REST on 8212/tcp), Satisfactory (HTTPS on 7777/tcp), Minecraft with a
plugin, Factorio... It is the best source of all, because it returns the NAMES and not
just the count. Nothing here is game-specific: the panel fetches a URL, reads the JSON
and finds the list/count by itself - or via the path you point it to.

The call is made from INSIDE the container, over SSH (injected - this module does not
know how to speak SSH, it only asks someone else to), and not from the panel: these
APIs are meant to listen on localhost (the Palworld docs explicitly say NOT to expose
the port to the internet), and this way they stay closed to the outside.
"""
from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from typing import Any

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import AuthError, QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike

HTTP_MAX_BYTES = 256 * 1024
HTTP_URL_MAX = 400
HTTP_ERROR_STATUS = 400
URL_RE = re.compile(r"^https?://[A-Za-z0-9._\-]{1,253}(:\d{1,5})?(/[^\s]*)?$")
STATUS_MARK = "__HTTP_STATUS__"

# curl is the first choice; python3 covers containers that only have the interpreter
# (the panel's test image, for example, does not ship curl).
HTTP_FETCH_SCRIPT = r"""
set -u
url=$1
auth=$2
corpo=$3
tmo=$4

if command -v curl >/dev/null 2>&1; then
  # -k: these APIs use self-signed certificates (Satisfactory, for example).
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
    # Arrives as a ready 'Name: value' (not every API authenticates via Authorization).
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
    # 401/404/500 are answers, not failures: the panel wants to see the code.
    dados, codigo = exc.read(), exc.code
except Exception as exc:
    # Closed port, DNS, timeout: one line for the panel to show, not a traceback.
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
    """Turns what is stored in the database into the WHOLE HTTP header ('Name: value').

    Formats: 'basic:user:password', 'bearer:token', 'header:Name: value' and a bare value.

    Returns the header with its name and all, not just the value, because of APIs that do
    not authenticate via Authorization - TeamSpeak's WebQuery wants 'x-api-key'. With only
    the value in hand, the only possible name would be the one hardcoded in the remote
    script.

    A bare value (old records, from when this returned only the value) still goes out as
    Authorization: changing that would silence the count for anyone who already had a
    token stored.
    """
    text = (stored or "").strip()
    if not text:
        return ""
    kind, _, rest = text.partition(":")
    if kind.lower() == "basic":
        return "Authorization: Basic " + base64.b64encode(rest.encode()).decode()
    if kind.lower() == "bearer":
        return "Authorization: Bearer " + rest
    # 'header:' is the escape hatch for everything else. What follows goes out raw, name
    # and all, because only whoever registered it knows what their API calls that header.
    if kind.lower() == "header" and ":" in rest:
        return rest.strip()
    return "Authorization: " + text


def _split_status(raw: str) -> tuple[str, int]:
    """Splits the body from the status marker the script appends at the end."""
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
    """Calls the URL from inside the container and returns the already parsed JSON.

    `ssh_output` is what actually speaks SSH (injected by the caller - this module only
    asks for a command to be run and its output returned). `require_json=False` is for
    callers that only want to know whether it worked: kick, ban and broadcast answer 200
    with an EMPTY body, and then "the reply is not JSON" would be an invented error on
    top of an action that succeeded.
    """
    url = (url or "").strip()
    if len(url) > HTTP_URL_MAX or not URL_RE.match(url):
        raise QueryError(Message("http.bad_url"))
    # An HTTP call from inside the container needs no right at all, in either mode.
    command = remote_cmd.unprivileged(
        "bash", "-lc", HTTP_FETCH_SCRIPT, "gp", url,
        auth_header(auth), (body or "").strip(), f"{timeout:g}",
    )
    try:
        raw = ssh_output(server, command, int(timeout) + 15)
    except RemoteError as exc:
        raise QueryError(str(exc)) from exc

    text, status = _split_status(raw)
    if status in (401, 403):
        # AuthError is a specialized QueryError: callers with a login configured use it
        # as the trigger to renew the token instead of just reporting the error.
        raise AuthError(Message("http.auth_failed", status=status))
    if status >= HTTP_ERROR_STATUS:
        raise QueryError(Message("http.bad_status", status=status))
    if len(text) > HTTP_MAX_BYTES:
        raise QueryError(Message("http.reply_too_big"))
    try:
        return json.loads(text)
    except ValueError:
        if not require_json:
            return {}
        sample = text.strip()[:120] or "(vazia)"
        raise QueryError(Message("http.not_json", sample=sample)) from None


# Keys games commonly use. Compared ignoring case and separators, so
# 'numConnectedPlayers', 'num_connected_players' and 'NUMCONNECTEDPLAYERS' are the same.
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
    """Walks a path like 'a.b[0].c'. An empty path returns the whole object."""
    current = data
    for part in PATH_RE.findall(path or ""):
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(current, list) or index >= len(current):
                raise QueryError(Message("http.path_missing", path=path))
            current = current[index]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise QueryError(Message("http.path_missing", path=path))
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
    """A ServerQuery connection, not a person in the channel.

    TeamSpeak returns in the SAME list both those in voice (client_type 0) and query
    connections (client_type 1) - and one of them is the panel itself, which just asked.
    Without removing those, the panel would count itself as an online user and send
    "joined the game" about itself every round. Games that do not publish client_type
    are not affected.
    """
    if not isinstance(item, dict):
        return False
    kind = {_slug(k): v for k, v in item.items()}.get("clienttype")
    if kind is None:
        return False
    try:
        # WebQuery sends everything as strings ("client_type": "1").
        return int(kind) != 0
    except (TypeError, ValueError):
        return False


# Kick and ban take an identifier, never the name: names change, repeat and are not keys.
ID_KEYS = ("userid", "playeruid", "playerid", "steamid", "accountid", "uid")


def _id_of(item: Any) -> str:
    """The player's identifier, when the API publishes one. Empty when it does not."""
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
    """A list only counts if it holds objects - and, if not empty, ones that look like players."""
    if not isinstance(item, list) or not all(isinstance(i, dict) for i in item):
        return False
    return not item or bool(_name_of(item[0]))


def _find_list(data: Any, depth: int = 0) -> list | None:
    """The first player list in the reply, searched by key name and by shape."""
    if _looks_like_player_list(data):
        return data
    if not isinstance(data, dict) or depth >= JSON_MAX_DEPTH:
        return None
    # The key wins: {"players": []} with nobody online is a valid reply, and by shape
    # alone (an empty list) it could not be recognized.
    for key, value in data.items():
        if _slug(key) in LIST_KEYS and isinstance(value, list):
            return value if all(isinstance(i, dict) for i in value) else None
    for value in data.values():
        found = _find_list(value, depth + 1)
        if found is not None:
            return found
    return None


def _find_value(data: Any, keys: set, types: tuple, depth: int = 0) -> Any:
    """The first value of the requested type stored under one of the known keys."""
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
    """The player list from the reply, or None when the API does not publish one.

    With the count path filled in and no list path, there is no search at all: whoever
    said where the number is is saying there is no list.
    """
    if list_path:
        found_list = _json_walk(data, list_path)
        if not isinstance(found_list, list):
            raise QueryError(Message("http.not_a_list", path=list_path))
    elif count_path:
        return None
    else:
        found_list = _find_list(data)

    if not isinstance(found_list, list):
        return None
    # Before counting and extracting names: what is dropped here is not a player and would
    # count as one.
    return [item for item in found_list if not _is_query_client(item)]


def _count_from_json(data: Any, count_path: str, player_list: list | None) -> int | None:
    """How many are online, via the given path or a known key.

    Returns None when there is a list: in that case its length is the count.
    """
    if count_path:
        raw = _json_walk(data, count_path)
        if isinstance(raw, list):
            return len(raw)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return int(raw)
        raise QueryError(Message("http.not_a_count", path=count_path))
    if player_list is not None:
        return None
    found = _find_value(data, COUNT_KEYS, (int, float))
    return int(found) if found is not None else None


def _names_from_json(player_list: list | None) -> list[dict]:
    """The list in the format the panel's screens expect. Capped at 128 per reply."""
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
    """Extracts players from arbitrary JSON.

    With no paths filled in, the panel looks for a player list by itself and, if there
    is none, for a number under some known key (currentplayernum, numplayers, ...).
    """
    player_list = _list_from_json(data, list_path, count_path)
    count = _count_from_json(data, count_path, player_list)
    names = _names_from_json(player_list)
    if count is None and player_list is not None:
        count = len(player_list)

    if count is None:
        raise QueryError(Message("http.no_players_found"))

    maximum = _find_value(data, MAX_KEYS, (int, float))
    return {
        "players": count,
        "list": names,
        "max_players": int(maximum) if maximum is not None else None,
        "server_name": _find_value(data, SERVER_NAME_KEYS, (str,)) or "",
        "map": "",
        "error": "",
    }
