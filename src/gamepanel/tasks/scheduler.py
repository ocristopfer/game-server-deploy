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
Task = tuple[str, Callable[[], Any]]


def tick(tasks: Iterable[Task], on_failure: Callable[[str], None]) -> None:
    """Uma volta do relogio.

    Cada tarefa vai no SEU try. Dividindo um try so, uma agenda quebrada levava junto o
    monitor e as amostras: a excecao subia na primeira tarefa e as outras tres nunca
    rodavam — para sempre, porque a tarefa quebrada quebrava de novo a cada volta. Por
    fora o painel parecia inteiro, e o botao de testar webhook (que nao passa por aqui)
    continuava funcionando e afastando a suspeita do lugar certo.
    """
    for name, task in tasks:
        try:
            task()
        # Uma tarefa nao derruba as outras.
        except Exception:  # noqa: BLE001
            on_failure(name)


class Clock:
    """A thread em si. `start()` e idempotente: duas chamadas nao dao duas threads."""

    def __init__(self, interval: float, one_round: Callable[[], None],
                 logger: logging.Logger) -> None:
        self._interval = interval
        self._one_round = one_round
        self._logger = logger
        self._started = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def _loop(self) -> None:
        # Event.wait no lugar de sleep: assim o `stop()` corta a espera na hora em vez
        # de deixar a thread pendurada ate o fim do intervalo.
        while not self._stop_event.wait(self._interval):
            try:
                self._one_round()
            # A thread nao pode morrer por causa de um tick.
            except Exception:
                self._logger.exception("falha no agendador")

    # A thread tem NOME, e nao e enfeite: sem ele um dump de pilha (`faulthandler`,
    # `py-spy`) mostra `Thread-1 (_loop)` e nao se sabe qual das threads de fundo do painel
    # travou. E e o nome que deixa um teste contar as threads DESTE relogio em vez de
    # `threading.active_count()`, que conta as alheias — importar o `app.py` ja sobe uma.
    THREAD_NAME = "gamepanel-scheduler"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._loop, daemon=True, name=self.THREAD_NAME).start()

    def stop(self) -> None:
        """Encerra a thread. O painel nao usa (o processo inteiro morre junto); existe
        para o teste nao deixar relogio batendo pelo resto da suite."""
        self._stop_event.set()
