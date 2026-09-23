"""Backup do container de jogo (gamepanel.runtime.backups): comando, listagem, apagar.

Nao existia suite dedicada antes da Fase 4 (mesmo achado dos modulos de runtime/
anteriores: so exercitado pelo sweep de rotas e pelos testes de agendamento, que
trocam o modulo inteiro por um fake em vez de chegar nestas funcoes). `ssh_run` entra
por injecao, como no resto de runtime/: os testes aqui usam uma saida fabricada, sem
SSH nenhum.
"""
from __future__ import annotations

import subprocess

import pytest

from gamepanel.runtime import backups as backupsmod
from gamepanel.runtime.ssh import RemoteError

SERVIDOR_SEM_CADASTRO = {
    "id": 1, "backup_paths": "", "config_path": "/opt/game/config", "service": "jogo1.service",
}
SERVIDOR_COM_CADASTRO = {
    "id": 1, "backup_paths": "/opt/game/save\n/opt/game/config\n", "config_path": "", "service": "jogo1.service",
}


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _ssh_run_of(stdout: str = "", returncode: int = 0, stderr: str = ""):
    def ssh_run(server, remote_cmd, timeout=None, stdin_data=None, multiplex=True):
        return _proc(returncode, stdout, stderr)
    return ssh_run


# --------------------------------------------------------- caminhos e prefixo

def test_backup_paths_sem_cadastro_usa_a_pasta_de_configuracao():
    assert backupsmod.backup_paths(SERVIDOR_SEM_CADASTRO, 8) == ["/opt/game/config"]


def test_backup_paths_sem_nada_cadastrado_e_vazio():
    server = {"backup_paths": "", "config_path": ""}
    assert backupsmod.backup_paths(server, 8) == []


def test_backup_paths_cadastrado_ganha_do_padrao():
    assert backupsmod.backup_paths(SERVIDOR_COM_CADASTRO, 8) == ["/opt/game/save", "/opt/game/config"]


def test_backup_paths_respeita_o_limite():
    server = {"backup_paths": "\n".join(f"/p{i}" for i in range(20)), "config_path": ""}
    assert backupsmod.backup_paths(server, 3) == ["/p0", "/p1", "/p2"]


def test_backup_prefix_sai_do_nome_do_servico():
    assert backupsmod.backup_prefix({"service": "palworld-1.service"}) == "palworld-1"


def test_backup_prefix_saneia_caracteres_fora_do_padrao():
    assert backupsmod.backup_prefix({"service": "meu jogo!.service"}) == "meu-jogo"


def test_backup_prefix_sem_servico_cai_no_padrao():
    assert backupsmod.backup_prefix({"service": ""}) == "jogo"


# ---------------------------------------------------------- nome do backup

def test_validate_backup_name_aceita_nome_valido():
    assert backupsmod.validate_backup_name("jogo1-20240101-1200.tar.gz") == "jogo1-20240101-1200.tar.gz"


def test_validate_backup_name_rejeita_sem_extensao():
    with pytest.raises(ValueError, match="invalido"):
        backupsmod.validate_backup_name("jogo1-20240101-1200")


def test_validate_backup_name_rejeita_barra():
    with pytest.raises(ValueError, match="invalido"):
        backupsmod.validate_backup_name("../outro/arquivo.tar.gz")


def test_validate_backup_name_rejeita_vazio():
    with pytest.raises(ValueError, match="invalido"):
        backupsmod.validate_backup_name("")


# ------------------------------------------------------------ comando

def test_comando_de_backup_inclui_prefixo_limite_e_caminhos():
    cmd = backupsmod.backup_command(SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 5, ["/opt/game/save"])
    assert "jogo1" in cmd
    assert "/var/backups/gamepanel" in cmd
    assert "/opt/game/save" in cmd


def test_comando_de_backup_leva_o_sufixo_quando_passado():
    cmd = backupsmod.backup_command(
        SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 5, ["/opt/game/save"], "-antes-de-restaurar",
    )
    assert "antes-de-restaurar" in cmd


# ------------------------------------------------------------- listar

def test_list_backups_parseia_linhas():
    output = "jogo1-20240101-1200.tar.gz\t1024\t2024-01-01 12:00\n"
    copies = backupsmod.list_backups(_ssh_run_of(output), SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 100)
    assert copies == [{
        "name": "jogo1-20240101-1200.tar.gz", "size": 1024, "mtime": "2024-01-01 12:00", "seguranca": False,
    }]


def test_list_backups_marca_a_copia_de_seguranca():
    output = "jogo1-20240101-1200-antes-de-restaurar.tar.gz\t512\t2024-01-01 12:00\n"
    copies = backupsmod.list_backups(_ssh_run_of(output), SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 100)
    assert copies[0]["seguranca"] is True


def test_list_backups_linha_malformada_e_ignorada():
    output = "so um campo sem tab\n"
    copies = backupsmod.list_backups(_ssh_run_of(output), SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 100)
    assert copies == []


def test_list_backups_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="falha ao listar")
    with pytest.raises(RemoteError):
        backupsmod.list_backups(ssh_run, SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", 100)


# -------------------------------------------------------------- apagar

def test_delete_backup_devolve_confirmacao():
    output = backupsmod.delete_backup(
        _ssh_run_of("backup apagado: jogo1-x.tar.gz (10 bytes)"),
        SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", "jogo1-x.tar.gz",
    )
    assert "apagado" in output


def test_delete_backup_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="backup nao encontrado")
    with pytest.raises(RemoteError):
        backupsmod.delete_backup(ssh_run, SERVIDOR_COM_CADASTRO, "/var/backups/gamepanel", "jogo1-x.tar.gz")
