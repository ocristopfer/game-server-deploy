"""Backup copy kept on the panel (gamepanel.runtime.backup_archive).

Local disk in a temporary folder, no SSH: the chunks that in a job come from the remote
`cat` are a list of bytes here.
"""
from __future__ import annotations

import os
import time

import pytest

from gamepanel.runtime import backup_archive
from gamepanel.runtime.backups import BACKUP_SCRIPT

DIR = "/var/backups/gamepanel"


def _store(root, name, data=b"abc", keep=10, prefix="valheim"):
    return backup_archive.store(str(root), prefix, name, [data], len(data), keep)


def _age(root, prefix, name, seconds_ago):
    path = os.path.join(str(root), prefix, name)
    ts = time.time() - seconds_ago
    os.utime(path, (ts, ts))


# ------------------------------------------------ which file the backup created

def test_a_frase_do_script_e_a_que_o_painel_procura():
    # Changing the sentence in BACKUP_SCRIPT without changing the expression would leave every
    # backup without the second copy - the job would fail with "nao disse qual arquivo criou".
    assert 'echo "backup pronto: $alvo ($(stat -Lc %s -- "$alvo") bytes)"' in BACKUP_SCRIPT


def test_acha_o_arquivo_e_o_tamanho_na_saida_do_backup():
    output = ("ignorado (ainda nao existe): /x\n"
              "backup pronto: /var/backups/gamepanel/valheim-20260101-120000.tar.gz (42 bytes)\n")
    assert backup_archive.created_file(output, DIR) == (
        "/var/backups/gamepanel/valheim-20260101-120000.tar.gz", 42)


def test_com_dois_backups_na_saida_vale_o_ultimo():
    output = (f"backup pronto: {DIR}/a-1.tar.gz (1 bytes)\n"
              f"restaurado: x\nbackup pronto: {DIR}/a-2.tar.gz (2 bytes)\n")
    assert backup_archive.created_file(output, DIR) == (f"{DIR}/a-2.tar.gz", 2)


def test_saida_sem_a_frase_nao_acha_nada():
    assert backup_archive.created_file("tar falhou (codigo 2)", DIR) is None


def test_arquivo_fora_da_pasta_de_backup_e_ignorado():
    # The path comes from the text of a remote command: it must not become "pull any file".
    assert backup_archive.created_file("backup pronto: /etc/shadow.tar.gz (9 bytes)", DIR) is None


def test_nome_invalido_na_pasta_certa_e_recusado():
    with pytest.raises(ValueError):
        backup_archive.created_file(f"backup pronto: {DIR}/..tar.gz (9 bytes)", DIR)


# ------------------------------------------------------------- storing

def test_guarda_a_copia_na_pasta_do_prefixo(tmp_path):
    written, removed = _store(tmp_path, "valheim-1.tar.gz", b"conteudo")
    assert (written, removed) == (8, [])
    assert (tmp_path / "valheim" / "valheim-1.tar.gz").read_bytes() == b"conteudo"


def test_copia_incompleta_nao_fica_com_o_nome_certo(tmp_path):
    # A remote `cat` that dies midway just stops sending chunks: the size is what catches it.
    with pytest.raises(OSError, match="incompleta"):
        backup_archive.store(str(tmp_path), "valheim", "valheim-1.tar.gz", [b"ab"], 10, 5)
    assert os.listdir(tmp_path / "valheim") == [], "nem a copia, nem o .parcial"


def test_retencao_apaga_as_mais_antigas_do_mesmo_prefixo(tmp_path):
    for i in range(3):
        _store(tmp_path, f"valheim-{i}.tar.gz")
        _age(tmp_path, "valheim", f"valheim-{i}.tar.gz", 100 - i)
    _store(tmp_path, "palworld-0.tar.gz", prefix="palworld")
    _written, removed = _store(tmp_path, "valheim-3.tar.gz", keep=2)
    assert sorted(removed) == ["valheim-0.tar.gz", "valheim-1.tar.gz"]
    assert [c["name"] for c in backup_archive.list_copies(str(tmp_path), "valheim")] == [
        "valheim-3.tar.gz", "valheim-2.tar.gz"]
    assert len(backup_archive.list_copies(str(tmp_path), "palworld")) == 1, "outro jogo nao entra na conta"


def test_retencao_zero_nunca_apaga(tmp_path):
    for i in range(4):
        _store(tmp_path, f"valheim-{i}.tar.gz", keep=0)
    assert len(backup_archive.list_copies(str(tmp_path), "valheim")) == 4


def test_prefixo_que_sairia_da_pasta_e_recusado(tmp_path):
    with pytest.raises(ValueError):
        _store(tmp_path, "x-1.tar.gz", prefix="../etc")


def test_prefixo_com_quebra_de_linha_no_fim_e_recusado(tmp_path):
    """The prefix comes from the URL, and a regex ending in `$` would accept "valheim\\n"."""
    with pytest.raises(ValueError):
        _store(tmp_path, "x-1.tar.gz", prefix="valheim\n")


# ------------------------------------------------------------ listing and deleting

def test_lista_marca_a_copia_de_seguranca_e_poe_a_mais_nova_em_cima(tmp_path):
    _store(tmp_path, "valheim-1.tar.gz")
    _age(tmp_path, "valheim", "valheim-1.tar.gz", 60)
    _store(tmp_path, "valheim-2-antes-de-restaurar.tar.gz")
    copies = backup_archive.list_copies(str(tmp_path), "valheim")
    assert [(c["name"], c["seguranca"]) for c in copies] == [
        ("valheim-2-antes-de-restaurar.tar.gz", True), ("valheim-1.tar.gz", False)]
    assert copies[0]["size"] == 3


def test_lista_de_prefixo_sem_pasta_e_vazia(tmp_path):
    assert backup_archive.list_copies(str(tmp_path), "nunca-guardou") == []


def test_apagar_devolve_o_tamanho_e_some_da_lista(tmp_path):
    _store(tmp_path, "valheim-1.tar.gz", b"12345")
    assert backup_archive.delete(str(tmp_path), "valheim", "valheim-1.tar.gz") == 5
    assert backup_archive.list_copies(str(tmp_path), "valheim") == []


def test_caminho_de_copia_que_nao_existe_levanta(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_archive.path_of(str(tmp_path), "valheim", "valheim-9.tar.gz")
