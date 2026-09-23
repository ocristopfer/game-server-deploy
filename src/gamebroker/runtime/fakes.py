"""Backends falsos: testes do broker e o broker de brinquedo do compose de dev."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from gamebroker.runtime.base import CtSpec
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import Game


class FakeProxmox:
    def __init__(self, ctids: set[int] | None = None, ips: set[str] | None = None):
        self.externos_ctids = set(ctids or ())
        self.externos_ips = set(ips or ())
        self.cts: dict[int, CtSpec] = {}
        self.parados: set[int] = set()
        self.chamadas: list[tuple[str, int]] = []
        self.falha_em: str | None = None
        self.online = True

    def _fail(self, etapa: str) -> None:
        if self.falha_em == etapa:
            raise RuntimeError(f"proxmox falso: {etapa} falhou")

    def ctids_and_ips(self) -> tuple[set[int], set[str]]:
        return (self.externos_ctids | set(self.cts),
                self.externos_ips | {c.ip for c in self.cts.values()})

    def create_ct(self, spec: CtSpec) -> None:
        self._fail("criar_ct")
        self.chamadas.append(("criar_ct", spec.ctid))
        self.cts[spec.ctid] = spec

    def start(self, ctid: int) -> None:
        self._fail("iniciar")
        self.chamadas.append(("iniciar", ctid))
        self.parados.discard(ctid)

    def stop(self, ctid: int) -> None:
        self._fail("parar")
        self.chamadas.append(("parar", ctid))
        self.parados.add(ctid)

    def destroy(self, ctid: int) -> None:
        self._fail("destruir")
        self.chamadas.append(("destruir", ctid))
        self.cts.pop(ctid, None)

    def belongs_to_broker(self, ctid: int) -> bool:
        return ctid in self.cts

    def reachable(self) -> bool:
        return self.online


class FakeOpnsense:
    def __init__(self, ocupadas: set[tuple[int, str]] | None = None):
        self.externas = set(ocupadas or ())
        self.regras: dict[int, list[tuple[str, int, str]]] = {}
        self.chamadas: list[tuple[str, int]] = []
        self.falha_em: str | None = None
        self.online = True

    def external_ports(self) -> set[tuple[int, str]]:
        open_ones = {(n, p) for rules in self.regras.values() for (_, n, p) in rules}
        return self.externas | open_ones

    def open_ports(self, ctid: int, ip: str, ports: Sequence[AllocatedPort]) -> None:
        if self.falha_em == "abrir":
            raise RuntimeError("opnsense falso: abrir falhou")
        self.chamadas.append(("abrir", ctid))
        self.regras[ctid] = [(ip, p.number, p.proto) for p in ports]

    def close_ports(self, ctid: int) -> None:
        self.chamadas.append(("fechar", ctid))
        self.regras.pop(ctid, None)

    def reachable(self) -> bool:
        return self.online


class FakeInstaller:
    def __init__(self) -> None:
        self.instalados: list[tuple[str, str]] = []
        self.failure = False

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        log(f"instalando {game.name} em {ip}")
        if self.failure:
            raise RuntimeError("instalador falso: steamcmd falhou")
        self.instalados.append((ip, game.key))
        log("instalacao concluida")


class FakeNetwork:
    def __init__(self, ocupados: set[str] | None = None):
        self.ocupados = set(ocupados or ())

    def answers(self, ip: str) -> bool:
        return ip in self.ocupados
