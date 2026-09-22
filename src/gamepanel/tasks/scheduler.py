"""O relogio do painel: uma thread que acorda de tempos em tempos e chama as tarefas.

Sao cinco (agendamentos, monitor, log em tempo real, amostras e limpeza) e elas moram
em `app.py`, cada uma com o seu proprio relogio interno — aqui nao ha regra nenhuma
sobre QUANDO cada uma deve rodar, so a batida.

Depende de o painel rodar com UM worker (e como o gunicorn e configurado aqui, veja o
provision-admin-lxc.sh): com dois processos, cada um teria a sua thread e a mesma
tarefa dispararia em dobro.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

# (nome para o log, o que rodar).
Tarefa = tuple[str, Callable[[], Any]]


def tick(tarefas: Iterable[Tarefa], ao_falhar: Callable[[str], None]) -> None:
    """Uma volta do relogio.

    Cada tarefa vai no SEU try. Dividindo um try so, uma agenda quebrada levava junto o
    monitor e as amostras: a excecao subia na primeira tarefa e as outras tres nunca
    rodavam — para sempre, porque a tarefa quebrada quebrava de novo a cada volta. Por
    fora o painel parecia inteiro, e o botao de testar webhook (que nao passa por aqui)
    continuava funcionando e afastando a suspeita do lugar certo.
    """
    for nome, tarefa in tarefas:
        try:
            tarefa()
        # Uma tarefa nao derruba as outras.
        except Exception:  # noqa: BLE001
            ao_falhar(nome)


class Relogio:
    """A thread em si. `start()` e idempotente: duas chamadas nao dao duas threads."""

    def __init__(self, intervalo: float, uma_volta: Callable[[], None],
                 logger: logging.Logger) -> None:
        self._intervalo = intervalo
        self._uma_volta = uma_volta
        self._logger = logger
        self._comecou = False
        self._lock = threading.Lock()
        self._parar = threading.Event()

    def _loop(self) -> None:
        # Event.wait no lugar de sleep: assim o `parar()` corta a espera na hora em vez
        # de deixar a thread pendurada ate o fim do intervalo.
        while not self._parar.wait(self._intervalo):
            try:
                self._uma_volta()
            # A thread nao pode morrer por causa de um tick.
            except Exception:
                self._logger.exception("falha no agendador")

    def start(self) -> None:
        with self._lock:
            if self._comecou:
                return
            self._comecou = True
        threading.Thread(target=self._loop, daemon=True).start()

    def parar(self) -> None:
        """Encerra a thread. O painel nao usa (o processo inteiro morre junto); existe
        para o teste nao deixar relogio batendo pelo resto da suite."""
        self._parar.set()
