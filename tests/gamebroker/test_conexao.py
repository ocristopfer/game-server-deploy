"""Cliente HTTP: TLS fixado, loopback e mensagens de erro sem segredo."""
from __future__ import annotations

import hashlib
import shutil
import ssl
import time
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gamebroker.conexao import Cliente, ErroDeConexao, RESPOSTA_MAX, normalizar_impressao
from gamebroker.http_falso import ServidorFalso

TOKEN = "segredo-que-nunca-pode-vazar"


def _eco(metodo, caminho, query, corpo, cabecalhos):
    return 200, {"metodo": metodo, "caminho": caminho, "query": query, "corpo": corpo,
                 "auth": cabecalhos.get("authorization"), "tipo": cabecalhos.get("content-type", "")}


@pytest.fixture
def eco():
    servidor = ServidorFalso(_eco)
    yield servidor
    servidor.parar()


def test_impressao_aceita_o_formato_do_script_de_verificacao():
    dois_pontos = ":".join(["9F"] * 32)
    assert normalizar_impressao(dois_pontos) == "9f" * 32
    assert normalizar_impressao("9F" * 32) == "9f" * 32
    assert normalizar_impressao("") == ""


@pytest.mark.parametrize("ruim", ["9F:92", "zz" * 32, "9F" * 33])
def test_impressao_invalida(ruim):
    with pytest.raises(ValueError, match="64 digitos"):
        normalizar_impressao(ruim)


@pytest.mark.parametrize("url", ["http://192.168.1.254:8006", "http://proxmox.local", "ftp://x", "sem-esquema", "https://"])
def test_url_insegura_ou_invalida_e_recusada(url):
    with pytest.raises(ValueError):
        Cliente(url, {})


def test_form_e_json_saem_no_formato_certo(eco):
    cliente = Cliente(eco.url, {"Authorization": f"Bearer {TOKEN}"})
    a = cliente.requisitar("POST", "/x?y=1", form={"a": "b c", "d": 2}).json
    assert a["corpo"] == {"a": "b c", "d": "2"}
    assert a["tipo"] == "application/x-www-form-urlencoded"
    assert a["query"] == {"y": "1"}
    b = cliente.requisitar("POST", "/x", json_corpo={"k": [1, 2]}).json
    assert b["corpo"] == {"k": [1, 2]}
    assert b["tipo"] == "application/json"
    assert b["auth"] == f"Bearer {TOKEN}"


def test_erro_sem_corpo_devolve_o_motivo_da_linha_de_status():
    servidor = ServidorFalso(lambda *_a: (403, "", "Permission check failed (/vms/399, VM.Allocate)"))
    try:
        resposta = Cliente(servidor.url, {}).requisitar("GET", "/x")
    finally:
        servidor.parar()
    assert resposta.status == 403
    assert not resposta.ok
    assert "VM.Allocate" in resposta.texto


def test_conexao_recusada_nao_vaza_o_token(eco):
    porta_morta = eco.url
    eco.parar()
    cliente = Cliente(porta_morta, {"Authorization": f"Bearer {TOKEN}"})
    with pytest.raises(ErroDeConexao) as erro:
        cliente.requisitar("GET", "/x")
    assert TOKEN not in str(erro.value)
    assert TOKEN not in repr(cliente)


def test_resposta_gigante_e_recusada():
    servidor = ServidorFalso(lambda *_a: (200, "x" * (RESPOSTA_MAX + 10)))
    try:
        with pytest.raises(ErroDeConexao, match="grande demais"):
            Cliente(servidor.url, {}).requisitar("GET", "/x")
    finally:
        servidor.parar()


def test_resposta_que_nao_e_json_vira_texto():
    servidor = ServidorFalso(lambda *_a: (200, "oi, sou texto"))
    try:
        resposta = Cliente(servidor.url, {}).requisitar("GET", "/x")
    finally:
        servidor.parar()
    assert resposta.json is None
    assert resposta.texto == "oi, sou texto"


# --- TLS fixado (precisa do binario openssl para gerar um certificado de teste) ----------

@pytest.fixture
def servidor_tls(tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl nao esta no PATH")
    cert, chave = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=teste", "-keyout", str(chave), "-out", str(cert)],
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
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.load_cert_chain(cert, chave)
    http.socket = contexto.wrap_socket(http.socket, server_side=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    yield f"https://127.0.0.1:{http.server_address[1]}", hashlib.sha256(der).hexdigest()
    http.shutdown()
    http.server_close()


def test_tls_com_a_impressao_certa_conecta(servidor_tls):
    url, impressao = servidor_tls
    assert Cliente(url, {}, impressao_sha256=impressao).requisitar("GET", "/").texto == "ok"


def test_tls_aceita_a_impressao_com_dois_pontos(servidor_tls):
    url, impressao = servidor_tls
    formatada = ":".join(impressao[i:i + 2] for i in range(0, 64, 2)).upper()
    assert Cliente(url, {}, impressao_sha256=formatada).requisitar("GET", "/").ok


def test_tls_com_impressao_errada_e_recusado(servidor_tls):
    url, _ = servidor_tls
    with pytest.raises(ErroDeConexao, match="nao confere"):
        Cliente(url, {}, impressao_sha256="00" * 32).requisitar("GET", "/")


def test_tls_autoassinado_sem_impressao_nao_e_aceito(servidor_tls):
    """Sem impressao vale a validacao normal: certificado autoassinado NAO passa."""
    url, _ = servidor_tls
    with pytest.raises(ErroDeConexao):
        Cliente(url, {}).requisitar("GET", "/")


# --- prazo por chamada -----------------------------------------------------------------------------

def _lento(segundos: float):
    def tratador(*_a):
        time.sleep(segundos)
        return 200, {"ok": True}
    return tratador


def test_prazo_da_chamada_vale_so_para_ela():
    servidor = ServidorFalso(_lento(0.8))
    try:
        cliente = Cliente(servidor.url, {}, timeout=30)
        with pytest.raises(ErroDeConexao, match="TimeoutError"):
            cliente.requisitar("GET", "/x", timeout=0.2)
        assert cliente.requisitar("GET", "/x").ok, "o prazo padrao do cliente nao foi alterado"
    finally:
        servidor.parar()
