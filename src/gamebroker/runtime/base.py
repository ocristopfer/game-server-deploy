"""Contratos dos quatro mundos com que o broker conversa.

O servico so conhece estas interfaces. Quem responde sao `proxmox.py`/`opnsense.py` em
producao e `fakes.py` nos testes.

Os nomes descrevem o PAPEL (`Compute`, `Ingress`) e nao o produto, e a instancia se
identifica por um `handle` opaco em vez de um `ctid`. Ver `docs/docker-backend-plan.md`,
secao 1: o substantivo do Proxmox tinha atravessado servico, banco e contrato da API, e
isso e barato de desfazer com zero instancias e caro com dez. O que NAO foi feito junto
esta na mesma secao, com o motivo: as secoes 1.5 a 1.7 desenham para um backend que ainda
nao existe, e a secao 0 do proprio plano diz que abstracao antes da primeira criacao real
codifica palpite.

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
class InstanceSpec:
    # Opaco de proposito: no Proxmox e o CTID em texto ("307"), no Docker seria o nome do
    # container. Quem o escolhe e quem cria — o servico so o carrega.
    handle: str
    hostname: str
    ip: str
    game: str
    memory_mb: int
    cores: int
    disk_gb: int


class Compute(Protocol):
    """Onde a instancia RODA. Hoje so ha o Proxmox; o nome descreve o papel, e nao o
    produto, porque `Proxmox` num Protocol e `ctid` num campo sao os dois substantivos
    que ficam caros de tirar depois que houver instancia em producao."""

    def handles_and_ips(self) -> tuple[set[str], set[str]]:
        """Handles e IPs que o compute ja usa (de qualquer dono, nao so do broker)."""

    def create(self, spec: InstanceSpec) -> None:
        """Cria a instancia no espaco do broker, a partir do modelo do jogo."""

    def start(self, handle: str) -> None: ...

    def stop(self, handle: str) -> None: ...

    def destroy(self, handle: str) -> None: ...

    def belongs_to_broker(self, handle: str) -> bool:
        """So `True` para instancia que o broker criou (no Proxmox: o pool)."""

    def reachable(self) -> bool: ...


class Ingress(Protocol):
    """Quem abre a porta para a internet. Hoje so ha o OPNsense."""

    def external_ports(self) -> set[tuple[int, str]]:
        """Portas ja redirecionadas no WAN, por qualquer regra (nao so as do broker)."""

    def open_ports(self, handle: str, ip: str, ports: Sequence[AllocatedPort]) -> None:
        """Cria as regras `gamepanel:<handle>` (destino = ip) e aplica. Idempotente."""

    def close_ports(self, handle: str) -> None:
        """Apaga SO as regras `gamepanel:<handle>` e aplica. Idempotente."""

    def reachable(self) -> bool: ...


class Installer(Protocol):
    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        """Instala o jogo dentro do CT por SSH e remove a chave do broker ao terminar.

        Continua recebendo IP, e nao handle: quem instala fala SSH com a maquina, nao com
        quem a criou. Tirar o instalador do servico e deixa-lo como detalhe do compute e a
        secao 1.6 do plano do Docker, adiada com o resto (ver o cabecalho deste arquivo).
        """


class Network(Protocol):
    def answers(self, ip: str) -> bool:
        """Alguem na LAN usa esse IP? (ping/ARP)"""
