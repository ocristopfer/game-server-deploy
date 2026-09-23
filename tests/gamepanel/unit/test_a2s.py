"""Protocolo A2S (gamepanel.runtime.a2s): consulta de jogadores por UDP.

Nao existia suite dedicada para isso antes da Fase 4 (achado da propria analise de
arquitetura) - o codigo so era exercitado indiretamente, pela tela cheia via docker
compose. Aqui um servidor UDP falso, em loopback, fala o protocolo de verdade (cabecalho,
desafio/resposta, pacote dividido) para provar o comportamento ANTES de qualquer
reorganizacao futura poder mudar ele sem ninguem perceber.
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
    """O corpo de uma resposta A2S_INFO, a partir do byte de versao do protocolo."""
    return (
        bytes([17])  # versao do protocolo, ignorada pelo leitor
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
    """Servidor UDP falso em 127.0.0.1: responde conforme o roteiro dado ao construir.

    `roteiro` mapeia o PRIMEIRO byte do pedido (depois do cabecalho 0xFFFFFFFF) para
    uma funcao que recebe os bytes do pedido inteiro e devolve a lista de respostas a
    enviar em sequencia (mais de uma resposta simula desafio ou pacote dividido).
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
    """Muitos servidores Unreal so respondem A2S_INFO - a lista e opcional."""
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
    """Nome vazio e como algumas implementacoes marcam slot livre - nao e jogador."""
    server = a2s_server({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=1)],
        b"U": lambda _req: [a2s.A2S_HEADER + b"D" + _player_payload([("", 0, 0.0), ("Carla", 5, 1.0)])],
    })
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert [p["name"] for p in info["list"]] == ["Carla"]


def test_desafio_e_respondido_antes_da_resposta_valer(a2s_server):
    """S2C_CHALLENGE ('A'): o servidor pede pra repetir o pedido com um desafio."""
    challenge = b"\x01\x02\x03\x04"

    def answers_info(pedido: bytes) -> list[bytes]:
        if pedido == a2s.A2S_INFO_REQ + challenge:
            return [a2s.A2S_HEADER + b"I" + _info_payload(players=9)]
        return [a2s.A2S_HEADER + b"A" + challenge]

    server = a2s_server({b"T": answers_info})
    info = a2s.query_players("127.0.0.1", server.port, timeout=1)
    assert info["players"] == 9


def test_resposta_dividida_em_varios_pacotes_e_remontada(a2s_server):
    """Resposta grande (varios jogadores) pode vir em pacotes 0xFFFFFFFE separados."""
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
    """Servidor que nunca responde: estoura o timeout, nao trava o teste."""
    server = a2s_server({})  # roteiro vazio: recebe o pedido e nunca responde
    with pytest.raises(a2s.QueryError, match="sem resposta"):
        a2s.query_players("127.0.0.1", server.port, timeout=0.2)


def test_tipo_de_resposta_inesperado_e_recusado(a2s_server):
    server = a2s_server({b"T": lambda _req: [a2s.A2S_HEADER + b"Z" + b"lixo"]})
    with pytest.raises(a2s.QueryError, match="inesperada"):
        a2s.query_players("127.0.0.1", server.port, timeout=1)


def test_resposta_truncada_nao_trava_so_recusa(a2s_server):
    """Corpo cortado no meio de uma string: `_Buffer` tem que recusar, nao travar."""
    server = a2s_server({b"T": lambda _req: [a2s.A2S_HEADER + b"I" + bytes([17]) + b"sem terminador"]})
    with pytest.raises(a2s.QueryError):
        a2s.query_players("127.0.0.1", server.port, timeout=1)
