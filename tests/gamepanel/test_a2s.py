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
    jogo: str = "Jogo de Teste", appid: int = 1234, players: int = 3, max_players: int = 10,
    bots: int = 0,
) -> bytes:
    """O corpo de uma resposta A2S_INFO, a partir do byte de versao do protocolo."""
    return (
        bytes([17])  # versao do protocolo, ignorada pelo leitor
        + _string(name) + _string(mapa) + _string(pasta) + _string(jogo)
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
        self._parar = False
        self._thread = threading.Thread(target=self._servir, daemon=True)
        self._thread.start()

    def _servir(self) -> None:
        while not self._parar:
            try:
                data, addr = self._sock.recvfrom(8192)
            except TimeoutError:
                continue
            tipo = data[4:5]
            funcao = self._roteiro.get(tipo)
            if funcao is None:
                continue
            for resposta in funcao(data):
                self._sock.sendto(resposta, addr)

    def fechar(self) -> None:
        self._parar = True
        self._thread.join(timeout=2)
        self._sock.close()


@pytest.fixture
def servidor_a2s():
    instancias = []

    def _cria(roteiro):
        servidor = _FakeA2sServer(roteiro)
        instancias.append(servidor)
        return servidor

    yield _cria
    for servidor in instancias:
        servidor.fechar()


def test_resposta_simples_sem_lista_de_jogadores(servidor_a2s):
    """Muitos servidores Unreal so respondem A2S_INFO - a lista e opcional."""
    servidor = servidor_a2s({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=7, max_players=32)],
    })
    info = a2s.query_players("127.0.0.1", servidor.port, timeout=1)
    assert info["players"] == 7
    assert info["max_players"] == 32
    assert info["server_name"] == "Servidor de teste"
    assert info["list"] == []
    assert info["error"] == ""


def test_lista_de_jogadores_quando_o_jogo_publica(servidor_a2s):
    servidor = servidor_a2s({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=2)],
        b"U": lambda _req: [a2s.A2S_HEADER + b"D" + _player_payload(
            [("Alice", 10, 120.5), ("Bob", 3, 45.0)])],
    })
    info = a2s.query_players("127.0.0.1", servidor.port, timeout=1)
    nomes = [p["name"] for p in info["list"]]
    assert nomes == ["Alice", "Bob"]
    assert info["list"][0]["score"] == 10
    assert info["list"][0]["seconds"] == pytest.approx(120.5)


def test_jogador_sem_nome_e_descartado_da_lista(servidor_a2s):
    """Nome vazio e como algumas implementacoes marcam slot livre - nao e jogador."""
    servidor = servidor_a2s({
        b"T": lambda _req: [a2s.A2S_HEADER + b"I" + _info_payload(players=1)],
        b"U": lambda _req: [a2s.A2S_HEADER + b"D" + _player_payload([("", 0, 0.0), ("Carla", 5, 1.0)])],
    })
    info = a2s.query_players("127.0.0.1", servidor.port, timeout=1)
    assert [p["name"] for p in info["list"]] == ["Carla"]


def test_desafio_e_respondido_antes_da_resposta_valer(servidor_a2s):
    """S2C_CHALLENGE ('A'): o servidor pede pra repetir o pedido com um desafio."""
    desafio = b"\x01\x02\x03\x04"

    def responde_info(pedido: bytes) -> list[bytes]:
        if pedido == a2s.A2S_INFO_REQ + desafio:
            return [a2s.A2S_HEADER + b"I" + _info_payload(players=9)]
        return [a2s.A2S_HEADER + b"A" + desafio]

    servidor = servidor_a2s({b"T": responde_info})
    info = a2s.query_players("127.0.0.1", servidor.port, timeout=1)
    assert info["players"] == 9


def test_resposta_dividida_em_varios_pacotes_e_remontada(servidor_a2s):
    """Resposta grande (varios jogadores) pode vir em pacotes 0xFFFFFFFE separados."""
    corpo = a2s.A2S_HEADER + b"I" + _info_payload(players=1)
    meio = len(corpo) // 2
    pacote1 = corpo[:meio]
    pacote2 = corpo[meio:]

    def responde_dividido(_pedido: bytes) -> list[bytes]:
        cabecalho1 = a2s.A2S_SPLIT + struct.pack("<lBBh", 1, 2, 0, 1024)
        cabecalho2 = a2s.A2S_SPLIT + struct.pack("<lBBh", 1, 2, 1, 1024)
        return [cabecalho1 + pacote1, cabecalho2 + pacote2]

    servidor = servidor_a2s({b"T": responde_dividido})
    info = a2s.query_players("127.0.0.1", servidor.port, timeout=1)
    assert info["players"] == 1


def test_sem_resposta_da_erro_de_consulta_nao_trava(servidor_a2s):
    """Servidor que nunca responde: estoura o timeout, nao trava o teste."""
    servidor = servidor_a2s({})  # roteiro vazio: recebe o pedido e nunca responde
    with pytest.raises(a2s.QueryError, match="sem resposta"):
        a2s.query_players("127.0.0.1", servidor.port, timeout=0.2)


def test_tipo_de_resposta_inesperado_e_recusado(servidor_a2s):
    servidor = servidor_a2s({b"T": lambda _req: [a2s.A2S_HEADER + b"Z" + b"lixo"]})
    with pytest.raises(a2s.QueryError, match="inesperada"):
        a2s.query_players("127.0.0.1", servidor.port, timeout=1)


def test_resposta_truncada_nao_trava_so_recusa(servidor_a2s):
    """Corpo cortado no meio de uma string: `_Buffer` tem que recusar, nao travar."""
    servidor = servidor_a2s({b"T": lambda _req: [a2s.A2S_HEADER + b"I" + bytes([17]) + b"sem terminador"]})
    with pytest.raises(a2s.QueryError):
        a2s.query_players("127.0.0.1", servidor.port, timeout=1)
