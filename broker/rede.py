"""Verificacao de IP na rede: alguem ja usa este endereco? (backend `Rede`)"""
from __future__ import annotations

import ipaddress
import subprocess


class RedeReal:
    """Um ping. E a ultima linha de defesa contra o aparelho com IP fixo que o Proxmox nunca
    viu (o banco do broker e o Proxmox so sabem dos CTs). Falha em pingar = livre; um aparelho
    que ignora ICMP passa, e por isso a faixa do broker fica longe dos IPs que voce usa a mao."""

    def __init__(self, timeout: float = 1.0):
        self._timeout = max(1, int(timeout))

    def responde(self, ip: str) -> bool:
        alvo = str(ipaddress.IPv4Address(ip))
        try:
            resultado = subprocess.run(
                ["ping", "-c", "1", "-W", str(self._timeout), alvo],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self._timeout + 3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return resultado.returncode == 0
