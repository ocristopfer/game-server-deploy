"""O relogio do painel (gamepanel.tasks.scheduler).

A regra de ouro aqui ja tinha teste pelo lado do painel (uma agenda quebrada nao pode
levar o monitor junto — test_alerts.py); estes sao os mesmos invariantes vistos de
perto, mais o que a classe `Relogio` acrescentou: `start()` duas vezes nao pode virar
duas threads, senao cada tarefa dispararia em dobro.
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
    """Sem o nome, "alguma coisa do relogio caiu" nao ajuda ninguem a procurar."""
    failed: list[str] = []

    def explode():
        raise ValueError("x")

    scheduler.tick((("limpeza", explode),), failed.append)
    assert failed == ["limpeza"]


def test_start_duas_vezes_nao_vira_duas_threads():
    """Duas threads fariam cada tarefa agendada disparar em dobro."""
    rounds = threading.Semaphore(0)
    clock_of = scheduler.Clock(0.01, rounds.release, logging.getLogger("teste"))

    def ours() -> int:
        """So as threads DESTE relogio, pelo nome.

        Era `threading.active_count()` antes e passava a maior parte das vezes: o numero e
        do PROCESSO inteiro, e importar o `gamepanel.app` ja sobe uma thread de agendador
        propria — qualquer thread alheia nascendo ou morrendo entre as duas leituras fazia
        a conta fechar errado. Falhou 1 em 3 rodando este balde sozinho.
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
    """Se a volta derrubasse a thread, o painel ficaria sem relogio ate reiniciar."""
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
