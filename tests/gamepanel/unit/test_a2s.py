"""A2S protocol (gamepanel.runtime.a2s): player query over UDP.

There was no dedicated suite for this before Phase 4 (a finding of the architecture
analysis itself) - the code was only exercised indirectly, by the full screen via docker
compose. Here a fake UDP server, on loopback, speaks the real protocol (header,
challenge/response, split packet) to prove the behavior BEFORE any future reorganization
can change it without anyone noticing.
"""
from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Callable

import pytest

from gamepanel.runtime import a2s


def _string(text: str) -> bytes:
    return text.encode("utf-8") + b"\x00"


def _info_payload(
    name: str = "Servidor de teste", mapa: str = "de_teste", pasta: str = "jogo",
    game: str = "Jogo de Teste", appid: int = 1234, players: int = 3, max_players: int = 10,
    bots: int = 0,
) -> bytes:
    """The body of an A2S_INFO response, starting at the protocol version byte."""
    return (
        bytes([17])  # protocol version, ignored by the reader
        + _string(name) + _string(mapa) + _string(pasta) + _string(game)
        + struct.pack("<h", appid)
        + bytes([players, max_players, bots])
    )


def _player_payload(players: list[tuple[str, int, float]]) -> bytes:
    body = bytes([len(players)])
    for name, score, seconds in players:
        body += bytes([0]) + _string(name) + struct.pack("<l", score) + struct.pack("<f", seconds)
    return body


class _FakeA2sServer:
    """Fake UDP server on 127.0.0.1: answers according to the script given at construction.

    `roteiro` maps the FIRST byte of the request (after the 0xFFFFFFFF header) to a
    function that receives the bytes of the whole request and returns the list of
    responses to send in sequence (more than one response simulates a challenge or a split
    packet).
    """

    def __init__(self, roteiro: dict[bytes, Callable[[bytes], list[bytes]]]):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.settimeout(2)
        self.port = self._sock.getsockname()[1]
        self._roteiro = roteiro
        self._stopped = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopped:
            try:
                data, addr = self._sock.recvfrom(8192)
            except TimeoutError:
                continue
            kind = data[4:5]
            call = self._roteiro.get(kind)
            if call is None:
                continue
            for response in call(data):
                self._sock.sendto(response, addr)

    def close(self) -> None:
        self._stopped = True
        self._thread.join(timeout=2)
        self._sock.close()


@pytest.fixture
def a2s_server():
    instances = []

    def _make(roteiro):
        server = _FakeA2sServer(roteiro)
        instances.append(server)
        return server

    yield _make
    for server in instances:
        server.close()


def test_resposta_simples_sem_lista_de_jogadores(a2s_server):
    """Many Unreal servers only answer A2S_INFO - the list is optional."""
    server = a2s_server({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=7, max_players=32)],
    })
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert info["players"] == 7
    assert info["max_players"] == 32
    assert info["server_name"] == "Servidor de teste"
    assert info["list"] == []
    assert info["error"] == ""


def test_lista_de_jogadores_quando_o_jogo_publica(a2s_server):
    server = a2s_server({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=2)],
        b"U": lambda _req: [a2s.A2S_HEADER + b"D" + _player_payload(
            [("Alice", 10, 120.5), ("Bob", 3, 45.0)])],
    })
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    names = [p["name"] for p in info["list"]]
    assert names == ["Alice", "Bob"]
    assert info["list"][0]["score"] == 10
    assert info["list"][0]["seconds"] == pytest.approx(120.5)


def test_jogador_sem_nome_e_descartado_da_lista(a2s_server):
    """An empty name is how some implementations mark a free slot - it is not a player."""
    server = a2s_server({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=1)],
        b"U": lambda _req: [a2s.A2S_HEADER + b"D" + _player_payload([("", 0, 0.0), ("Carla", 5, 1.0)])],
    })
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert [p["name"] for p in info["list"]] == ["Carla"]


def test_desafio_e_respondido_antes_da_resposta_valer(a2s_server):
    """S2C_CHALLENGE ('A'): the server asks for the request to be repeated with a challenge."""
    challenge = b"\x01\x02\x03\x04"

    def answers_info(pedido: bytes) -> list[bytes]:
        if pedido == a2s.A2S_INFO_REQ + challenge:
            return [a2s.A2S_HEADER + b"I" + _info_payload(players=9)]
        return [a2s.A2S_HEADER + b"A" + challenge]

    server = a2s_server({b"T": answers_info})
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert info["players"] == 9


def test_resposta_dividida_em_varios_pacotes_e_remontada(a2s_server):
    """A large response (several players) can come in separate 0xFFFFFFFE packets."""
    body = a2s.A2S_HEADER + b"I" + _info_payload(players=1)
    middle = len(body) // 2
    package1 = body[:middle]
    package2 = body[middle:]

    def answers_split(_pedido: bytes) -> list[bytes]:
        header1 = a2s.A2S_SPLIT + struct.pack("<lBBh", 1, 2, 0, 1024)
        header2 = a2s.A2S_SPLIT + struct.pack("<lBBh", 1, 2, 1, 1024)
        return [header1 + package1, header2 + package2]

    server = a2s_server({b"T": answers_split})
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert info["players"] == 1


def test_sem_resposta_da_erro_de_consulta_nao_trava(a2s_server):
    """A server that never answers: the timeout fires, the test does not hang."""
    server = a2s_server({})  # empty script: receives the request and never answers
    with pytest.raises(a2s.QueryError, match="sem resposta"):
        a2s.query_players("127.0.0.1", server.port, timeout=0.2)


def test_tipo_de_resposta_inesperado_e_recusado(a2s_server):
    server = a2s_server({b"T": lambda _req: [a2s.A2S_HEADER + b"Z" + b"lixo"]})
    with pytest.raises(a2s.QueryError, match="inesperada"):
        a2s.query_players("127.0.0.1", server.port, timeout=1)


def test_resposta_truncada_nao_trava_so_recusa(a2s_server):
    """Body cut in the middle of a string: `_Buffer` has to refuse, not hang."""
    server = a2s_server({b"T": lambda _req: [a2s.A2S_HEADER + b"I" + bytes([17]) + b"sem terminador"]})
    with pytest.raises(a2s.QueryError):
        a2s.query_players("127.0.0.1", server.port, timeout=1)
