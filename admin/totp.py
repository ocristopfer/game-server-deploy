#!/usr/bin/env python3
"""Segundo fator do login: TOTP (RFC 6238) e codigos de recuperacao, so com a stdlib.

Puro de proposito (sem Flask, sem banco), como `ui.py`: o `app.py` guarda o segredo e decide
quando pedir o codigo; aqui so existe a conta. Compativel com Google Authenticator, Authy,
Microsoft Authenticator, 1Password, Bitwarden e afins (SHA-1, 6 digitos, 30 s).

Duas decisoes que valem um comentario:

- **Codigo usado nao vale de novo.** `verificar` so aceita um passo MAIOR que o ultimo ja
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

PASSO_SEGUNDOS = 30
DIGITOS = 6
JANELA = 1
BYTES_DO_SEGREDO = 20          # 160 bits, o tamanho do SHA-1 (RFC 4226)
CODIGOS_DE_RECUPERACAO = 8

_SEIS_DIGITOS = re.compile(r"\d{6}")
_RECUPERACAO = re.compile(r"[0-9a-f]{10}")


def novo_segredo() -> str:
    """Segredo novo em base32 sem preenchimento (32 caracteres): o que o aplicativo digita."""
    return base64.b32encode(secrets.token_bytes(BYTES_DO_SEGREDO)).decode().rstrip("=")


def _bytes_do_segredo(segredo: str) -> bytes:
    limpo = re.sub(r"[\s-]", "", segredo).upper()
    return base64.b32decode(limpo + "=" * (-len(limpo) % 8))


def codigo(segredo: str, passo: int) -> str:
    """O codigo de 6 digitos de um passo de 30 s (HOTP de RFC 4226 com o passo como contador)."""
    mac = hmac.new(_bytes_do_segredo(segredo), struct.pack(">Q", passo), hashlib.sha1).digest()
    desvio = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[desvio:desvio + 4])[0] & 0x7FFFFFFF
    return str(numero % 10**DIGITOS).zfill(DIGITOS)


def passo_de(agora: float) -> int:
    return int(agora // PASSO_SEGUNDOS)


def verificar(segredo: str, digitado: str, agora: float, ultimo_passo: int = 0) -> int | None:
    """O passo que `digitado` confirma, ou None. Nunca devolve um passo <= `ultimo_passo`."""
    limpo = re.sub(r"[\s-]", "", digitado or "")
    if not _SEIS_DIGITOS.fullmatch(limpo):
        return None
    atual = passo_de(agora)
    achado: int | None = None
    # Testa os tres passos SEM parar no primeiro acerto: o tempo gasto nao conta qual foi.
    for passo in range(atual - JANELA, atual + JANELA + 1):
        confere = hmac.compare_digest(codigo(segredo, passo), limpo)
        if confere and passo > ultimo_passo and achado is None:
            achado = passo
    return achado


def uri(segredo: str, usuario: str, emissor: str = "Painel de Jogos") -> str:
    """O endereco otpauth:// que o aplicativo abre (no celular, tocar nele ja cadastra)."""
    rotulo = quote(f"{emissor}:{usuario}", safe="")
    return (f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor, safe='')}"
            f"&algorithm=SHA1&digits={DIGITOS}&period={PASSO_SEGUNDOS}")


def agrupar(segredo: str, tamanho: int = 4) -> str:
    """`ABCD EFGH ...`: mais facil de ler e de digitar. O aplicativo ignora os espacos."""
    return " ".join(segredo[i:i + tamanho] for i in range(0, len(segredo), tamanho))


# ------------------------------------------------------------ codigos de recuperacao

def _normaliza(texto: str) -> str:
    return re.sub(r"[\s-]", "", texto or "").lower()


def parece_codigo_de_recuperacao(digitado: str) -> bool:
    return bool(_RECUPERACAO.fullmatch(_normaliza(digitado)))


def novos_codigos(quantidade: int = CODIGOS_DE_RECUPERACAO) -> list[str]:
    """`abcde-12345`: 40 bits cada. Servem uma vez, para quem perdeu o celular."""
    codigos = []
    while len(codigos) < quantidade:
        bruto = secrets.token_hex(5)
        codigos.append(f"{bruto[:5]}-{bruto[5:]}")
    return codigos


def hash_do_codigo(codigo_de_recuperacao: str) -> str:
    """So o hash vai para o banco: quem ler o arquivo nao sai com codigos utilizaveis."""
    return hashlib.sha256(_normaliza(codigo_de_recuperacao).encode()).hexdigest()


def consumir(digitado: str, hashes: list[str]) -> list[str] | None:
    """Os hashes que sobram depois de gastar `digitado`, ou None se ele nao serve."""
    if not parece_codigo_de_recuperacao(digitado):
        return None
    alvo = hash_do_codigo(digitado)
    achado = None
    for h in hashes:
        if hmac.compare_digest(h, alvo):
            achado = h
    if achado is None:
        return None
    sobra = list(hashes)
    sobra.remove(achado)
    return sobra
