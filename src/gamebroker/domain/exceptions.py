"""Recusas que o broker sabe explicar. Todo o resto e erro interno (500, sem detalhe)."""
from __future__ import annotations


class Refusal(Exception):
    """Pedido que o broker entendeu e nao vai atender. A mensagem e para o usuario."""

    http = 400
    code = "pedido-invalido"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(Refusal):
    code = "validacao"

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field


class NotFound(Refusal):
    http = 404
    code = "nao-encontrado"


class Conflict(Refusal):
    http = 409
    code = "conflito"


class OutOfResources(Conflict):
    """Faixa de CTID/IP esgotada ou porta ocupada."""

    code = "sem-recurso"


class QuotaExceeded(Refusal):
    http = 429
    code = "cota"
