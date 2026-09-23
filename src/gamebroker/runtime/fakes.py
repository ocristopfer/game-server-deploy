"""Backends falsos: testes do broker e o broker de brinquedo do compose de dev."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from gamebroker.runtime.base import CtSpec
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import Game


class FakeProxmox:
    def __init__(self, ctids: set[int] | None = None, ips: set[str] | None = None):
        self.outside_ctids = set(ctids or ())
        self.outside_ips = set(ips or ())
        self.cts: dict[int, CtSpec] = {}
        self.stopped: set[int] = set()
        self.calls: list[tuple[str, int]] = []
        self.fail_on: str | None = None
        self.online = True

    def _fail(self, step: str) -> None:
        if self.fail_on == step:
            raise RuntimeError(f"proxmox falso: {step} falhou")

    def ctids_and_ips(self) -> tuple[set[int], set[str]]:
        return (self.outside_ctids | set(self.cts),
                self.outside_ips | {c.ip for c in self.cts.values()})

    def create_ct(self, spec: CtSpec) -> None:
        self._fail("criar_ct")
        self.calls.append(("criar_ct", spec.ctid))
        self.cts[spec.ctid] = spec

    def start(self, ctid: int) -> None:
        self._fail("iniciar")
        self.calls.append(("iniciar", ctid))
        self.stopped.discard(ctid)

    def stop(self, ctid: int) -> None:
        self._fail("parar")
        self.calls.append(("parar", ctid))
        self.stopped.add(ctid)

    def destroy(self, ctid: int) -> None:
        self._fail("destruir")
        self.calls.append(("destruir", ctid))
        self.cts.pop(ctid, None)

    def belongs_to_broker(self, ctid: int) -> bool:
        return ctid in self.cts

    def reachable(self) -> bool:
        return self.online


class FakeOpnsense:
    def __init__(self, taken: set[tuple[int, str]] | None = None):
        self.outside = set(taken or ())
        self.rules: dict[int, list[tuple[str, int, str]]] = {}
        self.calls: list[tuple[str, int]] = []
        self.fail_on: str | None = None
        self.online = True

    def external_ports(self) -> set[tuple[int, str]]:
        open_ones = {(n, p) for rules in self.rules.values() for (_, n, p) in rules}
        return self.outside | open_ones

    def open_ports(self, ctid: int, ip: str, ports: Sequence[AllocatedPort]) -> None:
        if self.fail_on == "abrir":
            raise RuntimeError("opnsense falso: abrir falhou")
        self.calls.append(("abrir", ctid))
        self.rules[ctid] = [(ip, p.number, p.proto) for p in ports]

    def close_ports(self, ctid: int) -> None:
        self.calls.append(("fechar", ctid))
        self.rules.pop(ctid, None)

    def reachable(self) -> bool:
        return self.online


class FakeInstaller:
    def __init__(self) -> None:
        self.installed: list[tuple[str, str]] = []
        self.failure = False

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None]) -> None:
        log(f"instalando {game.name} em {ip}")
        if self.failure:
            raise RuntimeError("instalador falso: steamcmd falhou")
        self.installed.append((ip, game.key))
        log("instalacao concluida")


class FakeNetwork:
    def __init__(self, taken: set[str] | None = None):
        self.taken = set(taken or ())

    def answers(self, ip: str) -> bool:
        return ip in self.taken
