#!/usr/bin/env python3
"""Tests for the broker client (`broker_client`): what goes on the wire and what NEVER leaks.

    pytest admin/test_broker_client.py

It talks to a real HTTP server on 127.0.0.1 (stdlib), not a mock: that way what is checked
is the request as built, not a function call. Pinned TLS uses the `openssl` binary to
generate a test certificate; without it those cases are skipped.
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


class FakeServer:
    """Test HTTP server: stores each request and answers whatever the test says."""

    def __init__(self) -> None:
        self.pedidos: list[dict] = []
        self.resposta: tuple[int, object] = (200, {})
        server = self

        class Manipulador(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                size = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(size).decode() if size else ""
                server.pedidos.append({
                    "metodo": self.command, "caminho": self.path,
                    "cabecalhos": {k.lower(): v for k, v in self.headers.items()},
                    "corpo": json.loads(body) if body else None,
                })
                status, data = server.resposta
                raw = (data if isinstance(data, str) else json.dumps(data)).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_DELETE = _handle

            def log_message(self, *_a) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    def stop_it(self) -> None:
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    fake = FakeServer()
    bc.configure(fake.url, TOKEN)
    yield fake
    fake.stop_it()


# --- what goes on the wire --------------------------------------------------------------------

def test_todo_pedido_leva_o_token_e_o_ator(server):
    bc.create("alfa", "Um", "chefe")
    request_body = server.pedidos[0]
    assert request_body["cabecalhos"]["authorization"] == f"Bearer {TOKEN}"
    assert request_body["cabecalhos"]["x-actor"] == "chefe"
    assert (request_body["metodo"], request_body["caminho"]) == ("POST", "/v1/instances")
    assert request_body["corpo"] == {"game": "alfa", "name": "Um"}


def test_consultas_nao_mandam_ator_nem_corpo(server):
    server.resposta = (200, [])
    bc.catalog()
    bc.instances()
    assert [p["caminho"] for p in server.pedidos] == ["/v1/catalog", "/v1/instances"]
    assert all(p["corpo"] is None and "x-actor" not in p["cabecalhos"] for p in server.pedidos)


def test_verbos_e_caminhos(server):
    bc.deactivate(7, "chefe")
    bc.remove(7, "Um", "chefe", db_only=True)
    bc.add_game({"key": "x"}, "chefe")
    bc.operation("a" * 32)
    bc.health()
    bc.update_info()
    bc.request_update("install", "chefe")
    assert [(p["metodo"], p["caminho"]) for p in server.pedidos] == [
        ("POST", "/v1/instances/7/deactivate"), ("DELETE", "/v1/instances/7"),
        ("POST", "/v1/catalog"), ("GET", f"/v1/operations/{'a' * 32}"), ("GET", "/v1/health"),
        ("GET", "/v1/update"), ("POST", "/v1/update")]
    assert server.pedidos[1]["corpo"] == {"confirmation": "Um", "db_only": True}
    assert server.pedidos[-1]["corpo"] == {"action": "install"}


def test_id_de_operacao_e_codificado_no_caminho(server):
    bc.operation("../../etc/passwd")
    assert server.pedidos[0]["caminho"] == "/v1/operations/..%2F..%2Fetc%2Fpasswd"


def test_id_de_instancia_precisa_ser_inteiro(server):
    with pytest.raises(ValueError):
        bc.deactivate("7; drop", "chefe")  # type: ignore[arg-type]
    assert server.pedidos == []


def test_prefixo_da_url_e_respeitado(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    fake = FakeServer()
    try:
        bc.configure(fake.url + "/broker/", TOKEN)
        fake.resposta = (200, {})
        bc.health()
        assert fake.pedidos[0]["caminho"] == "/broker/v1/health"
    finally:
        fake.stop_it()


# --- errors ---------------------------------------------------------------------------------------

def test_recusa_do_broker_vira_erro_com_mensagem_status_e_codigo(server):
    server.resposta = (429, {"erro": "limite de 8 instancias atingido", "codigo": "cota"})
    with pytest.raises(bc.BrokerError) as error:
        bc.create("alfa", "x", "chefe")
    assert error.value.message == "limite de 8 instancias atingido"
    assert (error.value.status, error.value.code) == (429, "cota")


def test_erro_sem_corpo_conhecido_tem_mensagem_generica(server):
    server.resposta = (502, "<html>bad gateway</html>")
    with pytest.raises(bc.BrokerError, match="HTTP 502"):
        bc.health()


def test_mensagem_de_erro_e_limitada(server):
    server.resposta = (400, {"erro": "x" * 5000, "codigo": "validacao"})
    with pytest.raises(bc.BrokerError) as error:
        bc.health()
    assert len(error.value.message) <= 300


def test_http_client_recusada_nao_vaza_o_token(server):
    server.stop_it()
    with pytest.raises(bc.BrokerError) as error:
        bc.health()
    assert TOKEN not in str(error.value)
    assert "não consegui falar com o broker" in str(error.value)


@pytest.mark.parametrize("funcao", [bc.catalog, bc.instances])
def test_lista_que_nao_e_lista_e_erro(server, funcao):
    server.resposta = (200, {"nao": "e lista"})
    with pytest.raises(bc.BrokerError, match="inesperada"):
        funcao()


def test_objeto_que_nao_e_objeto_e_erro(server):
    server.resposta = (200, [1, 2])
    with pytest.raises(bc.BrokerError, match="inesperada"):
        bc.health()


def test_sem_configurar_e_erro_claro(monkeypatch):
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(bc.BrokerError, match="não está configurado"):
        bc.health()


# --- configuration ------------------------------------------------------------------------------------

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


@pytest.mark.parametrize("bad", ["9F:92", "zz" * 32, "9F" * 33])
def test_impressao_invalida_e_erro_nao_ausencia(monkeypatch, bad):
    """A mistyped fingerprint must NOT become 'no fingerprint' (that would turn the pin off)."""
    monkeypatch.setattr(bc, "_config", {})
    with pytest.raises(ValueError, match="64 digitos"):
        bc.configure("https://broker:8443", TOKEN, bad)


def test_impressao_aceita_o_formato_do_script_de_verificacao():
    assert bc.normalize_fingerprint(":".join(["9F"] * 32)) == "9f" * 32
    assert bc.normalize_fingerprint("") == ""


# --- pinned TLS -----------------------------------------------------------------------------------------

@pytest.fixture
def broker_tls(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl nao esta no PATH")
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=broker", "-keyout", str(key), "-out", str(cert)],
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
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # The same TLS 1.2 floor as the real clients: the test server has no reason to offer less.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    http.socket = context.wrap_socket(http.socket, server_side=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    yield f"https://127.0.0.1:{http.server_address[1]}", fingerprint
    http.shutdown()
    http.server_close()


def test_tls_com_a_impressao_certa(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, fingerprint = broker_tls
    bc.configure(url, TOKEN, fingerprint)
    assert bc.health() == {"broker": True}


def test_tls_com_impressao_errada_e_recusado(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, _ = broker_tls
    bc.configure(url, TOKEN, "00" * 32)
    with pytest.raises(bc.BrokerError, match="não confere"):
        bc.health()


def test_tls_autoassinado_sem_impressao_nao_passa(monkeypatch, broker_tls):
    monkeypatch.setattr(bc, "_config", {})
    url, _ = broker_tls
    bc.configure(url, TOKEN)
    with pytest.raises(bc.BrokerError, match="não consegui falar"):
        bc.health()
