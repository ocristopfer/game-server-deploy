"""Queries players over Steam's A2S protocol - the same one the client's server browser
uses. It goes over UDP straight from the panel to the game's query port: no SSH, no
password and nothing installed in the container.
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
    """The API rejected the credential (401/403).

    Separate from QueryError so the HTTP path knows when logging in again is worth it:
    an expired token is the common case in game APIs (Satisfactory issues tokens with
    an expiry), and then the right thing is to renew it automatically instead of making
    someone paste a new token by hand.
    """


class _Buffer:
    """Sequential reader of the response body (all little-endian)."""

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
        # Server names often carry emoji and color codes; none of that may break the screen.
        return out.decode("utf-8", "replace")


def _udp_receive(sock: socket.socket) -> bytes:
    """Reads one response, reassembling it when the server splits it into several packets."""
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
    """Sends the request and handles the challenge the server may require."""
    sock.sendto(request, addr)
    data = _udp_receive(sock)
    if data[4:5] == b"A":  # S2C_CHALLENGE: resend the request carrying the challenge
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
    """Player count (A2S_INFO) and, when the game publishes it, the list (A2S_PLAYER)."""
    addr = (host, port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        try:
            buf = _ask(sock, addr, A2S_INFO_REQ, b"I")
            buf.byte()  # protocol version
            # `dict` without type parameters on purpose: the A2S reply mixes text (server
            # name, map) and numbers (players, cap) in the same record.
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

        # The name list is optional: many Unreal servers only answer the count.
        players: list[dict[str, Any]] = []
        try:
            buf = _ask(sock, addr, A2S_HEADER + b"U" + b"\xff\xff\xff\xff", b"D")
            count = buf.byte()
            for _ in range(min(count, _MAX_PLAYERS_IN_RESPONSE)):
                buf.byte()  # index, which servers usually leave at zero
                players.append({
                    "name": buf.string(),
                    "score": buf.long(),
                    "seconds": max(0.0, buf.float()),
                })
        except (QueryError, OSError, struct.error):  # TimeoutError is already an OSError
            players = []

    info["list"] = [p for p in players if p["name"]]
    info["error"] = ""
    return info
