"""Cliente do broker de provisionamento (painel -> broker). So stdlib.

O painel NAO guarda credencial de Proxmox nem de OPNsense; ele guarda so o token do
broker. Quem esta por tras dele (broker/) valida tudo de novo, entao este modulo e fino de
proposito: monta o pedido, fixa o certificado e devolve o JSON.

Duas regras de seguranca, iguais as do lado do broker (broker/conexao.py):

- **TLS fixado por impressao SHA-256** (`GAMEPANEL_BROKER_CERT_SHA256`), nunca verify=False.
  Sem impressao vale a validacao normal da cadeia. Sem TLS so em loopback, ou com
  `permitir_http` (o compose de desenvolvimento).
- **Nenhuma mensagem de erro carrega o token ou o corpo enviado.**

As funcoes publicas sao chamadas SEMPRE pelo modulo (`broker_client.criar(...)`), nunca
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

    def __init__(self, mensagem: str, status: int = 0, codigo: str = ""):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status
        self.codigo = codigo


_config: dict = {}


def normalizar_impressao(texto: str) -> str:
    if not texto.strip():
        return ""
    limpo = re.sub(r"[^0-9a-fA-F]", "", texto).lower()
    # Texto nao vazio que nao vira 64 digitos e erro de digitacao: aceitar como "sem
    # impressao" desligaria o pin em silencio.
    if not _IMPRESSAO_RE.fullmatch(limpo):
        raise ValueError("impressao SHA-256 invalida: esperados 64 digitos hexadecimais")
    return limpo


def configurar(url: str, token: str, impressao_sha256: str = "", permitir_http: bool = False) -> None:
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ValueError("GAMEPANEL_BROKER_URL deve ser http(s)://host[:porta]")
    if partes.scheme == "http" and partes.hostname not in _LOOPBACK and not permitir_http:
        raise ValueError("sem TLS so em loopback: use https:// e GAMEPANEL_BROKER_CERT_SHA256")
    if len(token) < TOKEN_MINIMO:
        raise ValueError(f"o token do broker precisa ter ao menos {TOKEN_MINIMO} caracteres")
    _config.clear()
    _config.update(
        https=partes.scheme == "https", host=partes.hostname,
        porta=partes.port or (443 if partes.scheme == "https" else 80),
        prefixo=partes.path.rstrip("/"), token=token,
        impressao=normalizar_impressao(impressao_sha256),
    )


def configurado() -> bool:
    return bool(_config)


class _ConexaoFixada(http.client.HTTPSConnection):
    def __init__(self, *args, impressao: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._impressao = impressao

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True) or b""  # type: ignore[union-attr]
        # compare_digest: tempo constante, como para qualquer comparacao de segredo.
        if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self._impressao):
            self.close()
            raise BrokerError("o certificado do broker nao confere com a impressao fixada")


def _conexao() -> http.client.HTTPConnection:
    c = _config
    if not c["https"]:
        return http.client.HTTPConnection(c["host"], c["porta"], timeout=TIMEOUT)
    if not c["impressao"]:
        return http.client.HTTPSConnection(c["host"], c["porta"], timeout=TIMEOUT,
                                           context=ssl.create_default_context())
    # A cadeia nao e validada porque o certificado do broker e autoassinado; quem o autentica
    # e a comparacao da impressao em _ConexaoFixada.connect. Os avisos abaixo sao falsos
    # positivos revisados (o teste com pin errado e sem pin prova).
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 na linha seguinte
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.check_hostname = False  # NOSONAR - identidade por impressao fixada
    contexto.verify_mode = ssl.CERT_NONE  # NOSONAR - identidade por impressao fixada
    return _ConexaoFixada(c["host"], c["porta"], timeout=TIMEOUT, context=contexto,
                          impressao=c["impressao"])


def _requisitar(metodo: str, caminho: str, corpo: object = None, ator: str = ""):
    if not configurado():
        raise BrokerError("o broker nao esta configurado neste painel")
    cabecalhos = {"Authorization": f"Bearer {_config['token']}", "Accept": "application/json"}
    if ator:
        cabecalhos["X-Ator"] = ator
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo).encode()
        cabecalhos["Content-Type"] = "application/json"
    conexao = _conexao()
    try:
        conexao.request(metodo, _config["prefixo"] + caminho, body=dados, headers=cabecalhos)
        resposta = conexao.getresponse()
        bruto = resposta.read(RESPOSTA_MAX + 1)
        status = resposta.status
    except BrokerError:
        raise
    except (OSError, http.client.HTTPException) as erro:
        # So o tipo do erro: nunca cabecalho (token) nem corpo enviado.
        raise BrokerError(f"nao consegui falar com o broker ({type(erro).__name__})") from None
    finally:
        conexao.close()
    if len(bruto) > RESPOSTA_MAX:
        raise BrokerError("resposta grande demais do broker")
    try:
        json_resposta = json.loads(bruto.decode("utf-8", errors="replace")) if bruto.strip() else None
    except ValueError:
        json_resposta = None
    if status >= 400:
        mensagem = json_resposta.get("erro") if isinstance(json_resposta, dict) else None
        codigo = json_resposta.get("codigo", "") if isinstance(json_resposta, dict) else ""
        raise BrokerError(str(mensagem or f"o broker respondeu HTTP {status}")[:300], status, str(codigo))
    return json_resposta


def _lista(dados: object) -> list:
    if not isinstance(dados, list):
        raise BrokerError("resposta inesperada do broker")
    return dados


def _objeto(dados: object) -> dict:
    if not isinstance(dados, dict):
        raise BrokerError("resposta inesperada do broker")
    return dados


# --- verbos (o broker nao tem nenhum outro) ---------------------------------------------

def saude() -> dict:
    return _objeto(_requisitar("GET", "/v1/saude"))


def catalogo() -> list:
    return _lista(_requisitar("GET", "/v1/catalogo"))


def adicionar_jogo(dados: dict, ator: str) -> dict:
    return _objeto(_requisitar("POST", "/v1/catalogo", dados, ator))


def instancias() -> list:
    return _lista(_requisitar("GET", "/v1/instancias"))


def criar(jogo: str, nome: str, ator: str) -> dict:
    return _objeto(_requisitar("POST", "/v1/instancias", {"jogo": jogo, "nome": nome}, ator))


def operacao(op_id: str) -> dict:
    return _objeto(_requisitar("GET", f"/v1/operacoes/{quote(op_id, safe='')}"))


def desativar(instancia_id: int, ator: str) -> dict:
    return _objeto(_requisitar("POST", f"/v1/instancias/{int(instancia_id)}/desativar", {}, ator))


def remover(instancia_id: int, confirma: str, ator: str, somente_banco: bool = False) -> dict:
    corpo = {"confirma": confirma, "somente_banco": bool(somente_banco)}
    return _objeto(_requisitar("DELETE", f"/v1/instancias/{int(instancia_id)}", corpo, ator))
