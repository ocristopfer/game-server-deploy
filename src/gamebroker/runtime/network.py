"""Checking an IP on the network: is anyone already using this address? (`Rede` backend)"""
from __future__ import annotations

import ipaddress
import subprocess


class RealNetwork:
    """A ping. It is the last line of defense against a device with a static IP that Proxmox
    never saw (the broker database and Proxmox only know about the CTs). Failing to ping = free;
    a device that ignores ICMP gets through, which is why the broker range stays away from the
    IPs you assign by hand."""

    def __init__(self, timeout: float = 1.0):
        self._timeout = max(1, int(timeout))

    def answers(self, ip: str) -> bool:
        target = str(ipaddress.IPv4Address(ip))
        try:
            # The argv is literal and the only variable value went through `IPv4Address`, which
            # rejects anything that is not an IP: nothing from outside reaches the command.
            # `ping` without an absolute path on purpose: it moves between distros
            # (/bin, /usr/bin, /sbin) and pinning one would break on half of them.
            result = subprocess.run(  # noqa: S603
                ["ping", "-c", "1", "-W", str(self._timeout), target],  # noqa: S607
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=self._timeout + 3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
