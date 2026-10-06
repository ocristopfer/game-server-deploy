"""WebAuthn (passkey): log in with the device's biometrics - stdlib only.

Same reason TOTP and QR are our own code: production only has the stdlib plus apt's Flask, so
there is no `cryptography` or `webauthn` to install. Only the SERVER side lives here, which is
verification: the device generates the key and signs; the panel stores the public key and checks.

What is included, and why:
- **CBOR** (RFC 8949, the subset WebAuthn uses): it is the format of the device's response.
- **ES256** (ECDSA on the P-256 curve, alg -7): Android, iPhone and security keys. The curve
  math is SEC 1's, in Jacobian coordinates (no division on every point addition).
- **RS256** (RSA PKCS#1 v1.5 with SHA-256, alg -257): Windows Hello.
- **Attestation is not checked** (we ask for `attestation: "none"`): it states the device MODEL,
  and the panel has no list of trusted models to compare against - checking without one is theater.

Rules the verification enforces, each one against an attack:
- single-use challenge kept ON THE SERVER (`Challenges`): without it, a captured signature
  would be valid again. The session will not do: the cookie belongs to the client, and an old
  saved cookie would bring back the challenge the following request had already spent;
- exact origin (`GAMEPANEL_WEBAUTHN_ORIGIN`): a fake page requests a signature with ANOTHER
  origin, and the device writes it into the signed clientDataJSON;
- RP ID hash in authenticatorData: the device only signs for the key's domain;
- UP (user present) and UV (verified - the device's biometrics or PIN): without UV, the passkey
  would only be "something you have", and it replaces the password AND the second factor;
- signature counter: a value that does not increase exposes a cloned key (when the device
  counts; a synced passkey always sends 0, and 0 proves nothing).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from typing import Any, NamedTuple

CHALLENGE_BYTES = 32
ALG_ES256 = -7
ALG_RS256 = -257
FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


class WebAuthnError(ValueError):
    """Response rejected. The message is for the log, never for the screen (it does not help an attacker)."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise WebAuthnError("base64url invalido") from exc


def new_challenge() -> str:
    return b64url(secrets.token_bytes(CHALLENGE_BYTES))


class Challenges:
    """Challenges issued and not yet used, in memory (the panel runs with a single worker).

    `take` REMOVES the challenge: a second request with the same response does not find it. The
    cap exists because asking for a login challenge does not require being logged in, and without
    it a loop of requests would fill memory; past the cap, the oldest goes (whoever was in the
    middle of a login tries again). The clock comes in through the constructor for the same reason
    as `Lockout`: `clock=time.monotonic` in the signature would keep the original function, and a
    test that swaps the clock would not reach it.
    """

    LIMIT = 500

    def __init__(self, clock: Any = None) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, str, dict]] = {}

    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    def issue(self, kind: str, ttl: float, data: dict | None = None) -> str:
        challenge = new_challenge()
        now = self._now()
        with self._lock:
            for key in [k for k, (until, _, _) in self._items.items() if until <= now]:
                del self._items[key]
            while len(self._items) >= self.LIMIT:
                del self._items[next(iter(self._items))]
            self._items[challenge] = (now + ttl, kind, dict(data or {}))
        return challenge

    def take(self, kind: str, challenge: str) -> dict | None:
        with self._lock:
            item = self._items.pop(challenge, None)
        if item is None or item[1] != kind or item[0] <= self._now():
            return None
        return item[2]

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


def client_challenge(raw: bytes) -> str:
    """The challenge the response claims to answer, to find the one that was issued.

    It only LOCATES: the real check (type, origin, challenge) still happens in `_client_data`.
    """
    try:
        client = json.loads(raw)
    except ValueError as exc:
        raise WebAuthnError("clientDataJSON invalido") from exc
    challenge = client.get("challenge") if isinstance(client, dict) else None
    if not isinstance(challenge, str) or not challenge:
        raise WebAuthnError("clientDataJSON sem desafio")
    return challenge


# ------------------------------------------------------------------ CBOR

def _cbor_head(data: bytes, offset: int) -> tuple[int, int, int]:
    """An item's header: (major type, argument, where the content starts)."""
    if offset >= len(data):
        raise WebAuthnError("CBOR truncado")
    major, info = data[offset] >> 5, data[offset] & 0x1F
    offset += 1
    if info < 24:
        return major, info, offset
    if info not in (24, 25, 26, 27):
        raise WebAuthnError("CBOR fora do subconjunto do WebAuthn")
    size = 1 << (info - 24)
    if offset + size > len(data):
        raise WebAuthnError("CBOR truncado")
    return major, int.from_bytes(data[offset:offset + size], "big"), offset + size


def cbor_decode(data: bytes, offset: int = 0) -> tuple[Any, int]:
    """One CBOR item starting at `offset` -> (value, where it ends). Only what WebAuthn uses:
    integers, bytes, text, list, map and true/false/null. No indefinite length and no float."""
    major, arg, offset = _cbor_head(data, offset)
    if major == 0:
        return arg, offset
    if major == 1:
        return -1 - arg, offset
    if major in (2, 3):
        if offset + arg > len(data):
            raise WebAuthnError("CBOR truncado")
        raw = data[offset:offset + arg]
        return (raw if major == 2 else raw.decode("utf-8")), offset + arg
    if major == 4:
        items = []
        for _ in range(arg):
            item, offset = cbor_decode(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        mapping: dict[Any, Any] = {}
        for _ in range(arg):
            key, offset = cbor_decode(data, offset)
            mapping[key], offset = cbor_decode(data, offset)
        return mapping, offset
    if major == 7 and arg in (20, 21, 22):
        return {20: False, 21: True, 22: None}[arg], offset
    raise WebAuthnError("CBOR fora do subconjunto do WebAuthn")


# ------------------------------------------------------------------ ES256 on the P-256 curve

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)

Jacobian = tuple[int, int, int]


def _double(p: Jacobian) -> Jacobian:
    x, y, z = p
    if y == 0 or z == 0:
        return (0, 1, 0)
    ysq = y * y % P
    s = 4 * x * ysq % P
    m = (3 * x * x + A * pow(z, 4, P)) % P
    nx = (m * m - 2 * s) % P
    ny = (m * (s - nx) - 8 * ysq * ysq) % P
    return (nx, ny, 2 * y * z % P)


def _add(p: Jacobian, q: Jacobian) -> Jacobian:
    if p[2] == 0:
        return q
    if q[2] == 0:
        return p
    z1z1, z2z2 = p[2] * p[2] % P, q[2] * q[2] % P
    u1, u2 = p[0] * z2z2 % P, q[0] * z1z1 % P
    s1, s2 = p[1] * z2z2 * q[2] % P, q[1] * z1z1 * p[2] % P
    if u1 == u2:
        return _double(p) if s1 == s2 else (0, 1, 0)
    h, r = (u2 - u1) % P, (s2 - s1) % P
    h2 = h * h % P
    h3 = h * h2 % P
    nx = (r * r - h3 - 2 * u1 * h2) % P
    ny = (r * (u1 * h2 - nx) - s1 * h3) % P
    return (nx, ny, h * p[2] * q[2] % P)


def _affine(p: Jacobian) -> tuple[int, int] | None:
    if p[2] == 0:
        return None
    zinv = pow(p[2], -1, P)
    return (p[0] * zinv * zinv % P, p[1] * zinv * zinv * zinv % P)


def _mul_add(k1: int, p1: tuple[int, int], k2: int, p2: tuple[int, int]) -> Jacobian:
    """k1*p1 + k2*p2 in one go (Shamir's trick): half the doublings of two separate products."""
    j1, j2 = (p1[0], p1[1], 1), (p2[0], p2[1], 1)
    both = _add(j1, j2)
    acc: Jacobian = (0, 1, 0)
    for i in range(max(k1.bit_length(), k2.bit_length()) - 1, -1, -1):
        acc = _double(acc)
        b1, b2 = (k1 >> i) & 1, (k2 >> i) & 1
        if b1 and b2:
            acc = _add(acc, both)
        elif b1:
            acc = _add(acc, j1)
        elif b2:
            acc = _add(acc, j2)
    return acc


def multiply(k: int, point: tuple[int, int]) -> tuple[int, int] | None:
    """k * point, affine. WebAuthn only verifies; Web Push (`webpush.py`) signs and does ECDH."""
    return _affine(_mul_add(k, point, 0, point))


def on_curve(x: int, y: int) -> bool:
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def _der_signature(der: bytes) -> tuple[int, int]:
    """SEQUENCE { INTEGER r, INTEGER s } - the format of the WebAuthn ES256 signature."""
    def integer(at: int) -> tuple[int, int]:
        if der[at] != 0x02 or at + 2 > len(der):
            raise WebAuthnError("assinatura DER invalida")
        size = der[at + 1]
        return int.from_bytes(der[at + 2:at + 2 + size], "big"), at + 2 + size
    if len(der) < 8 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise WebAuthnError("assinatura DER invalida")
    r, at = integer(2)
    s, at = integer(at)
    if at != len(der):
        raise WebAuthnError("assinatura DER invalida")
    return r, s


def verify_es256(x: int, y: int, message: bytes, der: bytes) -> bool:
    if not on_curve(x, y):
        return False
    r, s = _der_signature(der)
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _affine(_mul_add(e * w % N, G, r * w % N, (x, y)))
    return point is not None and point[0] % N == r


# ------------------------------------------------------------------ RS256

SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def verify_rs256(n: int, e: int, message: bytes, signature: bytes) -> bool:
    size = (n.bit_length() + 7) // 8
    if len(signature) != size or n.bit_length() < 2048:
        return False
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big")
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


# ------------------------------------------------------------------ COSE key

def check_cose_key(cose: bytes) -> int:
    """Checks that the public key is one the panel knows how to verify; returns the alg."""
    key, end = cbor_decode(cose)
    if not isinstance(key, dict) or end != len(cose):
        raise WebAuthnError("chave COSE invalida")
    alg = key.get(3)
    if alg == ALG_ES256 and key.get(1) == 2 and key.get(-1) == 1:
        x, y = key.get(-2), key.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
            raise WebAuthnError("chave EC2 invalida")
        if not on_curve(int.from_bytes(x, "big"), int.from_bytes(y, "big")):
            raise WebAuthnError("ponto fora da curva P-256")
        return alg
    if alg == ALG_RS256 and key.get(1) == 3 and isinstance(key.get(-1), bytes) and isinstance(key.get(-2), bytes):
        if int.from_bytes(key[-1], "big").bit_length() < 2048:
            raise WebAuthnError("chave RSA curta demais")
        return alg
    raise WebAuthnError(f"algoritmo nao suportado: {alg!r}")


def verify_signature(cose: bytes, message: bytes, signature: bytes) -> bool:
    key, _end = cbor_decode(cose)
    if key.get(3) == ALG_ES256:
        return verify_es256(int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big"), message, signature)
    if key.get(3) == ALG_RS256:
        return verify_rs256(int.from_bytes(key[-1], "big"), int.from_bytes(key[-2], "big"), message, signature)
    return False


# ------------------------------------------------------------------ ceremonies

class AuthData(NamedTuple):
    rp_id_hash: bytes
    flags: int
    sign_count: int
    credential_id: bytes
    public_key: bytes   # the COSE key as received (registration only)


def parse_auth_data(data: bytes) -> AuthData:
    if len(data) < 37:
        raise WebAuthnError("authenticatorData curto demais")
    rp_id_hash, flags = data[:32], data[32]
    (sign_count,) = struct.unpack(">I", data[33:37])
    credential_id = public_key = b""
    if flags & FLAG_AT:
        if len(data) < 55:
            raise WebAuthnError("attestedCredentialData truncado")
        (id_len,) = struct.unpack(">H", data[53:55])
        credential_id = data[55:55 + id_len]
        if len(credential_id) != id_len:
            raise WebAuthnError("credentialId truncado")
        _key, end = cbor_decode(data, 55 + id_len)
        public_key = data[55 + id_len:end]
    return AuthData(rp_id_hash, flags, sign_count, credential_id, public_key)


def _client_data(raw: bytes, kind: str, challenge: str, origin: str) -> None:
    try:
        client = json.loads(raw)
    except ValueError as exc:
        raise WebAuthnError("clientDataJSON invalido") from exc
    if not isinstance(client, dict) or client.get("type") != kind:
        raise WebAuthnError("tipo de cerimonia errado")
    if not challenge or not hmac.compare_digest(str(client.get("challenge", "")), challenge):
        raise WebAuthnError("desafio nao confere")
    if client.get("origin") != origin:
        raise WebAuthnError(f"origem nao confere: {client.get('origin')!r}")
    if client.get("crossOrigin") is True:
        raise WebAuthnError("cerimonia vinda de iframe de outra origem")


def _flags_and_rp(auth: AuthData, rp_id: str) -> None:
    if not hmac.compare_digest(auth.rp_id_hash, hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("RP ID nao confere")
    if not auth.flags & FLAG_UP or not auth.flags & FLAG_UV:
        raise WebAuthnError("o aparelho nao confirmou a pessoa (UP/UV)")


class NewCredential(NamedTuple):
    credential_id: str  # base64url
    public_key: bytes   # COSE
    sign_count: int


def verify_registration(*, challenge: str, origin: str, rp_id: str, client_data_json: bytes,
                        attestation_object: bytes) -> NewCredential:
    _client_data(client_data_json, "webauthn.create", challenge, origin)
    attestation, _end = cbor_decode(attestation_object)
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise WebAuthnError("attestationObject invalido")
    auth = parse_auth_data(attestation["authData"])
    _flags_and_rp(auth, rp_id)
    if not auth.flags & FLAG_AT or not auth.credential_id:
        raise WebAuthnError("o cadastro nao trouxe a credencial")
    check_cose_key(auth.public_key)
    return NewCredential(b64url(auth.credential_id), auth.public_key, auth.sign_count)


def verify_assertion(*, challenge: str, origin: str, rp_id: str, public_key: bytes, stored_count: int,
                     client_data_json: bytes, authenticator_data: bytes, signature: bytes) -> int:
    """Checks the login; returns the new counter to store."""
    _client_data(client_data_json, "webauthn.get", challenge, origin)
    auth = parse_auth_data(authenticator_data)
    _flags_and_rp(auth, rp_id)
    message = authenticator_data + hashlib.sha256(client_data_json).digest()
    if not verify_signature(public_key, message, signature):
        raise WebAuthnError("assinatura invalida")
    if (auth.sign_count or stored_count) and auth.sign_count <= stored_count:
        raise WebAuthnError("contador nao subiu: possivel chave clonada")
    return auth.sign_count
