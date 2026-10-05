"""Who is playing: where the number comes from, and what can be done with these people.

Three possible sources (A2S query, the game's own HTTP API, or the service log) and the
actions that same API accepts (kick, ban, announce): same credential, same port, same
expiring token.

It lives in `services/` and not in `runtime/` because of the DATABASE: the API token
expires, and renewing it means writing the new one to the server's record. `runtime/`
only speaks SSH and network, with no persistence at all, which is why whatever depended on
the database ended up in `app.py` until this layer existed.

Everything this module needs from the rest of the panel comes in through `PlayerDeps`
(SSH, database, log reading, A2S query). No import of `app.py`: it would be circular, and
this is what lets the whole count be tested without Flask, SSH or a container.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, TypedDict

from gamepanel.i18n import Message
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import http_probe, log_probe
from gamepanel.runtime.a2s import AuthError, QueryError
from gamepanel.runtime.ssh import RemoteError, ServerLike
from gamepanel.services import parallel

# Where the player count can come from. 'none' is the explicit off switch, unlike the
# empty value, which means "old record, infer it from the query port". 'net' counts the
# active conversations on the game port, through the CT firewall (`runtime.presence_probe`).
PLAYER_SOURCES = ("a2s", "http", "net", "log", "none")
# What complements the chosen source, in this order: whatever talks to the game LIVE comes
# before the log, which is rebuilt from events (see `configured_sources`). 'net' is not here:
# it has no field of its own that says whether the CT supports it, so it only counts when
# chosen.
COMBINE_ORDER = ("a2s", "http", "log")

# Columns that describe the HTTP call; they travel together between form, wizard and
# database. The column list lives in the repository: they are column names, and writing
# the same list in two places is how a new column lands in one and goes missing from the other.
HTTP_FIELDS = servers_repo.HTTP_FIELDS

PLAYER_MSG_MAX = 200
# The value is a catalog key (`gamepanel.i18n`), not the screen text.
PLAYER_ACTION_LABELS = {
    "announce": "player_action.announce",
    "kick": "player_action.kick",
    "ban": "player_action.ban",
}

# The catalog placeholders, as constants: they are the interface between the table below
# and `_fill`, and writing them by hand on every line is how one of them becomes
# "{mesage}" in a single game, unnoticed until someone tries to kick somebody.
BASE_MARK = "{base}"
PLAYER_MARK = "{player}"
MESSAGE_MARK = "{message}"

class ActionEntry(TypedDict):
    """One line of the action catalog.

    A TypedDict, and not a loose dict: without it `url` becomes `object` to the type
    checker, and the `.match()` right below turns into an error that only shows up at
    runtime.
    """

    name: str
    url: re.Pattern[str]
    # action -> (route, body) with the placeholders still to fill in.
    actions: dict[str, tuple[str, dict[str, str]]]


# Kick, ban and announce go out through the SAME API that already counts the players:
# another route, same credential. There is no standard across games, so there is a
# catalog, recognized by the count URL the server already has on record.
#
# Of the games this repo installs, only Palworld publishes these actions (Satisfactory has
# no kick in its API). A new game comes in as one more entry here, without touching the rest.
API_ACTIONS: tuple[ActionEntry, ...] = (
    {
        "name": "Palworld (REST)",
        "url": re.compile(r"^(?P<base>https?://[^/\s]+/v1/api)/players/?$", re.I),
        # action -> (route, body).
        "actions": {
            "announce": (f"{BASE_MARK}/announce", {"message": MESSAGE_MARK}),
            "kick": (f"{BASE_MARK}/kick",
                     {"userid": PLAYER_MARK, "message": MESSAGE_MARK}),
            "ban": (f"{BASE_MARK}/ban",
                    {"userid": PLAYER_MARK, "message": MESSAGE_MARK}),
        },
    },
)

# (server, url, auth, body, require_json) -> data already parsed.
HttpJson = Callable[..., Any]
# () -> a connection of its own (the count runs outside the request, so Flask's will not do).
Connect = Callable[[], sqlite3.Connection]
# (server, limit) -> lines of the service log.
ReadLogLines = Callable[..., list[str]]
# (host, port) -> answer of the A2S query.
QueryPlayers = Callable[[str, int], dict]
# (server) -> count from the active conversations on the game port.
PresencePlayers = Callable[[ServerLike], dict]


class PlayerDeps(NamedTuple):
    """What the count needs from the rest of the panel.

    It comes in as a parameter, and not through an import, for the usual two reasons:
    `app.py` imports this module (the reverse would be circular) and the test swaps any of
    these pieces for a fake without needing SSH or a container.
    """

    http_json: HttpJson
    connect: Connect
    read_log_lines: ReadLogLines
    query_players: QueryPlayers
    players_ttl: float
    presence_players: PresencePlayers


def _stored_value(server: ServerLike, column: str) -> str:
    try:
        return (server[column] or "").strip()
    except (IndexError, KeyError):
        # Row coming from a SELECT without the new columns (or a database before the migration).
        return ""


def _stored_max_players(server: ServerLike) -> int:
    # INTEGER column: `_stored_value` calls .strip() and would break here.
    try:
        return int(server["max_players"] or 0)
    except (IndexError, KeyError, TypeError, ValueError):
        return 0


def player_source(server: ServerLike) -> str:
    """How to count this server's players: 'a2s', 'http', 'log' or '' (off)."""
    chosen_one = (server["player_source"] or "").strip()
    if chosen_one in PLAYER_SOURCES:
        return "" if chosen_one == "none" else chosen_one
    # Old record, from before the field existed: query port filled in = A2S.
    return "a2s" if int(server["query_port"] or 0) else ""


# ------------------------------------------------- counting through the game API

def _has_login(server: ServerLike) -> bool:
    """True when the server is set up to obtain the token on its own."""
    return bool(_stored_value(server, "http_login_url")
                and _stored_value(server, "http_token_path"))


def http_login(deps: PlayerDeps, server: ServerLike) -> str:
    """Exchanges the credential for a token and stores it in the database. Returns the token."""
    url = _stored_value(server, "http_login_url")
    path = _stored_value(server, "http_token_path")
    if not url or not path:
        raise QueryError(Message("api.login_incomplete"))

    # The login goes WITHOUT Authorization: it is what produces the credential.
    data = deps.http_json(server, url, "", _stored_value(server, "http_login_body"))
    token = http_probe._json_walk(data, path)
    if not isinstance(token, str) or not token.strip():
        raise QueryError(Message("api.no_token_at", path=path))
    token = token.strip()
    # A connection of its own, and not Flask's: the count also runs outside a request
    # (cache/polling in a thread). The write here is a single row.
    con = deps.connect()
    try:
        with con:
            servers_repo.set_http_token(con, int(server["id"]), token)
    finally:
        con.close()
    return token


def call_game_api(deps: PlayerDeps, server: ServerLike, url: str, body: str = "",
                      require_json: bool = True) -> Any:
    """Calls the game API with the stored credential, renewing the token if it expired.

    It lives here, and not inside players_from_http, because counting is no longer the only
    thing that talks to this API: kick, ban and announce use the same port, the same
    password and the same expiring token.
    """
    with_login = _has_login(server)
    if with_login:
        token = _stored_value(server, "http_token")
        # With no stored token (first time, or after changing the password) go straight
        # through the login instead of spending a call that is going to fail.
        auth = f"bearer:{token}" if token else f"bearer:{http_login(deps, server)}"
    else:
        auth = server["http_auth"]

    try:
        return deps.http_json(server, url, auth, body, require_json)
    except AuthError:
        if not with_login:
            raise
        # Token expired or revoked: renew once and retry. If it fails again, the error
        # propagates - then the problem is the credential, not the token's lifetime.
        return deps.http_json(server, url, f"bearer:{http_login(deps, server)}", body, require_json)


def players_from_http(deps: PlayerDeps, server: ServerLike) -> dict:
    if not (server["http_url"] or "").strip():
        raise QueryError(Message("api.need_url"))
    data = call_game_api(deps, server, server["http_url"], server["http_body"])
    return http_probe.read_players_json(data, server["http_list_path"], server["http_count_path"])


# ----------------------------------------------------- counting through the log

def players_from_log(deps: PlayerDeps, server: ServerLike) -> dict:
    join_pattern = log_probe.compile_pattern(server["join_re"], "pattern.join")
    if not join_pattern:
        raise QueryError(Message("api.need_join_pattern"))
    leave_pattern = log_probe.compile_pattern(server["leave_re"], "pattern.leave")
    try:
        lines_of = deps.read_log_lines(server)
    except RemoteError as exc:
        raise QueryError(str(exc)) from exc

    result = log_probe.apply_log_events(lines_of, join_pattern, leave_pattern)
    result.update({"error": "", "max_players": None, "server_name": "", "map": ""})
    return result


# ------------------------------------------- actions on whoever is playing

def actions_api(server: ServerLike) -> dict[str, Any] | None:
    """Does this server's API accept actions? Returns the catalog entry, or None."""
    if player_source(server) != "http":
        return None
    url = (server["http_url"] or "").strip()
    for entry in API_ACTIONS:
        matches_it = entry["url"].match(url)
        if matches_it:
            found: dict[str, Any] = {**entry, "base": matches_it.group("base")}
            return found
    return None


def player_actions(server: ServerLike) -> list[str]:
    """Which actions the screen can offer on this server."""
    api = actions_api(server)
    return sorted(api["actions"]) if api else []


def _fill(mold: str, base: str, player: str, message: str) -> str:
    """Replaces the catalog placeholders.

    It deliberately does NOT use str.format: the message comes from whoever is typing, and
    a stray brace ('{') would blow up the format, or worse, become a path into the object.
    """
    return (mold.replace(BASE_MARK, base)
                 .replace(PLAYER_MARK, player)
                 .replace(MESSAGE_MARK, message))


def player_action(deps: PlayerDeps, server: ServerLike, action: str, player: str,
                    message: str) -> str:
    """Runs the action on the game API. Returns the phrase that goes to the screen."""
    api = actions_api(server)
    if not api or action not in api["actions"]:
        raise QueryError(Message("api.action_not_published"))
    if action == "announce":
        if not message:
            raise QueryError(Message("api.write_the_notice"))
    elif not player:
        raise QueryError(Message("api.no_player_id"))

    route, mold = api["actions"][action]
    body = {key: _fill(value, api["base"], player, message)
             for key, value in mold.items()}
    # require_json=False: these routes answer 200 with an empty body.
    call_game_api(deps, server, _fill(route, api["base"], player, message),
                      json.dumps(body), require_json=False)
    return PLAYER_ACTION_LABELS.get(action, action)


# ------------------------------------------------------ the count itself

# Process cache: several screens and the monitor ask the same thing in a row, and each
# query costs a trip to the game (or to the log, over SSH). `app.py` publishes this same
# object under the old name, and the tests' `database` fixture clears it between cases.
_players_cache: dict[int, tuple[float, dict]] = {}
_players_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    """Forgets the stored count; use after changing HOW the server counts."""
    with _players_lock:
        _players_cache.pop(server_id, None)


def _count_now(deps: PlayerDeps, server: ServerLike, source: str) -> dict:
    if source == "log":
        return players_from_log(deps, server)
    if source == "http":
        return players_from_http(deps, server)
    if source == "net":
        return deps.presence_players(server)
    port = int(server["query_port"] or 0)
    if not port:
        raise QueryError(Message("api.need_query_port"))
    return deps.query_players(server["host"], port)


def configured_sources(server: ServerLike) -> list[str]:
    """The sources this server has filled in, the CHOSEN one first.

    The chosen one still rules the count; the others only come in to cover what it does
    not provide. Behind it come the ones that talk to the game live (A2S, API) and last the
    log, which gets it wrong when the server goes down without writing the leaves. 'none'
    turns all of them off, including those with filled-in fields: it is the way to silence
    a server without deleting its record.
    """
    chosen = player_source(server)
    if not chosen:
        return []
    ready = {
        "a2s": int(server["query_port"] or 0) > 0,
        "http": bool(_stored_value(server, "http_url")),
        "log": bool(_stored_value(server, "join_re")),
    }
    return [chosen] + [s for s in COMBINE_ORDER if s != chosen and ready[s]]


def _names_from_others(deps: PlayerDeps, server: ServerLike, data: dict,
                       others: list[str]) -> None:
    """The count came without names (A2S of an Unreal game, DayZ): ask the rest for names.

    The NUMBER is still the one from the source that counted - it talks to the game now;
    the log's list is rebuilt from events and may still hold someone who dropped without a
    leave line. That is why the list is cut to the latest joiners, as many as the count
    says, and the screen warns when the two do not match.
    """
    count = data.get("players") or 0
    if not count or data.get("list"):
        # Nobody online, or the source already said who: asking another would only waste SSH.
        return
    for source in others:
        try:
            names = _count_now(deps, server, source).get("list") or []
        except QueryError:
            # A complementing source fails silently: the count is already on the screen, and
            # the error of the main source (if any) is what matters to the reader.
            continue
        if names:
            data["list"] = names[-count:]
            data["names_from"] = source
            data["names_partial"] = len(names) != count
            return


def _count_combined(deps: PlayerDeps, server: ServerLike, sources: list[str]) -> dict:
    """Counts with the first source that answers and fills in names from the following ones."""
    first_error = ""
    for position, source in enumerate(sources):
        try:
            data = _count_now(deps, server, source)
        except QueryError as exc:
            first_error = first_error or str(exc)
            continue
        data["configured"] = True
        data["source"] = source
        if not data.get("max_players"):
            # The log and active connections do not know the total; A2S brings its own and
            # beats the record.
            data["max_players"] = _stored_max_players(server) or None
        if position:
            # It fell back to a reserve: the screen shows the number, and the chosen source's
            # error comes along so nobody thinks A2S is working when the log was what answered.
            data["fallback_error"] = first_error
        _names_from_others(deps, server, data, sources[position + 1:])
        return data
    return {"configured": True, "error": first_error, "players": None, "list": [],
            "source": sources[0]}


def server_players(deps: PlayerDeps, server: ServerLike, force: bool = False) -> dict:
    sources = configured_sources(server)
    if not sources:
        return {"configured": False, "error": "", "players": None, "list": [], "source": ""}

    key = int(server["id"])
    now_ts = time.monotonic()
    if not force:
        with _players_lock:
            cached = _players_cache.get(key)
        if cached and now_ts - cached[0] < deps.players_ttl:
            return cached[1]

    data = _count_combined(deps, server, sources)

    with _players_lock:
        _players_cache[key] = (now_ts, data)
    return data


def all_players(count_one: Callable[[ServerLike], dict], servers: Sequence[ServerLike],
                join_timeout: float, msg_timeout: str) -> dict[int, dict]:
    """Queries all of them in parallel: it is 3s of waiting each when one is down.

    `count_one` is received ready-made (and not built here from `deps`) because the caller
    is `app.py`, and there that name may have been swapped for a fake in the test: building
    the call in here would bypass the swap, silently.
    """
    return parallel.per_server(
        count_one, servers, join_timeout,
        {"configured": True, "error": msg_timeout, "players": None, "list": [], "source": ""},
    )
