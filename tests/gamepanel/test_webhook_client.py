"""Entrega de alerta em webhook (gamepanel.integrations.webhook_client).

So a recusa de URL invalida tinha teste antes da Fase 4 — o POST em si, nao. E ali
moram coisas que importam quando o canal fica mudo: o corpo tem de agradar Discord E
Slack, o motivo da recusa do destino tem de chegar a tela (senao um 400 por payload
torto e um 403 do Cloudflare ficam com a mesma cara), e um destino pendurado nao pode
segurar a volta do monitor.

O servidor aqui e um HTTP de verdade em loopback: a alternativa seria trocar o
`urllib` por um falso, e ai o teste passaria a exercitar o falso.
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
    """Guarda o que recebeu e responde o que o teste mandar responder."""

    def __init__(self, status: int = 204, body: bytes = b"", expects: float = 0.0):
        self.recebidos: list[dict] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            # Nome em maiusculas porque e o que o BaseHTTPRequestHandler procura.
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
                pass  # sem ruido no relatorio do pytest

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
    """A URL e uma credencial: um screenshot da tela nao pode dar escrita no canal."""
    masked = wc.mask_url("https://discord.com/api/webhooks/123456/token-secreto")
    assert "token-secreto" not in masked


# ------------------------------------------------------------------ envio

@pytest.mark.parametrize("url", ["", "nao-e-url", "file:///etc/passwd", "ftp://x/y"])
def test_url_invalida_e_recusada_antes_de_qualquer_socket(url):
    assert wc.send(url, "oi", 1, UA).startswith("URL invalida")


def test_envio_que_da_certo_devolve_string_vazia():
    with _FakeServer() as srv:
        assert wc.send(srv.url, "o servidor caiu", 5, UA) == ""
        assert len(srv.recebidos) == 1


def test_o_corpo_agrada_discord_e_slack_ao_mesmo_tempo():
    """'content' e o campo do Discord, 'text' o do Slack; cada um ignora o outro."""
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
    """Sem o corpo da resposta, um 400 por payload torto e um 403 por bloqueio ficam iguais."""
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
    """Um webhook quebrado nao pode derrubar o monitor junto."""
    # Porta fechada em loopback: recusa na hora, sem esperar timeout.
    error = wc.send("http://127.0.0.1:1/webhook", "oi", 1, UA)
    assert error.startswith("nao consegui chamar o webhook")


def test_destino_pendurado_respeita_o_prazo():
    """Sem prazo, um destino que nao responde seguraria a volta inteira do monitor."""
    with _FakeServer(expects=3) as srv:
        beginning = time.monotonic()
        error = wc.send(srv.url, "oi", 0.3, UA)
        spent = time.monotonic() - beginning
    assert error.startswith("nao consegui chamar o webhook")
    assert spent < 2
