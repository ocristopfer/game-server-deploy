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
def cache_limpo():
    ss._status_cache.clear()
    yield
    ss._status_cache.clear()


def saida_de(**campos) -> str:
    return "\n".join(f"{k}={v}" for k, v in campos.items())


def ssh_que_responde(texto: str, registro: list | None = None):
    def ssh_output(server, comando, timeout=None):
        if registro is not None:
            registro.append(comando)
        return texto
    return ssh_output


def test_le_os_quatro_campos_do_systemctl():
    texto = saida_de(ActiveState="active", SubState="running", NRestarts="2", Result="success")
    estado = ss.server_status(ssh_que_responde(texto), SERVIDOR, 5)
    assert estado["reachable"] is True
    assert estado["service"] == "active"
    assert estado["sub"] == "running"
    assert estado["restarts"] == 2
    assert estado["result"] == "success"
    assert estado["error"] == ""


def test_pergunta_pelos_campos_que_distinguem_parada_de_queda():
    """Sem Result e NRestarts nao da para separar 'eu parei' de 'quebrou em loop'."""
    registro: list = []
    ss.server_status(ssh_que_responde(saida_de(ActiveState="active"), registro), SERVIDOR, 5)
    comando = registro[0]
    assert "systemctl show palworld.service" in comando
    for campo in ("ActiveState", "SubState", "NRestarts", "Result"):
        assert campo in comando


def test_unidade_inexistente_vira_inactive():
    """`systemctl show` sai com 0 e ActiveState vazio para unidade que nao existe."""
    estado = ss.server_status(ssh_que_responde(saida_de(ActiveState="")), SERVIDOR, 5)
    assert estado["reachable"] is True
    assert estado["service"] == "inactive"


def test_systemd_antigo_sem_nrestarts_nao_quebra():
    """NRestarts so existe no systemd >= 235; sem ele o painel so nao avisa desse evento."""
    estado = ss.server_status(ssh_que_responde(saida_de(ActiveState="active")), SERVIDOR, 5)
    assert estado["restarts"] == 0


def test_nrestarts_que_nao_e_numero_vira_zero():
    texto = saida_de(ActiveState="active", NRestarts="[not set]")
    assert ss.server_status(ssh_que_responde(texto), SERVIDOR, 5)["restarts"] == 0


def test_container_inalcancavel_vira_estado_e_nao_excecao():
    """A lista de servidores nao pode cair porque um container esta fora do ar."""
    def explode(server, comando, timeout=None):
        raise RemoteError("tempo esgotado (20s) executando no host 10.0.0.1")

    estado = ss.server_status(explode, SERVIDOR, 5)
    assert estado["reachable"] is False
    assert estado["service"] == "inacessivel"
    assert "tempo esgotado" in estado["error"]


def test_segunda_pergunta_dentro_do_prazo_vem_do_cache():
    chamadas: list = []
    ssh = ssh_que_responde(saida_de(ActiveState="active"), chamadas)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.server_status(ssh, SERVIDOR, 5)
    assert len(chamadas) == 1


def test_force_vai_ao_container_de_novo():
    chamadas: list = []
    ssh = ssh_que_responde(saida_de(ActiveState="active"), chamadas)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.server_status(ssh, SERVIDOR, 5, force=True)
    assert len(chamadas) == 2


def test_prazo_zero_nao_aproveita_nada():
    chamadas: list = []
    ssh = ssh_que_responde(saida_de(ActiveState="active"), chamadas)
    ss.server_status(ssh, SERVIDOR, 0)
    ss.server_status(ssh, SERVIDOR, 0)
    assert len(chamadas) == 2


def test_invalidate_obriga_a_perguntar_de_novo():
    """Depois de um start/stop o estado guardado esta velho na hora."""
    chamadas: list = []
    ssh = ssh_que_responde(saida_de(ActiveState="active"), chamadas)
    ss.server_status(ssh, SERVIDOR, 5)
    ss.invalidate(1)
    ss.server_status(ssh, SERVIDOR, 5)
    assert len(chamadas) == 2


def test_erro_tambem_fica_em_cache():
    """Container fora do ar custa o timeout inteiro; repetir a cada tela nao se paga."""
    chamadas: list = []

    def explode(server, comando, timeout=None):
        chamadas.append(comando)
        raise RemoteError("sem rota")

    ss.server_status(explode, SERVIDOR, 5)
    estado = ss.server_status(explode, SERVIDOR, 5)
    assert estado["service"] == "inacessivel"
    assert len(chamadas) == 1
