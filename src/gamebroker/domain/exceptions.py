"""Refusals the broker knows how to explain. Everything else is an internal error (500, no details)."""
from __future__ import annotations


class Refusal(Exception):
    """A request the broker understood and will not fulfill. The message is meant for the user."""

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
    """CTID/IP range exhausted or port taken."""

    code = "sem-recurso"


class QuotaExceeded(Refusal):
    http = 429
    code = "cota"
