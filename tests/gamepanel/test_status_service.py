"""Estado do servico do jogo (gamepanel.services.status_service).

A LEITURA do `systemctl show` nao tinha teste antes da Fase 4: os testes de alerta
montam o dicionario de estado a mao e trocam `server_status` inteiro por um falso, o
que exercita a regra do alerta e nunca o que chega do container. E ai moram coisas que
so aparecem em maquina de verdade — systemd antigo sem `NRestarts`, unidade que nao
existe, container inalcancavel.
"""
from __future__ import annotations

import pytest

from gamepanel.runtime.ssh import RemoteError
from gamepanel.services import status_service as ss

SERVIDOR = {"id": 1, "service": "palworld.service"}


@pytest.fixture(autouse=True)
def clean_cache():
    ss._status_cache.clear()
    yield
    ss._status_cache.clear()


def output_of(**campos) -> str:
    return "\n".join(f"{k}={v}" for k, v in campos.items())


def ssh_that_answers(text: str, registro: list | None = None):
    def ssh_output(server, comando, timeout=None):
        if registro is not None:
            registro.append(comando)
        return text
    return ssh_output


def test_le_os_quatro_campos_do_systemctl():
    text = output_of(ActiveState="active", SubState="running", NRestarts="2", Result="success")
    state = ss.server_status(ssh_that_answers(text), SERVIDOR, 5)
    assert state["reachable"] is True
    assert state["service"] == "active"
    assert state["sub"] == "running"
    assert state["restarts"] == 2
    assert state["result"] == "success"
    assert state["error"] == ""


def test_pergunta_pelos_campos_que_distinguem_parada_de_queda():
    """Sem Result e NRestarts nao da para separar 'eu parei' de 'quebrou em loop'."""
    record: list = []
    ss.server_status(ssh_that_answers(output_of(ActiveState="active"), record), SERVIDOR, 5)
    command = record[0]
    assert "systemctl show palworld.service" in command
    for field in ("ActiveState", "SubState", "NRestarts", "Result"):
        assert field in command


def test_unidade_inexistente_vira_inactive():
    """`systemctl show` sai com 0 e ActiveState vazio para unidade que nao existe."""
    state = ss.server_status(ssh_that_answers(output_of(ActiveState="")), SERVIDOR, 5)
    assert state["reachable"] is True
    assert state["service"] == "inactive"


def test_systemd_antigo_sem_nrestarts_nao_quebra():
    """NRestarts so existe no systemd >= 235; sem ele o painel so nao avisa desse evento."""
    state = ss.server_status(ssh_that_answers(output_of(ActiveState="active")), SERVIDOR, 5)
    assert state["restarts"] == 0


def test_nrestarts_que_nao_e_numero_vira_zero():
    text = output_of(ActiveState="active", NRestarts="[not set]")
    assert ss.server_status(ssh_that_answers(text), SERVIDOR, 5)["restarts"] == 0


def test_container_inalcancavel_vira_estado_e_nao_excecao():
    """A lista de servidores nao pode cair porque um container esta fora do ar."""
    def explode(server, comando, timeout=None):
        raise RemoteError("tempo esgotado (20s) executando no host 10.0.0.1")

    state = ss.server_status(explode, SERVIDOR, 5)
    assert state["reachable"] is False
    assert state["service"] == "inacessivel"
    assert "tempo esgotado" in state["error"]


def test_segunda_pergunta_dentro_do_prazo_vem_do_cache():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.server_status(ssh, SERVIDOR, 5)
    assert len(calls) == 1


def test_force_vai_ao_container_de_novo():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.server_status(ssh, SERVIDOR, 5, force=True)
    assert len(calls) == 2


def test_prazo_zero_nao_aproveita_nada():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVIDOR, 0)
    ss.server_status(ssh, SERVIDOR, 0)
    assert len(calls) == 2


def test_invalidate_obriga_a_perguntar_de_novo():
    """Depois de um start/stop o estado guardado esta velho na hora."""
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.invalidate(1)
    ss.server_status(ssh, SERVIDOR, 5)
    assert len(calls) == 2


def test_erro_tambem_fica_em_cache():
    """Container fora do ar custa o timeout inteiro; repetir a cada tela nao se paga."""
    calls: list = []

    def explode(server, comando, timeout=None):
        calls.append(comando)
        raise RemoteError("sem rota")

    ss.server_status(explode, SERVIDOR, 5)
    state = ss.server_status(explode, SERVIDOR, 5)
    assert state["service"] == "inacessivel"
    assert len(calls) == 1
