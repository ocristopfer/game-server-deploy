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
    rodaram: list[str] = []
    falharam: list[str] = []

    def explode():
        raise RuntimeError("agenda quebrada")

    scheduler.tick(
        (("agenda", explode),
         ("monitor", lambda: rodaram.append("monitor")),
         ("amostras", lambda: rodaram.append("amostras"))),
        falharam.append,
    )
    assert rodaram == ["monitor", "amostras"]
    assert falharam == ["agenda"]


def test_a_falha_e_anunciada_com_o_nome_da_tarefa():
    """Sem o nome, "alguma coisa do relogio caiu" nao ajuda ninguem a procurar."""
    falharam: list[str] = []

    def explode():
        raise ValueError("x")

    scheduler.tick((("limpeza", explode),), falharam.append)
    assert falharam == ["limpeza"]


def test_start_duas_vezes_nao_vira_duas_threads():
    """Duas threads fariam cada tarefa agendada disparar em dobro."""
    voltas = threading.Semaphore(0)
    relogio = scheduler.Relogio(0.01, voltas.release, logging.getLogger("teste"))
    antes = threading.active_count()
    try:
        relogio.start()
        relogio.start()
        relogio.start()
        assert voltas.acquire(timeout=2), "o relogio nem chegou a bater"
        assert threading.active_count() - antes == 1
    finally:
        relogio.parar()


def test_a_thread_sobrevive_a_um_tique_que_explode():
    """Se a volta derrubasse a thread, o painel ficaria sem relogio ate reiniciar."""
    batidas: list[int] = []

    def volta():
        batidas.append(1)
        raise RuntimeError("tique ruim")

    relogio = scheduler.Relogio(0.01, volta, logging.getLogger("teste"))
    relogio.start()
    try:
        fim = time.monotonic() + 2
        while len(batidas) < 3 and time.monotonic() < fim:
            time.sleep(0.01)
        assert len(batidas) >= 3, "a thread parou no primeiro erro"
    finally:
        relogio.parar()


def test_parar_encerra_a_batida():
    batidas: list[int] = []
    relogio = scheduler.Relogio(0.01, lambda: batidas.append(1), logging.getLogger("teste"))
    relogio.start()
    fim = time.monotonic() + 2
    while not batidas and time.monotonic() < fim:
        time.sleep(0.01)
    assert batidas, "o relogio nem comecou"
    relogio.parar()
    time.sleep(0.05)
    quantas = len(batidas)
    time.sleep(0.1)
    assert len(batidas) == quantas, "continuou batendo depois de parar"
