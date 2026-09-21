"""Recusas que o broker sabe explicar. Todo o resto e erro interno (500, sem detalhe)."""
from __future__ import annotations


class Recusa(Exception):
    """Pedido que o broker entendeu e nao vai atender. A mensagem e para o usuario."""

    http = 400
    codigo = "pedido-invalido"

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class ErroDeValidacao(Recusa):
    codigo = "validacao"

    def __init__(self, campo: str, mensagem: str):
        super().__init__(f"{campo}: {mensagem}")
        self.campo = campo


class NaoEncontrado(Recusa):
    http = 404
    codigo = "nao-encontrado"


class Conflito(Recusa):
    http = 409
    codigo = "conflito"


class SemRecurso(Conflito):
    """Faixa de CTID/IP esgotada ou porta ocupada."""

    codigo = "sem-recurso"


class CotaExcedida(Recusa):
    http = 429
    codigo = "cota"
