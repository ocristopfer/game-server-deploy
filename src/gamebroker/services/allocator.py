"""Escolha de CTID, IP e portas. Funcoes puras: quem sabe o que esta ocupado (banco,
Proxmox, OPNsense, rede) monta os conjuntos e entrega aqui.

A porta interna e a externa sao SEMPRE iguais. Jogo `shiftable` recebe um bloco de portas
seguidas de uma FAIXA PROPRIA do broker (longe das portas padrao dos jogos, que os seus
servidores antigos ja usam) e o instalador avisa o jogo (GAME_PORT/QUERY_PORT); jogo que nao
desloca fica com as portas padrao e e recusado se houver conflito. Mapear porta externa
diferente da interna pareceria mais flexivel, mas o jogo anuncia a propria porta na lista da
Steam e o cliente tentaria uma porta que ninguem escuta.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from gamebroker.domain.exceptions import OutOfResources
from gamebroker.services.catalog import Game

ROLE_GAME = "jogo"
ROLE_QUERY = "query"
ROLE_EXTRA = "extra"


@dataclass(frozen=True)
class AllocatedPort:
    base: int
    number: int
    proto: str
    role: str

    @property
    def key(self) -> tuple[int, str]:
        return (self.number, self.proto)

    def __str__(self) -> str:
        return f"{self.number}/{self.proto}"


def ips_in_range(prefix: str, start: int, fim: int) -> tuple[str, ...]:
    """`ips_da_faixa("192.168.2", 30, 99)`: os enderecos candidatos, validados como IPv4."""
    if not 1 <= start <= fim <= 254:
        raise ValueError("faixa de IP invalida")
    return tuple(str(ipaddress.IPv4Address(f"{prefix}.{n}")) for n in range(start, fim + 1))


def pick_ctid(span: Iterable[int], taken: set[int]) -> int:
    for ctid in span:
        if ctid not in taken:
            return ctid
    raise OutOfResources("nao ha CTID livre na faixa do broker")


def pick_ip(candidates: Iterable[str], taken: set[str], answers: Callable[[str], bool]) -> str:
    """Primeiro IP fora do banco/Proxmox e que ninguem na rede responde.

    O ultimo teste pega o aparelho que tem IP fixo na mao e o Proxmox nunca soube.
    """
    for ip in candidates:
        if ip not in taken and not answers(ip):
            return ip
    raise OutOfResources("nao ha IP livre na faixa do broker")


def pick_ip_and_ctid(candidates: Iterable[str], ctid_base: int, ctids_taken: set[int],
                       ips_taken: set[str], answers: Callable[[str], bool]) -> tuple[str, int]:
    """IP e CTID juntos: o CTID e `ctid_base` + o ultimo numero do IP (.102 -> 302).

    Escolher os dois separados deixaria o CTID e o IP andarem em ritmos diferentes assim que
    um container fosse apagado na mao, e a regra de cabeca (ver o IP, saber o CTID) deixaria
    de valer. Aqui um IP so serve se o CTID dele tambem estiver livre.
    """
    for ip in candidates:
        ctid = ctid_base + int(ip.rsplit(".", 1)[1])
        if ip not in ips_taken and ctid not in ctids_taken and not answers(ip):
            return ip, ctid
    raise OutOfResources("nao ha IP/CTID livre na faixa do broker")


def _role_of(game: Game, base: int) -> str:
    if base == game.game_port:
        return ROLE_GAME
    if game.query_port and base == game.query_port:
        return ROLE_QUERY
    return ROLE_EXTRA


def _as_block(game: Game, start: int) -> list[AllocatedPort]:
    """Cada porta-base distinta do jogo vira um numero do bloco; a mesma base em UDP e TCP
    (Satisfactory) fica com o mesmo numero nos dois protocolos."""
    number_of: dict[int, int] = {}
    for port in game.ports:
        number_of.setdefault(port.number, start + len(number_of))
    return [AllocatedPort(p.number, number_of[p.number], p.proto, _role_of(game, p.number))
            for p in game.ports]


def allocate_ports(game: Game, busy: set[tuple[int, str]], span: range) -> list[AllocatedPort]:
    """Jogo fixo: as portas padrao. Jogo `shiftable`: o primeiro bloco livre da `faixa`."""
    if not game.shiftable:
        candidates = [AllocatedPort(p.number, p.number, p.proto, _role_of(game, p.number)) for p in game.ports]
        conflicts = [c for c in candidates if c.key in busy]
        if conflicts:
            raise OutOfResources(f"porta {conflicts[0]} ja esta em uso: este jogo nao aceita mudar de porta")
        return candidates
    size = len({p.number for p in game.ports})
    for start in range(span.start, span.stop - size + 1):
        candidates = _as_block(game, start)
        if not any(c.key in busy for c in candidates):
            return candidates
    raise OutOfResources(f"a faixa de portas do broker ({span.start}-{span.stop - 1}) esta cheia")


def port_with_role(ports: Iterable[AllocatedPort], role: str) -> int:
    return next((p.number for p in ports if p.role == role), 0)


def port_from_base(ports: Iterable[AllocatedPort], base: int) -> int:
    """O numero alocado para a porta que o jogo chama de `base` (0 se nao houver)."""
    return next((p.number for p in ports if p.base == base), 0)
