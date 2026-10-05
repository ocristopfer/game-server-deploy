"""Game service state (gamepanel.services.status_service).

READING `systemctl show` had no test before Phase 4: the alert tests build the state
dictionary by hand and swap the whole `server_status` for a fake, which exercises the
alert rule and never what comes from the container. And that is where things live that
only show up on a real machine - old systemd without `NRestarts`, a unit that does not
exist, an unreachable container.
"""
from __future__ import annotations

import pytest

from gamepanel.runtime.ssh import RemoteError
from gamepanel.services import status_service as ss

SERVER = {"id": 1, "service": "palworld.service"}


@pytest.fixture(autouse=True)
def clean_cache():
    ss._status_cache.clear()
    yield
    ss._status_cache.clear()


def output_of(**fields) -> str:
    return "\n".join(f"{k}={v}" for k, v in fields.items())


def ssh_that_answers(text: str, record: list | None = None):
    def ssh_output(server, command, timeout=None):
        if record is not None:
            record.append(command)
        return text
    return ssh_output


def test_le_os_quatro_campos_do_systemctl():
    text = output_of(ActiveState="active", SubState="running", NRestarts="2", Result="success")
    state = ss.server_status(ssh_that_answers(text), SERVER, 5)
    assert state["reachable"] is True
    assert state["service"] == "active"
    assert state["sub"] == "running"
    assert state["restarts"] == 2
    assert state["result"] == "success"
    assert state["error"] == ""


def test_pergunta_pelos_campos_que_distinguem_parada_de_queda():
    """Without Result and NRestarts there is no telling 'I stopped it' from 'crashing in a loop'."""
    record: list = []
    ss.server_status(ssh_that_answers(output_of(ActiveState="active"), record), SERVER, 5)
    command = record[0]
    assert "systemctl show palworld.service" in command
    for field in ("ActiveState", "SubState", "NRestarts", "Result"):
        assert field in command


def test_unidade_inexistente_vira_inactive():
    """`systemctl show` exits 0 with an empty ActiveState for a unit that does not exist."""
    state = ss.server_status(ssh_that_answers(output_of(ActiveState="")), SERVER, 5)
    assert state["reachable"] is True
    assert state["service"] == "inactive"


def test_systemd_antigo_sem_nrestarts_nao_quebra():
    """NRestarts only exists in systemd >= 235; without it the panel just does not report that event."""
    state = ss.server_status(ssh_that_answers(output_of(ActiveState="active")), SERVER, 5)
    assert state["restarts"] == 0


def test_nrestarts_que_nao_e_numero_vira_zero():
    text = output_of(ActiveState="active", NRestarts="[not set]")
    assert ss.server_status(ssh_that_answers(text), SERVER, 5)["restarts"] == 0


def test_container_inalcancavel_vira_estado_e_nao_excecao():
    """The server list must not go down because one container is offline."""
    def explode(server, command, timeout=None):
        raise RemoteError("tempo esgotado (20s) executando no host 10.0.0.1")

    state = ss.server_status(explode, SERVER, 5)
    assert state["reachable"] is False
    assert state["service"] == "inacessivel"
    assert "tempo esgotado" in state["error"]


def test_segunda_pergunta_dentro_do_prazo_vem_do_cache():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVER, 5)
    ss.server_status(ssh, SERVER, 5)
    assert len(calls) == 1


def test_force_vai_ao_container_de_novo():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVER, 5)
    ss.server_status(ssh, SERVER, 5, force=True)
    assert len(calls) == 2


def test_prazo_zero_nao_aproveita_nada():
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVER, 0)
    ss.server_status(ssh, SERVER, 0)
    assert len(calls) == 2


def test_invalidate_obriga_a_perguntar_de_novo():
    """After a start/stop the stored state is immediately stale."""
    calls: list = []
    ssh = ssh_that_answers(output_of(ActiveState="active"), calls)
    ss.server_status(ssh, SERVER, 5)
    ss.invalidate(1)
    ss.server_status(ssh, SERVER, 5)
    assert len(calls) == 2


def test_erro_tambem_fica_em_cache():
    """An offline container costs the whole timeout; repeating that on every screen does not pay off."""
    calls: list = []

    def explode(server, command, timeout=None):
        calls.append(command)
        raise RemoteError("sem rota")

    ss.server_status(explode, SERVER, 5)
    state = ss.server_status(explode, SERVER, 5)
    assert state["service"] == "inacessivel"
    assert len(calls) == 1
