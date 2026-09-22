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


class ErroDeConexao(Exception):
    """Nao conectou, certificado nao confere ou resposta invalida."""


@dataclass(frozen=True)
class Resposta:
    status: int
    json: object
    texto: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def normalizar_impressao(texto: str) -> str:
    """Aceita `9F:92:...` (como o verificar-broker-acesso.ps1 imprime) ou hex corrido."""
    if not texto.strip():
        return ""
    limpo = re.sub(r"[^0-9a-fA-F]", "", texto).lower()
    # Texto nao vazio que nao vira 64 digitos e erro de digitacao: aceitar como "sem
    # impressao" desligaria o pin em silencio.
    if not _IMPRESSAO_RE.fullmatch(limpo):
        raise ValueError("impressao SHA-256 invalida: esperados 64 digitos hexadecimais")
    return limpo


class _ConexaoFixada(http.client.HTTPSConnection):
    def __init__(self, *args, impressao: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._impressao = impressao

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True) or b""  # type: ignore[union-attr]
        atual = hashlib.sha256(der).hexdigest()
        # compare_digest: tempo constante, como para qualquer comparacao de segredo.
        if not hmac.compare_digest(atual, self._impressao):
            self.close()
            raise ErroDeConexao("o certificado do servidor nao confere com a impressao fixada")


class Cliente:
    def __init__(self, base_url: str, cabecalhos: dict[str, str], impressao_sha256: str = "",
                 timeout: float = 30.0):
        partes = urlsplit(base_url)
        if partes.scheme not in ("http", "https") or not partes.hostname:
            raise ValueError("base_url deve ser http(s)://host[:porta]")
        if partes.scheme == "http" and partes.hostname not in _LOOPBACK:
            raise ValueError("sem TLS so em loopback: use https:// (e a impressao do certificado)")
        self._https = partes.scheme == "https"
        self._host = partes.hostname
        self._porta = partes.port or (443 if self._https else 80)
        self._prefixo = partes.path.rstrip("/")
        self._cabecalhos = dict(cabecalhos)
        self._impressao = normalizar_impressao(impressao_sha256)
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"Cliente({self._host}:{self._porta})"

    def _conexao(self, timeout: float) -> http.client.HTTPConnection:
        if not self._https:
            return http.client.HTTPConnection(self._host, self._porta, timeout=timeout)
        if not self._impressao:
            return http.client.HTTPSConnection(self._host, self._porta, timeout=timeout,
                                               context=ssl.create_default_context())
        # A cadeia nao e validada porque o certificado e autoassinado; quem autentica o
        # servidor e a comparacao da impressao em _ConexaoFixada.connect. Por isso os tres
        # avisos abaixo sao falsos positivos revisados (teste com pin errado e sem pin).
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # NOSONAR - TLS >= 1.2 na linha seguinte
        contexto.minimum_version = ssl.TLSVersion.TLSv1_2
        contexto.check_hostname = False  # NOSONAR - identidade por impressao fixada
        contexto.verify_mode = ssl.CERT_NONE  # NOSONAR - identidade por impressao fixada
        return _ConexaoFixada(self._host, self._porta, timeout=timeout, context=contexto,
                              impressao=self._impressao)

    def requisitar(self, metodo: str, caminho: str, *, form: dict | None = None,
                   json_corpo: object = None, timeout: float | None = None) -> Resposta:
        """`timeout` (s) vale so para esta chamada: uma sonda de saude precisa de poucos segundos,
        enquanto uma instalacao longa usa o padrao do cliente."""
        cabecalhos = dict(self._cabecalhos)
        corpo: bytes | None = None
        if form is not None:
            corpo = urlencode(form).encode()
            cabecalhos["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_corpo is not None:
            corpo = json.dumps(json_corpo).encode()
            cabecalhos["Content-Type"] = "application/json"
        conexao = self._conexao(self._timeout if timeout is None else timeout)
        try:
            conexao.request(metodo, self._prefixo + caminho, body=corpo, headers=cabecalhos)
            resposta = conexao.getresponse()
            bruto = resposta.read(RESPOSTA_MAX + 1)
            motivo = resposta.reason or ""
            status = resposta.status
        except ErroDeConexao:
            raise
        except (OSError, http.client.HTTPException) as erro:
            # So o tipo e a mensagem do erro de rede: nunca cabecalho nem corpo enviado.
            raise ErroDeConexao(f"{type(erro).__name__} ao falar com {self._host}:{self._porta}") from None
        finally:
            conexao.close()
        if len(bruto) > RESPOSTA_MAX:
            raise ErroDeConexao("resposta grande demais")
        texto = bruto.decode("utf-8", errors="replace")
        # O Proxmox explica o 403/500 na linha de status, nao no corpo.
        if not texto.strip() and status >= 400:
            texto = motivo
        try:
            dados = json.loads(texto) if texto.strip() else None
        except ValueError:
            dados = None
        return Resposta(status, dados, texto)
