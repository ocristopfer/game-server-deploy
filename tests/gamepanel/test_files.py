"""Editor de arquivos e upload/download (gamepanel.runtime.files): scripts SSH + parsing.

Nao existia suite dedicada antes da Fase 4 (mesmo achado dos modulos anteriores: so
exercitado indiretamente, pelo sweep de rotas em test_users.py, que nunca chega a
chamar `list_dir`/`read_file`/etc. de verdade). `ssh_run`/`ssh_argv` entram por
injecao, como em todo modulo de runtime/: a maioria dos testes aqui usa uma saida
FABRICADA (sem SSH nenhum); os dois que streamam de um PROCESSO de verdade
(`ssh_stream_in`/`stream_remote_file`) usam `cat`/`sh` locais no lugar do ssh - por
isso so rodam em POSIX, mesmo motivo do test_terminal.py.
"""
from __future__ import annotations

import base64
import os
import subprocess
from io import BytesIO

import pytest

from gamepanel.runtime import files as filesmod
from gamepanel.runtime.ssh import RemoteError

SERVER = {"id": 1, "host": "10.0.0.1", "ssh_port": 22, "ssh_user": "root"}


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _ssh_run_of(stdout: str = "", returncode: int = 0, stderr: str = "", capturar: list | None = None):
    def ssh_run(server, remote_cmd, timeout=None, stdin_data=None, multiplex=True):
        if capturar is not None:
            capturar.append({"remote_cmd": remote_cmd, "stdin_data": stdin_data})
        return _proc(returncode, stdout, stderr)
    return ssh_run


# ------------------------------------------------------------ caminho

def test_clean_path_resolve_pontos():
    assert filesmod.clean_path("/a/b/../c", ()) == "/a/c"


def test_clean_path_exige_absoluto():
    with pytest.raises(ValueError, match="absoluto"):
        filesmod.clean_path("relativo", ())


def test_clean_path_rejeita_caractere_de_controle():
    with pytest.raises(ValueError, match="invalido"):
        filesmod.clean_path("/a\nb", ())


def test_clean_path_rejeita_caminho_longo_demais():
    with pytest.raises(ValueError, match="longo demais"):
        filesmod.clean_path("/" + "a" * 500, ())


def test_clean_path_barra_configurada_libera_tudo():
    assert filesmod.clean_path("/qualquer/coisa", ("/",)) == "/qualquer/coisa"


def test_clean_path_fora_das_raizes_e_recusado():
    with pytest.raises(ValueError, match="fora das pastas"):
        filesmod.clean_path("/outra/pasta", ("/opt/game",))


def test_clean_path_prefixo_parecido_nao_engana_a_raiz():
    # /opt/gamex nao pode passar so porque comeca com o texto "/opt/game".
    with pytest.raises(ValueError, match="fora das pastas"):
        filesmod.clean_path("/opt/gamex/save", ("/opt/game",))


def test_parent_of():
    assert filesmod.parent_of("/a/b/c") == "/a/b"
    assert filesmod.parent_of("/a") == "/"


# ------------------------------------------------------------- listar

def test_list_dir_parseia_entradas_e_ordena_pastas_primeiro():
    output = (
        "f\t?\t120\t2024-01-01 10:00\t644\tzeta.txt\n"
        "d\t?\t0\t2024-01-01 09:00\t755\talfa\n"
    )
    entries, more = filesmod.list_dir(_ssh_run_of(output), SERVER, "/opt/game", 800)
    assert [e["name"] for e in entries] == ["alfa", "zeta.txt"]
    assert entries[0]["dir"] is True
    assert entries[1]["size"] == 120
    assert more is False


def test_list_dir_link_usa_o_tipo_do_alvo():
    output = "l\td\t0\t2024-01-01 09:00\t777\tatalho\n"
    entries, _mais = filesmod.list_dir(_ssh_run_of(output), SERVER, "/opt/game", 800)
    assert entries[0]["link"] is True
    assert entries[0]["dir"] is True


def test_list_dir_linha_malformada_e_ignorada():
    output = "so\tum\tcampo\n" + "f\t?\t10\t2024-01-01 09:00\t644\tok.txt\n"
    entries, _mais = filesmod.list_dir(_ssh_run_of(output), SERVER, "/opt/game", 800)
    assert len(entries) == 1


def test_list_dir_no_limite_avisa_que_ha_mais():
    output = "f\t?\t1\t2024-01-01 09:00\t644\tum.txt\n"
    _entries, more = filesmod.list_dir(_ssh_run_of(output), SERVER, "/opt/game", 1)
    assert more is True


def test_list_dir_retorno_diferente_de_zero_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="pasta nao encontrada: /x")
    with pytest.raises(RemoteError, match="pasta nao encontrada"):
        filesmod.list_dir(ssh_run, SERVER, "/x", 10)


# -------------------------------------------------- busca de config

def test_find_config_files_parseia_linhas():
    output = "120\t2024-01-01 10:00\t/opt/game/server.cfg\n"
    results = filesmod.find_config_files(_ssh_run_of(output), SERVER, "/opt/game", ("*.cfg",))
    assert results == [{"size": 120, "mtime": "2024-01-01 10:00", "path": "/opt/game/server.cfg"}]


def test_find_config_files_linha_malformada_e_ignorada():
    # Menos de duas tabs - falta pelo menos o caminho.
    output = "so isso\n"
    results = filesmod.find_config_files(_ssh_run_of(output), SERVER, "/opt/game", ("*.cfg",))
    assert results == []


def test_find_config_files_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="pasta nao encontrada")
    with pytest.raises(RemoteError):
        filesmod.find_config_files(ssh_run, SERVER, "/x", ("*.cfg",))


# ----------------------------------------------------------- metadados

def test_stat_file_le_metadados():
    output = "META|4096|2024-01-01 10:00:00.123456|644|steam|steam\n"
    meta = filesmod.stat_file(_ssh_run_of(output), SERVER, "/opt/game/x.cfg")
    assert meta["size"] == 4096
    assert meta["mtime"] == "2024-01-01 10:00:00"
    assert meta["mode"] == "644"
    assert meta["owner"] == "steam:steam"
    assert meta["name"] == "x.cfg"


def test_stat_file_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=5, stderr="sem permissao de leitura")
    with pytest.raises(RemoteError):
        filesmod.stat_file(ssh_run, SERVER, "/x")


def test_stat_file_meta_mal_formada_vira_remote_error():
    with pytest.raises(RemoteError, match="inesperada"):
        filesmod.stat_file(_ssh_run_of("nao-e-meta\n"), SERVER, "/x")


# --------------------------------------------------------- ler arquivo

def test_read_file_texto_simples():
    payload = base64.b64encode(b"ola mundo").decode()
    output = f"META|9|2024-01-01 10:00:00|644|steam|steam|full\n{payload}"
    doc = filesmod.read_file(_ssh_run_of(output), SERVER, "/opt/game/x.txt", 1000, 100)
    assert doc["text"] == "ola mundo"
    assert doc["binary"] is False
    assert doc["truncated"] is False
    assert doc["editable"] is True
    assert doc["crlf"] is False


def test_read_file_binario_nao_vira_texto():
    payload = base64.b64encode(b"\x00\x01\x02").decode()
    output = f"META|3|2024-01-01 10:00:00|644|steam|steam|full\n{payload}"
    doc = filesmod.read_file(_ssh_run_of(output), SERVER, "/x.bin", 1000, 100)
    assert doc["binary"] is True
    assert doc["text"] == ""
    assert doc["editable"] is False


def test_read_file_truncado_nao_e_editavel():
    payload = base64.b64encode(b"fim").decode()
    output = f"META|999999|2024-01-01 10:00:00|644|steam|steam|tail\n{payload}"
    doc = filesmod.read_file(_ssh_run_of(output), SERVER, "/grande.log", 10, 100)
    assert doc["truncated"] is True
    assert doc["editable"] is False


def test_read_file_crlf_detectado():
    payload = base64.b64encode(b"linha1\r\nlinha2").decode()
    output = f"META|14|2024-01-01 10:00:00|644|steam|steam|full\n{payload}"
    doc = filesmod.read_file(_ssh_run_of(output), SERVER, "/x.ini", 1000, 100)
    assert doc["crlf"] is True


def test_read_file_base64_corrompido_vira_remote_error():
    output = "META|3|2024-01-01 10:00:00|644|steam|steam|full\nnao-e-base64!!"
    with pytest.raises(RemoteError, match="corrompido"):
        filesmod.read_file(_ssh_run_of(output), SERVER, "/x", 1000, 100)


def test_read_file_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="arquivo nao encontrado")
    with pytest.raises(RemoteError):
        filesmod.read_file(ssh_run, SERVER, "/x", 1000, 100)


# -------------------------------------------------- gravar e apagar

def test_write_file_manda_base64_por_stdin_e_devolve_confirmacao():
    captured: list = []
    ssh_run = _ssh_run_of("gravado: 9 bytes", capturar=captured)
    result = filesmod.write_file(ssh_run, SERVER, "/opt/game/x.cfg", b"ola mundo")
    assert result == "gravado: 9 bytes"
    assert base64.b64decode(captured[0]["stdin_data"]) == b"ola mundo"


def test_write_file_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=4, stderr="nao e um arquivo comum")
    with pytest.raises(RemoteError):
        filesmod.write_file(ssh_run, SERVER, "/x", b"a")


def test_delete_file_devolve_confirmacao():
    result = filesmod.delete_file(_ssh_run_of("apagado: /x (10 bytes)"), SERVER, "/x")
    assert "apagado" in result


def test_delete_file_erro_vira_remote_error():
    ssh_run = _ssh_run_of(returncode=3, stderr="arquivo nao encontrado")
    with pytest.raises(RemoteError):
        filesmod.delete_file(ssh_run, SERVER, "/x")


# ------------------------------------------------------- streaming

posix_apenas = pytest.mark.skipif(
    os.name != "posix", reason="exercita um processo local (cat/sh); so roda no container")


def _empty_argv():
    def ssh_argv(server, connect_timeout=10, **_ignora):
        return []
    return ssh_argv


def _argv_sh_c(script: str):
    def ssh_argv(server, **_ignora):
        return ["sh", "-c", script]
    return ssh_argv


@posix_apenas
def test_ssh_stream_in_envia_a_entrada_para_o_processo():
    source_dir = BytesIO(b"conteudo do arquivo")
    output = filesmod.ssh_stream_in(_empty_argv(), SERVER, "cat", source_dir, timeout=5, chunk_size=4)
    assert output == "conteudo do arquivo"


@posix_apenas
def test_ssh_stream_in_processo_que_falha_vira_remote_error():
    source_dir = BytesIO(b"x" * 100)
    with pytest.raises(RemoteError):
        filesmod.ssh_stream_in(_empty_argv(), SERVER, "false", source_dir, timeout=5, chunk_size=4)


@posix_apenas
def test_stream_remote_file_le_a_saida_em_pedacos():
    generator = filesmod.stream_remote_file(_argv_sh_c("printf abcdef"), SERVER, "/qualquer", chunk_size=2)
    chunks = list(generator)
    assert b"".join(chunks) == b"abcdef"


@posix_apenas
def test_stream_remote_file_cancelado_no_meio_nao_trava():
    # Simula o navegador desistindo no meio do download: o generator so precisa
    # fechar sem travar, sem deixar o processo remoto orfao.
    generator = filesmod.stream_remote_file(
        _argv_sh_c("printf abcdefghij; sleep 5"), SERVER, "/qualquer", chunk_size=2,
    )
    first = next(generator)
    assert first == b"ab"
    generator.close()
