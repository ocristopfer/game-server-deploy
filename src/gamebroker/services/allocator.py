"""Choice of CTID, IP and ports. Pure functions: whoever knows what is taken (database,
Proxmox, OPNsense, network) builds the sets and hands them over here.

The internal and external ports are ALWAYS equal. A `shiftable` game gets a block of
consecutive ports from the broker's OWN RANGE (away from the games' default ports, which your
older servers already use) and the installer tells the game (GAME_PORT/QUERY_PORT); a game that
does not shift keeps the default ports and is refused if there is a conflict. Mapping an
external port different from the internal one would look more flexible, but the game announces
its own port in the Steam list and the client would try a port nobody listens on.
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
    """`ips_da_faixa("10.20.1", 30, 99)`: the candidate addresses, validated as IPv4."""
    if not 1 <= start <= fim <= 254:
        raise ValueError("faixa de IP invalida")
    return tuple(str(ipaddress.IPv4Address(f"{prefix}.{n}")) for n in range(start, fim + 1))


def pick_ctid(span: Iterable[int], taken: set[int]) -> int:
    for ctid in span:
        if ctid not in taken:
            return ctid
    raise OutOfResources("nao ha CTID livre na faixa do broker")


def pick_ip(candidates: Iterable[str], taken: set[str], answers: Callable[[str], bool]) -> str:
    """First IP that is not in the database/Proxmox and that nobody on the network answers for.

    The last check catches the device with a hand-assigned static IP that Proxmox never knew about.
    """
    for ip in candidates:
        if ip not in taken and not answers(ip):
            return ip
    raise OutOfResources("nao ha IP livre na faixa do broker")


def pick_ip_and_ctid(candidates: Iterable[str], ctid_base: int, ctids_taken: set[int],
                       ips_taken: set[str], answers: Callable[[str], bool]) -> tuple[str, int]:
    """IP and CTID together: the CTID is `ctid_base` + the last number of the IP (.102 -> 302).

    Choosing the two separately would let CTID and IP drift apart as soon as a container was
    deleted by hand, and the mental rule (see the IP, know the CTID) would stop holding. Here
    an IP only qualifies if its CTID is free too.
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
    """Each distinct base port of the game becomes one number of the block; the same base in UDP
    and TCP (Satisfactory) gets the same number in both protocols."""
    number_of: dict[int, int] = {}
    for port in game.ports:
        number_of.setdefault(port.number, start + len(number_of))
    return [AllocatedPort(p.number, number_of[p.number], p.proto, _role_of(game, p.number))
            for p in game.ports]


def allocate_ports(game: Game, busy: set[tuple[int, str]], span: range) -> list[AllocatedPort]:
    """Fixed game: the default ports. `shiftable` game: the first free block of `faixa`."""
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
    """The number allocated for the port the game calls `base` (0 if there is none)."""
    return next((p.number for p in ports if p.base == base), 0)
