"""Hash e conferencia de senha. So stdlib, como o resto de `security/`.

`scrypt` e nao PBKDF2 nem bcrypt: e o que a stdlib oferece com custo de MEMORIA, e custo
de memoria e o que encarece o ataque em GPU. Producao nao tem pip (ver CLAUDE.md), entao
`argon2` esta fora de alcance — e trocar de algoritmo depois nao invalida as senhas
guardadas, porque o formato carrega os parametros.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from gamepanel.i18n import Message

# Formato guardado: `scrypt$N$r$p$salt$digest`. Os parametros vao JUNTO com o hash de
# proposito — subir o custo no futuro nao invalida as senhas ja gravadas, porque cada
# uma e conferida com os parametros com que foi criada.
ALGORITHM = "scrypt"
COST_N = 2 ** 14
BLOCK_R = 8
PARALLEL_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

MIN_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=COST_N, r=BLOCK_R,
                            p=PARALLEL_P, dklen=KEY_BYTES)
    return f"{ALGORITHM}${COST_N}${BLOCK_R}${PARALLEL_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Nunca levanta: um hash corrompido no banco e "senha errada", nao um 500.

    A comparacao final e `compare_digest` — tempo constante. Um `==` aqui vazaria, pelo
    tempo de resposta, quantos bytes do inicio batem.
    """
    try:
        algorithm, cost, block, parallel, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(cost),
            r=int(block),
            p=int(parallel),
            dklen=len(digest_hex) // 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_password(new: str, confirm: str) -> str:
    """Devolve a mensagem de erro; string vazia quando a senha serve.

    A mensagem e uma `i18n.Message` (que E uma `str`), e nao texto fixo: estas duas
    apareciam em portugues tambem na tela em ingles, porque o texto cru nao e chave de
    catalogo nenhuma e a cascata do `translate` o devolvia inteiro.
    """
    if len(new) < MIN_LENGTH:
        return Message("flash.password_too_short", n=MIN_LENGTH)
    if new != confirm:
        return Message("flash.password_mismatch")
    return ""
