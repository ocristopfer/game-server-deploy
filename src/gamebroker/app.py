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

from gamebroker.domain.exceptions import ErroDeValidacao, Recusa
from gamebroker.services.instance_service import Servico

TOKEN_MINIMO = 32
CORPO_MAX = 64 * 1024
_OPERACAO_RE = re.compile(r"[0-9a-f]{32}", re.ASCII)
CABECALHO_ATOR = "X-Ator"

log = logging.getLogger("broker")


def criar_app(servico: Servico, token: str, ips_permitidos: tuple[str, ...] = ()) -> Flask:
    if len(token) < TOKEN_MINIMO:
        raise ValueError(f"o token do broker precisa ter ao menos {TOKEN_MINIMO} caracteres")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = CORPO_MAX

    @app.before_request
    def autenticar():
        if ips_permitidos and request.remote_addr not in ips_permitidos:
            return _erro("origem nao permitida", "origem", 403)
        enviado = request.headers.get("Authorization", "")
        esperado = f"Bearer {token}"
        # compare_digest: tempo constante, para o token nao ser descoberto byte a byte.
        if not hmac.compare_digest(enviado.encode(), esperado.encode()):
            return _erro("token ausente ou invalido", "nao-autenticado", 401)
        return None

    @app.errorhandler(Recusa)
    def recusa(erro: Recusa):
        return _erro(erro.mensagem, erro.codigo, erro.http)

    @app.errorhandler(HTTPException)
    def erro_http(erro: HTTPException):
        # 404, 405, 413...: sao do Flask, nao do broker. Sem este handler o catch-all
        # abaixo os transformaria em 500 e esconderia rota errada como "erro interno".
        return _erro(erro.name.lower(), "http", erro.code or 500)

    @app.errorhandler(Exception)
    def inesperado(erro: Exception):
        # Detalhe so no log do broker: a mensagem do erro pode citar caminho ou endereco interno.
        log.exception("erro interno", exc_info=erro)
        return _erro("erro interno do broker", "interno", 500)

    def ator() -> str:
        return request.headers.get(CABECALHO_ATOR, "")

    @app.get("/v1/saude")
    def saude():
        return jsonify(servico.saude())

    @app.get("/v1/catalogo")
    def catalogo():
        return jsonify([j.as_public() for j in servico.catalogo.list_all()])

    @app.post("/v1/catalogo")
    def catalogo_adicionar():
        return jsonify(servico.adicionar_jogo(_corpo(), ator())), 201

    @app.get("/v1/instancias")
    def instancias():
        return jsonify(servico.instancias())

    @app.post("/v1/instancias")
    def instancias_criar():
        corpo = _corpo()
        resposta = servico.criar(str(corpo.get("jogo", "")), corpo.get("nome", ""), ator())
        return jsonify(resposta), 202

    @app.get("/v1/operacoes/<op_id>")
    def operacao(op_id: str):
        if not _OPERACAO_RE.fullmatch(op_id):
            raise ErroDeValidacao("operacao", "identificador invalido")
        return jsonify(servico.operacao(op_id))

    @app.post("/v1/instancias/<int:instancia_id>/desativar")
    def instancias_desativar(instancia_id: int):
        return jsonify(servico.desativar(instancia_id, ator()))

    @app.delete("/v1/instancias/<int:instancia_id>")
    def instancias_remover(instancia_id: int):
        corpo = _corpo()
        somente_banco = corpo.get("somente_banco", False)
        if not isinstance(somente_banco, bool):
            raise ErroDeValidacao("somente_banco", "deve ser verdadeiro ou falso")
        return jsonify(servico.remover(instancia_id, corpo.get("confirma"), ator(), somente_banco))

    return app


def _corpo() -> dict:
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        raise ErroDeValidacao("corpo", "esperado um objeto JSON")
    return dados


def _erro(mensagem: str, codigo: str, http: int):
    return jsonify({"erro": mensagem, "codigo": codigo}), http
