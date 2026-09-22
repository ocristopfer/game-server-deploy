"""Validacao do formulario de servidor (gamepanel.services.server_service).

Nao havia teste direto antes da Fase 4: o cadastro so era exercitado pelas rotas, que
conferem o caso feliz e um ou outro campo. E aqui que se decide o que entra no banco —
e quase todo campo daqui acaba dentro de um comando remoto ou de uma chamada com
credencial, entao o que interessa testar e a RECUSA.

A convencao do modulo e nao levantar: devolve o cadastro limpo e a lista de erros, e a
tela mostra todos de uma vez. Ha um teste so para isso (`erros_se_acumulam`).
"""
from __future__ import annotations

import pytest

from gamepanel.runtime import files
from gamepanel.services import server_service as ss

LIMITES = ss.FormLimits(
    config_files_max=8, backup_paths_max=8, http_url_max=300, http_body_max=2000,
    http_path_max=120, re_max_len=300, player_sources=("a2s", "http", "log", "none"),
)

MINIMO = {"name": "Palworld", "host": "10.0.0.1", "service": "palworld.service"}


def clean_path(raw: str) -> str:
    """O `clean_path` de verdade, sem restricao de pasta."""
    return files.clean_path(raw, ("/",))


def valida(**campos) -> tuple[dict, list[str]]:
    return ss.form_server({**MINIMO, **campos}, clean_path, LIMITES)


# ------------------------------------------------------------- caso feliz

def test_cadastro_minimo_passa_e_assume_os_padroes():
    data, errors = valida()
    assert errors == []
    assert data["name"] == "Palworld"
    assert data["ssh_user"] == "root", "sem usuario informado, root"
    assert data["ssh_port"] == 22
    assert data["query_port"] == 0, "0 e o desligado da consulta"
    assert data["player_source"] == ""


def test_espacos_nas_pontas_somem():
    data, errors = valida(name="  Palworld  ", host=" 10.0.0.1 ")
    assert errors == []
    assert data["name"] == "Palworld"
    assert data["host"] == "10.0.0.1"


# ------------------------------------------------------ identificacao

def test_nome_vazio_e_recusado():
    _dados, errors = valida(name="")
    assert any("nome" in e.lower() for e in errors)


@pytest.mark.parametrize("host", ["", "com espaco", "10.0.0.1/rota", "a" * 300])
def test_host_invalido_e_recusado(host):
    _dados, errors = valida(host=host)
    assert any("Host invalido" in e for e in errors)


@pytest.mark.parametrize("user", ["Root", "1nome", "com espaco", "x" * 40])
def test_usuario_ssh_invalido_e_recusado(user):
    _dados, errors = valida(ssh_user=user)
    assert any("Usuario SSH" in e for e in errors)


def test_servico_sem_sufixo_ganha_o_sufixo():
    """Ninguem deveria ser incomodado por esquecer '.service'."""
    data, errors = valida(service="dragonwilds")
    assert errors == []
    assert data["service"] == "dragonwilds.service"


@pytest.mark.parametrize("service", ["", "com espaco.service", "/etc/passwd"])
def test_servico_invalido_e_recusado(service):
    _dados, errors = valida(service=service)
    assert any("Servico invalido" in e for e in errors)


# ------------------------------------------------------------- portas

@pytest.mark.parametrize("porta", ["0", "65536", "-1", "abc", "22.5"])
def test_porta_ssh_fora_da_faixa_e_recusada(porta):
    _dados, errors = valida(ssh_port=porta)
    assert any("Porta SSH" in e for e in errors)


def test_porta_de_consulta_aceita_zero_para_desligar():
    data, errors = valida(query_port="0")
    assert errors == []
    assert data["query_port"] == 0


def test_porta_de_consulta_fora_da_faixa_e_recusada():
    _dados, errors = valida(query_port="99999")
    assert any("Porta de consulta" in e for e in errors)


# --------------------------------------------------------- caminhos

def test_arquivos_de_config_aceitam_virgula_e_quebra_de_linha():
    data, errors = valida(config_files="/opt/a.ini,/opt/b.ini\n/opt/c.ini")
    assert errors == []
    assert data["config_files"].splitlines() == ["/opt/a.ini", "/opt/b.ini", "/opt/c.ini"]


def test_arquivo_de_config_repetido_entra_uma_vez_so():
    data, errors = valida(config_files="/opt/a.ini\n/opt/./a.ini")
    assert errors == []
    assert data["config_files"] == "/opt/a.ini"


def test_arquivo_de_config_relativo_e_recusado():
    _dados, errors = valida(config_files="config.ini")
    assert any("Arquivo de configuracao invalido" in e for e in errors)


def test_passar_do_limite_de_arquivos_corta_e_avisa():
    demais = "\n".join(f"/opt/{i}.ini" for i in range(12))
    data, errors = valida(config_files=demais)
    assert any("No maximo 8 arquivos" in e for e in errors)
    assert len(data["config_files"].splitlines()) == 8


def test_backup_da_raiz_e_recusado():
    """Guardar '/' seria tentar um tar do container inteiro."""
    _dados, errors = valida(backup_paths="/")
    assert any("Backup da raiz" in e for e in errors)


def test_passar_do_limite_de_caminhos_de_backup_corta_e_avisa():
    demais = "\n".join(f"/opt/save{i}" for i in range(12))
    data, errors = valida(backup_paths=demais)
    assert any("No maximo 8 caminhos" in e for e in errors)
    assert len(data["backup_paths"].splitlines()) == 8


def test_pasta_de_config_relativa_e_recusada():
    _dados, errors = valida(config_path="opt/game")
    assert any("Pasta de configuracao invalida" in e for e in errors)


def test_caminho_de_log_com_espaco_e_recusado():
    """O caminho entra num comando remoto sem aspas (o '*' precisa expandir)."""
    _dados, errors = valida(log_path="/var/log/meu jogo.log")
    assert any("caminho de log" in e.lower() for e in errors)


def test_caminho_de_log_com_glob_passa():
    data, errors = valida(log_path="/opt/game/profiles/*.ADM")
    assert errors == []
    assert data["log_path"] == "/opt/game/profiles/*.ADM"


# -------------------------------------------------------------- regex

def test_regex_que_nao_compila_e_recusado():
    _dados, errors = valida(join_re="(sem fechar")
    assert errors
    assert not _dados["join_re"], "regex torto nao pode ir para o banco"


def test_regex_valido_passa_inteiro():
    data, errors = valida(join_re=r"Join succeeded: (?P<name>.+)")
    assert errors == []
    assert data["join_re"] == r"Join succeeded: (?P<name>.+)"


# --------------------------------------------------------------- HTTP

def test_url_da_api_invalida_e_recusada():
    _dados, errors = valida(http_url="127.0.0.1:8212/v1/api/players")
    assert any("URL da API" in e for e in errors)


def test_corpo_que_nao_e_json_e_recusado():
    _dados, errors = valida(http_body="{isso nao e json}")
    assert any("Corpo da requisicao" in e for e in errors)


def test_caminho_json_com_caractere_estranho_e_recusado():
    _dados, errors = valida(http_list_path="data/players")
    assert any("Caminho da lista" in e for e in errors)


def test_login_sem_caminho_do_token_e_recusado():
    """Os tres campos do login andam juntos; meio preenchido quase sempre e engano."""
    _dados, errors = valida(http_login_url="http://127.0.0.1:8212/login")
    assert any("caminho do token" in e for e in errors)


def test_login_completo_passa():
    data, errors = valida(
        http_login_url="http://127.0.0.1:8212/login",
        http_login_body='{"user":"admin"}',
        http_token_path="data.token",
    )
    assert errors == []
    assert data["http_token_path"] == "data.token"


# ----------------------------------------------------- fonte da contagem

def test_fonte_de_contagem_desconhecida_e_recusada():
    data, errors = valida(player_source="rcon")
    assert any("Forma de contar" in e for e in errors)
    assert data["player_source"] == ""


@pytest.mark.parametrize("fonte", ["a2s", "http", "log", "none"])
def test_fontes_conhecidas_passam(fonte):
    data, errors = valida(player_source=fonte)
    assert errors == []
    assert data["player_source"] == fonte


# ------------------------------------------------------------- juntos

def test_erros_se_acumulam():
    """A tela mostra tudo de uma vez: corrigir um campo por envio seria cruel."""
    _dados, errors = valida(name="", host="nao vale", ssh_port="0", service="")
    assert len(errors) >= 4
