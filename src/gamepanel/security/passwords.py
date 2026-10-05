"""Password hashing and verification. Stdlib only, like the rest of `security/`.

`scrypt` and not PBKDF2 or bcrypt: it is what the stdlib offers with a MEMORY cost, and memory
cost is what makes a GPU attack expensive. Production has no pip (see CLAUDE.md), so `argon2`
is out of reach - and switching algorithms later does not invalidate stored passwords,
because the format carries the parameters.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from gamepanel.i18n import Message

# Stored format is `scrypt$N$r$p$salt$digest`. The parameters travel WITH the hash on
# purpose - raising the cost in the future does not invalidate passwords already stored,
# because each one is checked with the parameters it was created with.
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
    """Never raises: a corrupted hash in the database is "wrong password", not a 500.

    The final comparison is `compare_digest` - constant time. A `==` here would leak, through
    the response time, how many leading bytes match.
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
    """Returns the error message; an empty string when the password is acceptable.

    The message is an `i18n.Message` (which IS a `str`), not fixed text: these two used to
    show up in Portuguese on the English screen too, because the raw text is not a catalog
    key and the `translate` cascade returned it whole.
    """
    if len(new) < MIN_LENGTH:
        return Message("flash.password_too_short", n=MIN_LENGTH)
    if new != confirm:
        return Message("flash.password_mismatch")
    return ""
