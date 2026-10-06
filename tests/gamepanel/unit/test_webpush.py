"""Web Push crypto (`security/webpush.py`): each piece against its published vector.

No `cryptography` here or in production: the vectors are what prove the hand-written AES, GCM,
ECDH/HKDF and the VAPID signature, the same way `test_webauthn.py` proves the curve.
"""
from __future__ import annotations

import base64
import json

import pytest

from gamepanel.security import webauthn as wa
from gamepanel.security import webpush

# RFC 8291, Appendix A: the full example, from the keys to the encrypted body.
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_AS_PUBLIC = ("BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8")
RFC_UA_PUBLIC = ("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4")
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PB"
    "ru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)


def test_aes128_bate_com_o_vetor_do_fips_197():
    key = bytes(range(16))
    block = bytes.fromhex("00112233445566778899aabbccddeeff")
    assert webpush.aes128_block(key, block).hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"


@pytest.mark.parametrize(("plaintext", "expected"), [
    # NIST GCM test cases 1 and 2 (zero key, zero IV).
    (b"", "58e2fccefa7e3061367f1d57a4e7455a"),
    (bytes(16), "0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf"),
])
def test_gcm_bate_com_os_vetores_do_nist(plaintext, expected):
    assert webpush.aes128gcm_encrypt(bytes(16), bytes(12), plaintext).hex() == expected


def test_gcm_com_varios_blocos():
    # NIST GCM test case 3: four full blocks, a real key and IV.
    key = bytes.fromhex("feffe9928665731c6d6a8f9467308308")
    iv = bytes.fromhex("cafebabefacedbaddecaf888")
    plaintext = bytes.fromhex(
        "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
        "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b391aafd255")
    out = webpush.aes128gcm_encrypt(key, iv, plaintext)
    assert out[:-16].hex() == (
        "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091473f5985")
    assert out[-16:].hex() == "4d5c2af327cd64a62cf35abd2ba6fab4"


def test_criptografia_bate_com_o_exemplo_da_rfc_8291():
    sender = webpush.keypair_from_text(RFC_AS_PRIVATE)
    assert wa.b64url(sender.public) == RFC_AS_PUBLIC
    body = webpush.encrypt(RFC_PLAINTEXT, wa.unb64url(RFC_UA_PUBLIC), wa.unb64url(RFC_AUTH),
                           sender=sender, salt=wa.unb64url(RFC_SALT))
    assert wa.b64url(body) == RFC_BODY


def test_cada_mensagem_usa_chave_e_salt_novos():
    # Reusing either repeats the GCM key+nonce: the one mistake GCM does not survive.
    ua, auth = wa.unb64url(RFC_UA_PUBLIC), wa.unb64url(RFC_AUTH)
    first, second = webpush.encrypt(b"x", ua, auth), webpush.encrypt(b"x", ua, auth)
    assert first[:16] != second[:16]
    assert first[21:86] != second[21:86]


@pytest.mark.parametrize("bad", [
    b"",
    b"\x04" + bytes(64),                       # not on the curve
    b"\x02" + wa.unb64url(RFC_UA_PUBLIC)[1:33],  # compressed
])
def test_chave_do_aparelho_invalida_e_recusada(bad):
    with pytest.raises(webpush.PushError):
        webpush.encrypt(b"x", bad, wa.unb64url(RFC_AUTH))


def test_auth_secret_de_tamanho_errado_e_recusado():
    with pytest.raises(webpush.PushError):
        webpush.encrypt(b"x", wa.unb64url(RFC_UA_PUBLIC), b"curto")


def test_payload_grande_demais_e_recusado():
    with pytest.raises(webpush.PushError):
        webpush.encrypt(b"x" * (webpush.MAX_PLAINTEXT + 1), wa.unb64url(RFC_UA_PUBLIC),
                        wa.unb64url(RFC_AUTH))


def test_chave_vapid_volta_igual_do_texto():
    pair = webpush.new_keypair()
    assert webpush.keypair_from_text(webpush.private_to_text(pair)) == pair


def _der(raw: bytes) -> bytes:
    def integer(v: bytes) -> bytes:
        v = v.lstrip(b"\0") or b"\0"
        if v[0] & 0x80:
            v = b"\0" + v
        return b"\x02" + bytes([len(v)]) + v
    body = integer(raw[:32]) + integer(raw[32:])
    return b"\x30" + bytes([len(body)]) + body


def test_jwt_vapid_e_verificavel_com_a_chave_publica():
    pair = webpush.new_keypair()
    header = webpush.vapid_header(pair, "https://fcm.googleapis.com", "mailto:a@b.c", 1_900_000_000)
    assert header.startswith("vapid t=")
    token, key = header[len("vapid t="):].split(", k=")
    assert wa.unb64url(key) == pair.public
    head, claims, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert decoded == {"aud": "https://fcm.googleapis.com", "exp": 1_900_000_000, "sub": "mailto:a@b.c"}
    x, y = int.from_bytes(pair.public[1:33], "big"), int.from_bytes(pair.public[33:], "big")
    raw = wa.unb64url(signature)
    assert len(raw) == 64
    assert wa.verify_es256(x, y, f"{head}.{claims}".encode(), _der(raw))
    assert not wa.verify_es256(x, y, f"{head}.{claims}x".encode(), _der(raw))
