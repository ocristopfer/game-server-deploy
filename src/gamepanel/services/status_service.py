"""Esta de pe? O estado do servico do jogo dentro do container, com cache curto.

`systemctl show` no lugar de `is-active` porque a mesma ida de SSH ja traz o que
distingue "eu parei" de "quebrou" (Result) e o contador de reinicios automaticos
(NRestarts) — sem ele um loop de crash e invisivel: entre uma queda e a proxima o
`is-active` responde 'active' e o painel nunca ve nada.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from gamepanel.runtime.ssh import RemoteError, ServerLike, quote_command

# (server, comando) -> saida; RemoteError quando a ida de SSH falha.
SshOutput = Callable[..., str]

# Cache de processo, compartilhado com quem publica estes nomes em `app.py`: a mesma
# tela pergunta o estado varias vezes por segundo (lista, medidor, aba aberta ao lado).
_status_cache: dict[int, tuple[float, dict]] = {}
_status_lock = threading.Lock()


def invalidate(server_id: int) -> None:
    with _status_lock:
        _status_cache.pop(int(server_id), None)


def _systemctl_fields(ssh_output: SshOutput, server: ServerLike) -> dict[str, str]:
    # Ele sai com 0 mesmo para unidade que nao existe, entao nao precisa de '|| true'.
    raw = ssh_output(server, quote_command(
        "systemctl", "show", server["service"],
        "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "Result",
    ))
    fields = {}
    for line in raw.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    return fields


def server_status(ssh_output: SshOutput, server: ServerLike, ttl: float,
                  force: bool = False) -> dict:
    key = int(server["id"])
    now = time.monotonic()
    if not force:
        with _status_lock:
            cached = _status_cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]

    state = {"reachable": False, "service": "desconhecido", "error": "",
             "sub": "", "restarts": 0, "result": ""}
    try:
        fields = _systemctl_fields(ssh_output, server)
        state["reachable"] = True
        state["service"] = fields.get("ActiveState") or "inactive"
        state["sub"] = fields.get("SubState", "")
        state["result"] = fields.get("Result", "")
        # NRestarts so existe no systemd >= 235; sem ele o loop de restart nao e
        # detectavel e o painel simplesmente nao avisa desse evento nesse servidor.
        try:
            state["restarts"] = int(fields.get("NRestarts", "0") or 0)
        except ValueError:
            state["restarts"] = 0
    except RemoteError as exc:
        state["error"] = str(exc)
        state["service"] = "inacessivel"

    with _status_lock:
        _status_cache[key] = (now, state)
    return state
