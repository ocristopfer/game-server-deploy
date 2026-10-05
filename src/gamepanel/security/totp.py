#!/usr/bin/env python3
"""Second login factor: TOTP (RFC 6238) and recovery codes, stdlib only.

Pure on purpose (no Flask, no database), like `navigation.py`: `app.py` stores the secret and
decides when to ask for the code; only the math lives here. Compatible with Google
Authenticator, Authy, Microsoft Authenticator, 1Password, Bitwarden and the like (SHA-1, 6
digits, 30 s).

Two decisions worth a comment:

- **A used code is not valid again.** `verify` only accepts a step GREATER than the last one
  used: someone who peeked at the code over a shoulder (or in a proxy's trail) cannot log in
  with it during the next 30 s.
- **A +-1 step window** (90 s in total) for a phone clock that is slightly off. It is what the
  apps tolerate; a wider window only raises the odds of a lucky guess.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1
SECRET_BYTES = 20          # 160 bits, the SHA-1 size (RFC 4226)
RECOVERY_CODES = 8

_SIX_DIGITS = re.compile(r"\d{6}")
_RECOVERY_CODE = re.compile(r"[0-9a-f]{10}")


def new_secret() -> str:
    """A new unpadded base32 secret (32 characters): what gets typed into the app."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    clean = re.sub(r"[\s-]", "", secret).upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def code(secret: str, step: int) -> str:
    """The 6-digit code for a 30 s step (RFC 4226 HOTP with the step as the counter)."""
    # SHA-1 is required by RFC 6238/4226 (HOTP/TOTP), not our choice - changing the hash
    # would break compatibility with every authenticator app in existence.
    mac = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), hashlib.sha1).digest()  # NOSONAR
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def step_of(now: float) -> int:
    return int(now // STEP_SECONDS)


def verify(secret: str, entered: str, now: float, last_step: int = 0) -> int | None:
    """The step that `entered` confirms, or None. Never returns a step <= `last_step`."""
    clean = re.sub(r"[\s-]", "", entered or "")
    if not _SIX_DIGITS.fullmatch(clean):
        return None
    current = step_of(now)
    found: int | None = None
    # Tries all three steps WITHOUT stopping at the first match: the time taken does not tell which.
    for step in range(current - WINDOW, current + WINDOW + 1):
        matches = hmac.compare_digest(code(secret, step), clean)
        if matches and step > last_step and found is None:
            found = step
    return found


def uri(secret: str, username: str, issuer: str = "Painel de Jogos") -> str:
    """The otpauth:// address the app opens (on a phone, tapping it registers right away)."""
    label = quote(f"{issuer}:{username}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def group(secret: str, size: int = 4) -> str:
    """`ABCD EFGH ...`: easier to read and to type. The app ignores the spaces."""
    return " ".join(secret[i:i + size] for i in range(0, len(secret), size))


# ------------------------------------------------------------ recovery codes

def _normalize(text: str) -> str:
    return re.sub(r"[\s-]", "", text or "").lower()


def looks_like_recovery_code(entered: str) -> bool:
    return bool(_RECOVERY_CODE.fullmatch(_normalize(entered)))


def new_recovery_codes(count: int = RECOVERY_CODES) -> list[str]:
    """`abcde-12345`: 40 bits each. Single use, for someone who lost their phone."""
    codes: list[str] = []
    while len(codes) < count:
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(recovery_code: str) -> str:
    """Only the hash goes to the database: whoever reads the file gets no usable codes."""
    return hashlib.sha256(_normalize(recovery_code).encode()).hexdigest()


def consume(entered: str, hashes: list[str]) -> list[str] | None:
    """The hashes left after spending `entered`, or None if it is not valid."""
    if not looks_like_recovery_code(entered):
        return None
    target = hash_recovery_code(entered)
    found = None
    for h in hashes:
        if hmac.compare_digest(h, target):
            found = h
    if found is None:
        return None
    remaining = list(hashes)
    remaining.remove(found)
    return remaining
