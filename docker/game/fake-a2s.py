#!/usr/bin/env python3
"""Fake A2S query server, so the panel has something to count in the local environment.

Answers enough of the Steam protocol to exercise the real code path:
the challenge (S2C_CHALLENGE), A2S_INFO with the count and A2S_PLAYER with the list.

The player count changes by itself over time, so you can watch the panel update.
A file at /run/fake-players forces a fixed value (used by the tests).
"""
import os
import socket
import struct
import sys
import time

HEADER = b"\xff\xff\xff\xff"
PORTA = int(os.environ.get("GAME_QUERY_PORT", "27015"))
NOME = os.environ.get("GAME_QUERY_NAME", "Servidor de teste do painel")
MAPA = os.environ.get("GAME_QUERY_MAP", "Gielinor")
MAX_JOGADORES = int(os.environ.get("GAME_QUERY_MAX", "32"))
ARQUIVO_FORCADO = "/run/fake-players"
DESAFIO = b"\x11\x22\x33\x44"

NOMES = ["Alex", "Bruno", "Ana", "Bea", "Caio", "Duda", "Edu", "Fefe"]


def quantos_agora() -> int:
    """Fixed value if someone wrote to /run/fake-players; otherwise it oscillates with the clock."""
    try:
        with open(ARQUIVO_FORCADO, "r", encoding="utf-8") as fh:
            return max(0, min(MAX_JOGADORES, int(fh.read().strip())))
    except (OSError, ValueError):
        return int(time.time() // 20) % 5


def texto(valor: str) -> bytes:
    return valor.encode("utf-8") + b"\x00"


def resposta_info(quantos: int) -> bytes:
    corpo = b"I" + bytes([17])
    corpo += texto(NOME) + texto(MAPA) + texto("pal") + texto("Palworld")
    # The A2S field is 16 bits: the real server sends the truncated appid here
    # (the full value comes later, in the optional block).
    corpo += struct.pack("<H", 2394010 & 0xFFFF)
    corpo += bytes([quantos, MAX_JOGADORES, 0])
    corpo += b"d" + b"l" + b"\x00" + b"\x00"       # dedicated, linux, public, no VAC
    corpo += texto("v0.5.2-fake")  # A2S "version" field, free text
    return HEADER + corpo


def resposta_jogadores(quantos: int) -> bytes:
    corpo = b"D" + bytes([quantos])
    agora = time.time()
    for i in range(quantos):
        corpo += bytes([i])
        corpo += texto(NOMES[i % len(NOMES)])
        corpo += struct.pack("<l", (i + 1) * 10)
        corpo += struct.pack("<f", (agora % 3600) + i * 60)
    return HEADER + corpo


def main() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORTA))
    print(f"fake-a2s escutando em 0.0.0.0:{PORTA}", flush=True)

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except OSError as exc:
            print(f"fake-a2s: erro no recvfrom: {exc}", file=sys.stderr, flush=True)
            continue
        if not data.startswith(HEADER):
            continue

        try:
            responder(sock, addr, data[4:5], data[5:], quantos_agora())
        except (OSError, struct.error, ValueError) as exc:
            # A weird request must not bring down the whole service.
            print(f"fake-a2s: pedido ignorado ({exc})", file=sys.stderr, flush=True)


def responder(sock, addr, tipo: bytes, resto: bytes, quantos: int) -> None:
    if tipo == b"T":  # A2S_INFO. Requires the challenge the first time, as Steam does.
        if resto[-4:] != DESAFIO:
            sock.sendto(HEADER + b"A" + DESAFIO, addr)
        else:
            sock.sendto(resposta_info(quantos), addr)
    elif tipo == b"U":  # A2S_PLAYER
        if resto[:4] != DESAFIO:
            sock.sendto(HEADER + b"A" + DESAFIO, addr)
        else:
            sock.sendto(resposta_jogadores(quantos), addr)


if __name__ == "__main__":
    main()
