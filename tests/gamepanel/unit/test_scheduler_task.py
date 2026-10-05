"""The panel clock (gamepanel.tasks.scheduler).

The golden rule here was already tested from the panel side (a broken schedule must not
take the monitor down with it - test_alerts.py); these are the same invariants seen up
close, plus what the `Relogio` class added: calling `start()` twice must not turn into two
threads, or every task would fire twice.
"""
from __future__ import annotations

import logging
import threading
import time

from gamepanel.tasks import scheduler


def test_uma_tarefa_que_explode_nao_impede_as_outras():
    ran: list[str] = []
    failed: list[str] = []

    def explode():
        raise RuntimeError("agenda quebrada")

    scheduler.tick(
        (("agenda", explode),
         ("monitor", lambda: ran.append("monitor")),
         ("amostras", lambda: ran.append("amostras"))),
        failed.append,
    )
    assert ran == ["monitor", "amostras"]
    assert failed == ["agenda"]


def test_a_falha_e_anunciada_com_o_nome_da_tarefa():
    """Without the name, "something in the clock died" helps nobody look for it."""
    failed: list[str] = []

    def explode():
        raise ValueError("x")

    scheduler.tick((("limpeza", explode),), failed.append)
    assert failed == ["limpeza"]


def test_start_duas_vezes_nao_vira_duas_threads():
    """Two threads would make every scheduled task fire twice."""
    rounds = threading.Semaphore(0)
    clock_of = scheduler.Clock(0.01, rounds.release, logging.getLogger("teste"))

    def ours() -> int:
        """Only THIS clock's threads, by name.

        It used to be `threading.active_count()` and passed most of the time: the number is
        for the whole PROCESS, and importing `gamepanel.app` already starts a scheduler thread
        of its own - any unrelated thread starting or dying between the two readings made the
        count come out wrong. It failed 1 in 3 when running this bucket alone.
        """
        return sum(1 for t in threading.enumerate() if t.name == scheduler.Clock.THREAD_NAME)

    before = ours()
    try:
        clock_of.start()
        clock_of.start()
        clock_of.start()
        assert rounds.acquire(timeout=2), "o relogio nem chegou a bater"
        assert ours() - before == 1
    finally:
        clock_of.stop()


def test_a_thread_sobrevive_a_um_tique_que_explode():
    """If the tick killed the thread, the panel would be without a clock until restarted."""
    beats: list[int] = []

    def round_trip():
        beats.append(1)
        raise RuntimeError("tique ruim")

    clock_of = scheduler.Clock(0.01, round_trip, logging.getLogger("teste"))
    clock_of.start()
    try:
        end_at = time.monotonic() + 2
        while len(beats) < 3 and time.monotonic() < end_at:
            time.sleep(0.01)
        assert len(beats) >= 3, "a thread parou no primeiro erro"
    finally:
        clock_of.stop()


def test_parar_encerra_a_batida():
    beats: list[int] = []
    clock_of = scheduler.Clock(0.01, lambda: beats.append(1), logging.getLogger("teste"))
    clock_of.start()
    end_at = time.monotonic() + 2
    while not beats and time.monotonic() < end_at:
        time.sleep(0.01)
    assert beats, "o relogio nem comecou"
    clock_of.stop()
    time.sleep(0.05)
    how_many_f = len(beats)
    time.sleep(0.1)
    assert len(beats) == how_many_f, "continuou batendo depois de parar"
