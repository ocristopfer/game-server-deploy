"""Escolha de CTID, IP e portas. Funcoes puras: quem sabe o que esta ocupado (banco,
Proxmox, OPNsense, rede) monta os conjuntos e entrega aqui.

A porta interna e a externa sao SEMPRE iguais. Jogo `deslocavel` recebe um bloco de portas
seguidas de uma FAIXA PROPRIA do broker (longe das portas padrao dos jogos, que os seus
servidores antigos ja usam) e o instalador avisa o jogo (GAME_PORT/QUERY_PORT); jogo que nao
desloca fica com as portas padrao e e recusado se houver conflito. Mapear porta externa
diferente da interna pareceria mais flexivel, mas o jogo anuncia a propria porta na lista da
Steam e o cliente tentaria uma porta que ninguem escuta.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .catalogo import Jogo
from .erros import SemRecurso

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


def escolher_ip_e_ctid(candidatos: Iterable[str], ctid_base: int, ctids_usados: set[int],
                       ips_usados: set[str], responde: Callable[[str], bool]) -> tuple[str, int]:
    """IP e CTID juntos: o CTID e `ctid_base` + o ultimo numero do IP (.102 -> 302).

    Escolher os dois separados deixaria o CTID e o IP andarem em ritmos diferentes assim que
    um container fosse apagado na mao, e a regra de cabeca (ver o IP, saber o CTID) deixaria
    de valer. Aqui um IP so serve se o CTID dele tambem estiver livre.
    """
    for ip in candidatos:
        ctid = ctid_base + int(ip.rsplit(".", 1)[1])
        if ip not in ips_usados and ctid not in ctids_usados and not responde(ip):
            return ip, ctid
    raise SemRecurso("nao ha IP/CTID livre na faixa do broker")


def _papel(jogo: Jogo, base: int) -> str:
    if base == jogo.porta_jogo:
        return PAPEL_JOGO
    if jogo.porta_query and base == jogo.porta_query:
        return PAPEL_QUERY
    return PAPEL_EXTRA


def _em_bloco(jogo: Jogo, inicio: int) -> list[PortaAlocada]:
    """Cada porta-base distinta do jogo vira um numero do bloco; a mesma base em UDP e TCP
    (Satisfactory) fica com o mesmo numero nos dois protocolos."""
    numero_de: dict[int, int] = {}
    for porta in jogo.portas:
        numero_de.setdefault(porta.numero, inicio + len(numero_de))
    return [PortaAlocada(p.numero, numero_de[p.numero], p.proto, _papel(jogo, p.numero))
            for p in jogo.portas]


def alocar_portas(jogo: Jogo, ocupadas: set[tuple[int, str]], faixa: range) -> list[PortaAlocada]:
    """Jogo fixo: as portas padrao. Jogo `deslocavel`: o primeiro bloco livre da `faixa`."""
    if not jogo.deslocavel:
        candidatas = [PortaAlocada(p.numero, p.numero, p.proto, _papel(jogo, p.numero)) for p in jogo.portas]
        conflitos = [c for c in candidatas if c.chave in ocupadas]
        if conflitos:
            raise SemRecurso(f"porta {conflitos[0]} ja esta em uso: este jogo nao aceita mudar de porta")
        return candidatas
    tamanho = len({p.numero for p in jogo.portas})
    for inicio in range(faixa.start, faixa.stop - tamanho + 1):
        candidatas = _em_bloco(jogo, inicio)
        if not any(c.chave in ocupadas for c in candidatas):
            return candidatas
    raise SemRecurso(f"a faixa de portas do broker ({faixa.start}-{faixa.stop - 1}) esta cheia")


def porta_do_papel(portas: Iterable[PortaAlocada], papel: str) -> int:
    return next((p.numero for p in portas if p.papel == papel), 0)
