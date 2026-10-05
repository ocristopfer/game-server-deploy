"""Fake backends: broker tests and the toy broker of the dev compose.

The STEP names (`create`, `start`, `open`, ...) are what a test puts in `fail_on` to make a
step fail: they are a contract with `test_instance_service.py`, not screen text.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from gamebroker.runtime.base import InstanceSpec
from gamebroker.services.allocator import AllocatedPort
from gamebroker.services.catalog import Game


class FakeCompute:
    def __init__(self, handles: set[str] | None = None, ips: set[str] | None = None):
        self.outside_handles = set(handles or ())
        self.outside_ips = set(ips or ())
        self.cts: dict[str, InstanceSpec] = {}
        self.stopped: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.fail_on: str | None = None
        self.online = True

    def _fail(self, step: str) -> None:
        if self.fail_on == step:
            raise RuntimeError(f"compute falso: {step} falhou")

    def handles_and_ips(self) -> tuple[set[str], set[str]]:
        return (self.outside_handles | set(self.cts),
                self.outside_ips | {c.ip for c in self.cts.values()})

    def create(self, spec: InstanceSpec) -> None:
        self._fail("create")
        self.calls.append(("create", spec.handle))
        self.cts[spec.handle] = spec

    def start(self, handle: str) -> None:
        self._fail("start")
        self.calls.append(("start", handle))
        self.stopped.discard(handle)

    def stop(self, handle: str) -> None:
        self._fail("stop")
        self.calls.append(("stop", handle))
        self.stopped.add(handle)

    def destroy(self, handle: str) -> None:
        self._fail("destroy")
        self.calls.append(("destroy", handle))
        self.cts.pop(handle, None)

    def belongs_to_broker(self, handle: str) -> bool:
        return handle in self.cts

    def reachable(self) -> bool:
        return self.online


class FakeIngress:
    def __init__(self, taken: set[tuple[int, str]] | None = None):
        self.outside = set(taken or ())
        self.rules: dict[str, list[tuple[str, int, str]]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_on: str | None = None
        self.online = True

    def external_ports(self) -> set[tuple[int, str]]:
        open_ones = {(n, p) for rules in self.rules.values() for (_, n, p) in rules}
        return self.outside | open_ones

    def open_ports(self, handle: str, ip: str, ports: Sequence[AllocatedPort]) -> None:
        if self.fail_on == "open":
            raise RuntimeError("ingress falso: abrir falhou")
        self.calls.append(("open", handle))
        self.rules[handle] = [(ip, p.number, p.proto) for p in ports]

    def close_ports(self, handle: str) -> None:
        self.calls.append(("close", handle))
        self.rules.pop(handle, None)

    def reachable(self) -> bool:
        return self.online


class FakeInstaller:
    def __init__(self) -> None:
        self.installed: list[tuple[str, str]] = []
        self.failure = False
        # Runs in the MIDDLE of the installation: this is how a test requests cancellation while
        # it is happening, without any thread.
        self.during: Callable[[], None] | None = None

    def install(self, ip: str, game: Game, ports: Sequence[AllocatedPort],
                 log: Callable[[str], None], cancel: threading.Event | None = None) -> None:
        log(f"instalando {game.name} em {ip}")
        if self.during is not None:
            self.during()
        if cancel is not None and cancel.is_set():
            raise RuntimeError("instalacao cancelada")
        if self.failure:
            raise RuntimeError("instalador falso: steamcmd falhou")
        self.installed.append((ip, game.key))
        log("instalacao concluida")


class FakeNetwork:
    def __init__(self, taken: set[str] | None = None):
        self.taken = set(taken or ())

    def answers(self, ip: str) -> bool:
        return ip in self.taken
