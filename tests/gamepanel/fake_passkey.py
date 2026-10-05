"""A fake passkey "device": builds the responses a phone would send.

Signing ECDSA only needs the curve arithmetic, which `security/webauthn.py` already has. It
lives next to `conftest.py` because it is shared by `unit/` (the verification) and
`integration/` (the routes), and each bucket has to run on its own.
"""
from __future__ import annotations

import hashlib
import json
import struct

from gamepanel.security import webauthn as wa

PRIVATE = 0x1B2C3D4E5F60718293A4B5C6D7E8F90112233445566778899AABBCCDDEEFF00
CRED_ID = b"credencial-do-celular"


def cbor(value) -> bytes:
    def head(major: int, arg: int) -> bytes:
        if arg < 24:
            return bytes([major << 5 | arg])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if arg < 1 << (8 * size):
                return bytes([major << 5 | info]) + arg.to_bytes(size, "big")
        raise ValueError(arg)
    if value is None:
        return bytes([0xF6])
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


def public_point(d: int = PRIVATE) -> tuple[int, int]:
    point = wa._affine(wa._mul_add(d, wa.G, 0, wa.G))
    if point is None:
        raise ValueError(d)
    return point


def cose_es256(d: int = PRIVATE) -> bytes:
    x, y = public_point(d)
    return cbor({1: 2, 3: -7, -1: 1, -2: x.to_bytes(32, "big"), -3: y.to_bytes(32, "big")})


def der_int(v: int) -> bytes:
    raw = v.to_bytes((v.bit_length() + 8) // 8, "big")
    return b"\x02" + bytes([len(raw)]) + raw


def sign_es256(message: bytes, d: int = PRIVATE, k: int = 0x7777) -> bytes:
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    r = public_point(k)[0] % wa.N
    s = pow(k, -1, wa.N) * (e + r * d) % wa.N
    body = der_int(r) + der_int(s)
    return b"\x30" + bytes([len(body)]) + body


def auth_data(rp_id: str, flags: int = wa.FLAG_UP | wa.FLAG_UV, count: int = 0,
              key: bytes | None = None, cred_id: bytes = CRED_ID) -> bytes:
    data = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", count)
    if key is not None:
        data += b"\x00" * 16 + struct.pack(">H", len(cred_id)) + cred_id + key
    return data


def client_data(kind: str, challenge: str, origin: str, **extra) -> bytes:
    return json.dumps({"type": kind, "challenge": challenge, "origin": origin, **extra}).encode()


def attestation(rp_id: str, flags: int = wa.FLAG_UP | wa.FLAG_UV | wa.FLAG_AT,
                key: bytes | None = None, cred_id: bytes = CRED_ID) -> bytes:
    data = auth_data(rp_id, flags, key=cose_es256() if key is None else key, cred_id=cred_id)
    return cbor({"fmt": "none", "attStmt": {}, "authData": data})
