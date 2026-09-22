#!/usr/bin/env python3
"""Testes do cliente do broker (`broker_client`): o que vai no fio e o que NUNCA vaza.

    pytest admin/test_broker_client.py

Fala com um servidor HTTP de verdade em 127.0.0.1 (stdlib), nao com um mock: assim o que se
confere e o pedido montado, e nao a chamada de uma funcao. O TLS fixado usa o binario
`openssl` para gerar um certificado de teste; sem ele esses casos sao pulados.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gamepanel.integrations import broker_client as bc

TOKEN = "t" * 40


class Servidor:
    """Servidor HTTP de teste: guarda cada pedido e responde o que o teste mandar."""

    def __init__(self) -> None:
        self.pedidos: list[dict] = []
        self.resposta: tuple[int, object] = (200, {})
        servidor = self

        class Manipulador(BaseHTTPRequestHandler):
            def _tratar(self) -> None:
                tamanho = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(tamanho).decode() if tamanho else ""
                servidor.pedidos.append({
                    "metodo": self.command, "caminho": self.path,
                    "cabecalhos": {k.lower(): v for k, v in self.headers.items()},
                    "corpo": json.loads(body) if body else None,
                })
                status, data = servidor.resposta
                raw = (data if isinstance(data, str) else json.dumps(data)).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_DELETE = _tratar

            def log_message(self, *_a) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    def parar(self) -> None:
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def servidor(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    falso = Servidor()
    bc.configure(falso.url, TOKEN)
    yield falso
    falso.parar()


# --- o que vai no fio -------------------------------------------------------------------------

def test_todo_pedido_leva_o_token_e_o_ator(servidor):
    bc.create("alfa", "Um", "chefe")
    pedido = servidor.pedidos[0]
    assert pedido["cabecalhos"]["authorization"] == f"Bearer {TOKEN}"
    assert pedido["cabecalhos"]["x-ator"] == "chefe"
    assert (pedido["metodo"], pedido["caminho"]) == ("POST", "/v1/instancias")
    assert pedido["corpo"] == {"jogo": "alfa", "nome": "Um"}


def test_consultas_nao_mandam_ator_nem_corpo(servidor):
    servidor.resposta = (200, [])
    bc.catalog()
    bc.instances()
    assert [p["caminho"] for p in servidor.pedidos] == ["/v1/catalogo", "/v1/instancias"]
    assert all(p["corpo"] is None and "x-ator" not in p["cabecalhos"] for p in servidor.pedidos)


def test_verbos_e_caminhos(servidor):
    bc.deactivate(7, "chefe")
    bc.remove(7, "Um", "chefe", db_only=True)
    bc.add_game({"chave": "x"}, "chefe")
    bc.operation("a" * 32)
    bc.health()
    assert [(p["metodo"], p["caminho"]) for p in servidor.pedidos] == [
        ("POST", "/v1/instancias/7/desativar"), ("DELETE", "/v1/instancias/7"),
        ("POST", "/v1/catalogo"), ("GET", f"/v1/operacoes/{'a' * 32}"), ("GET", "/v1/saude")]
    assert servidor.pedidos[1]["corpo"] == {"confirma": "Um", "somente_banco": True}


def test_id_de_operacao_e_codificado_no_caminho(servidor):
    bc.operation("../../etc/passwd")
    assert servidor.pedidos[0]["caminho"] == "/v1/operacoes/..%2F..%2Fetc%2Fpasswd"


def test_id_de_instancia_precisa_ser_inteiro(servidor):
    with pytest.raises(ValueError):
        bc.deactivate("7; drop", "chefe")  # type: ignore[arg-type]
    assert servidor.pedidos == []


def test_prefixo_da_url_e_respeitado(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    falso = Servidor()
    try:
        bc.configure(falso.url + "/broker/", TOKEN)
        falso.resposta = (200, {})
        bc.health()
        assert falso.pedidos[0]["caminho"] == "/broker/v1/saude"
    finally:
        falso.parar()


# --- erros ----------------------------------------------------------------------------------------

def test_recusa_do_broker_vira_erro_com_mensagem_status_e_codigo(servidor):
    servidor.resposta = (429, {"erro": "limite de 8 instancias atingido", "codigo": "cota"})
    with pytest.raises(bc.BrokerError) as error:
        bc.create("alfa", "x", "chefe")
    assert error.value.message == "limite de 8 instancias atingido"
    assert (error.value.status, error.value.codigo) == (429, "cota")


def test_erro_sem_corpo_conhecido_tem_mensagem_generica(servidor):
    servidor.resposta = (502, "<html>bad gateway</html>")
    with pytest.raises(bc.BrokerError, match="HTTP 502"):
        bc.health()


def test_mensagem_de_erro_e_limitada(servidor):
    servidor.resposta = (400, {"erro": "x" * 5000, "codigo": "validacao"})
    with pytest.raises(bc.BrokerError) as error:
        bc.health()
    assert len(error.value.message) <= 300


def test_conexao_recusada_nao_vaza_o_token(servidor):
    servidor.parar()
    with pytest.raises(bc.BrokerError) as error:
        bc.health()
    assert TOKEN not in str(error.value)
    assert "nao consegui falar com o broker" in str(error.value)


@pytest.mark.parametrize("funcao", [bc.catalog, bc.instances])
def test_lista_que_nao_e_lista_e_erro(servidor, funcao):
    servidor.resposta = (200, {"nao": "e lista"})
    with pytest.raises(bc.BrokerError, match="inesperada"):
        funcao()


def test_objeto_que_nao_e_objeto_e_erro(servidor):
    servidor.resposta = (200, [1, 2])
    with pytest.raises(bc.BrokerError, match="inesperada"):
        bc.health()


def test_sem_configurar_e_erro_claro(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(bc.BrokerError, match="nao esta configurado"):
        bc.health()


# --- configuracao ------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["ftp://x", "sem-esquema", "https://", "http://broker.exemplo:8443"])
def test_url_invalida_ou_sem_tls_fora_do_loopback(monkeypatch, url):
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(ValueError):
        bc.configure(url, TOKEN)


def test_http_fora_do_loopback_so_com_permissao_explicita(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    bc.configure("http://broker:8090", TOKEN, allow_http=True)
    assert bc.is_configured()


def test_token_curto_e_recusado(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(ValueError, match="32 caracteres"):
        bc.configure("https://broker:8443", "curto")


@pytest.mark.parametrize("ruim", ["9F:92", "zz" * 32, "9F" * 33])
def test_impressao_invalida_e_erro_nao_ausencia(monkeypatch, ruim):
    """Impressao digitada errada NAO pode virar 'sem impressao' (desligaria o pin)."""
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(ValueError, match="64 digitos"):
        bc.configure("https://broker:8443", TOKEN, ruim)


def test_impressao_aceita_o_formato_do_script_de_verificacao():
    assert bc.normalize_fingerprint(":".join(["9F"] * 32)) == "9f" * 32
    assert bc.normalize_fingerprint("") == ""


# --- TLS fixado -----------------------------------------------------------------------------------------

@pytest.fixture
def broker_tls(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl nao esta no PATH")
    cert, chave = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=broker", "-keyout", str(chave), "-out", str(cert)],
                   check=True, capture_output=True)

    class Manipulador(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"broker": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(cert, chave)
    http.socket = contexto.wrap_socket(http.socket, server_side=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    impressao = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    yield f"https://127.0.0.1:{http.server_address[1]}", impressao
    http.shutdown()
    http.server_close()


def test_tls_com_a_impressao_certa(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, impressao = broker_tls
    bc.configure(url, TOKEN, impressao)
    assert bc.health() == {"broker": True}


def test_tls_com_impressao_errada_e_recusado(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, _ = broker_tls
    bc.configure(url, TOKEN, "00" * 32)
    with pytest.raises(bc.BrokerError, match="nao confere"):
        bc.health()


def test_tls_autoassinado_sem_impressao_nao_passa(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, _ = broker_tls
    bc.configure(url, TOKEN)
    with pytest.raises(bc.BrokerError, match="nao consegui falar"):
        bc.health()
