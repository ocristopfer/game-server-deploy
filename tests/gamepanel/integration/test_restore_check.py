"""The member check of the restore (`runtime.backups._RESTORE_CHECK_AWK`), run by a real awk.

The restore extracts an archive that lives in a folder the game can write to. Before anything
is extracted, the check reads the archive listing (`tar --numeric-owner --quoting-style=c -tv`)
and refuses the WHOLE restore on an absolute path, a `..`, a link that leaves the backup paths,
a device, a setuid file, or a file whose folder has no entry of its own. What it prints is the
list of backup paths to extract - members anywhere else are simply left out.

The listings here are written by hand in tar's exact format, so the test needs only awk (no tar,
no root, nothing extracted anywhere). The full script, with tar and the planted links, was
measured on Debian 13 (GNU tar 1.35) - see the comment above `RESTORE_SCRIPT`.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from gamepanel.runtime import backups

AWK = shutil.which("awk")
pytestmark = pytest.mark.skipif(AWK is None, reason="sem awk no PATH")

DIR = 'drwxr-xr-x 1000/1000         0 2026-10-05 13:06 '
FILE = '-rw-r--r-- 1000/1000         3 2026-10-05 13:06 '
SAVE = [DIR + '"opt/game/Saved/"', DIR + '"opt/game/Saved/sub/"', FILE + '"opt/game/Saved/sub/f"']


def check(lines: list[str], allowed: tuple[str, ...] = ("/opt/game/Saved",)) -> tuple[int, str, str]:
    env = {**os.environ, "GP_ALLOWED": "".join(f"{p}\n" for p in allowed), "LC_ALL": "C"}
    proc = subprocess.run(
        [AWK, backups._RESTORE_CHECK_AWK], input="".join(f"{ln}\n" for ln in lines),
        capture_output=True, text=True, env=env, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def test_arquivo_normal_passa_e_diz_o_que_extrair():
    assert check(SAVE) == (0, "opt/game/Saved\n", "")


def test_o_que_esta_fora_das_pastas_de_backup_fica_de_fora_sem_recusar():
    code, out, _ = check([*SAVE, DIR + '"opt/game/Other/"', FILE + '"opt/game/Other/x"'])
    assert (code, out) == (0, "opt/game/Saved\n")


def test_so_entram_as_pastas_que_o_arquivo_traz():
    code, out, _ = check(SAVE, ("/opt/game/Saved", "/home/steam/.config/x"))
    assert (code, out) == (0, "opt/game/Saved\n")


def test_nada_nas_pastas_de_backup_devolve_lista_vazia():
    assert check([DIR + '"opt/game/Other/"'])[:2] == (0, "")


@pytest.mark.parametrize(("line", "reason"), [
    (FILE + '"/etc/cron.d/x"', "caminho absoluto"),
    (FILE + '"opt/game/Saved/../../../etc/x"', "caminho com .."),
    ('lrwxrwxrwx 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/l" -> "/etc/passwd"', "link para fora"),
    ('lrwxrwxrwx 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/l" -> "../../Other/x"', "link para fora"),
    ('lrwxrwxrwx 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/l" -> "../../../../../.."', "link para fora"),
    ('hrw-r--r-- 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/h" link to "etc/shadow"', "link para fora"),
    ('hrw-r--r-- 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/h" link to "opt/game/Saved/../x"', "link fisico"),
    ('crw-r--r-- 0/0 1,3 2026-10-05 13:06 "opt/game/Saved/sub/null"', "tipo de arquivo"),
    ('prw-r--r-- 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/fifo"', "tipo de arquivo"),
    ('-rwsr-xr-x 0/0 3 2026-10-05 13:06 "opt/game/Saved/sub/suid"', "setuid"),
    ('-rwxr-sr-x 0/0 3 2026-10-05 13:06 "opt/game/Saved/sub/sgid"', "setuid"),
])
def test_membro_perigoso_recusa_a_restauracao_inteira(line, reason):
    code, out, err = check([*SAVE, line])
    assert code != 0
    assert out == "", "recusada, nada pode ir para a lista de extracao"
    assert reason in err


def test_membro_perigoso_fora_das_pastas_tambem_recusa():
    """Absolute and `..` refuse even outside the backup paths: such an archive was not made by
    the panel, and nothing in it is trusted."""
    code, _, err = check([*SAVE, FILE + '"/etc/x"'])
    assert code != 0 and "caminho absoluto" in err


def test_link_dentro_das_pastas_passa():
    code, out, _ = check([*SAVE,
                          'lrwxrwxrwx 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/sub/l" -> "f"',
                          'lrwxrwxrwx 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/a b" -> "sub/../sub/f"',
                          'hrw-r--r-- 1000/1000 0 2026-10-05 13:06 "opt/game/Saved/h" link to "opt/game/Saved/sub/f"'])
    assert (code, out) == (0, "opt/game/Saved\n")


def test_arquivo_sem_a_entrada_da_pasta_e_recusado():
    """Without the folder entry, tar creates the file THROUGH whatever is at that path - a link
    the game planted included. tar -c always writes the entry, so its absence is a crafted file."""
    code, _, err = check([DIR + '"opt/game/Saved/"', FILE + '"opt/game/Saved/sub/f"'])
    assert code != 0 and "sem a pasta" in err


def test_nome_com_aspas_e_espaco_e_lido_inteiro():
    code, out, _ = check([*SAVE, FILE + r'"opt/game/Saved/a \"b\" -> c"'])
    assert (code, out) == (0, "opt/game/Saved\n")


@pytest.mark.parametrize("allowed", [(), ("/",), ("/opt/game/Savé",), ("/opt/../..",)])
def test_pasta_de_backup_que_nao_da_para_conferir_recusa(allowed):
    code, out, _ = check(SAVE, allowed)
    assert code != 0 and out == ""


def test_linha_que_nao_e_do_tar_recusa():
    code, _, err = check(["isto nao e uma linha do tar"])
    assert code != 0 and "nao entendi" in err


def test_o_programa_nao_tem_aspas_simples():
    """It travels inside a single-quoted bash string: one apostrophe and the restore script
    stops parsing - on the day someone needs the backup back."""
    assert "'" not in backups._RESTORE_CHECK_AWK
