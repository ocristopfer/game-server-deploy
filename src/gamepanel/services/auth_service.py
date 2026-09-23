"""Trava de tentativas: quantas erradas cabem numa janela, e quanto falta para liberar.

Sem Flask e sem banco. O estado vive na MEMORIA do processo de proposito — o painel roda
com um worker so (ver `provision-admin-lxc.sh`), e guardar isso no banco custaria uma
escrita por tentativa errada, que e exatamente o que um ataque produz em volume.

Reiniciar o painel zera as travas. E aceitavel: quem reinicia e quem tem acesso ao
container, e ja pode mais do que isso.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class Lockout:
    """Uma trava, com seu proprio limite e sua propria janela.

    Cada etapa do login tem a sua (senha e codigo), e nao uma so com dois limites: errar
    a senha cinco vezes nao pode gastar as tentativas de quem ja passou dela e esta
    digitando o codigo.
    """

    def __init__(self, tries: int, window: float,
                 clock: Callable[[], float] | None = None) -> None:
        self._tries = tries
        self._window = window
        # `clock=time.time` na assinatura pareceria mais direto e QUEBRARIA os testes: o
        # valor padrao e avaliado uma vez, na definicao, e guardaria a funcao original —
        # o `monkeypatch.setattr(time, "time", ...)` de `test_2fa.py` passaria a nao ter
        # efeito nenhum. Guardando None, o nome e resolvido no modulo a cada chamada.
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        # O painel serve varias abas ao mesmo tempo, e duas tentativas simultaneas
        # mexeriam na mesma lista.
        self._lock = threading.Lock()

    def _now(self) -> float:
        return self._clock() if self._clock else time.time()

    def remaining(self, key: str) -> int:
        """Segundos que faltam para liberar; 0 quando ainda ha tentativa.

        Limpa as tentativas vencidas na passagem: a janela e deslizante, e sem isso uma
        conta ficaria trancada para sempre depois de cinco erros bem espacados.
        """
        with self._lock:
            now = self._now()
            fresh = [t for t in self._failures.get(key, []) if now - t < self._window]
            self._failures[key] = fresh
            if len(fresh) < self._tries:
                return 0
            # Arredonda para cima: dizer "faltam 0 segundos" e mandar tentar de novo para
            # levar o mesmo 429.
            return int(self._window - (now - fresh[0])) + 1

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(self._now())

    def clear(self, key: str) -> None:
        """Acertou: as tentativas anteriores deixam de contar.

        Sem isto, quem erra quatro vezes, acerta, e erra a quinta amanha ficaria trancado
        por causa de erros de ontem.
        """
        with self._lock:
            self._failures.pop(key, None)

    def reset(self) -> None:
        """Esquece TODAS as chaves. So para o `conftest.py`, entre um teste e o outro."""
        with self._lock:
            self._failures.clear()
