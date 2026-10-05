"""Removing UE4SS Lua mods (both installers share the block): the folder and ONLY its mods.txt line."""
from __future__ import annotations

import os
import shutil

import pytest

from gamepanel.games.mods import ue4ss_linux_remote, ue4ss_remote

MODS_TXT = "﻿; comentario do dono\r\nCheatManagerEnablerMod : 0\r\nMeuMod : 1\r\nOutro : 1\r\n"


def test_tira_so_a_linha_do_mod_e_guarda_bom_crlf_e_comentarios():
    text = ue4ss_remote.without_mod_lines(MODS_TXT, {"MeuMod"})
    assert text == "﻿; comentario do dono\r\nCheatManagerEnablerMod : 0\r\nOutro : 1\r\n"


def test_bom_fica_mesmo_quando_a_primeira_linha_sai():
    text = ue4ss_remote.without_mod_lines("﻿MeuMod : 1\nOutro : 0\n", {"MeuMod"})
    assert text == "﻿Outro : 0\n"


def test_linha_comentada_com_o_mesmo_nome_fica():
    text = ue4ss_remote.without_mod_lines("; MeuMod : 1\nMeuMod : 1\n", {"MeuMod"})
    assert text == "; MeuMod : 1\n"


@pytest.fixture
def mods(tmp_path):
    mods_dir = tmp_path / "ue4ss" / "Mods"
    for name in ("MeuMod", "Outro", "shared"):
        (mods_dir / name / "Scripts").mkdir(parents=True)
        (mods_dir / name / "Scripts" / "main.lua").write_text("print(1)", encoding="utf-8")
    (mods_dir / "mods.txt").write_bytes(MODS_TXT.encode("utf-8"))
    return mods_dir


@pytest.mark.parametrize("module", [ue4ss_remote, ue4ss_linux_remote])
def test_remove_a_pasta_e_a_linha(module, mods, capsys):
    result = module.remove_lua_mods(str(mods), ["MeuMod"])
    assert result == {"removed": ["MeuMod"]}
    assert not (mods / "MeuMod").exists()
    assert (mods / "Outro").is_dir()
    assert (mods / "mods.txt").read_bytes().decode("utf-8") == (
        "﻿; comentario do dono\r\nCheatManagerEnablerMod : 0\r\nOutro : 1\r\n")


def test_pasta_que_ja_nao_existe_ainda_limpa_a_linha(mods):
    shutil.rmtree(mods / "MeuMod")
    assert ue4ss_linux_remote.remove_lua_mods(str(mods), ["MeuMod"]) == {"removed": []}
    assert "MeuMod" not in (mods / "mods.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["shared", "../MeuMod", "a/b", ".", "..", ".oculto", ""])
def test_nome_proibido_nao_apaga_nada(mods, name):
    with pytest.raises(ValueError):
        ue4ss_linux_remote.remove_lua_mods(str(mods), [name])
    assert (mods / "shared").is_dir() and (mods / "MeuMod").is_dir()


def test_arquivo_solto_nao_e_mod(mods):
    """mods.txt itself passes the name rule: only a FOLDER (or a link) is a Lua mod."""
    with pytest.raises(ValueError):
        ue4ss_linux_remote.remove_lua_mods(str(mods), ["mods.txt"])
    assert (mods / "mods.txt").exists()


def _can_symlink(tmp_path) -> bool:
    try:
        os.symlink(tmp_path, tmp_path / "probe-link", target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    os.remove(tmp_path / "probe-link")
    return True


def test_pasta_de_mods_que_e_link_e_recusada(tmp_path, mods):
    if not _can_symlink(tmp_path):
        pytest.skip("este sistema nao cria links simbolicos sem privilegio")
    victim = tmp_path / "fora"
    (victim / "MeuMod").mkdir(parents=True)
    link = tmp_path / "link-mods"
    os.symlink(victim, link, target_is_directory=True)
    with pytest.raises(ValueError):
        ue4ss_remote.remove_lua_mods(str(link), ["MeuMod"])
    assert (victim / "MeuMod").is_dir()


def test_main_remove_sem_exigir_o_overlay(mods, capsys, monkeypatch):
    """Removing touches no environment: a helper-mode CT without the overlay can still do it."""
    exe_dir = mods.parent.parent
    monkeypatch.setattr(ue4ss_linux_remote, "overlay_problem", lambda unit: "sem overlay")
    code = ue4ss_linux_remote.main(["--overlay", "--unit", "dragonwilds.service", "mod-remove", str(exe_dir), "MeuMod"])
    assert code == 0, capsys.readouterr().out
    assert not (mods / "MeuMod").exists()
