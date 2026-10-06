"""Web Push (the phone's notifications) - stdlib only.

Same reason TOTP, QR and WebAuthn are our own code: production only has the stdlib plus apt's
Flask, so there is no `cryptography` or `pywebpush` to install. Only the SENDING side lives here:
the browser creates the subscription, the panel stores it and encrypts each message to it.

What is included, and why:
- **VAPID** (RFC 8292): the push service (Google, Mozilla, Apple) only accepts a message signed
  by the key the subscription was created with. The key pair is the panel's, generated once and
  kept in the database; the signature is an ES256 JWT on the P-256 curve `webauthn` already has.
- **aes128gcm** (RFC 8188 + RFC 8291): the payload is encrypted to the DEVICE, with an ephemeral
  ECDH key per message. The push service carries the message and cannot read it - a server name
  and "it went down" go through Google or Apple, and that is the only way they are allowed to.
- **AES-128 and GCM**: the stdlib has no AES. The cipher here only ENCRYPTS (the device decrypts),
  and only a few hundred bytes per alert, so a plain table implementation is fast enough. The
  tests check it against FIPS-197, the NIST GCM vectors and the full RFC 8291 example.

The scalar multiplication is not constant time. It signs one JWT per push service per hour and
the timing is buried in an HTTPS round trip to a third party; WebAuthn never needed it because it
only VERIFIES. Worth knowing before reusing it anywhere a private key meets an attacker's clock.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import struct
from typing import NamedTuple

from gamepanel.security import webauthn as curve

# RFC 8291: the device's public key is an uncompressed P-256 point, the auth secret 16 bytes.
POINT_BYTES = 65
AUTH_SECRET_BYTES = 16
SALT_BYTES = 16
# One record is enough: a push message is capped at 4096 bytes by every push service, and the
# record size has to be bigger than the whole payload for it to fit in a single record.
RECORD_SIZE = 4096
# What the push services accept in the body, after encryption: 4096 minus the header (86 bytes),
# minus the GCM tag (16) and the delimiter (1). The caller trims before calling `encrypt`.
MAX_PLAINTEXT = RECORD_SIZE - 86 - 16 - 1
TAG_BYTES = 16


class PushError(ValueError):
    """A subscription the panel cannot encrypt to (malformed key). For the log only."""


# ------------------------------------------------------------------ AES-128, FIPS-197

def _sbox() -> bytes:
    """The S-box computed from its definition (inverse in GF(2^8) + affine map).

    Computed and not pasted: 256 hex bytes typed by hand are 256 chances of a typo that only the
    test vector would catch, and the definition is shorter than the table.
    """
    box = bytearray(256)
    p = q = 1
    while True:
        # p walks the multiplicative group by 3, q by its inverse (1/3).
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ _rotl8(q, 1) ^ _rotl8(q, 2) ^ _rotl8(q, 3) ^ _rotl8(q, 4)
        box[p] = x ^ 0x63
        if p == 1:
            break
    box[0] = 0x63
    return bytes(box)


def _rotl8(x: int, shift: int) -> int:
    return ((x << shift) | (x >> (8 - shift))) & 0xFF


SBOX = _sbox()


def _xtime(b: int) -> int:
    return ((b << 1) ^ 0x1B) & 0xFF if b & 0x80 else b << 1


def _expand_key(key: bytes) -> list[bytes]:
    """The 11 round keys of AES-128."""
    if len(key) != 16:
        raise PushError("AES-128 key must be 16 bytes")
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = [SBOX[b] for b in temp[1:] + temp[:1]]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], temp, strict=True)])
    return [bytes(b for word in words[r * 4:r * 4 + 4] for b in word) for r in range(11)]


def _encrypt_block(round_keys: list[bytes], block: bytes) -> bytes:
    # The state is column-major: byte i is row i % 4, column i // 4.
    s = [a ^ b for a, b in zip(block, round_keys[0], strict=True)]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]
        # ShiftRows: row r moves r columns to the left.
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if rnd != 10:
            mixed = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c:4 * c + 4]
                t = a0 ^ a1 ^ a2 ^ a3
                mixed += [a0 ^ t ^ _xtime(a0 ^ a1), a1 ^ t ^ _xtime(a1 ^ a2),
                          a2 ^ t ^ _xtime(a2 ^ a3), a3 ^ t ^ _xtime(a3 ^ a0)]
            s = mixed
        s = [a ^ b for a, b in zip(s, round_keys[rnd], strict=True)]
    return bytes(s)


def aes128_block(key: bytes, block: bytes) -> bytes:
    """One block, for the FIPS-197 test. GCM uses the expanded key directly."""
    return _encrypt_block(_expand_key(key), block)


# ------------------------------------------------------------------ GCM (NIST SP 800-38D)

GCM_R = 0xE1 << 120


def _gf_mult(x: int, y: int) -> int:
    """Multiplication in GF(2^128) with GCM's bit order (bit 0 is the MOST significant)."""
    z, v = 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ GCM_R if v & 1 else v >> 1
    return z


def _ghash(h: int, data: bytes) -> int:
    y = 0
    for i in range(0, len(data), 16):
        y = _gf_mult(y ^ int.from_bytes(data[i:i + 16].ljust(16, b"\0"), "big"), h)
    return y


def aes128gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """Ciphertext followed by the 16-byte tag. No associated data: RFC 8188 uses none."""
    if len(nonce) != 12:
        raise PushError("GCM nonce must be 12 bytes")
    keys = _expand_key(key)
    h = int.from_bytes(_encrypt_block(keys, bytes(16)), "big")
    j0 = nonce + b"\0\0\0\1"
    out = bytearray()
    for i in range(0, len(plaintext), 16):
        counter = nonce + struct.pack(">I", i // 16 + 2)
        stream = _encrypt_block(keys, counter)
        out += bytes(a ^ b for a, b in zip(plaintext[i:i + 16], stream, strict=False))
    lengths = struct.pack(">QQ", 0, len(plaintext) * 8)
    padded = bytes(out) + b"\0" * (-len(out) % 16)
    s = _ghash(h, padded + lengths)
    tag = (s ^ int.from_bytes(_encrypt_block(keys, j0), "big")).to_bytes(16, "big")
    return bytes(out) + tag


# ------------------------------------------------------------------ keys and ECDH

class KeyPair(NamedTuple):
    private: int
    public: bytes   # uncompressed point, 65 bytes (0x04 || x || y)


def _point_bytes(point: tuple[int, int]) -> bytes:
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def _parse_point(raw: bytes) -> tuple[int, int]:
    if len(raw) != POINT_BYTES or raw[0] != 0x04:
        raise PushError("device key is not an uncompressed P-256 point")
    x, y = int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")
    # Off the curve, ECDH would compute on another (weaker) curve with the panel's ephemeral key.
    if not curve.on_curve(x, y):
        raise PushError("device key is not on P-256")
    return x, y


def _multiply(k: int, point: tuple[int, int]) -> tuple[int, int]:
    result = curve.multiply(k, point)
    if result is None:
        raise PushError("point at infinity")
    return result


def keypair_from_private(private: int) -> KeyPair:
    if not 1 <= private < curve.N:
        raise PushError("private key out of range")
    return KeyPair(private, _point_bytes(_multiply(private, curve.G)))


def new_keypair() -> KeyPair:
    return keypair_from_private(secrets.randbelow(curve.N - 1) + 1)


def private_to_text(pair: KeyPair) -> str:
    return curve.b64url(pair.private.to_bytes(32, "big"))


def keypair_from_text(text: str) -> KeyPair:
    try:
        raw = curve.unb64url(text)
    except curve.WebAuthnError as exc:
        raise PushError("stored key is not base64url") from exc
    if len(raw) != 32:
        raise PushError("stored key must be 32 bytes")
    return keypair_from_private(int.from_bytes(raw, "big"))


def _ecdh(private: int, peer: bytes) -> bytes:
    return _multiply(private, _parse_point(peer))[0].to_bytes(32, "big")


# ------------------------------------------------------------------ RFC 8291 + RFC 8188

def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *,
            sender: KeyPair | None = None, salt: bytes | None = None) -> bytes:
    """The request body for one device (header + one record), `Content-Encoding: aes128gcm`.

    `sender` and `salt` exist for the RFC 8291 test vector; a real message always gets a fresh
    ephemeral key and salt - reusing either would repeat the content key and the GCM nonce, which
    is the one mistake GCM does not survive.
    """
    if len(auth_secret) != AUTH_SECRET_BYTES:
        raise PushError("auth secret must be 16 bytes")
    if len(plaintext) > MAX_PLAINTEXT:
        raise PushError("payload too large for one push message")
    sender = sender or new_keypair()
    salt = salt or secrets.token_bytes(SALT_BYTES)
    shared = _ecdh(sender.private, ua_public)
    # HKDF (RFC 5869) with SHA-256, written out: each expand is a single block (<= 32 bytes).
    prk_key = _hmac(auth_secret, shared)
    key_info = b"WebPush: info\0" + ua_public + sender.public
    ikm = _hmac(prk_key, key_info + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\0\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\0\x01")[:12]
    # 0x02 = "last record"; no padding (the alert text is not a secret worth hiding the size of).
    record = aes128gcm_encrypt(cek, nonce, plaintext + b"\x02")
    header = salt + struct.pack(">I", RECORD_SIZE) + bytes([len(sender.public)]) + sender.public
    return header + record


# ------------------------------------------------------------------ VAPID (RFC 8292)

def sign_es256(private: int, message: bytes) -> bytes:
    """ECDSA P-256 / SHA-256, raw r || s (64 bytes): the JWS format, not WebAuthn's DER."""
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        k = secrets.randbelow(curve.N - 1) + 1
        r = _multiply(k, curve.G)[0] % curve.N
        if r == 0:
            continue
        s = pow(k, -1, curve.N) * (e + r * private) % curve.N
        if s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def vapid_header(pair: KeyPair, audience: str, subject: str, expires_at: int) -> str:
    """The `Authorization` header: `vapid t=<JWT>, k=<public key>`.

    `aud` is the push service's origin (scheme + host), `exp` at most 24 h ahead (the services
    refuse more), `sub` a contact for the push service operator to reach whoever runs the panel.
    """
    head = curve.b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = {"aud": audience, "exp": int(expires_at), "sub": subject}
    body = curve.b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode("ascii")
    token = f"{head}.{body}.{curve.b64url(sign_es256(pair.private, signing_input))}"
    return f"vapid t={token}, k={curve.b64url(pair.public)}"
