"""Validacao do formulario de servidor: o que chega da tela vira cadastro, ou erro.

Um lugar so para uma razao pratica: quase todo campo daqui acaba dentro de um comando
remoto (a unidade do systemd, a pasta do save, o regex do log) ou de uma chamada HTTP
com credencial. Espalhar essa conferencia pelas rotas e como se perde uma delas.

A convencao das funcoes abaixo e sempre a mesma: devolvem o valor JA limpo e anotam o
problema na lista `errors` que recebem — nao levantam. E o que permite a tela mostrar
TODOS os erros do formulario de uma vez, em vez de um por vez a cada envio.

Campo vazio quase nunca e erro: significa "nao uso esse recurso". Quem exige
preenchimento diz isso explicitamente (nome, host, usuario e servico).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from gamepanel.i18n import Message
from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.http_probe import URL_RE
from gamepanel.runtime.log_probe import compile_pattern, valid_log_path

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
JSON_PATH_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{0,120}$")

MAX_PORT = 65535
NOTES_MAX = 2000
GAME_PORT_MAX = 120
CONFIG_PATH_MAX = 400
HTTP_AUTH_MAX = 300

# Qualquer coisa com `.get(nome, padrao)` serve: o formulario do Flask, ou um dict no teste.
Form = Mapping[str, Any]
# Caminho absoluto ja normalizado; levanta ValueError no que nao presta.
CleanPath = Callable[[str], str]


class FormLimits(NamedTuple):
    """Os tetos que valem para este cadastro. Vem de fora porque sao configuracao."""

    config_files_max: int
    backup_paths_max: int
    http_url_max: int
    http_body_max: int
    http_path_max: int
    re_max_len: int
    player_sources: tuple[str, ...]


def _field(form: Form, name: str, cap: int) -> str:
    """Um campo de texto do formulario: sem espacos nas pontas e com teto de tamanho."""
    return (form.get(name, "") or "").strip()[:cap]


def _port_field(value: str | None, default: int, minimum: int, error: Message,
           errors: list[str]) -> int:
    """Le uma porta do formulario; `minimo` 0 permite desligar o recurso."""
    raw = (value or "").strip() or str(default)
    if raw.isdigit() and minimum <= int(raw) <= MAX_PORT:
        return int(raw)
    errors.append(error)
    return default


def _service_field(value: str | None, errors: list[str]) -> str:
    service = (value or "").strip()
    if service and not service.endswith(".service"):
        service = f"{service}.service"  # o sufixo e o de sempre: nao vale incomodar
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
    """Le a lista de arquivos de configuracao (um caminho absoluto por linha)."""
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
    """Le a lista do que entra no backup (um caminho absoluto por linha).

    Vazio e a resposta certa para a maioria dos cadastros: sem nada aqui o backup leva a
    pasta de configuracao do servidor, que e onde o save costuma morar.
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
    """URL valida, ou string vazia com o erro anotado. Vazio nao e erro: e "nao usa"."""
    if raw and not URL_RE.match(raw):
        errors.append(error)
        return ""
    return raw


def _json_or_error(raw: str, label: str, errors: list[str]) -> str:
    """Corpo JSON valido, ou string vazia com o erro anotado."""
    if not raw:
        return ""
    try:
        json.loads(raw)
    except ValueError as exc:
        errors.append(Message("form.bad_json", label=label, reason=exc))
        return ""
    return raw


def _json_paths(form: Form, cap: int, errors: list[str]) -> dict:
    """Os tres caminhos de navegacao na resposta (lista, contagem, token)."""
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
    """Le e confere os campos da chamada HTTP (URL, autenticacao, corpo, caminhos)."""
    url = _url_or_error(
        _field(form, "http_url", limits.http_url_max),
        Message("form.bad_api_url"), errors,
    )
    body = _json_or_error(
        _field(form, "http_body", limits.http_body_max),
        Message("form.request_body"), errors,
    )
    paths = _json_paths(form, limits.http_path_max, errors)

    # Login automatico: os tres campos andam juntos. Preencher so parte deles quase
    # sempre e engano, e falhar aqui e melhor do que descobrir na hora da consulta.
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
        # Guarda a senha da API como ela precisa ser mandada. O banco do painel ja da
        # acesso de root aos containers, entao isso nao amplia o estrago de um vazamento
        # — mas trate o arquivo panel.db como segredo.
        "http_auth": _field(form, "http_auth", HTTP_AUTH_MAX),
        "http_body": body,
        **paths,
    }


def _log_path(value: str | None, errors: list[str]) -> str:
    try:
        return valid_log_path(value)
    except ValueError as exc:
        errors.append(str(exc).capitalize())
        return ""


def _pattern(value: str | None, label: str, cap: int, errors: list[str]) -> str:
    """Guarda o regex so depois de conferir que ele compila."""
    text = (value or "").strip()[:cap]
    if not text:
        return ""
    try:
        compile_pattern(text, label)
    except QueryError as exc:
        errors.append(str(exc))
        return ""
    return text


def form_server(form: Form, clean_path: CleanPath,
                limits: FormLimits) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = form.get("name", "").strip()
    host = form.get("host", "").strip()
    ssh_user = form.get("ssh_user", "").strip() or "root"
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
            "join_re": _pattern(form.get("join_re"), "pattern.join", limits.re_max_len, errors),
            "leave_re": _pattern(form.get("leave_re"), "pattern.leave", limits.re_max_len, errors),
            "error_re": _pattern(form.get("error_re"), "pattern.error", limits.re_max_len, errors),
            **_http_fields(form, limits, errors),
        },
        errors,
    )
