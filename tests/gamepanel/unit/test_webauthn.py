"""WebAuthn proprio (security/webauthn.py): CBOR, ES256, RS256 e as regras das cerimonias.

O aparelho e simulado aqui com a mesma matematica (assinar ECDSA so precisa da curva): cada
teste monta a resposta que um celular mandaria e confere o que o painel aceita ou recusa.
"""
from __future__ import annotations

import hashlib

import fake_passkey
import pytest
from fake_passkey import CRED_ID, PRIVATE, cbor, cose_es256, der_int, public_point, sign_es256

from gamepanel.security import webauthn as wa

ORIGIN = "https://painel.exemplo.com"
RP_ID = "painel.exemplo.com"
CHALLENGE = wa.b64url(b"" * 32)


def auth_data(flags: int = wa.FLAG_UP | wa.FLAG_UV, count: int = 0, rp_id: str = RP_ID,
              key: bytes | None = None) -> bytes:
    return fake_passkey.auth_data(rp_id, flags, count, key)


def client_data(kind: str, challenge: str = CHALLENGE, origin: str = ORIGIN, **extra) -> bytes:
    return fake_passkey.client_data(kind, challenge, origin, **extra)


def registration(**over):
    flags = over.pop("flags", wa.FLAG_UP | wa.FLAG_UV | wa.FLAG_AT)
    data = auth_data(flags, rp_id=over.pop("rp_id", RP_ID), key=over.pop("key", cose_es256()))
    attestation = cbor({"fmt": "none", "attStmt": {}, "authData": data})
    args = {"challenge": CHALLENGE, "origin": ORIGIN, "rp_id": RP_ID,
            "client_data_json": over.pop("client", client_data("webauthn.create")),
            "attestation_object": attestation}
    args.update(over)
    return wa.verify_registration(**args)


def assertion(stored: int = 0, count: int = 0, flags: int = wa.FLAG_UP | wa.FLAG_UV, **over):
    data = auth_data(flags, count, rp_id=over.pop("rp_id", RP_ID))
    client = over.pop("client", client_data("webauthn.get"))
    signature = over.pop("signature", sign_es256(data + hashlib.sha256(client).digest()))
    args = {"challenge": CHALLENGE, "origin": ORIGIN, "rp_id": RP_ID, "public_key": cose_es256(),
            "stored_count": stored, "client_data_json": client, "authenticator_data": data,
            "signature": signature}
    args.update(over)
    return wa.verify_assertion(**args)


# ------------------------------------------------------------------ testes

def test_cbor_le_o_que_o_webauthn_usa():
    value = {"a": [1, -7, b"\x00\xff", True, None], 3: -257, "grande": 2**40}
    assert wa.cbor_decode(cbor(value)) == (value, len(cbor(value)))


def test_cbor_truncado_e_recusado():
    with pytest.raises(wa.WebAuthnError):
        wa.cbor_decode(cbor(b"0123456789")[:-3])


def test_es256_confere_assinatura_certa_e_recusa_a_errada():
    x, y = public_point()
    message = b"mensagem"
    assert wa.verify_es256(x, y, message, sign_es256(message))
    assert not wa.verify_es256(x, y, b"outra", sign_es256(message))
    other_x, other_y = public_point(PRIVATE + 1)
    assert not wa.verify_es256(other_x, other_y, message, sign_es256(message))


def test_es256_vetor_conhecido():
    """Vetor de teste do RFC 6979, A.2.5 (P-256, SHA-256, mensagem 'sample'): confere a
    matematica contra uma assinatura que NAO foi feita por este arquivo."""
    x = 0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6
    y = 0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299
    r = 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716
    s = 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8
    body = der_int(r) + der_int(s)
    der = b"\x30" + bytes([len(body)]) + body
    assert wa.verify_es256(x, y, b"sample", der)
    assert not wa.verify_es256(x, y, b"samplE", der)


def test_rs256_confere_e_recusa():
    # Chave RSA de 2048 bits so para teste (e = 65537), assinatura PKCS#1 v1.5 feita a mao.
    n, e, d = RSA_TEST_KEY
    message = b"windows hello"
    size = (n.bit_length() + 7) // 8
    t = wa.SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    signature = pow(int.from_bytes(em, "big"), d, n).to_bytes(size, "big")
    assert wa.verify_rs256(n, e, message, signature)
    assert not wa.verify_rs256(n, e, b"outra", signature)


def test_cadastro_devolve_a_credencial():
    cred = registration()
    assert cred.credential_id == wa.b64url(CRED_ID)
    assert cred.public_key == cose_es256()


@pytest.mark.parametrize(("over", "reason"), [
    ({"client": client_data("webauthn.get")}, "tipo"),
    ({"client": client_data("webauthn.create", challenge=wa.b64url(b"\x02" * 32))}, "desafio"),
    ({"client": client_data("webauthn.create", origin="https://falso.com")}, "origem"),
    ({"client": client_data("webauthn.create", crossOrigin=True)}, "iframe"),
    ({"rp_id": "falso.com"}, "RP ID"),
    ({"flags": wa.FLAG_UP | wa.FLAG_AT}, "UP/UV"),
    ({"key": cbor({1: 2, 3: -7, -1: 1, -2: b"\x01" * 32, -3: b"\x02" * 32})}, "curva"),
    ({"key": cbor({1: 1, 3: -8, -1: 6, -2: b"\x01" * 32})}, "algoritmo"),
])
def test_cadastro_recusado(over, reason):
    with pytest.raises(wa.WebAuthnError, match=reason):
        registration(**over)


def test_login_confere_e_devolve_o_contador():
    assert assertion(stored=0, count=0) == 0  # passkey sincronizada: sempre 0
    assert assertion(stored=5, count=6) == 6


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"client": client_data("webauthn.create")}, "tipo"),
    ({"client": client_data("webauthn.get", challenge="")}, "desafio"),
    ({"client": client_data("webauthn.get", origin="http://painel.exemplo.com")}, "origem"),
    ({"rp_id": "outro.com"}, "RP ID"),
    ({"flags": wa.FLAG_UP}, "UP/UV"),
    ({"signature": sign_es256(b"outra coisa")}, "assinatura"),
    ({"stored": 9, "count": 9}, "clonada"),
    ({"stored": 9, "count": 0}, "clonada"),
])
def test_login_recusado(kwargs, reason):
    with pytest.raises(wa.WebAuthnError, match=reason):
        assertion(**kwargs)


def test_desafio_novo_a_cada_vez():
    first, second = wa.new_challenge(), wa.new_challenge()
    assert first != second
    assert len(wa.unb64url(wa.new_challenge())) == wa.CHALLENGE_BYTES


# Chave RSA de teste (2048 bits), gerada uma vez e colada aqui: gerar primos a cada rodada
# gastaria segundos para provar a mesma coisa. Nao protege nada.
RSA_TEST_KEY = (
    int(
        "c3749fa92dbabf34977e0e1616f288df9b63f9a7f4cb2273ba4e5ff8b5a5fdb99fc32d897b1db74664899d8d482f13c5"
        "3f42ed48e02bc68c16adb6d1668d0fea1b12bc2c965ef8c03f7466771cfd16d2d6a31760a3f89a1858d53978fd1f118d"
        "db7ab8950e7e24d0b495b48ec1b2f292f8e46eec99f6b98bb90133373d6f9dc21e1b9bb2b29a4f6f6ee55bc3948c6c39"
        "2ec6f791b587e092dc5cb84d769c69d23345860972b653cdf996d77a3104427863ff36794b9aa5db6c761170dc344866"
        "4babc0b269692aeb241cb53e0345c88f4fc40700783b8324294e969cb635426034516e91677d5b120c731e690350865b"
        "4e6c79d31a5cf193f1adadd4e239d203", 16),
    65537,
    int(
        "15b013274a93b633b7bb9d0486775308bccd531e77e3326774fccd59638e8fa0d1416f041a4d29d0fdc6e75c8dedeb5b"
        "afb1557308acd2d328910e001e48f8c3194df2e35fac1a1dfaec87921ffd5552ffce0902082fc5a97df1eaf6a9df90ab"
        "14f78113c90fe635e253da3d1cf1264978a4a04a50ab37db7123d8f300362a62f6072648779059c87a6dc54207ee0d6e"
        "2e57d7d68e5871e73fcc2b34d389726ab4d115621a7f47dac0e23c21cf6b8b7941145f9bd921857ade686049c6df95a7"
        "92f1e09fe74408d108f26cc550ec14c1edc5279b8d3c31e77176e4516351b6c889bdf459caed5c42590b07c182f1a6fb"
        "df653765b3525b0ccd62924a7c711241", 16),
)


def test_desafio_e_de_uso_unico_e_vence():
    now = [100.0]
    store = wa.Challenges(clock=lambda: now[0])
    first = store.issue("login", 10, {"uid": 1})
    assert store.take("register", first) is None  # tipo errado tambem gasta
    second = store.issue("login", 10)
    assert store.take("login", second) == {}
    assert store.take("login", second) is None
    third = store.issue("login", 10)
    now[0] += 11
    assert store.take("login", third) is None


def test_desafios_tem_teto():
    store = wa.Challenges()
    first = store.issue("login", 60)
    for _ in range(wa.Challenges.LIMIT):
        store.issue("login", 60)
    assert store.take("login", first) is None
