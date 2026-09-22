#!/usr/bin/env python3
"""Segundo fator do login: TOTP (RFC 6238) e codigos de recuperacao, so com a stdlib.

Puro de proposito (sem Flask, sem banco), como `navigation.py`: o `app.py` guarda o
segredo e decide quando pedir o codigo; aqui so existe a conta. Compativel com Google
Authenticator, Authy, Microsoft Authenticator, 1Password, Bitwarden e afins (SHA-1, 6
digitos, 30 s).

Duas decisoes que valem um comentario:

- **Codigo usado nao vale de novo.** `verify` so aceita um passo MAIOR que o ultimo ja
  usado: quem espiou o codigo por cima do ombro (ou no rastro de um proxy) nao entra com ele
  nos 30 s seguintes.
- **Janela de +-1 passo** (90 s no total) para relogio de celular levemente fora de hora. E o
  mesmo que os aplicativos toleram; uma janela maior so aumenta a chance de acerto no chute.
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
SECRET_BYTES = 20          # 160 bits, o tamanho do SHA-1 (RFC 4226)
RECOVERY_CODES = 8

_SIX_DIGITS = re.compile(r"\d{6}")
_RECOVERY_CODE = re.compile(r"[0-9a-f]{10}")


def new_secret() -> str:
    """Segredo novo em base32 sem preenchimento (32 caracteres): o que o aplicativo digita."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    clean = re.sub(r"[\s-]", "", secret).upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def code(secret: str, step: int) -> str:
    """O codigo de 6 digitos de um passo de 30 s (HOTP de RFC 4226 com o passo como contador)."""
    # SHA-1 e exigido pelo RFC 6238/4226 (HOTP/TOTP), nao escolha nossa - trocar o hash
    # quebraria compatibilidade com todo aplicativo autenticador que existe.
    mac = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), hashlib.sha1).digest()  # NOSONAR
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def step_of(now: float) -> int:
    return int(now // STEP_SECONDS)


def verify(secret: str, entered: str, now: float, last_step: int = 0) -> int | None:
    """O passo que `entered` confirma, ou None. Nunca devolve um passo <= `last_step`."""
    clean = re.sub(r"[\s-]", "", entered or "")
    if not _SIX_DIGITS.fullmatch(clean):
        return None
    current = step_of(now)
    found: int | None = None
    # Testa os tres passos SEM parar no primeiro acerto: o tempo gasto nao conta qual foi.
    for step in range(current - WINDOW, current + WINDOW + 1):
        matches = hmac.compare_digest(code(secret, step), clean)
        if matches and step > last_step and found is None:
            found = step
    return found


def uri(secret: str, username: str, issuer: str = "Painel de Jogos") -> str:
    """O endereco otpauth:// que o aplicativo abre (no celular, tocar nele ja cadastra)."""
    label = quote(f"{issuer}:{username}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def group(secret: str, size: int = 4) -> str:
    """`ABCD EFGH ...`: mais facil de ler e de digitar. O aplicativo ignora os espacos."""
    return " ".join(secret[i:i + size] for i in range(0, len(secret), size))


# ------------------------------------------------------------ codigos de recuperacao

def _normalize(text: str) -> str:
    return re.sub(r"[\s-]", "", text or "").lower()


def looks_like_recovery_code(entered: str) -> bool:
    return bool(_RECOVERY_CODE.fullmatch(_normalize(entered)))


def new_recovery_codes(count: int = RECOVERY_CODES) -> list[str]:
    """`abcde-12345`: 40 bits cada. Servem uma vez, para quem perdeu o celular."""
    codes: list[str] = []
    while len(codes) < count:
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def hash_recovery_code(recovery_code: str) -> str:
    """So o hash vai para o banco: quem ler o arquivo nao sai com codigos utilizaveis."""
    return hashlib.sha256(_normalize(recovery_code).encode()).hexdigest()


def consume(entered: str, hashes: list[str]) -> list[str] | None:
    """Os hashes que sobram depois de gastar `entered`, ou None se ele nao serve."""
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
