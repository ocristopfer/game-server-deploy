#!/usr/bin/env python3
"""Fake REST API, in the Palworld format, to exercise the HTTP player count.

Serves /v1/api/info, /v1/api/metrics and /v1/api/players with Basic auth, just like
the real one (user 'admin' + the server's AdminPassword). It listens only on 127.0.0.1
precisely to prove the point: the panel reaches this API because the call leaves from
INSIDE the container, over SSH -- from outside it is closed.

The player count follows the same /run/fake-players that fake-a2s uses, so both
sources count the same thing and can be compared with each other.
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

NOMES = ["Alex", "Bruno", "Ana", "Bea", "Caio", "Duda", "Edu", "Fefe"]
ESPERADO = "Basic " + base64.b64encode(f"admin:{SENHA}".encode()).decode()


def quantos_agora() -> int:
    """Same rule as fake-a2s: forced value, or oscillating with the clock."""
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

# Action routes. Like the real ones, they answer 200 with an EMPTY body - and that is
# exactly the detail the panel has to cope with without calling it an error.
ROTAS_POST = ("/v1/api/announce", "/v1/api/kick", "/v1/api/ban")
ARQUIVO_ACOES = "/run/fake-actions.log"


def registra_acao(rota: str, corpo: dict) -> None:
    """Writes the action to a file, so the tests can check what arrived."""
    linha = json.dumps({"rota": rota, "corpo": corpo}, ensure_ascii=False)
    print(f"fake-restapi: acao {linha}", flush=True)
    try:
        with open(ARQUIVO_ACOES, "a", encoding="utf-8") as fh:
            fh.write(linha + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):  # noqa: A003 - stdlib signature
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
        # The real one requires Basic auth on everything; that 401 is exactly what the
        # panel assistant uses to say "there is an API here, it just wants a password".
        if self.headers.get("Authorization", "") == ESPERADO:
            return True
        self._responde(401, {"error": "unauthorized"},
                       (("WWW-Authenticate", 'Basic realm="palworld"'),))
        return False

    def do_GET(self) -> None:  # noqa: N802 - name required by the stdlib
        rota = ROTAS.get(self.path.split("?")[0])
        if rota is None:
            self._responde(404, {"error": "not found"})
            return
        if not self._autorizado():
            return
        self._responde(200, rota(quantos_agora()))

    def do_POST(self) -> None:  # noqa: N802 - name required by the stdlib
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
        # 200 with an EMPTY body, like the real one.
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    servidor = HTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"fake-restapi escutando em 127.0.0.1:{PORTA} (admin/{SENHA})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
