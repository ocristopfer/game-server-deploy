"""Contratos dos quatro mundos com que o broker conversa.

O servico so conhece estas interfaces. Na Fase 1 quem responde sao os falsos de
`fakes.py`; Proxmox, OPNsense e SSH de verdade entram nas fases seguintes sem mexer no
servico nem nos testes dele.

Regra para toda implementacao real: mensagem de erro NAO pode carregar token, senha ou
corpo de resposta bruto - o texto vai parar no log da operacao e o painel o exibe.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import Game


@dataclass(frozen=True)
class CtSpec:
    ctid: int
    hostname: str
    ip: str
    game: str
    memory_mb: int
    cores: int
    disk_gb: int


class Proxmox(Protocol):
    def ctids_and_ips(self) -> tuple[set[int], set[str]]:
        """CTIDs e IPs que o Proxmox ja usa (de qualquer dono, nao so do broker)."""

    def create_ct(self, spec: CtSpec) -> None:
        """Cria o CT no pool do broker, com a tag do broker, a partir do template dourado."""

    def start(self, ctid: int) -> None: ...

    def stop(self, ctid: int) -> None: ...

    def destroy(self, ctid: int) -> None: ...

    def belongs_to_broker(self, ctid: int) -> bool:
        """So `True` para CT no pool do broker E com a tag do broker."""

    def reachable(self) -> bool: ...


class Opnsense(Protocol):
    def external_ports(self) -> set[tuple[int, str]]:
        """Portas ja redirecionadas no WAN, por qualquer regra (nao so as do broker)."""

    def open_ports(self, ctid: int, ip: str, ports: Sequence[AllocatedPort]) -> None:
        """Cria as regras `gamepanel:<ctid>` (destino = ip) e aplica. Idempotente."""

    def close_ports(self, ctid: int) -> None:
        """Apaga SO as regras `gamepanel:<ctid>` e aplica. Idempotente."""

    def reachable(self) -> bool: ...


class Installer(Protocol):
    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        """Instala o jogo dentro do CT por SSH e remove a chave do broker ao terminar."""


class Network(Protocol):
    def answers(self, ip: str) -> bool:
        """Alguem na LAN usa esse IP? (ping/ARP)"""
