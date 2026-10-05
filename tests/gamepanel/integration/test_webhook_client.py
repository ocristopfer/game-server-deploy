"""Alert delivery over webhook (gamepanel.integrations.webhook_client).

Only the refusal of an invalid URL had a test before Phase 4 - the POST itself did not. And
that is where things live that matter when the channel goes quiet: the body has to please
Discord AND Slack, the destination's reason for refusing has to reach the screen (otherwise
a 400 for a malformed payload and a 403 from Cloudflare look the same), and a hanging
destination must not hold up the monitor tick.

The server here is real HTTP on loopback: the alternative would be swapping `urllib` for a
fake, and then the test would be exercising the fake.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gamepanel.integrations import webhook_client as wc

UA = "GamePanel/teste"


class _FakeServer:
    """Keeps what it received and answers whatever the test tells it to."""

    def __init__(self, status: int = 204, body: bytes = b"", expects: float = 0.0):
        self.recebidos: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            # Uppercase name because that is what BaseHTTPRequestHandler looks for.
            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(size)
                server.recebidos.append({
                    "corpo": json.loads(raw.decode("utf-8")),
                    "content_type": self.headers.get("Content-Type", ""),
                    "user_agent": self.headers.get("User-Agent", ""),
                })
                if expects:
                    time.sleep(expects)
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def log_message(self, *_a):
                pass  # no noise in the pytest report

        self._http = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._http.server_address[1]}/webhook"
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._http.shutdown()
        self._http.server_close()


# ------------------------------------------------------------- mascara_url

@pytest.mark.parametrize(("url", "expected"), [
    ("https://discord.com/api/webhooks/123456/segredo-do-token",
     "discord.com/.../123456/********"),
    ("https://hooks.slack.com/serviceslongo", "hooks.slack.com/.../********"),
    ("https://exemplo.com", "exemplo.com"),
    ("", ""),
])
def test_mascara_mostra_o_canal_e_esconde_o_token(url, expected):
    assert wc.mask_url(url) == expected


def test_mascara_nao_deixa_o_token_aparecer():
    """The URL is a credential: a screenshot of the screen must not grant write access to the channel."""
    masked = wc.mask_url("https://discord.com/api/webhooks/123456/token-secreto")
    assert "token-secreto" not in masked


# ------------------------------------------------------------------ sending

@pytest.mark.parametrize("url", ["", "nao-e-url", "file:///etc/passwd", "ftp://x/y"])
def test_url_invalida_e_recusada_antes_de_qualquer_socket(url):
    assert wc.send(url, "oi", 1, UA).startswith("URL inválida")


def test_envio_que_da_certo_devolve_string_vazia():
    with _FakeServer() as srv:
        assert wc.send(srv.url, "o servidor caiu", 5, UA) == ""
        assert len(srv.recebidos) == 1


def test_o_corpo_agrada_discord_e_slack_ao_mesmo_tempo():
    """'content' is Discord's field, 'text' is Slack's; each ignores the other."""
    with _FakeServer() as srv:
        wc.send(srv.url, "**Palworld**\ncaiu", 5, UA)
    body = srv.recebidos[0]["corpo"]
    assert body["content"] == "**Palworld**\ncaiu"
    assert body["text"] == body["content"]
    assert srv.recebidos[0]["content_type"] == "application/json"


def test_manda_o_user_agent_configurado():
    with _FakeServer() as srv:
        wc.send(srv.url, "oi", 5, UA)
    assert srv.recebidos[0]["user_agent"] == UA


def test_recusa_do_destino_chega_com_codigo_e_motivo():
    """Without the response body, a 400 for a malformed payload and a 403 for blocking look the same."""
    body = json.dumps({"message": "Invalid Webhook Token"}).encode()
    with _FakeServer(status=401, body=body) as srv:
        error = wc.send(srv.url, "oi", 5, UA)
    assert "HTTP 401" in error
    assert "Invalid Webhook Token" in error


def test_recusa_sem_corpo_fica_so_no_codigo():
    with _FakeServer(status=403) as srv:
        error = wc.send(srv.url, "oi", 5, UA)
    assert error == "o webhook respondeu HTTP 403"


def test_motivo_longo_demais_e_cortado():
    body = b'{"message": "' + b"x" * 5000 + b'"}'
    with _FakeServer(status=400, body=body) as srv:
        error = wc.send(srv.url, "oi", 5, UA)
    assert len(error) < wc.ERROR_MAX + 100


def test_destino_fora_do_ar_vira_motivo_e_nao_excecao():
    """A broken webhook must not take the monitor down with it."""
    # Closed port on loopback: refused immediately, without waiting for a timeout.
    error = wc.send("http://127.0.0.1:1/webhook", "oi", 1, UA)
    assert error.startswith("não consegui chamar o webhook")


def test_destino_pendurado_respeita_o_prazo():
    """Without a deadline, a destination that does not answer would hold up the whole monitor tick."""
    with _FakeServer(expects=3) as srv:
        beginning = time.monotonic()
        error = wc.send(srv.url, "oi", 0.3, UA)
        spent = time.monotonic() - beginning
    assert error.startswith("não consegui chamar o webhook")
    assert spent < 2
