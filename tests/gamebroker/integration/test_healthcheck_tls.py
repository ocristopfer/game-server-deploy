"""`gamebroker.healthcheck` against a real HTTPS server with a self-signed certificate - the
broker's own setup. Needs the `openssl` command (skipped without it)."""
from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gamebroker import healthcheck

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl ausente")
TOKEN = "t" * 40


def _cert(folder, name):
    key, cert = folder / f"{name}.key", folder / f"{name}.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=gamebroker", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    return key, cert


@pytest.fixture
def broker(tmp_path, monkeypatch):
    key, cert = _cert(tmp_path, "real")
    answer = {"status": 200, "body": {"broker": True, "proxmox": False, "opnsense": False}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path == "/v1/health" and self.headers.get("Authorization") == f"Bearer {TOKEN}"
            status = answer["status"] if ok else 401
            body = json.dumps(answer["body"] if ok else {"erro": "token"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # The same TLS 1.2 floor as the real clients: the test server has no reason to offer less.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n")
    monkeypatch.setattr(healthcheck, "TOKEN_FILE", str(token_file))
    monkeypatch.setattr(healthcheck, "CERT_FILE", str(cert))
    yield server.server_address[1], answer, tmp_path
    server.shutdown()


def test_broker_saudavel_mesmo_com_proxmox_e_opnsense_fora(broker):
    port, _, _ = broker
    assert healthcheck.check(port) == ""
    assert healthcheck.main(["--port", str(port)]) == 0


def test_broker_que_nao_se_diz_saudavel_falha(broker):
    port, answer, _ = broker
    answer["body"] = {"broker": False}
    assert healthcheck.check(port) != ""


def test_token_errado_falha(broker, monkeypatch):
    port, _, tmp_path = broker
    (tmp_path / "token").write_text("outro-token")
    assert healthcheck.check(port) == "HTTP 401"


def test_certificado_que_nao_e_o_do_ct_e_recusado(broker, monkeypatch):
    port, _, tmp_path = broker
    _key, other = _cert(tmp_path, "outro")
    monkeypatch.setattr(healthcheck, "CERT_FILE", str(other))
    assert healthcheck.check(port).startswith("no answer")
