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

from gamepanel.runtime.a2s import QueryError
from gamepanel.runtime.http_probe import URL_RE
from gamepanel.runtime.log_probe import compile_pattern, log_path_valido

UNIT_RE = re.compile(r"^[A-Za-z0-9@._-]{1,80}\.service$")
HOST_RE = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
CAMINHO_JSON_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{0,120}$")

PORTA_MAX = 65535
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


def _campo(form: Form, nome: str, teto: int) -> str:
    """Um campo de texto do formulario: sem espacos nas pontas e com teto de tamanho."""
    return (form.get(nome, "") or "").strip()[:teto]


def _porta(valor: str | None, padrao: int, minimo: int, erro: str, errors: list[str]) -> int:
    """Le uma porta do formulario; `minimo` 0 permite desligar o recurso."""
    bruto = (valor or "").strip() or str(padrao)
    if bruto.isdigit() and minimo <= int(bruto) <= PORTA_MAX:
        return int(bruto)
    errors.append(erro)
    return padrao


def _servico(valor: str | None, errors: list[str]) -> str:
    service = (valor or "").strip()
    if service and not service.endswith(".service"):
        service = f"{service}.service"  # o sufixo e o de sempre: nao vale incomodar
    if not UNIT_RE.match(service):
        errors.append("Servico invalido (ex.: dragonwilds.service).")
    return service


def _pasta_config(valor: str | None, clean_path: CleanPath, errors: list[str]) -> str:
    caminho = (valor or "").strip()[:CONFIG_PATH_MAX]
    if not caminho:
        return ""
    try:
        return clean_path(caminho)
    except ValueError as exc:
        errors.append(f"Pasta de configuracao invalida: {exc}")
        return ""


def _arquivos_config(valor: str | None, clean_path: CleanPath, maximo: int,
                     errors: list[str]) -> str:
    """Le a lista de arquivos de configuracao (um caminho absoluto por linha)."""
    caminhos: list[str] = []
    for linha in (valor or "").replace(",", "\n").splitlines():
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            limpo = clean_path(bruto)
        except ValueError as exc:
            errors.append(f"Arquivo de configuracao invalido ({bruto}): {exc}")
            continue
        if limpo not in caminhos:
            caminhos.append(limpo)
    if len(caminhos) > maximo:
        errors.append(f"No maximo {maximo} arquivos de configuracao por servidor.")
        caminhos = caminhos[:maximo]
    return "\n".join(caminhos)


def _caminhos_backup(valor: str | None, clean_path: CleanPath, maximo: int,
                     errors: list[str]) -> str:
    """Le a lista do que entra no backup (um caminho absoluto por linha).

    Vazio e a resposta certa para a maioria dos cadastros: sem nada aqui o backup leva a
    pasta de configuracao do servidor, que e onde o save costuma morar.
    """
    caminhos: list[str] = []
    for linha in (valor or "").replace(",", "\n").splitlines():
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            limpo = clean_path(bruto)
        except ValueError as exc:
            errors.append(f"Caminho de backup invalido ({bruto}): {exc}")
            continue
        if limpo == "/":
            errors.append("Backup da raiz nao: aponte a pasta do save ou da configuracao.")
            continue
        if limpo not in caminhos:
            caminhos.append(limpo)
    if len(caminhos) > maximo:
        errors.append(f"No maximo {maximo} caminhos de backup por servidor.")
        caminhos = caminhos[:maximo]
    return "\n".join(caminhos)


def _url_ou_erro(bruto: str, erro: str, errors: list[str]) -> str:
    """URL valida, ou string vazia com o erro anotado. Vazio nao e erro: e "nao usa"."""
    if bruto and not URL_RE.match(bruto):
        errors.append(erro)
        return ""
    return bruto


def _json_ou_erro(bruto: str, rotulo: str, errors: list[str]) -> str:
    """Corpo JSON valido, ou string vazia com o erro anotado."""
    if not bruto:
        return ""
    try:
        json.loads(bruto)
    except ValueError as exc:
        errors.append(f"{rotulo} nao e JSON valido: {exc}.")
        return ""
    return bruto


def _caminhos_json(form: Form, teto: int, errors: list[str]) -> dict:
    """Os tres caminhos de navegacao na resposta (lista, contagem, token)."""
    caminhos = {}
    for campo, rotulo in (("http_list_path", "lista"), ("http_count_path", "contagem"),
                          ("http_token_path", "token")):
        texto = _campo(form, campo, teto)
        if texto and not CAMINHO_JSON_RE.match(texto):
            errors.append(f"Caminho da {rotulo} invalido (use algo como 'data.players').")
            texto = ""
        caminhos[campo] = texto
    return caminhos


def _campos_http(form: Form, limites: FormLimits, errors: list[str]) -> dict:
    """Le e confere os campos da chamada HTTP (URL, autenticacao, corpo, caminhos)."""
    url = _url_ou_erro(
        _campo(form, "http_url", limites.http_url_max),
        "URL da API invalida (ex.: http://127.0.0.1:8212/v1/api/players).", errors,
    )
    corpo = _json_ou_erro(
        _campo(form, "http_body", limites.http_body_max), "Corpo da requisicao", errors,
    )
    caminhos = _caminhos_json(form, limites.http_path_max, errors)

    # Login automatico: os tres campos andam juntos. Preencher so parte deles quase
    # sempre e engano, e falhar aqui e melhor do que descobrir na hora da consulta.
    login_url = _url_ou_erro(
        _campo(form, "http_login_url", limites.http_url_max),
        "URL de login invalida (ex.: https://127.0.0.1:7787/api/v1).", errors,
    )
    login_body = _json_ou_erro(
        _campo(form, "http_login_body", limites.http_body_max), "Corpo do login", errors,
    )
    if (login_url or login_body) and not caminhos["http_token_path"]:
        errors.append("Para o login automatico, informe tambem o caminho do token "
                      "(ex.: data.authenticationToken).")

    return {
        "http_url": url,
        "http_login_url": login_url,
        "http_login_body": login_body,
        # Guarda a senha da API como ela precisa ser mandada. O banco do painel ja da
        # acesso de root aos containers, entao isso nao amplia o estrago de um vazamento
        # — mas trate o arquivo panel.db como segredo.
        "http_auth": _campo(form, "http_auth", HTTP_AUTH_MAX),
        "http_body": corpo,
        **caminhos,
    }


def _caminho_log(valor: str | None, errors: list[str]) -> str:
    try:
        return log_path_valido(valor)
    except ValueError as exc:
        errors.append(str(exc).capitalize())
        return ""


def _padrao(valor: str | None, rotulo: str, teto: int, errors: list[str]) -> str:
    """Guarda o regex so depois de conferir que ele compila."""
    texto = (valor or "").strip()[:teto]
    if not texto:
        return ""
    try:
        compile_pattern(texto, rotulo)
    except QueryError as exc:
        errors.append(str(exc))
        return ""
    return texto


def form_server(form: Form, clean_path: CleanPath,
                limites: FormLimits) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = form.get("name", "").strip()
    host = form.get("host", "").strip()
    ssh_user = form.get("ssh_user", "").strip() or "root"
    origem = (form.get("player_source", "") or "").strip()
    if origem and origem not in limites.player_sources:
        errors.append("Forma de contar jogadores invalida.")
        origem = ""

    if not name:
        errors.append("Informe um nome.")
    if not HOST_RE.match(host):
        errors.append("Host invalido (use o IP ou hostname do container).")
    if not USER_RE.match(ssh_user):
        errors.append("Usuario SSH invalido.")

    return (
        {
            "name": name,
            "host": host,
            "ssh_user": ssh_user,
            "ssh_port": _porta(form.get("ssh_port"), 22, 1, "Porta SSH invalida.", errors),
            "service": _servico(form.get("service"), errors),
            "game_port": form.get("game_port", "").strip()[:GAME_PORT_MAX],
            "notes": form.get("notes", "").strip()[:NOTES_MAX],
            "config_path": _pasta_config(form.get("config_path"), clean_path, errors),
            "config_files": _arquivos_config(
                form.get("config_files"), clean_path, limites.config_files_max, errors),
            "backup_paths": _caminhos_backup(
                form.get("backup_paths"), clean_path, limites.backup_paths_max, errors),
            "log_path": _caminho_log(form.get("log_path"), errors),
            "query_port": _porta(
                form.get("query_port"), 0, 0,
                "Porta de consulta invalida (use 0 para desligar).", errors,
            ),
            "player_source": origem,
            "join_re": _padrao(form.get("join_re"), "entrada", limites.re_max_len, errors),
            "leave_re": _padrao(form.get("leave_re"), "saida", limites.re_max_len, errors),
            "error_re": _padrao(form.get("error_re"), "erro", limites.re_max_len, errors),
            **_campos_http(form, limites, errors),
        },
        errors,
    )
