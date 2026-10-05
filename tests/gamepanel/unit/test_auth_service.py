"""The attempt lockout, on its own: no HTTP, no database and no sleeping.

`test_2fa.py` and `test_login.py` prove the lockout is WIRED on the right screens. Here the
rule itself is proven - the sliding window, the rounding up, the isolation between keys -
which over HTTP would cost a 15-minute window of fake clock per case.
"""
from __future__ import annotations

import threading

from gamepanel.services.auth_service import Lockout


class Clock:
    """A clock that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_dentro_do_limite_nao_trava():
    clock = Clock()
    lock = Lockout(3, 60.0, clock)
    for _ in range(2):
        lock.record_failure("ana")
    assert lock.remaining("ana") == 0


def test_a_tentativa_que_estoura_o_limite_tranca():
    clock = Clock()
    lock = Lockout(3, 60.0, clock)
    for _ in range(3):
        lock.record_failure("ana")
    assert lock.remaining("ana") > 0


def test_a_espera_nunca_e_zero_segundos():
    """`int()` of 0.4 s would give 0, and the screen would say to try again only to get another 429."""
    clock = Clock()
    lock = Lockout(1, 60.0, clock)
    lock.record_failure("ana")
    clock.advance(59.9)
    assert lock.remaining("ana") == 1


def test_a_janela_desliza_pela_tentativa_mais_ANTIGA():
    """Five well-spaced mistakes must not lock the account forever."""
    clock = Clock()
    lock = Lockout(2, 60.0, clock)
    lock.record_failure("ana")
    clock.advance(59.0)
    lock.record_failure("ana")
    assert lock.remaining("ana") > 0
    # The first one leaves the window and only one is left: attempts are available again.
    clock.advance(2.0)
    assert lock.remaining("ana") == 0


def test_acertar_apaga_o_que_ja_tinha_errado():
    clock = Clock()
    lock = Lockout(2, 60.0, clock)
    lock.record_failure("ana")
    lock.clear("ana")
    lock.record_failure("ana")
    assert lock.remaining("ana") == 0


def test_uma_conta_trancada_nao_tranca_a_outra():
    clock = Clock()
    lock = Lockout(1, 60.0, clock)
    lock.record_failure("ana")
    assert lock.remaining("ana") > 0
    assert lock.remaining("bia") == 0


def test_duas_travas_nao_dividem_tentativa():
    """The password lockout and the code lockout are separate objects: mistyping the password
    must not spend the attempts of someone who already got past it and is typing the code."""
    clock = Clock()
    password, code = Lockout(1, 60.0, clock), Lockout(1, 60.0, clock)
    password.record_failure("ana")
    assert code.remaining("ana") == 0


def test_a_leitura_limpa_o_que_venceu():
    """Without pruning on the way, the list of an account under attack would grow forever."""
    clock = Clock()
    lock = Lockout(5, 60.0, clock)
    for _ in range(4):
        lock.record_failure("ana")
    clock.advance(61.0)
    lock.remaining("ana")
    assert lock._failures["ana"] == []


def test_reset_esquece_todas_as_chaves():
    clock = Clock()
    lock = Lockout(1, 60.0, clock)
    lock.record_failure("ana")
    lock.record_failure("bia")
    lock.reset()
    assert lock.remaining("ana") == 0
    assert lock.remaining("bia") == 0


def test_tentativas_simultaneas_nao_se_perdem():
    """The panel serves several tabs at once; without the lock, two `append`s on the same
    list can become one and the lockout would take longer to close than it should."""
    clock = Clock()
    lock = Lockout(1_000, 60.0, clock)
    threads = [threading.Thread(target=lambda: [lock.record_failure("ana")
                                                for _ in range(50)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(lock._failures["ana"]) == 400


def test_sem_relogio_injetado_o_nome_e_resolvido_na_HORA(monkeypatch):
    """`clock=time.time` as the default value in the signature would keep the original
    function and the login suites' `monkeypatch` would silently stop taking effect."""
    import time as stdlib_time

    lock = Lockout(1, 60.0)
    monkeypatch.setattr(stdlib_time, "time", lambda: 5_000.0)
    lock.record_failure("ana")
    assert lock._failures["ana"] == [5_000.0]
