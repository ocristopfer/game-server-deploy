"""CPU, memoria, disco e rede do container, com cache curto.

O script remoto e a leitura dos numeros moram em `runtime.metrics_probe`; aqui fica o
que sobra de decisao: quando vale reaproveitar a leitura anterior e o que a tela recebe
quando o container nao responde.

Cada leitura custa uma ida de SSH de ~1s (sao duas amostras espacadas dentro do
container). Sem o cache, tres abas abertas na mesma tela viram tres sessoes de SSH por
segundo no mesmo servidor.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gamepanel.runtime import metrics_probe
from gamepanel.runtime.ssh import RemoteError, ServerLike, quote_command

# (server, comando, timeout) -> saida; RemoteError quando a ida de SSH falha.
SshOutput = Callable[..., str]

_metrics_cache: dict[int, tuple[float, dict]] = {}
_metrics_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    with _metrics_lock:
        _metrics_cache.pop(int(server_id), None)


def server_metrics(ssh_output: SshOutput, server: ServerLike, dir_padrao: str, ttl: float,
                   force: bool = False) -> dict:
    """Uso de CPU, memoria, disco e rede do container."""
    key = int(server["id"])
    agora = time.monotonic()
    if not force:
        with _metrics_lock:
            cached = _metrics_cache.get(key)
        if cached and agora - cached[0] < ttl:
            return cached[1]

    alvo = server["config_path"] or dir_padrao
    try:
        raw = ssh_output(
            server,
            quote_command("bash", "-lc", metrics_probe.METRICS_SCRIPT, "gp", server["service"], alvo),
            timeout=30,
        )
        data = metrics_probe.parse_metrics(raw)
        data["error"] = ""
    except RemoteError as exc:
        data = {"error": str(exc)}

    with _metrics_lock:
        _metrics_cache[key] = (agora, data)
    return data
