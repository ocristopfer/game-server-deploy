"""Consulta jogadores pelo protocolo A2S da Steam — o mesmo que a lista de servidores
do cliente usa. Vai por UDP direto do painel para a porta de query do jogo: nao passa
por SSH, nao precisa de senha e nao exige nada instalado no container.
"""
from __future__ import annotations

import socket
import struct
from typing import Any

from gamepanel.i18n import Message

A2S_HEADER = b"\xff\xff\xff\xff"
A2S_SPLIT = b"\xff\xff\xff\xfe"
A2S_INFO_REQ = A2S_HEADER + b"TSource Engine Query\x00"

_MAX_PLAYERS_IN_RESPONSE = 128


class QueryError(RuntimeError):
    pass


class AuthError(QueryError):
    """A API recusou a credencial (401/403).

    Separada de QueryError para o caminho HTTP saber quando vale a pena refazer o
    login: token expirado e o caso comum em API de jogo (a do Satisfactory emite
    token com prazo), e ai o certo e renovar sozinho em vez de exigir que alguem
    cole um token novo na mao.
    """


class _Buffer:
    """Leitor sequencial do corpo da resposta (tudo little-endian)."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise QueryError(Message("a2s.truncated"))
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def byte(self) -> int:
        return self._take(1)[0]

    def short(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def long(self) -> int:
        return struct.unpack("<l", self._take(4))[0]

    def float(self) -> float:
        return struct.unpack("<f", self._take(4))[0]

    def string(self) -> str:
        end = self.data.find(b"\x00", self.pos)
        if end < 0:
            raise QueryError(Message("a2s.unterminated_text"))
        out = self.data[self.pos:end]
        self.pos = end + 1
        # Nome de servidor costuma vir com emoji e cor; nada disso pode derrubar a tela.
        return out.decode("utf-8", "replace")


def _udp_receive(sock: socket.socket) -> bytes:
    """Le uma resposta, remontando quando o servidor divide em varios pacotes."""
    data, _ = sock.recvfrom(8192)
    if data[:4] != A2S_SPLIT:
        return data

    parts: dict[int, bytes] = {}
    total = 1
    while True:
        _pid, total, number, _size = struct.unpack_from("<lBBh", data, 4)
        parts[number] = data[12:]
        if len(parts) >= total:
            break
        data, _ = sock.recvfrom(8192)
        if data[:4] != A2S_SPLIT:
            raise QueryError(Message("a2s.split_incomplete"))
    whole = b"".join(parts[i] for i in sorted(parts))
    if whole[:4] == A2S_HEADER:
        return whole
    raise QueryError(Message("a2s.split_unknown"))


def _ask(sock: socket.socket, addr: tuple[str, int], request: bytes, response_type: bytes) -> _Buffer:
    """Manda o pedido e trata o desafio (challenge) que o servidor pode exigir."""
    sock.sendto(request, addr)
    data = _udp_receive(sock)
    if data[4:5] == b"A":  # S2C_CHALLENGE: repete o pedido carregando o desafio
        challenge = data[5:9]
        if request == A2S_INFO_REQ:
            sock.sendto(request + challenge, addr)
        else:
            sock.sendto(request[:5] + challenge, addr)
        data = _udp_receive(sock)
    if data[4:5] != response_type:
        raise QueryError(Message("a2s.unexpected_reply", kind=repr(data[4:5])))
    buf = _Buffer(data)
    buf.pos = 5
    return buf


def query_players(host: str, port: int, timeout: float = 3.0) -> dict[str, Any]:
    """Numero de jogadores (A2S_INFO) e, quando o jogo publica, a lista (A2S_PLAYER)."""
    addr = (host, port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            buf = _ask(sock, addr, A2S_INFO_REQ, b"I")
            buf.byte()  # versao do protocolo
            # `dict` sem parametro de proposito: a resposta A2S mistura texto (nome do
            # servidor, mapa) e numero (jogadores, teto) na mesma ficha.
            info: dict[str, Any] = {
                "server_name": buf.string(),
                "map": buf.string(),
                "folder": buf.string(),
                "game": buf.string(),
            }
            buf.short()  # steam appid
            info["players"] = buf.byte()
            info["max_players"] = buf.byte()
            info["bots"] = buf.byte()
        except TimeoutError:
            raise QueryError(Message("a2s.no_reply", seconds=f"{timeout:g}",
                                      port=port)) from None
        except (OSError, struct.error) as exc:
            raise QueryError(Message("a2s.query_failed", host=host, port=port,
                                      reason=exc)) from exc

        # A lista de nomes e opcional: varios servidores Unreal so respondem a contagem.
        players: list[dict[str, Any]] = []
        try:
            buf = _ask(sock, addr, A2S_HEADER + b"U" + b"\xff\xff\xff\xff", b"D")
            count = buf.byte()
            for _ in range(min(count, _MAX_PLAYERS_IN_RESPONSE)):
                buf.byte()  # indice, que os servidores costumam zerar
                players.append({
                    "name": buf.string(),
                    "score": buf.long(),
                    "seconds": max(0.0, buf.float()),
                })
        except (QueryError, OSError, struct.error):  # TimeoutError ja e um OSError
            players = []

    info["list"] = [p for p in players if p["name"]]
    info["error"] = ""
    return info
