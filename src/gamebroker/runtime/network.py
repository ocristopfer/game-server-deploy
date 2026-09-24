"""Verificacao de IP na rede: alguem ja usa este endereco? (backend `Rede`)"""
from __future__ import annotations

import ipaddress
import subprocess


class RealNetwork:
    """Um ping. E a ultima linha de defesa contra o aparelho com IP fixo que o Proxmox nunca
    viu (o banco do broker e o Proxmox so sabem dos CTs). Falha em pingar = livre; um aparelho
    que ignora ICMP passa, e por isso a faixa do broker fica longe dos IPs que voce usa a mao."""

    def __init__(self, timeout: float = 1.0):
        self._timeout = max(1, int(timeout))

    def answers(self, ip: str) -> bool:
        target = str(ipaddress.IPv4Address(ip))
        try:
            # O argv e literal e o unico valor variavel passou por `IPv4Address`, que
            # recusa qualquer coisa que nao seja um IP: nada de fora chega ao comando.
            # `ping` sem caminho absoluto de proposito: ele muda de lugar entre distros
            # (/bin, /usr/bin, /sbin) e fixar um quebraria em metade delas.
            result = subprocess.run(  # noqa: S603
                ["ping", "-c", "1", "-W", str(self._timeout), target],  # noqa: S607
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self._timeout + 3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
