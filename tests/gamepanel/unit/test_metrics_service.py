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

SERVER = {"id": 1, "service": "palworld.service", "config_path": "/opt/game"}
MINIMAL_OUTPUT = "cores|2\nload|0.10 0.20 0.15\n"


@pytest.fixture(autouse=True)
def clean_cache():
    ms._metrics_cache.clear()
    yield
    ms._metrics_cache.clear()


def ssh_that_answers(text: str = MINIMAL_OUTPUT, record: list | None = None):
    def ssh_output(server, command, timeout=None):
        if record is not None:
            record.append(command)
        return text
    return ssh_output


def test_le_os_numeros_do_container():
    data = ms.server_metrics(ssh_that_answers(), SERVER, "/opt/padrao", 5)
    assert data["cores"] == 2
    assert data["load"] == "0.10 0.20 0.15"
    assert data["error"] == ""


def test_mede_o_disco_da_pasta_do_cadastro():
    record: list = []
    ms.server_metrics(ssh_that_answers(record=record), SERVER, "/opt/padrao", 5)
    assert "/opt/game" in record[0]


def test_sem_pasta_no_cadastro_usa_a_padrao():
    record: list = []
    server = {**SERVER, "config_path": ""}
    ms.server_metrics(ssh_that_answers(record=record), server, "/opt/padrao", 5)
    assert "/opt/padrao" in record[0]


def test_container_fora_do_ar_vira_erro_e_nao_excecao():
    def explode(server, command, timeout=None):
        raise RemoteError("tempo esgotado (30s)")

    data = ms.server_metrics(explode, SERVER, "/opt/padrao", 5)
    assert "tempo esgotado" in data["error"]
    # Sem os medidores: a tela mostra o erro no lugar das barras, e nao barras zeradas.
    assert "cpu_pct" not in data


def test_segunda_leitura_dentro_do_prazo_vem_do_cache():
    calls: list = []
    ssh = ssh_that_answers(record=calls)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    assert len(calls) == 1


def test_force_le_de_novo():
    calls: list = []
    ssh = ssh_that_answers(record=calls)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5, force=True)
    assert len(calls) == 2


def test_invalidate_esquece_a_leitura():
    calls: list = []
    ssh = ssh_that_answers(record=calls)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    ms.invalidate(1)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    assert len(calls) == 2


def test_cada_servidor_tem_o_seu_cache():
    calls: list = []
    ssh = ssh_that_answers(record=calls)
    ms.server_metrics(ssh, SERVER, "/opt/padrao", 5)
    ms.server_metrics(ssh, {**SERVER, "id": 2}, "/opt/padrao", 5)
    assert len(calls) == 2
