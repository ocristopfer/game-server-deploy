"""O relogio de "ja e hora?", sozinho — sem banco, sem SSH e sem dormir.

Ate aqui essa decisao era uma variavel de modulo com `global` em cima, e so dava para
exercita-la de fora, por `monitor_servers()`. As regras que importam sao tres: a primeira
volta sempre vale, `force` passa por cima do intervalo, e perguntar nao consome a janela.
"""
from __future__ import annotations

from gamepanel.tasks.ticker import Ticker


def test_a_primeira_volta_sempre_vale():
    """Quem acabou de subir o painel quer a leitura agora, nao daqui a um intervalo."""
    assert Ticker().due(now=1_000.0, interval=60.0)


def test_antes_do_intervalo_nao_e_hora():
    tick = Ticker()
    tick.mark(1_000.0)
    assert not tick.due(1_030.0, 60.0)


def test_no_intervalo_exato_ja_e_hora():
    """`>=` e nao `>`: com `<`, um monitor de 60s andaria a cada 60s + uma volta."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_060.0, 60.0)


def test_force_passa_por_cima_do_intervalo():
    """E o botao "conferir agora" da tela: ninguem espera o proximo ciclo por ter clicado."""
    tick = Ticker()
    tick.mark(1_000.0)
    assert tick.due(1_001.0, 60.0, force=True)


def test_perguntar_nao_consome_a_janela():
    """O relogio do medidor de recurso so anota quando algo FOI lido. Se `due` anotasse
    sozinho, uma volta sem nenhum alerta de recurso ligado gastaria o intervalo e a volta
    seguinte — ja com um deles ligado — esperaria tudo de novo."""
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
    """O passo do monitor encurta quando ha alerta de jogador ligado: o mesmo relogio
    responde a 60s e a 15s conforme a volta."""
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
    """Seis ritmos, seis instancias: adiantar o do log nao pode calar o do monitor."""
    one, other = Ticker(), Ticker()
    one.mark(1_000.0)
    assert other.due(1_001.0, 60.0)
