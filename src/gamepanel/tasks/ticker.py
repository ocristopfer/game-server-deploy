"""Relogio de "ja e hora?" — um por ritmo, em vez de um `global` por ritmo.

O painel tem seis passos diferentes rodando na mesma thread de fundo (monitor, estado
do servico, medidor de recurso, log, amostra, limpeza do historico), e cada um era uma
variavel de modulo com `global` em cima. Duas consequencias, as duas ja pagas:

- o `conftest.py` precisava zerar as seis PELO NOME, e uma renomeada em silencio faria
  um teste herdar o relogio do anterior — sem erro, so com um alerta que nao dispara;
- decidir "ja e hora?" so dava para testar mexendo em `global`, entao ninguem testou.

E de proposito que `due` NAO anota a passagem: o relogio do medidor de recurso so avanca
quando algum alerta de recurso esta ligado. Perguntar e anotar sao duas coisas, e junta-las
faria a janela ser consumida por uma volta que nao leu nada.
"""
from __future__ import annotations


class Ticker:
    def __init__(self) -> None:
        # Zero (e nao "agora") para a primeira volta sempre valer: quem acabou de subir
        # o painel quer a primeira leitura ja, nao daqui a um intervalo.
        self._last = 0.0

    def due(self, now: float, interval: float, force: bool = False) -> bool:
        """Passou tempo suficiente? `force` e o botao "conferir agora" da tela."""
        return force or now - self._last >= interval

    def mark(self, now: float) -> None:
        self._last = now

    def reset(self) -> None:
        """Volta ao estado de painel recem-subido. So para o `conftest.py`."""
        self._last = 0.0
