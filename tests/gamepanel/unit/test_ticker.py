"""The "is it time yet?" clock, on its own - no database, no SSH and no sleeping.

Until now this decision was a module variable with `global` on top, and it could only be
exercised from outside, through `monitor_servers()`. Three rules matter: the first tick
always counts, `force` overrides the interval, and asking does not consume the window.
"""
from __future__ import annotations

from gamepanel.tasks.ticker import Ticker


def test_a_primeira_volta_sempre_vale():
    """Whoever just started the panel wants the reading now, not one interval from now."""
    assert Ticker().due(now=1_000.0, interval=60.0)


def test_antes_do_intervalo_nao_e_hora():
    tick = Ticker()
    tick.mark(1_000.0)
    assert not tick.due(1_030.0, 60.0)


def test_no_intervalo_exato_ja_e_hora():
    """`>=` and not `>`: with `<`, a 60s monitor would move every 60s + one tick."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_060.0, 60.0)


def test_force_passa_por_cima_do_intervalo():
    """It is the screen's "check now" button: nobody waits for the next cycle after clicking."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_001.0, 60.0, force=True)


def test_perguntar_nao_consome_a_janela():
    """The resource gauge clock only records when something WAS read. If `due` recorded by
    itself, a tick with no resource alert enabled would spend the interval, and the next
    tick - with one of them now enabled - would wait the whole thing again."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_060.0, 60.0)
    assert tick.due(1_060.0, 60.0), "perguntar duas vezes da a mesma resposta"


def test_anotar_adia_a_proxima():
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_060.0, 60.0)
    tick.mark(1_060.0)
    assert not tick.due(1_060.0, 60.0)


def test_o_intervalo_e_por_CHAMADA_e_nao_do_relogio():
    """The monitor step shortens when a player alert is on: the same clock answers to 60s
    and to 15s depending on the tick."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert not tick.due(1_020.0, 60.0)
    assert tick.due(1_020.0, 15.0)


def test_reset_volta_ao_painel_recem_subido():
    tick = Ticker()
    tick.mark(1_000.0)
    assert not tick.due(1_001.0, 60.0)
    tick.reset()
    assert tick.due(1_001.0, 60.0)


def test_um_relogio_nao_mexe_no_outro():
    """Six rhythms, six instances: advancing the log one must not silence the monitor's."""
    one, other = Ticker(), Ticker()
    one.mark(1_000.0)
    assert other.due(1_001.0, 60.0)
