"""Medidores do container (gamepanel.services.metrics_service).

A leitura dos numeros ja tem suite propria (test_metrics_probe.py). O que falta e o
que este modulo acrescenta: quando vale reaproveitar a leitura anterior — cada uma
custa ~1s de SSH, e a tela de detalhe pergunta a cada poucos segundos — e o que a tela
recebe quando o container nao responde.
"""
from __future__ import annotations

import pytest

from gamepanel.runtime.ssh import RemoteError
from gamepanel.services import metrics_service as ms

SERVIDOR = {"id": 1, "service": "palworld.service", "config_path": "/opt/game"}
SAIDA_MINIMA = "cores|2\nload|0.10 0.20 0.15\n"


@pytest.fixture(autouse=True)
def cache_limpo():
    ms._metrics_cache.clear()
    yield
    ms._metrics_cache.clear()


def ssh_que_responde(text: str = SAIDA_MINIMA, registro: list | None = None):
    def ssh_output(server, comando, timeout=None):
        if registro is not None:
            registro.append(comando)
        return text
    return ssh_output


def test_le_os_numeros_do_container():
    data = ms.server_metrics(ssh_que_responde(), SERVIDOR, "/opt/padrao", 5)
    assert data["cores"] == 2
    assert data["load"] == "0.10 0.20 0.15"
    assert data["error"] == ""


def test_mede_o_disco_da_pasta_do_cadastro():
    registro: list = []
    ms.server_metrics(ssh_que_responde(registro=registro), SERVIDOR, "/opt/padrao", 5)
    assert "/opt/game" in registro[0]


def test_sem_pasta_no_cadastro_usa_a_padrao():
    registro: list = []
    servidor = {**SERVIDOR, "config_path": ""}
    ms.server_metrics(ssh_que_responde(registro=registro), servidor, "/opt/padrao", 5)
    assert "/opt/padrao" in registro[0]


def test_container_fora_do_ar_vira_erro_e_nao_excecao():
    def explode(server, comando, timeout=None):
        raise RemoteError("tempo esgotado (30s)")

    data = ms.server_metrics(explode, SERVIDOR, "/opt/padrao", 5)
    assert "tempo esgotado" in data["error"]
    # Sem os medidores: a tela mostra o erro no lugar das barras, e nao barras zeradas.
    assert "cpu_pct" not in data


def test_segunda_leitura_dentro_do_prazo_vem_do_cache():
    chamadas: list = []
    ssh = ssh_que_responde(registro=chamadas)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    assert len(chamadas) == 1


def test_force_le_de_novo():
    chamadas: list = []
    ssh = ssh_que_responde(registro=chamadas)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5, force=True)
    assert len(chamadas) == 2


def test_invalidate_esquece_a_leitura():
    chamadas: list = []
    ssh = ssh_que_responde(registro=chamadas)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    ms.invalidate(1)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    assert len(chamadas) == 2


def test_cada_servidor_tem_o_seu_cache():
    chamadas: list = []
    ssh = ssh_que_responde(registro=chamadas)
    ms.server_metrics(ssh, SERVIDOR, "/opt/padrao", 5)
    ms.server_metrics(ssh, {**SERVIDOR, "id": 2}, "/opt/padrao", 5)
    assert len(chamadas) == 2
