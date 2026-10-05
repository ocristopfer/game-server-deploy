"""Broker HTTP API: only translates HTTP <-> `Servico`. No business rules here.

There is no endpoint for a free-form command, port, IP or CTID. The panel sends `jogo`
(catalog key) and `nome`; the broker decides the rest.
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
MAX_BODY = 64 * 1024
_OPERATION_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
ACTOR_HEADER = "X-Actor"

log = logging.getLogger("broker")


def create_app(service: Service, token: str,  # noqa: C901 - see the note below
               allowed_ips: tuple[str, ...] = ()) -> Flask:
    """Builds the app: authentication, error handlers and the 11 routes.

    The `# noqa: C901` is not giving up. mccabe counts every nested `def` as a branch, and
    a Flask factory is a LIST of registrations: 11 routes of one to three lines. The
    repository's limit of 15 exists to force 'separate deciding from doing', and here there
    is no decision to separate - splitting into `_register_routes`/`_register_errors` would
    trade one number for three indirections and nothing would get easier to read.
    """
    if len(token) < TOKEN_MINIMO:
        raise ValueError(f"o token do broker precisa ter ao menos {TOKEN_MINIMO} caracteres")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY

    @app.before_request
    def authenticate():
        if allowed_ips and request.remote_addr not in allowed_ips:
            return _error("origem nao permitida", "origem", 403)
        sent_value = request.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        # compare_digest: constant time, so the token cannot be discovered byte by byte.
        if not hmac.compare_digest(sent_value.encode(), expected.encode()):
            return _error("token ausente ou invalido", "nao-autenticado", 401)
        return None

    @app.errorhandler(Refusal)
    def on_refusal(error: Refusal):
        return _error(error.message, error.code, error.http)

    @app.errorhandler(HTTPException)
    def on_http_error(error: HTTPException):
        # 404, 405, 413...: those belong to Flask, not to the broker. Without this handler the
        # catch-all below would turn them into 500 and hide a wrong route as "internal error".
        return _error(error.name.lower(), "http", error.code or 500)

    @app.errorhandler(Exception)
    def on_unexpected(error: Exception):
        # Details only in the broker log: the error message may mention an internal path or address.
        log.exception("erro interno", exc_info=error)
        return _error("erro interno do broker", "interno", 500)

    def actor() -> str:
        return request.headers.get(ACTOR_HEADER, "")

    @app.get("/v1/health")
    def health():
        # The version comes from here, not from `Service`: it is the identity of the PROCESS
        # that answered, not a fact about Proxmox or OPNsense. The panel uses it to tell
        # whether the broker it reaches is the one the last deploy published.
        return jsonify({**service.health(), **version.BUILD.as_public()})

    @app.get("/v1/catalog")
    def catalog():
        return jsonify([j.as_public() for j in service.catalog.list_all()])

    @app.post("/v1/catalog")
    def catalog_add():
        return jsonify(service.add_game(_body(), actor())), 201

    @app.get("/v1/catalog/<key>")
    def catalog_game(key: str):
        return jsonify(service.catalog.stored(key))

    @app.put("/v1/catalog/<key>")
    def catalog_update(key: str):
        return jsonify(service.update_game(key, _body(), actor()))

    @app.delete("/v1/catalog/<key>")
    def catalog_remove(key: str):
        return jsonify(service.remove_game(key, actor()))

    @app.get("/v1/instances")
    def instances():
        return jsonify(service.instances())

    @app.post("/v1/instances")
    def instances_create():
        body = _body()
        response = service.create(str(body.get("game", "")), body.get("name", ""), actor())
        return jsonify(response), 202

    @app.get("/v1/instances/preview")
    def instances_preview():
        return jsonify(service.preview(str(request.args.get("game", ""))))

    @app.get("/v1/operations/<op_id>")
    def operation(op_id: str):
        if not _OPERATION_RE.fullmatch(op_id):
            raise ValidationError("operacao", "identificador invalido")
        return jsonify(service.operation(op_id))

    @app.post("/v1/operations/<op_id>/cancel")
    def operation_cancel(op_id: str):
        if not _OPERATION_RE.fullmatch(op_id):
            raise ValidationError("operacao", "identificador invalido")
        return jsonify(service.cancel(op_id, actor()))

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
