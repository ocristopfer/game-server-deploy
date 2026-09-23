"""Cliente HTTP: TLS fixado, loopback e mensagens de erro sem segredo."""
from __future__ import annotations

import hashlib
import shutil
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fake_http import FakeServer

from gamebroker.integrations.http_client import RESPOSTA_MAX, Client, ConnectionFailed, normalize_fingerprint

TOKEN = "segredo-que-nunca-pode-vazar"


def _echo(metodo, caminho, query, corpo, headers):
    return 200, {"metodo": metodo, "caminho": caminho, "query": query, "corpo": corpo,
                 "auth": headers.get("authorization"), "tipo": headers.get("content-type", "")}


@pytest.fixture
def echo_server():
    server = FakeServer(_echo)
    yield server
    server.stop()


def test_impressao_aceita_o_formato_do_script_de_verificacao():
    colon = ":".join(["9F"] * 32)
    assert normalize_fingerprint(colon) == "9f" * 32
    assert normalize_fingerprint("9F" * 32) == "9f" * 32
    assert normalize_fingerprint("") == ""


@pytest.mark.parametrize("ruim", ["9F:92", "zz" * 32, "9F" * 33])
def test_impressao_invalida(ruim):
    with pytest.raises(ValueError, match="64 digitos"):
        normalize_fingerprint(ruim)


@pytest.mark.parametrize("url", ["http://192.168.1.254:8006", "http://proxmox.local", "ftp://x", "sem-esquema", "https://"])
def test_url_insegura_ou_invalida_e_recusada(url):
    with pytest.raises(ValueError):
        Client(url, {})


def test_form_e_json_saem_no_formato_certo(echo_server):
    client = Client(echo_server.url, {"Authorization": f"Bearer {TOKEN}"})
    a = client.request("POST", "/x?y=1", form={"a": "b c", "d": 2}).json
    assert a["corpo"] == {"a": "b c", "d": "2"}
    assert a["tipo"] == "application/x-www-form-urlencoded"
    assert a["query"] == {"y": "1"}
    b = client.request("POST", "/x", json_corpo={"k": [1, 2]}).json
    assert b["corpo"] == {"k": [1, 2]}
    assert b["tipo"] == "application/json"
    assert b["auth"] == f"Bearer {TOKEN}"


def test_erro_sem_corpo_devolve_o_motivo_da_linha_de_status():
    server = FakeServer(lambda *_a: (403, "", "Permission check failed (/vms/399, VM.Allocate)"))
    try:
        response = Client(server.url, {}).request("GET", "/x")
    finally:
        server.stop()
    assert response.status == 403
    assert not response.ok
    assert "VM.Allocate" in response.text


def test_http_client_recusada_nao_vaza_o_token(echo_server):
    dead_port = echo_server.url
    echo_server.stop()
    client = Client(dead_port, {"Authorization": f"Bearer {TOKEN}"})
    with pytest.raises(ConnectionFailed) as error:
        client.request("GET", "/x")
    assert TOKEN not in str(error.value)
    assert TOKEN not in repr(client)


def test_resposta_gigante_e_recusada():
    server = FakeServer(lambda *_a: (200, "x" * (RESPOSTA_MAX + 10)))
    try:
        with pytest.raises(ConnectionFailed, match="grande demais"):
            Client(server.url, {}).request("GET", "/x")
    finally:
        server.stop()


def test_resposta_que_nao_e_json_vira_texto():
    server = FakeServer(lambda *_a: (200, "oi, sou texto"))
    try:
        response = Client(server.url, {}).request("GET", "/x")
    finally:
        server.stop()
    assert response.json is None
    assert response.text == "oi, sou texto"


# --- TLS fixado (precisa do binario openssl para gerar um certificado de teste) ----------

@pytest.fixture
def tls_server(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl nao esta no PATH")
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=teste", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)

    class Manipulador(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_a):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    http.socket = context.wrap_socket(http.socket, server_side=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    yield f"https://127.0.0.1:{http.server_address[1]}", hashlib.sha256(der).hexdigest()
    http.shutdown()
    http.server_close()


def test_tls_com_a_impressao_certa_conecta(tls_server):
    url, fingerprint = tls_server
    assert Client(url, {}, fingerprint_sha256=fingerprint).request("GET", "/").text == "ok"


def test_tls_aceita_a_impressao_com_dois_pontos(tls_server):
    url, fingerprint = tls_server
    formatted = ":".join(fingerprint[i:i + 2] for i in range(0, 64, 2)).upper()
    assert Client(url, {}, fingerprint_sha256=formatted).request("GET", "/").ok


def test_tls_com_impressao_errada_e_recusado(tls_server):
    url, _ = tls_server
    with pytest.raises(ConnectionFailed, match="nao confere"):
        Client(url, {}, fingerprint_sha256="00" * 32).request("GET", "/")


def test_tls_autoassinado_sem_impressao_nao_e_aceito(tls_server):
    """Sem impressao vale a validacao normal: certificado autoassinado NAO passa."""
    url, _ = tls_server
    with pytest.raises(ConnectionFailed):
        Client(url, {}).request("GET", "/")


# --- prazo por chamada -----------------------------------------------------------------------------

def _slow(segundos: float):
    def handler(*_a):
        time.sleep(segundos)
        return 200, {"ok": True}
    return handler


def test_prazo_da_chamada_vale_so_para_ela():
    server = FakeServer(_slow(0.8))
    try:
        client = Client(server.url, {}, timeout=30)
        with pytest.raises(ConnectionFailed, match="TimeoutError"):
            client.request("GET", "/x", timeout=0.2)
        assert client.request("GET", "/x").ok, "o prazo padrao do cliente nao foi alterado"
    finally:
        server.stop()
