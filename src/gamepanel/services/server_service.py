"""Validation of the server form: what arrives from the screen becomes a record, or an error.

One single place for a practical reason: almost every field here ends up inside a remote
command (the systemd unit, the save folder, the log regex) or an HTTP call carrying a
credential. Spreading these checks across the routes is how one of them gets lost.

The functions below always follow the same convention: they return the value ALREADY
cleaned and note the problem in the `errors` list they receive; they do not raise. That
is what lets the screen show ALL the form errors at once, instead of one per submission.

An empty field is almost never an error: it means "I do not use this feature". Fields
that require a value say so explicitly (name, host, user and service).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from gamepanel.i18n import Message
from gamepanel.runtime import remote_cmd
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.http_probe import URL_RE
from gamepanel.runtime.log_probe import compile_pattern, valid_log_path

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
# The host ends up as an ssh argument, so it must not start with "-": a host like
# "-oProxyCommand..." would be read as an option, and that option runs a command ON THE PANEL.
# `\Z`, not `$`: `$` also matches before a trailing newline.
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}\Z")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\Z")
JSON_PATH_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{0,120}$")

MAX_PORT = 65535
NOTES_MAX = 2000
GAME_PORT_MAX = 120
CONFIG_PATH_MAX = 400
HTTP_AUTH_MAX = 300

# Anything with `.get(name, default)` will do: the Flask form, or a dict in the test.
Form = Mapping[str, Any]
# An absolute, already normalized path; raises ValueError on anything that is no good.
CleanPath = Callable[[str], str]


class FormLimits(NamedTuple):
    """The caps that apply to this record. They come from outside because they are configuration."""

    config_files_max: int
    backup_paths_max: int
    http_url_max: int
    http_body_max: int
    http_path_max: int
    re_max_len: int
    player_sources: tuple[str, ...]


def _field(form: Form, name: str, cap: int) -> str:
    """A text field of the form: no whitespace at the ends and with a length cap."""
    return (form.get(name, "") or "").strip()[:cap]


def _port_field(value: str | None, default: int, minimum: int, error: Message,
           errors: list[str]) -> int:
    """Reads a port from the form; `minimum` 0 allows turning the feature off."""
    raw = (value or "").strip() or str(default)
    if raw.isdigit() and minimum <= int(raw) <= MAX_PORT:
        return int(raw)
    errors.append(error)
    return default


# A server's slots: above this it is an extra digit, not a real game.
MAX_PLAYERS_LIMIT = 1000


def _count_field(value: str | None, errors: list[str]) -> int:
    """The server's slots; empty = 0 (unknown, or the counting source reports it)."""
    raw = (value or "").strip() or "0"
    if raw.isdigit() and int(raw) <= MAX_PLAYERS_LIMIT:
        return int(raw)
    errors.append(Message("form.bad_max_players"))
    return 0


def _service_field(value: str | None, errors: list[str]) -> str:
    service = (value or "").strip()
    if service and not service.endswith(".service"):
        service = f"{service}.service"  # the suffix is always the same: not worth bothering
    if not UNIT_RE.match(service):
        errors.append(Message("form.bad_service"))
    return service


def _config_folder(value: str | None, clean_path: CleanPath, errors: list[str]) -> str:
    path = (value or "").strip()[:CONFIG_PATH_MAX]
    if not path:
        return ""
    try:
        return clean_path(path)
    except ValueError as exc:
        errors.append(Message("form.bad_config_folder", reason=exc))
        return ""


def _config_files(value: str | None, clean_path: CleanPath, maximum: int,
                     errors: list[str]) -> str:
    """Reads the list of configuration files (one absolute path per line)."""
    paths: list[str] = []
    for line in (value or "").replace(",", "\n").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            clean = clean_path(raw)
        except ValueError as exc:
            errors.append(Message("form.bad_config_file", path=raw, reason=exc))
            continue
        if clean not in paths:
            paths.append(clean)
    if len(paths) > maximum:
        errors.append(Message("form.too_many_config_files", n=maximum))
        paths = paths[:maximum]
    return "\n".join(paths)


def _backup_paths(value: str | None, clean_path: CleanPath, maximum: int,
                     errors: list[str]) -> str:
    """Reads the list of what goes into the backup (one absolute path per line).

    Empty is the right answer for most records: with nothing here the backup takes the
    server's configuration folder, which is where the save usually lives.
    """
    paths: list[str] = []
    for line in (value or "").replace(",", "\n").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            clean = clean_path(raw)
        except ValueError as exc:
            errors.append(Message("form.bad_backup_path", path=raw, reason=exc))
            continue
        if clean == "/":
            errors.append(Message("form.no_root_backup"))
            continue
        if clean not in paths:
            paths.append(clean)
    if len(paths) > maximum:
        errors.append(Message("form.too_many_backup_paths", n=maximum))
        paths = paths[:maximum]
    return "\n".join(paths)


def _url_or_error(raw: str, error: Message, errors: list[str]) -> str:
    """A valid URL, or an empty string with the error noted. Empty is not an error: it means "not used"."""
    if raw and not URL_RE.match(raw):
        errors.append(error)
        return ""
    return raw


def _json_or_error(raw: str, label: str, errors: list[str]) -> str:
    """A valid JSON body, or an empty string with the error noted."""
    if not raw:
        return ""
    try:
        json.loads(raw)
    except ValueError as exc:
        errors.append(Message("form.bad_json", label=label, reason=exc))
        return ""
    return raw


def _json_paths(form: Form, cap: int, errors: list[str]) -> dict:
    """The three navigation paths into the response (list, count, token)."""
    paths = {}
    for field, label in (("http_list_path", "form.path_list"),
                          ("http_count_path", "form.path_count"),
                          ("http_token_path", "form.path_token")):
        text = _field(form, field, cap)
        if text and not JSON_PATH_RE.match(text):
            errors.append(Message("form.bad_json_path", label=Message(label)))
            text = ""
        paths[field] = text
    return paths


def _http_fields(form: Form, limits: FormLimits, errors: list[str]) -> dict:
    """Reads and checks the HTTP call fields (URL, authentication, body, paths)."""
    url = _url_or_error(
        _field(form, "http_url", limits.http_url_max),
        Message("form.bad_api_url"), errors,
    )
    body = _json_or_error(
        _field(form, "http_body", limits.http_body_max),
        Message("form.request_body"), errors,
    )
    paths = _json_paths(form, limits.http_path_max, errors)

    # Automatic login: the three fields go together. Filling in only some of them is
    # almost always a mistake, and failing here beats finding out at query time.
    login_url = _url_or_error(
        _field(form, "http_login_url", limits.http_url_max),
        Message("form.bad_login_url"), errors,
    )
    login_body = _json_or_error(
        _field(form, "http_login_body", limits.http_body_max),
        Message("form.login_body"), errors,
    )
    if (login_url or login_body) and not paths["http_token_path"]:
        errors.append(Message("form.login_needs_token_path"))

    return {
        "http_url": url,
        "http_login_url": login_url,
        "http_login_body": login_body,
        # Stores the API password the way it has to be sent. The panel database already
        # grants root access to the containers, so this does not widen the damage of a
        # leak, but treat the panel.db file as a secret.
        "http_auth": _field(form, "http_auth", HTTP_AUTH_MAX),
        "http_body": body,
        **paths,
    }


def _log_path(value: str | None, errors: list[str]) -> str:
    try:
        return valid_log_path(value)
    except ValueError as exc:
        # The `Message` itself, not `str(exc)`: the string is the deploy language, and the
        # form shows the error in the language of whoever is filling it in.
        errors.append(exc.args[0] if exc.args else str(exc))
        return ""


def _pattern(value: str | None, label: str, cap: int, errors: list[str]) -> str:
    """Stores the regex only after checking that it compiles."""
    text = (value or "").strip()[:cap]
    if not text:
        return ""
    try:
        compile_pattern(text, label)
    except QueryError as exc:
        errors.append(exc.args[0] if exc.args else str(exc))
        return ""
    return text


def form_server(form: Form, clean_path: CleanPath,
                limits: FormLimits) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = form.get("name", "").strip()
    host = form.get("host", "").strip()
    # An empty field means the default for a new server - the unprivileged login user. An
    # existing server always posts its own value back, so editing never flips it by itself.
    ssh_user = form.get("ssh_user", "").strip() or remote_cmd.HELPER_USER
    source = (form.get("player_source", "") or "").strip()
    if source and source not in limits.player_sources:
        errors.append(Message("form.bad_player_source"))
        source = ""

    if not name:
        errors.append(Message("form.need_name"))
    if not HOST_RE.match(host):
        errors.append(Message("form.bad_host"))
    if not USER_RE.match(ssh_user):
        errors.append(Message("form.bad_ssh_user"))

    return (
        {
            "name": name,
            "host": host,
            "ssh_user": ssh_user,
            "ssh_port": _port_field(form.get("ssh_port"), 22, 1, Message("form.bad_ssh_port"), errors),
            "service": _service_field(form.get("service"), errors),
            "game_port": form.get("game_port", "").strip()[:GAME_PORT_MAX],
            "notes": form.get("notes", "").strip()[:NOTES_MAX],
            "config_path": _config_folder(form.get("config_path"), clean_path, errors),
            "config_files": _config_files(
                form.get("config_files"), clean_path, limits.config_files_max, errors),
            "backup_paths": _backup_paths(
                form.get("backup_paths"), clean_path, limits.backup_paths_max, errors),
            "log_path": _log_path(form.get("log_path"), errors),
            "query_port": _port_field(
                form.get("query_port"), 0, 0,
                Message("form.bad_query_port"), errors,
            ),
            "player_source": source,
            "max_players": _count_field(form.get("max_players"), errors),
            "join_re": _pattern(form.get("join_re"), "pattern.join", limits.re_max_len, errors),
            "leave_re": _pattern(form.get("leave_re"), "pattern.leave", limits.re_max_len, errors),
            "error_re": _pattern(form.get("error_re"), "pattern.error", limits.re_max_len, errors),
            **_http_fields(form, limits, errors),
        },
        errors,
    )
