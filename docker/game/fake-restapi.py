#!/usr/bin/env python3
"""API REST de mentira, no formato da do Palworld, para exercitar a contagem por HTTP.

Serve /v1/api/info, /v1/api/metrics e /v1/api/players com autenticacao Basic, igual
a de verdade (usuario 'admin' + a AdminPassword do servidor). Escuta so em 127.0.0.1
justamente para provar o ponto: o painel alcanca essa API porque a chamada sai de
DENTRO do container, por SSH — de fora ela esta fechada.

O numero de jogadores acompanha o mesmo /run/fake-players que o fake-a2s usa, entao as
duas fontes contam a mesma coisa e da para comparar uma com a outra.
"""
import base64
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORTA = int(os.environ.get("GAME_API_PORT", "8212"))
SENHA = os.environ.get("GAME_API_PASSWORD", "troque-me")
NOME = os.environ.get("GAME_QUERY_NAME", "Servidor de teste do painel")
MAX_JOGADORES = int(os.environ.get("GAME_QUERY_MAX", "32"))
ARQUIVO_FORCADO = "/run/fake-players"

NOMES = ["Cristopfer", "Guilherme", "Ana", "Bea", "Caio", "Duda", "Edu", "Fefe"]
ESPERADO = "Basic " + base64.b64encode(f"admin:{SENHA}".encode()).decode()


def quantos_agora() -> int:
    """Mesmo criterio do fake-a2s: valor forcado, ou oscilando com o relogio."""
    try:
        with open(ARQUIVO_FORCADO, "r", encoding="utf-8") as fh:
            return max(0, min(MAX_JOGADORES, int(fh.read().strip())))
    except (OSError, ValueError):
        return int(time.time() // 20) % 5


def jogadores(quantos: int) -> dict:
    agora = time.time()
    return {
        "players": [
            {
                "name": NOMES[i % len(NOMES)],
                "accountName": f"steam_{i}",
                "playerId": f"{i:08X}",
                "userId": f"steam_7656119800000{i:04d}",
                "ip": f"10.0.0.{20 + i}",
                "ping": round(12.0 + i * 1.5, 2),
                "location_x": round((agora % 1000) + i, 2),
                "location_y": round((agora % 700) - i, 2),
                "level": 5 + i,
                "building_count": 3 * i,
            }
            for i in range(quantos)
        ]
    }


def metricas(quantos: int) -> dict:
    return {
        "serverfps": 60,
        "currentplayernum": quantos,
        "serverframetime": 16.67,
        "maxplayernum": MAX_JOGADORES,
        "uptime": int(time.monotonic()),
        "days": 5,
        "basecampnum": 2,
    }


ROTAS = {
    "/v1/api/info": lambda _q: {"version": "v0.5.2-fake", "servername": NOME,
                                "description": "Container falso do docker compose",
                                "worldguid": "00000000000000000000000000000000"},
    "/v1/api/metrics": metricas,
    "/v1/api/players": jogadores,
}

# Rotas de acao. Como as de verdade, elas respondem 200 com o corpo VAZIO - e justamente
# esse detalhe que o painel precisa aguentar sem chamar de erro.
ROTAS_POST = ("/v1/api/announce", "/v1/api/kick", "/v1/api/ban")
ARQUIVO_ACOES = "/run/fake-actions.log"


def registra_acao(rota: str, corpo: dict) -> None:
    """Deixa a acao num arquivo, para os testes conferirem o que chegou."""
    linha = json.dumps({"rota": rota, "corpo": corpo}, ensure_ascii=False)
    print(f"fake-restapi: acao {linha}", flush=True)
    try:
        with open(ARQUIVO_ACOES, "a", encoding="utf-8") as fh:
            fh.write(linha + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):  # noqa: A003 - assinatura da stdlib
        print(f"fake-restapi: {formato % args}", flush=True)

    def _responde(self, codigo: int, corpo: dict, extra: tuple = ()) -> None:
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        for chave, valor in extra:
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(dados)

    def _autorizado(self) -> bool:
        # A de verdade exige Basic auth em tudo; e justamente o 401 que o assistente
        # do painel usa para dizer "existe uma API aqui, ela so quer senha".
        if self.headers.get("Authorization", "") == ESPERADO:
            return True
        self._responde(401, {"error": "unauthorized"},
                       (("WWW-Authenticate", 'Basic realm="palworld"'),))
        return False

    def do_GET(self) -> None:  # noqa: N802 - nome exigido pela stdlib
        rota = ROTAS.get(self.path.split("?")[0])
        if rota is None:
            self._responde(404, {"error": "not found"})
            return
        if not self._autorizado():
            return
        self._responde(200, rota(quantos_agora()))

    def do_POST(self) -> None:  # noqa: N802 - nome exigido pela stdlib
        caminho = self.path.split("?")[0]
        if caminho not in ROTAS_POST:
            self._responde(404, {"error": "not found"})
            return
        if not self._autorizado():
            return
        tamanho = int(self.headers.get("Content-Length") or 0)
        bruto = self.rfile.read(tamanho).decode("utf-8", "replace") if tamanho else ""
        try:
            corpo = json.loads(bruto) if bruto else {}
        except ValueError:
            self._responde(400, {"error": "body is not json"})
            return
        if caminho != "/v1/api/announce" and not str(corpo.get("userid", "")).strip():
            self._responde(400, {"error": "userid is required"})
            return
        registra_acao(caminho, corpo)
        # 200 com corpo VAZIO, como a de verdade.
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    servidor = HTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"fake-restapi escutando em 127.0.0.1:{PORTA} (admin/{SENHA})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
