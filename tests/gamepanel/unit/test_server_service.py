"""Validation of the server form (gamepanel.services.server_service).

There was no direct test before Phase 4: registration was only exercised through the routes,
which check the happy path and the odd field. This is where it is decided what goes into the
database - and almost every field here ends up inside a remote command or a call with
credentials, so what matters to test is the REJECTION.

The module's convention is not to raise: it returns the cleaned record and the list of errors,
and the screen shows all of them at once. There is a test just for that (`erros_se_acumulam`).
"""
from __future__ import annotations

import pytest

from gamepanel.runtime import files
from gamepanel.services import server_service as ss

LIMITS = ss.FormLimits(
    config_files_max=8, backup_paths_max=8, http_url_max=300, http_body_max=2000,
    http_path_max=120, re_max_len=300, player_sources=("a2s", "http", "log", "none"),
)

MINIMAL = {"name": "Palworld", "host": "10.0.0.1", "service": "palworld.service"}


def clean_path(raw: str) -> str:
    """The real `clean_path`, with no folder restriction."""
    return files.clean_path(raw, ("/",))


def validate(**fields) -> tuple[dict, list[str]]:
    return ss.form_server({**MINIMAL, **fields}, clean_path, LIMITS)


# ------------------------------------------------------------- happy path

def test_cadastro_minimo_passa_e_assume_os_padroes():
    data, errors = validate()
    assert errors == []
    assert data["name"] == "Palworld"
    assert data["ssh_user"] == "gamepanel", "sem usuario informado, o usuario sem root (servidor novo)"
    assert data["ssh_port"] == 22
    assert data["query_port"] == 0, "0 e o desligado da consulta"
    assert data["player_source"] == ""


def test_espacos_nas_pontas_somem():
    data, errors = validate(name="  Palworld  ", host=" 10.0.0.1 ")
    assert errors == []
    assert data["name"] == "Palworld"
    assert data["host"] == "10.0.0.1"


# ------------------------------------------------------ identification

def test_nome_vazio_e_recusado():
    _data, errors = validate(name="")
    assert any("nome" in e.lower() for e in errors)


@pytest.mark.parametrize("host", ["", "com espaco", "10.0.0.1/rota", "a" * 300])
def test_host_invalido_e_recusado(host):
    _data, errors = validate(host=host)
    assert any("Host inválido" in e for e in errors)


@pytest.mark.parametrize("user", ["Root", "1nome", "com espaco", "x" * 40])
def test_usuario_ssh_invalido_e_recusado(user):
    _data, errors = validate(ssh_user=user)
    assert any("Usuário SSH" in e for e in errors)


def test_instance_service_sem_sufixo_ganha_o_sufixo():
    """Nobody should be bothered for forgetting '.service'."""
    data, errors = validate(service="dragonwilds")
    assert errors == []
    assert data["service"] == "dragonwilds.service"


@pytest.mark.parametrize("service", ["", "com espaco.service", "/etc/passwd"])
def test_instance_service_invalido_e_recusado(service):
    _data, errors = validate(service=service)
    assert any("Serviço inválido" in e for e in errors)


# ------------------------------------------------------------- ports

@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "22.5"])
def test_porta_ssh_fora_da_faixa_e_recusada(port):
    _data, errors = validate(ssh_port=port)
    assert any("Porta SSH" in e for e in errors)


def test_porta_de_consulta_aceita_zero_para_desligar():
    data, errors = validate(query_port="0")
    assert errors == []
    assert data["query_port"] == 0


def test_porta_de_consulta_fora_da_faixa_e_recusada():
    _data, errors = validate(query_port="99999")
    assert any("Porta de consulta" in e for e in errors)


# --------------------------------------------------------- paths

def test_arquivos_de_config_aceitam_virgula_e_quebra_de_linha():
    data, errors = validate(config_files="/opt/a.ini,/opt/b.ini\n/opt/c.ini")
    assert errors == []
    assert data["config_files"].splitlines() == ["/opt/a.ini", "/opt/b.ini", "/opt/c.ini"]


def test_arquivo_de_config_repetido_entra_uma_vez_so():
    data, errors = validate(config_files="/opt/a.ini\n/opt/./a.ini")
    assert errors == []
    assert data["config_files"] == "/opt/a.ini"


def test_arquivo_de_config_relativo_e_recusado():
    _data, errors = validate(config_files="config.ini")
    assert any("Arquivo de configuração inválido" in e for e in errors)


def test_passar_do_limite_de_arquivos_corta_e_avisa():
    too_many = "\n".join(f"/opt/{i}.ini" for i in range(12))
    data, errors = validate(config_files=too_many)
    assert any("No máximo 8 arquivos" in e for e in errors)
    assert len(data["config_files"].splitlines()) == 8


def test_backup_da_raiz_e_recusado():
    """Storing '/' would mean trying to tar the whole container."""
    _data, errors = validate(backup_paths="/")
    assert any("Backup da raiz" in e for e in errors)


def test_passar_do_limite_de_caminhos_de_backup_corta_e_avisa():
    too_many = "\n".join(f"/opt/save{i}" for i in range(12))
    data, errors = validate(backup_paths=too_many)
    assert any("No máximo 8 caminhos" in e for e in errors)
    assert len(data["backup_paths"].splitlines()) == 8


def test_pasta_de_config_relativa_e_recusada():
    _data, errors = validate(config_path="opt/game")
    assert any("Pasta de configuração inválida" in e for e in errors)


def test_caminho_de_log_com_espaco_e_recusado():
    """The path goes into a remote command unquoted (the '*' needs to expand)."""
    _data, errors = validate(log_path="/var/log/meu jogo.log")
    assert any("caminho de log" in e.lower() for e in errors)


def test_caminho_de_log_com_glob_passa():
    data, errors = validate(log_path="/opt/game/profiles/*.ADM")
    assert errors == []
    assert data["log_path"] == "/opt/game/profiles/*.ADM"


# -------------------------------------------------------------- regex

def test_regex_que_nao_compila_e_recusado():
    _data, errors = validate(join_re="(sem fechar")
    assert errors
    assert not _data["join_re"], "regex torto nao pode ir para o banco"


def test_regex_valido_passa_inteiro():
    data, errors = validate(join_re=r"Join succeeded: (?P<name>.+)")
    assert errors == []
    assert data["join_re"] == r"Join succeeded: (?P<name>.+)"


# --------------------------------------------------------------- HTTP

def test_url_da_api_invalida_e_recusada():
    _data, errors = validate(http_url="127.0.0.1:8212/v1/api/players")
    assert any("URL da API" in e for e in errors)


def test_corpo_que_nao_e_json_e_recusado():
    _data, errors = validate(http_body="{isso nao e json}")
    assert any("Corpo da requisição" in e for e in errors)


def test_caminho_json_com_caractere_estranho_e_recusado():
    _data, errors = validate(http_list_path="data/players")
    assert any("Caminho da lista" in e for e in errors)


def test_login_sem_caminho_do_token_e_recusado():
    """The three login fields go together; half filled in is almost always a mistake."""
    _data, errors = validate(http_login_url="http://127.0.0.1:8212/login")
    assert any("caminho do token" in e for e in errors)


def test_login_completo_passa():
    data, errors = validate(
        http_login_url="http://127.0.0.1:8212/login",
        http_login_body='{"user":"admin"}',
        http_token_path="data.token",
    )
    assert errors == []
    assert data["http_token_path"] == "data.token"


# ----------------------------------------------------- count source

def test_fonte_de_contagem_desconhecida_e_recusada():
    data, errors = validate(player_source="rcon")
    assert any("Forma de contar" in e for e in errors)
    assert data["player_source"] == ""


@pytest.mark.parametrize("source", ["a2s", "http", "log", "none"])
def test_fontes_conhecidas_passam(source):
    data, errors = validate(player_source=source)
    assert errors == []
    assert data["player_source"] == source


# ------------------------------------------------------------- together

def test_erros_se_acumulam():
    """The screen shows everything at once: fixing one field per submit would be cruel."""
    _data, errors = validate(name="", host="nao vale", ssh_port="0", service="")
    assert len(errors) >= 4
