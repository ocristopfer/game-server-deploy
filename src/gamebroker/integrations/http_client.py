"""Cliente HTTP minimo (so stdlib) para as APIs do Proxmox e do OPNsense.

Duas regras de seguranca moram aqui, para nao dependerem de cada chamador lembrar delas:

- **TLS fixado por impressao digital.** Os dois usam certificado autoassinado. Em vez de
  desligar a verificacao (`verify=False`, que aceita QUALQUER certificado), o cliente aceita
  so o certificado cuja impressao SHA-256 e a configurada. Sem impressao, vale a validacao
  normal da cadeia. Trocar o certificado no Proxmox exige atualizar a impressao - de
  proposito: e o que barra um "homem no meio" dentro da LAN.
- **Sem TLS so em loopback** (testes). Token em HTTP puro por cima da rede nao existe aqui.

Nada neste modulo escreve cabecalho, token ou corpo de requisicao em mensagem de erro: o
texto da excecao vai parar no log da operacao e o painel o exibe.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import ssl
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

RESPOSTA_MAX = 2_000_000
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_IMPRESSAO_RE = re.compile(r"[0-9a-f]{64}")


class ConnectionFailed(Exception):
    """Nao conectou, certificado nao confere ou resposta invalida."""


@dataclass(frozen=True)
class Response:
    status: int
    json: object
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def normalize_fingerprint(text: str) -> str:
    """Aceita `9F:92:...` (como o check-broker-access.ps1 imprime) ou hex corrido."""
    if not text.strip():
        return ""
    clean = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    # Texto nao vazio que nao vira 64 digitos e erro de digitacao: aceitar como "sem
    # impressao" desligaria o pin em silencio.
    if not _IMPRESSAO_RE.fullmatch(clean):
        raise ValueError("impressao SHA-256 invalida: esperados 64 digitos hexadecimais")
    return clean


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, *args, fingerprint: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._impressao = fingerprint

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True) or b""  # type: ignore[union-attr]
        current_one = hashlib.sha256(der).hexdigest()
        # compare_digest: tempo constante, como para qualquer comparacao de segredo.
        if not hmac.compare_digest(current_one, self._impressao):
            self.close()
            raise ConnectionFailed("o certificado do servidor nao confere com a impressao fixada")


class Client:
    def __init__(self, base_url: str, headers: dict[str, str], fingerprint_sha256: str = "",
                 timeout: float = 30.0):
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("base_url deve ser http(s)://host[:porta]")
        if parts.scheme == "http" and parts.hostname not in _LOOPBACK:
            raise ValueError("sem TLS so em loopback: use https:// (e a impressao do certificado)")
        self._https = parts.scheme == "https"
        self._host = parts.hostname
        self._port = parts.port or (443 if self._https else 80)
        self._prefix = parts.path.rstrip("/")
        self._headers = dict(headers)
        self._impressao = normalize_fingerprint(fingerprint_sha256)
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"Cliente({self._host}:{self._port})"

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        if not self._https:
            return http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        if not self._impressao:
            return http.client.HTTPSConnection(self._host, self._port, timeout=timeout,
                                               context=ssl.create_default_context())
        # A cadeia nao e validada porque o certificado e autoassinado; quem autentica o
        # servidor e a comparacao da impressao em _ConexaoFixada.connect. Por isso os tres
        # avisos abaixo sao falsos positivos revisados (teste com pin errado e sem pin).
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 na linha seguinte
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False  # NOSONAR - identidade por impressao fixada
        context.verify_mode = ssl.CERT_NONE  # NOSONAR - identidade por impressao fixada
        return _PinnedConnection(self._host, self._port, timeout=timeout, context=context,
                              fingerprint=self._impressao)

    def request(self, method: str, path: str, *, form: dict | None = None,
                   json_body: object = None, timeout: float | None = None) -> Response:
        """`timeout` (s) vale so para esta chamada: uma sonda de saude precisa de poucos segundos,
        enquanto uma instalacao longa usa o padrao do cliente."""
        headers = dict(self._headers)
        body: bytes | None = None
        if form is not None:
            body = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        connection = self._connection(self._timeout if timeout is None else timeout)
        try:
            connection.request(method, self._prefix + path, body=body, headers=headers)
            response = connection.getresponse()
            raw_text = response.read(RESPOSTA_MAX + 1)
            reason = response.reason or ""
            status = response.status
        except ConnectionFailed:
            raise
        except (OSError, http.client.HTTPException) as error:
            # So o tipo e a mensagem do erro de rede: nunca cabecalho nem corpo enviado.
            raise ConnectionFailed(f"{type(error).__name__} ao falar com {self._host}:{self._port}") from None
        finally:
            connection.close()
        if len(raw_text) > RESPOSTA_MAX:
            raise ConnectionFailed("resposta grande demais")
        text = raw_text.decode("utf-8", errors="replace")
        # O Proxmox explica o 403/500 na linha de status, nao no corpo.
        if not text.strip() and status >= 400:
            text = reason
        try:
            data = json.loads(text) if text.strip() else None
        except ValueError:
            data = None
        return Response(status, data, text)
