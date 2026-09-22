"""Perguntar a mesma coisa a varios servidores ao mesmo tempo.

Estado, medidores e contagem de jogadores custam, cada um, uma ida de rede por
servidor. Em serie a tela paga a soma — e com um container fora do ar, a soma dos
tempos esgotados. Esta era a mesma trinta linhas escrita tres vezes (status, recursos,
jogadores), cada copia com um detalhe diferente.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from gamepanel.runtime.ssh import ServerLike


def per_server(
    query: Callable[[ServerLike], dict],
    servers: Sequence[ServerLike],
    timeout: float,
    fallback: dict,
) -> dict[int, dict]:
    """Roda `consulta` para cada servidor em paralelo; devolve {id do servidor: resposta}.

    Quem nao voltou dentro de `timeout` entra com uma COPIA de `fallback` — copia, e nao
    o mesmo objeto em varias chaves: a tela e o monitor escrevem em cima do que recebem,
    e um dicionario compartilhado faria a anotacao de um servidor aparecer no outro.
    """
    results: dict[int, dict] = {}
    lock = threading.Lock()

    def work(srv: ServerLike) -> None:
        data = query(srv)
        with lock:
            results[int(srv["id"])] = data

    threads = [threading.Thread(target=work, args=(s,), daemon=True) for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
    for srv in servers:
        results.setdefault(int(srv["id"]), dict(fallback))
    return results
