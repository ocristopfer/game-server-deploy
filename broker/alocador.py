"""Escolha de CTID, IP e portas. Funcoes puras: quem sabe o que esta ocupado (banco,
Proxmox, OPNsense, rede) monta os conjuntos e entrega aqui.

A porta interna e a externa sao SEMPRE iguais. Jogo `deslocavel` ganha o mesmo
deslocamento em todas as portas e o instalador avisa o jogo (GAME_PORT/QUERY_PORT);
jogo que nao desloca e recusado se houver conflito. Mapear porta externa diferente da
interna pareceria mais flexivel, mas o jogo anuncia a propria porta na lista da Steam e o
cliente tentaria uma porta que ninguem escuta.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .catalogo import Jogo
from .erros import SemRecurso

DESLOCAMENTO_MAX = 100
PAPEL_JOGO = "jogo"
PAPEL_QUERY = "query"
PAPEL_EXTRA = "extra"


@dataclass(frozen=True)
class PortaAlocada:
    base: int
    numero: int
    proto: str
    papel: str

    @property
    def chave(self) -> tuple[int, str]:
        return (self.numero, self.proto)

    def __str__(self) -> str:
        return f"{self.numero}/{self.proto}"


def ips_da_faixa(prefixo: str, inicio: int, fim: int) -> tuple[str, ...]:
    """`ips_da_faixa("192.168.2", 30, 99)`: os enderecos candidatos, validados como IPv4."""
    if not 1 <= inicio <= fim <= 254:
        raise ValueError("faixa de IP invalida")
    return tuple(str(ipaddress.IPv4Address(f"{prefixo}.{n}")) for n in range(inicio, fim + 1))


def escolher_ctid(faixa: Iterable[int], usados: set[int]) -> int:
    for ctid in faixa:
        if ctid not in usados:
            return ctid
    raise SemRecurso("nao ha CTID livre na faixa do broker")


def escolher_ip(candidatos: Iterable[str], usados: set[str], responde: Callable[[str], bool]) -> str:
    """Primeiro IP fora do banco/Proxmox e que ninguem na rede responde.

    O ultimo teste pega o aparelho que tem IP fixo na mao e o Proxmox nunca soube.
    """
    for ip in candidatos:
        if ip not in usados and not responde(ip):
            return ip
    raise SemRecurso("nao ha IP livre na faixa do broker")


def _papel(jogo: Jogo, base: int) -> str:
    if base == jogo.porta_jogo:
        return PAPEL_JOGO
    if jogo.porta_query and base == jogo.porta_query:
        return PAPEL_QUERY
    return PAPEL_EXTRA


def alocar_portas(jogo: Jogo, ocupadas: set[tuple[int, str]]) -> list[PortaAlocada]:
    """Menor deslocamento em que TODAS as portas do jogo estao livres no WAN."""
    limite = DESLOCAMENTO_MAX if jogo.deslocavel else 0
    primeiro_conflito: str | None = None
    for deslocamento in range(limite + 1):
        candidatas = [PortaAlocada(p.numero, p.numero + deslocamento, p.proto, _papel(jogo, p.numero))
                      for p in jogo.portas]
        if any(c.numero > 65535 for c in candidatas):
            break
        conflitos = [c for c in candidatas if c.chave in ocupadas]
        if not conflitos:
            return candidatas
        primeiro_conflito = primeiro_conflito or str(conflitos[0])
    motivo = "este jogo nao aceita mudar de porta" if not jogo.deslocavel else "sem faixa livre"
    raise SemRecurso(f"porta {primeiro_conflito} ja esta em uso: {motivo}")


def porta_do_papel(portas: Iterable[PortaAlocada], papel: str) -> int:
    return next((p.numero for p in portas if p.papel == papel), 0)
