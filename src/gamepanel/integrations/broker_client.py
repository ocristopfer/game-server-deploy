"""Cliente do broker de provisionamento (painel -> broker). So stdlib.

O painel NAO guarda credencial de Proxmox nem de OPNsense; ele guarda so o token do
broker. Quem esta por tras dele (broker/) valida tudo de novo, entao este modulo e fino de
proposito: monta o pedido, fixa o certificado e devolve o JSON.

Duas regras de seguranca, iguais as do lado do broker (broker/conexao.py):

- **TLS fixado por impressao SHA-256** (`GAMEPANEL_BROKER_CERT_SHA256`), nunca verify=False.
  Sem impressao vale a validacao normal da cadeia. Sem TLS so em loopback, ou com
  `permitir_http` (o compose de desenvolvimento).
- **Nenhuma mensagem de erro carrega o token ou o corpo enviado.**

As funcoes publicas sao chamadas SEMPRE pelo modulo (`broker_client.create(...)`), nunca
importadas por nome: e assim que os testes as trocam por falsas com `monkeypatch`.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import ssl
from urllib.parse import quote, urlsplit

TIMEOUT = 30.0
RESPOSTA_MAX = 2_000_000
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_IMPRESSAO_RE = re.compile(r"[0-9a-f]{64}")
TOKEN_MINIMO = 32


class BrokerError(Exception):
    """O broker recusou o pedido (mensagem explicavel) ou nao foi possivel falar com ele."""

    def __init__(self, message: str, status: int = 0, codigo: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.codigo = codigo


_config: dict = {}


def normalize_fingerprint(text: str) -> str:
    if not text.strip():
        return ""
    clean = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    # Texto nao vazio que nao vira 64 digitos e erro de digitacao: aceitar como "sem
    # impressao" desligaria o pin em silencio.
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
        # compare_digest: tempo constante, como para qualquer comparacao de segredo.
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self._impressao):
            self.close()
            raise BrokerError("o certificado do broker nao confere com a impressao fixada")


def _connection() -> http.client.HTTPConnection:
    c = _config
    if not c["https"]:
        return http.client.HTTPConnection(c["host"], c["porta"], timeout=TIMEOUT)
    if not c["fingerprint"]:
        return http.client.HTTPSConnection(c["host"], c["porta"], timeout=TIMEOUT,
                                           context=ssl.create_default_context())
    # A cadeia nao e validada porque o certificado do broker e autoassinado; quem o autentica
    # e a comparacao da impressao em _ConexaoFixada.connect. Os avisos abaixo sao falsos
    # positivos revisados (o teste com pin errado e sem pin prova).
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 na linha seguinte
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False  # NOSONAR - identidade por impressao fixada
    context.verify_mode = ssl.CERT_NONE  # NOSONAR - identidade por impressao fixada
    return _PinnedConnection(c["host"], c["porta"], timeout=TIMEOUT, context=context,
                          fingerprint=c["fingerprint"])


def _request(method: str, path: str, body: object = None, actor: str = ""):
    if not is_configured():
        raise BrokerError("o broker nao esta configurado neste painel")
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
        # So o tipo do erro: nunca cabecalho (token) nem corpo enviado.
        raise BrokerError(f"nao consegui falar com o broker ({type(failure).__name__})") from None
    finally:
        connection.close()
    if len(raw_text) > RESPOSTA_MAX:
        raise BrokerError("resposta grande demais do broker")
    try:
        json_resposta = json.loads(raw_text.decode("utf-8", errors="replace")) if raw_text.strip() else None
    except ValueError:
        json_resposta = None
    if status >= 400:
        message = json_resposta.get("erro") if isinstance(json_resposta, dict) else None
        code = json_resposta.get("codigo", "") if isinstance(json_resposta, dict) else ""
        raise BrokerError(str(message or f"o broker respondeu HTTP {status}")[:300], status, str(code))
    return json_resposta


def _as_list(data: object) -> list:
    if not isinstance(data, list):
        raise BrokerError("resposta inesperada do broker")
    return data


def _as_object(data: object) -> dict:
    if not isinstance(data, dict):
        raise BrokerError("resposta inesperada do broker")
    return data


# --- verbos (o broker nao tem nenhum outro) ---------------------------------------------

def health() -> dict:
    return _as_object(_request("GET", "/v1/health"))


def catalog() -> list:
    return _as_list(_request("GET", "/v1/catalog"))


def add_game(data: dict, actor: str) -> dict:
    return _as_object(_request("POST", "/v1/catalog", data, actor))


def instances() -> list:
    return _as_list(_request("GET", "/v1/instances"))


def create(game: str, name: str, actor: str) -> dict:
    return _as_object(_request("POST", "/v1/instances", {"game": game, "name": name}, actor))


def operation(op_id: str) -> dict:
    return _as_object(_request("GET", f"/v1/operations/{quote(op_id, safe='')}"))


def deactivate(instance_id: int, actor: str) -> dict:
    return _as_object(_request("POST", f"/v1/instances/{int(instance_id)}/deactivate", {}, actor))


def remove(instance_id: int, confirmation: str, actor: str, db_only: bool = False) -> dict:
    body = {"confirmation": confirmation, "db_only": bool(db_only)}
    return _as_object(_request("DELETE", f"/v1/instances/{int(instance_id)}", body, actor))
