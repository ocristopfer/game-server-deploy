"""A trava de tentativas, sozinha: sem HTTP, sem banco e sem dormir.

`test_2fa.py` e `test_login.py` provam que a trava esta LIGADA nas telas certas. Aqui se
prova a regra em si — a janela deslizante, o arredondamento para cima, o isolamento entre
chaves — que por HTTP custaria uma janela de 15 minutos de relogio falso por caso.
"""
from __future__ import annotations

import threading

from gamepanel.services.auth_service import Lockout


class Clock:
    """Relogio que so anda quando o teste manda."""

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
    """`int()` de 0,4 s daria 0, e a tela mandaria tentar de novo para levar outro 429."""
    clock = Clock()
    lock = Lockout(1, 60.0, clock)
    lock.record_failure("ana")
    clock.advance(59.9)
    assert lock.remaining("ana") == 1


def test_a_janela_desliza_pela_tentativa_mais_ANTIGA():
    """Cinco erros bem espacados nao podem trancar a conta para sempre."""
    clock = Clock()
    lock = Lockout(2, 60.0, clock)
    lock.record_failure("ana")
    clock.advance(59.0)
    lock.record_failure("ana")
    assert lock.remaining("ana") > 0
    # A primeira sai da janela e sobra uma so: volta a haver tentativa.
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
    """A da senha e a do codigo sao objetos separados: errar a senha nao pode gastar as
    tentativas de quem ja passou dela e esta digitando o codigo."""
    clock = Clock()
    password, code = Lockout(1, 60.0, clock), Lockout(1, 60.0, clock)
    password.record_failure("ana")
    assert code.remaining("ana") == 0


def test_a_leitura_limpa_o_que_venceu():
    """Sem a limpeza na passagem, a lista de uma conta sob ataque cresceria sem fim."""
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
    """O painel serve varias abas ao mesmo tempo; sem o lock, dois `append` na mesma
    lista podem virar um e a trava demoraria mais a fechar do que devia."""
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
    """`clock=time.time` como valor padrao da assinatura guardaria a funcao original e o
    `monkeypatch` das suites de login deixaria de valer, em silencio."""
    import time as stdlib_time

    lock = Lockout(1, 60.0)
    monkeypatch.setattr(stdlib_time, "time", lambda: 5_000.0)
    lock.record_failure("ana")
    assert lock._failures["ana"] == [5_000.0]
