"""Client for the provisioning broker (panel -> broker). Stdlib only.

The panel does NOT store Proxmox or OPNsense credentials; it only stores the broker's
token. Whatever sits behind it (broker/) validates everything again, so this module is thin
on purpose: it builds the request, pins the certificate and returns the JSON.

Two security rules, the same as on the broker side (gamebroker/integrations/http_client.py):

- **TLS pinned by SHA-256 fingerprint** (`GAMEPANEL_BROKER_CERT_SHA256`), never verify=False.
  Without a fingerprint the normal chain validation applies. No TLS only on loopback, or
  with `allow_http` (the development compose).
- **No error message carries the token or the request body.**

The public functions are ALWAYS called through the module (`broker_client.create(...)`),
never imported by name: that is how the tests swap them for fakes with `monkeypatch`.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import ssl
from urllib.parse import quote, urlsplit

from gamepanel.i18n import Message

TIMEOUT = 30.0
RESPOSTA_MAX = 2_000_000
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_IMPRESSAO_RE = re.compile(r"[0-9a-f]{64}")
TOKEN_MINIMO = 32


class BrokerError(Exception):
    """The broker refused the request (explainable message) or it could not be reached."""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


_config: dict = {}


def normalize_fingerprint(text: str) -> str:
    if not text.strip():
        return ""
    clean = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    # Non-empty text that does not become 64 digits is a typo: accepting it as "no
    # fingerprint" would silently turn the pin off.
    if not _IMPRESSAO_RE.fullmatch(clean):
        raise ValueError("impressao SHA-256 invalida: esperados 64 digitos hexadecimais")
    return clean


def configure(url: str, token: str, fingerprint_sha256: str = "", allow_http: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("GAMEPANEL_BROKER_URL deve ser http(s)://host[:porta]")
    if parts.scheme == "http" and parts.hostname not in _LOOPBACK and not allow_http:
        raise ValueError("sem TLS so em loopback: use https:// e GAMEPANEL_BROKER_CERT_SHA256")
    if len(token) < TOKEN_MINIMO:
        raise ValueError(f"o token do broker precisa ter ao menos {TOKEN_MINIMO} caracteres")
    _config.clear()
    _config.update(
        https=parts.scheme == "https", host=parts.hostname,
        porta=parts.port or (443 if parts.scheme == "https" else 80),
        prefixo=parts.path.rstrip("/"), token=token,
        fingerprint=normalize_fingerprint(fingerprint_sha256),
    )


def is_configured() -> bool:
    return bool(_config)


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, *args, fingerprint: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._impressao = fingerprint

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True) or b""  # type: ignore[union-attr]
        # compare_digest: constant time, as for any secret comparison.
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self._impressao):
            self.close()
            raise BrokerError(Message("broker.cert_mismatch"))


def _connection() -> http.client.HTTPConnection:
    c = _config
    if not c["https"]:
        return http.client.HTTPConnection(c["host"], c["porta"], timeout=TIMEOUT)
    if not c["fingerprint"]:
        return http.client.HTTPSConnection(c["host"], c["porta"], timeout=TIMEOUT,
                                           context=ssl.create_default_context())
    # The chain is not validated because the broker's certificate is self-signed; what
    # authenticates it is the fingerprint comparison in _PinnedConnection.connect. The warnings
    # below are reviewed false positives (the tests with a wrong pin and with no pin prove it).
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 on the next line
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False  # NOSONAR - identity via pinned fingerprint
    context.verify_mode = ssl.CERT_NONE  # NOSONAR - identity via pinned fingerprint
    return _PinnedConnection(c["host"], c["porta"], timeout=TIMEOUT, context=context,
                          fingerprint=c["fingerprint"])


def _request(method: str, path: str, body: object = None, actor: str = ""):
    if not is_configured():
        raise BrokerError(Message("broker.not_configured"))
    headers = {"Authorization": f"Bearer {_config['token']}", "Accept": "application/json"}
    if actor:
        headers["X-Actor"] = actor
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    connection = _connection()
    try:
        connection.request(method, _config["prefixo"] + path, body=data, headers=headers)
        response = connection.getresponse()
        raw_text = response.read(RESPOSTA_MAX + 1)
        status = response.status
    except BrokerError:
        raise
    except (OSError, http.client.HTTPException) as failure:
        # Only the error type: never a header (token) nor the request body.
        raise BrokerError(Message("broker.unreachable", kind=type(failure).__name__)) from None
    finally:
        connection.close()
    if len(raw_text) > RESPOSTA_MAX:
        raise BrokerError(Message("broker.reply_too_big"))
    try:
        json_resposta = json.loads(raw_text.decode("utf-8", errors="replace")) if raw_text.strip() else None
    except ValueError:
        json_resposta = None
    if status >= 400:
        message = json_resposta.get("erro") if isinstance(json_resposta, dict) else None
        code = json_resposta.get("codigo", "") if isinstance(json_resposta, dict) else ""
        # The broker's own sentence comes as it is (it is the broker's text, not a catalog key);
        # without one, the panel's sentence, as a `Message` so it follows the viewer's language.
        reason = str(message)[:300] if message else Message("broker.http_status", status=status)
        raise BrokerError(reason, status, str(code))
    return json_resposta


def _as_list(data: object) -> list:
    if not isinstance(data, list):
        raise BrokerError(Message("broker.unexpected_reply"))
    return data


def _as_object(data: object) -> dict:
    if not isinstance(data, dict):
        raise BrokerError(Message("broker.unexpected_reply"))
    return data


# --- verbs (the broker has no others) -------------------------------------------------

def health() -> dict:
    return _as_object(_request("GET", "/v1/health"))


def catalog() -> list:
    return _as_list(_request("GET", "/v1/catalog"))


def add_game(data: dict, actor: str) -> dict:
    return _as_object(_request("POST", "/v1/catalog", data, actor))


def game(key: str) -> dict:
    return _as_object(_request("GET", f"/v1/catalog/{quote(key, safe='')}"))


def update_game(key: str, data: dict, actor: str) -> dict:
    return _as_object(_request("PUT", f"/v1/catalog/{quote(key, safe='')}", data, actor))


def remove_game(key: str, actor: str) -> dict:
    """Delete a dynamic game; on an edited curated one, undo the edit (restores the curated)."""
    return _as_object(_request("DELETE", f"/v1/catalog/{quote(key, safe='')}", {}, actor))


def instances() -> list:
    return _as_list(_request("GET", "/v1/instances"))


def create(game: str, name: str, actor: str) -> dict:
    return _as_object(_request("POST", "/v1/instances", {"game": game, "name": name}, actor))


def preview(game: str) -> dict:
    """CT, IP and ports a creation of this game would get right now. Reserves nothing."""
    return _as_object(_request("GET", f"/v1/instances/preview?game={quote(game, safe='')}"))


def cancel(op_id: str, actor: str) -> dict:
    return _as_object(_request("POST", f"/v1/operations/{quote(op_id, safe='')}/cancel", {}, actor))


def operation(op_id: str) -> dict:
    return _as_object(_request("GET", f"/v1/operations/{quote(op_id, safe='')}"))


def deactivate(instance_id: int, actor: str) -> dict:
    return _as_object(_request("POST", f"/v1/instances/{int(instance_id)}/deactivate", {}, actor))


def remove(instance_id: int, confirmation: str, actor: str, db_only: bool = False) -> dict:
    body = {"confirmation": confirmation, "db_only": bool(db_only)}
    return _as_object(_request("DELETE", f"/v1/instances/{int(instance_id)}", body, actor))


def update_info() -> dict:
    """The broker's version and its updater's last status (`status` None = it never ran there)."""
    return _as_object(_request("GET", "/v1/update"))


def request_update(action: str, actor: str) -> dict:
    """Ask the broker's root updater to `check` or `install`; it runs within a second."""
    return _as_object(_request("POST", "/v1/update", {"action": action}, actor))
