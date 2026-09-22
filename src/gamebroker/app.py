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

from gamebroker.domain.exceptions import Refusal, ValidationError
from gamebroker.services.instance_service import Service

TOKEN_MINIMO = 32
CORPO_MAX = 64 * 1024
_OPERACAO_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
CABECALHO_ATOR = "X-Ator"

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
        enviado = request.headers.get("Authorization", "")
        esperado = f"Bearer {token}"
        # compare_digest: tempo constante, para o token nao ser descoberto byte a byte.
        if not hmac.compare_digest(enviado.encode(), esperado.encode()):
            return _error("token ausente ou invalido", "nao-autenticado", 401)
        return None

    @app.errorhandler(Refusal)
    def on_refusal(erro: Refusal):
        return _error(erro.message, erro.code, erro.http)

    @app.errorhandler(HTTPException)
    def on_http_error(erro: HTTPException):
        # 404, 405, 413...: sao do Flask, nao do broker. Sem este handler o catch-all
        # abaixo os transformaria em 500 e esconderia rota errada como "erro interno".
        return _error(erro.name.lower(), "http", erro.code or 500)

    @app.errorhandler(Exception)
    def on_unexpected(erro: Exception):
        # Detalhe so no log do broker: a mensagem do erro pode citar caminho ou endereco interno.
        log.exception("erro interno", exc_info=erro)
        return _error("erro interno do broker", "interno", 500)

    def actor() -> str:
        return request.headers.get(CABECALHO_ATOR, "")

    @app.get("/v1/saude")
    def health():
        return jsonify(service.health())

    @app.get("/v1/catalogo")
    def catalog():
        return jsonify([j.as_public() for j in service.catalog.list_all()])

    @app.post("/v1/catalogo")
    def catalog_add():
        return jsonify(service.add_game(_body(), actor())), 201

    @app.get("/v1/instancias")
    def instances():
        return jsonify(service.instances())

    @app.post("/v1/instancias")
    def instances_create():
        body = _body()
        resposta = service.create(str(body.get("jogo", "")), body.get("nome", ""), actor())
        return jsonify(resposta), 202

    @app.get("/v1/operacoes/<op_id>")
    def operation(op_id: str):
        if not _OPERACAO_RE.fullmatch(op_id):
            raise ValidationError("operacao", "identificador invalido")
        return jsonify(service.operation(op_id))

    @app.post("/v1/instancias/<int:instance_id>/desativar")
    def instances_deactivate(instance_id: int):
        return jsonify(service.deactivate(instance_id, actor()))

    @app.delete("/v1/instancias/<int:instance_id>")
    def instances_remove(instance_id: int):
        body = _body()
        db_only = body.get("somente_banco", False)
        if not isinstance(db_only, bool):
            raise ValidationError("somente_banco", "deve ser verdadeiro ou falso")
        return jsonify(service.remove(instance_id, body.get("confirma"), actor(), db_only))

    return app


def _body() -> dict:
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        raise ValidationError("corpo", "esperado um objeto JSON")
    return dados


def _error(message: str, code: str, http: int):
    return jsonify({"erro": message, "codigo": code}), http
