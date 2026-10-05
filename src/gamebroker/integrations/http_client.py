"""Minimal HTTP client (stdlib only) for the Proxmox and OPNsense APIs.

Two security rules live here, so they do not depend on each caller remembering them:

- **TLS pinned by fingerprint.** Both use self-signed certificates. Instead of turning
  verification off (`verify=False`, which accepts ANY certificate), the client accepts only
  the certificate whose SHA-256 fingerprint is the configured one. Without a fingerprint,
  normal chain validation applies. Replacing the certificate on Proxmox requires updating the
  fingerprint - on purpose: that is what stops a "man in the middle" inside the LAN.
- **No TLS only on loopback** (tests). A token in plain HTTP over the network does not exist here.

Nothing in this module writes headers, tokens or request bodies into an error message: the
exception text ends up in the operation log and the panel displays it.
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
    """Could not connect, certificate does not match, or invalid response."""


@dataclass(frozen=True)
class Response:
    status: int
    json: object
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def normalize_fingerprint(text: str) -> str:
    """Accepts `9F:92:...` (as check-broker-access.ps1 prints it) or plain hex."""
    if not text.strip():
        return ""
    clean = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    # Non-empty text that does not become 64 digits is a typo: accepting it as "no
    # fingerprint" would silently turn the pin off.
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
        # compare_digest: constant time, as for any secret comparison.
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
        # The chain is not validated because the certificate is self-signed; what authenticates
        # the server is the fingerprint comparison in _ConexaoFixada.connect. That is why the
        # three warnings below are reviewed false positives (tested with a wrong pin and no pin).
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 on the next line
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False  # NOSONAR - identity via pinned fingerprint
        context.verify_mode = ssl.CERT_NONE  # NOSONAR - identity via pinned fingerprint
        return _PinnedConnection(self._host, self._port, timeout=timeout, context=context,
                              fingerprint=self._impressao)

    def request(self, method: str, path: str, *, form: dict | None = None,
                   json_body: object = None, timeout: float | None = None) -> Response:
        """`timeout` (s) applies only to this call: a health probe needs a few seconds,
        while a long installation uses the client's default."""
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
            # Only the network error's type and message: never headers or the body sent.
            raise ConnectionFailed(f"{type(error).__name__} ao falar com {self._host}:{self._port}") from None
        finally:
            connection.close()
        if len(raw_text) > RESPOSTA_MAX:
            raise ConnectionFailed("resposta grande demais")
        text = raw_text.decode("utf-8", errors="replace")
        # Proxmox explains the 403/500 in the status line, not in the body.
        if not text.strip() and status >= 400:
            text = reason
        try:
            data = json.loads(text) if text.strip() else None
        except ValueError:
            data = None
        return Response(status, data, text)
