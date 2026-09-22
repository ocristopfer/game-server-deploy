"""Backends falsos: testes do broker e o broker de brinquedo do compose de dev."""
from __future__ import annotations

from collections.abc import Callable, Sequence

from gamebroker.runtime.base import EspecificacaoDeCt
from gamebroker.services.allocator import PortaAlocada
from gamebroker.services.catalog import Jogo


class ProxmoxFalso:
    def __init__(self, ctids: set[int] | None = None, ips: set[str] | None = None):
        self.externos_ctids = set(ctids or ())
        self.externos_ips = set(ips or ())
        self.cts: dict[int, EspecificacaoDeCt] = {}
        self.parados: set[int] = set()
        self.chamadas: list[tuple[str, int]] = []
        self.falha_em: str | None = None
        self.online = True

    def _falhar(self, etapa: str) -> None:
        if self.falha_em == etapa:
            raise RuntimeError(f"proxmox falso: {etapa} falhou")

    def ctids_e_ips(self) -> tuple[set[int], set[str]]:
        return (self.externos_ctids | set(self.cts),
                self.externos_ips | {c.ip for c in self.cts.values()})

    def criar_ct(self, especificacao: EspecificacaoDeCt) -> None:
        self._falhar("criar_ct")
        self.chamadas.append(("criar_ct", especificacao.ctid))
        self.cts[especificacao.ctid] = especificacao

    def iniciar(self, ctid: int) -> None:
        self._falhar("iniciar")
        self.chamadas.append(("iniciar", ctid))
        self.parados.discard(ctid)

    def parar(self, ctid: int) -> None:
        self._falhar("parar")
        self.chamadas.append(("parar", ctid))
        self.parados.add(ctid)

    def destruir(self, ctid: int) -> None:
        self._falhar("destruir")
        self.chamadas.append(("destruir", ctid))
        self.cts.pop(ctid, None)

    def pertence_ao_broker(self, ctid: int) -> bool:
        return ctid in self.cts

    def acessivel(self) -> bool:
        return self.online


class OpnsenseFalso:
    def __init__(self, ocupadas: set[tuple[int, str]] | None = None):
        self.externas = set(ocupadas or ())
        self.regras: dict[int, list[tuple[str, int, str]]] = {}
        self.chamadas: list[tuple[str, int]] = []
        self.falha_em: str | None = None
        self.online = True

    def portas_externas(self) -> set[tuple[int, str]]:
        abertas = {(n, p) for regras in self.regras.values() for (_, n, p) in regras}
        return self.externas | abertas

    def abrir(self, ctid: int, ip: str, portas: Sequence[PortaAlocada]) -> None:
        if self.falha_em == "abrir":
            raise RuntimeError("opnsense falso: abrir falhou")
        self.chamadas.append(("abrir", ctid))
        self.regras[ctid] = [(ip, p.numero, p.proto) for p in portas]

    def fechar(self, ctid: int) -> None:
        self.chamadas.append(("fechar", ctid))
        self.regras.pop(ctid, None)

    def acessivel(self) -> bool:
        return self.online


class InstaladorFalso:
    def __init__(self) -> None:
        self.instalados: list[tuple[str, str]] = []
        self.falha = False

    def instalar(self, ip: str, jogo: Jogo, portas: Sequence[PortaAlocada],
                 log: Callable[[str], None]) -> None:
        log(f"instalando {jogo.nome} em {ip}")
        if self.falha:
            raise RuntimeError("instalador falso: steamcmd falhou")
        self.instalados.append((ip, jogo.chave))
        log("instalacao concluida")


class RedeFalsa:
    def __init__(self, ocupados: set[str] | None = None):
        self.ocupados = set(ocupados or ())

    def responde(self, ip: str) -> bool:
        return ip in self.ocupados
