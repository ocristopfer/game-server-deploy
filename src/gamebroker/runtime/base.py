"""Contracts for the four worlds the broker talks to.

The service only knows these interfaces. Whoever answers is `proxmox.py`/`opnsense.py` in
production and `fakes.py` in tests.

The names describe the ROLE (`Compute`, `Ingress`) and not the product, and the instance is
identified by an opaque `handle` instead of a `ctid`. See `docs/docker-backend-plan.md`,
section 1: the Proxmox noun had crossed the service, the database and the API contract, and
that is cheap to undo with zero instances and expensive with ten. What was NOT done at the
same time is in the same section, with the reason: sections 1.5 to 1.7 design for a backend
that does not exist yet, and section 0 of the plan itself says that abstraction before the
first real creation encodes a guess.

Rule for every real implementation: an error message must NOT carry a token, password or raw
response body - the text ends up in the operation log and the panel displays it.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import Game


@dataclass(frozen=True)
class InstanceSpec:
    # Opaque on purpose: on Proxmox it is the CTID as text ("307"), on Docker it would be the
    # container name. Whoever creates it picks it - the service only carries it.
    handle: str
    hostname: str
    ip: str
    game: str
    memory_mb: int
    cores: int
    disk_gb: int


class Compute(Protocol):
    """Where the instance RUNS. Today there is only Proxmox; the name describes the role, not
    the product, because `Proxmox` in a Protocol and `ctid` in a field are the two nouns that
    become expensive to remove once there are instances in production."""

    def handles_and_ips(self) -> tuple[set[str], set[str]]:
        """Handles and IPs the compute already uses (by any owner, not just the broker)."""

    def create(self, spec: InstanceSpec) -> None:
        """Creates the instance in the broker's space, from the game's template."""

    def start(self, handle: str) -> None: ...

    def stop(self, handle: str) -> None: ...

    def destroy(self, handle: str) -> None: ...

    def belongs_to_broker(self, handle: str) -> bool:
        """`True` only for an instance the broker created (on Proxmox: the pool)."""

    def reachable(self) -> bool: ...


class Ingress(Protocol):
    """Who opens the port to the internet. Today there is only OPNsense."""

    def external_ports(self) -> set[tuple[int, str]]:
        """Ports already forwarded on the WAN, by any rule (not just the broker's)."""

    def open_ports(self, handle: str, ip: str, ports: Sequence[AllocatedPort]) -> None:
        """Creates the `gamepanel:<handle>` rules (destination = ip) and applies. Idempotent."""

    def close_ports(self, handle: str) -> None:
        """Deletes ONLY the `gamepanel:<handle>` rules and applies. Idempotent."""

    def reachable(self) -> bool: ...


class Installer(Protocol):
    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None], cancel: threading.Event | None = None) -> None:
        """Installs the game inside the CT over SSH and removes the broker key when done.

        `cancel` triggered midway: stops whatever is running and raises an error. Undoing the
        CT is the service's job (`_undo`), as with any other failure.

        It still receives the IP, not the handle: the installer talks SSH to the machine, not
        to whoever created it. Taking the installer out of the service and making it a detail
        of the compute is section 1.6 of the Docker plan, postponed with the rest (see this
        file's header).
        """


class Network(Protocol):
    def answers(self, ip: str) -> bool:
        """Is anyone on the LAN using this IP? (ping/ARP)"""
