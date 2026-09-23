"""API HTTP do broker: so traduz HTTP <-> `Servico`. Sem regra de negocio aqui.

Nao existe endpoint de comando livre, de porta livre, de IP livre nem de CTID livre. O
painel manda `jogo` (chave do catalogo) e `nome`; o resto o broker decide.
"""
from __future__ import annotations

import hmac
import logging
import re

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from gamebroker import version
from gamebroker.domain.exceptions import Refusal, ValidationError
from gamebroker.services.instance_service import Service

TOKEN_MINIMO = 32
CORPO_MAX = 64 * 1024
_OPERACAO_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
ACTOR_HEADER = "X-Actor"

log = logging.getLogger("broker")


def create_app(service: Service, token: str, allowed_ips: tuple[str, ...] = ()) -> Flask:
    if len(token) < TOKEN_MINIMO:
        raise ValueError(f"o token do broker precisa ter ao menos {TOKEN_MINIMO} caracteres")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = CORPO_MAX

    @app.before_request
    def authenticate():
        if allowed_ips and request.remote_addr not in allowed_ips:
            return _error("origem nao permitida", "origem", 403)
        sent_value = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        # compare_digest: tempo constante, para o token nao ser descoberto byte a byte.
        if not hmac.compare_digest(sent_value.encode(), expected.encode()):
            return _error("token ausente ou invalido", "nao-autenticado", 401)
        return None

    @app.errorhandler(Refusal)
    def on_refusal(error: Refusal):
        return _error(error.message, error.code, error.http)

    @app.errorhandler(HTTPException)
    def on_http_error(error: HTTPException):
        # 404, 405, 413...: sao do Flask, nao do broker. Sem este handler o catch-all
        # abaixo os transformaria em 500 e esconderia rota errada como "erro interno".
        return _error(error.name.lower(), "http", error.code or 500)

    @app.errorhandler(Exception)
    def on_unexpected(error: Exception):
        # Detalhe so no log do broker: a mensagem do erro pode citar caminho ou endereco interno.
        log.exception("erro interno", exc_info=error)
        return _error("erro interno do broker", "interno", 500)

    def actor() -> str:
        return request.headers.get(ACTOR_HEADER, "")

    @app.get("/v1/health")
    def health():
        # A versao vem daqui, e nao do `Service`: ela e identidade do PROCESSO que
        # respondeu, nao um fato sobre Proxmox ou OPNsense. O painel usa para dizer se o
        # broker que ele alcanca e o que o ultimo deploy publicou.
        return jsonify({**service.health(), **version.BUILD.as_public()})

    @app.get("/v1/catalog")
    def catalog():
        return jsonify([j.as_public() for j in service.catalog.list_all()])

    @app.post("/v1/catalog")
    def catalog_add():
        return jsonify(service.add_game(_body(), actor())), 201

    @app.get("/v1/instances")
    def instances():
        return jsonify(service.instances())

    @app.post("/v1/instances")
    def instances_create():
        body = _body()
        response = service.create(str(body.get("game", "")), body.get("name", ""), actor())
        return jsonify(response), 202

    @app.get("/v1/operations/<op_id>")
    def operation(op_id: str):
        if not _OPERACAO_RE.fullmatch(op_id):
            raise ValidationError("operacao", "identificador invalido")
        return jsonify(service.operation(op_id))

    @app.post("/v1/instances/<int:instance_id>/deactivate")
    def instances_deactivate(instance_id: int):
        return jsonify(service.deactivate(instance_id, actor()))

    @app.delete("/v1/instances/<int:instance_id>")
    def instances_remove(instance_id: int):
        body = _body()
        db_only = body.get("db_only", False)
        if not isinstance(db_only, bool):
            raise ValidationError("db_only", "deve ser verdadeiro ou falso")
        return jsonify(service.remove(instance_id, body.get("confirmation"), actor(), db_only))

    return app


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("corpo", "esperado um objeto JSON")
    return data


def _error(message: str, code: str, http: int):
    return jsonify({"erro": message, "codigo": code}), http
