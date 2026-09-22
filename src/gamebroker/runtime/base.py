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

from gamebroker.services.allocator import PortaAlocada
from gamebroker.services.catalog import Jogo


@dataclass(frozen=True)
class EspecificacaoDeCt:
    ctid: int
    hostname: str
    ip: str
    jogo: str
    memoria_mb: int
    cores: int
    disco_gb: int


class Proxmox(Protocol):
    def ctids_e_ips(self) -> tuple[set[int], set[str]]:
        """CTIDs e IPs que o Proxmox ja usa (de qualquer dono, nao so do broker)."""

    def criar_ct(self, especificacao: EspecificacaoDeCt) -> None:
        """Cria o CT no pool do broker, com a tag do broker, a partir do template dourado."""

    def iniciar(self, ctid: int) -> None: ...

    def parar(self, ctid: int) -> None: ...

    def destruir(self, ctid: int) -> None: ...

    def pertence_ao_broker(self, ctid: int) -> bool:
        """So `True` para CT no pool do broker E com a tag do broker."""

    def acessivel(self) -> bool: ...


class Opnsense(Protocol):
    def portas_externas(self) -> set[tuple[int, str]]:
        """Portas ja redirecionadas no WAN, por qualquer regra (nao so as do broker)."""

    def abrir(self, ctid: int, ip: str, portas: Sequence[PortaAlocada]) -> None:
        """Cria as regras `gamepanel:<ctid>` (destino = ip) e aplica. Idempotente."""

    def fechar(self, ctid: int) -> None:
        """Apaga SO as regras `gamepanel:<ctid>` e aplica. Idempotente."""

    def acessivel(self) -> bool: ...


class Instalador(Protocol):
    def instalar(self, ip: str, jogo: Jogo, portas: Sequence[PortaAlocada],
                 log: Callable[[str], None]) -> None:
        """Instala o jogo dentro do CT por SSH e remove a chave do broker ao terminar."""


class Rede(Protocol):
    def responde(self, ip: str) -> bool:
        """Alguem na LAN usa esse IP? (ping/ARP)"""
