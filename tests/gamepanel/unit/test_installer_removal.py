"""Thunderstore and SML removal: an rmtree that fails must not come back as "removed"."""
from __future__ import annotations

import os
import shutil

import pytest

from gamepanel.games.mods import sml_remote, thunderstore_remote


@pytest.fixture
def plugin(tmp_path):
    folder = tmp_path / "BepInEx" / "plugins" / "deca-VampireCommandFramework"
    folder.mkdir(parents=True)
    (folder / "VCF.dll").write_bytes(b"x")
    return tmp_path


@pytest.fixture
def sml_mod(tmp_path):
    folder = tmp_path / "FactoryGame" / "Mods" / "RefinedPower"
    folder.mkdir(parents=True)
    (folder / "x.pak").write_bytes(b"x")
    return tmp_path


def _denied(path, *a, **k):
    # What steam meets on a folder a root install left behind: the plugin stays and keeps loading.
    raise PermissionError(13, "Permission denied", str(path))


def test_plugin_que_nao_sai_vira_erro(plugin, monkeypatch):
    monkeypatch.setattr(shutil, "rmtree", _denied)
    with pytest.raises(OSError):
        thunderstore_remote.remove_plugin(str(plugin), "deca", "VampireCommandFramework")


def test_plugin_sai_de_verdade(plugin):
    assert thunderstore_remote.remove_plugin(str(plugin), "deca", "VampireCommandFramework") == {"removed": True}
    assert os.listdir(plugin / "BepInEx" / "plugins") == []


def test_mod_do_sml_que_nao_sai_vira_erro(sml_mod, monkeypatch):
    monkeypatch.setattr(shutil, "rmtree", _denied)
    with pytest.raises(OSError):
        sml_remote.remove(str(sml_mod), "RefinedPower")


def test_mod_do_sml_que_nao_existe_nao_e_erro(sml_mod):
    assert sml_remote.remove(str(sml_mod), "OutroMod") == {"removed": False}


def _can_symlink(tmp_path) -> bool:
    try:
        os.symlink(tmp_path, tmp_path / "probe", target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    os.remove(tmp_path / "probe")
    return True


def test_pasta_de_plugins_que_e_link_e_recusada(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("este sistema nao cria links simbolicos sem privilegio")
    outside = tmp_path / "fora" / "deca-VampireCommandFramework"
    outside.mkdir(parents=True)
    game = tmp_path / "jogo" / "BepInEx"
    game.mkdir(parents=True)
    os.symlink(tmp_path / "fora", game / "plugins", target_is_directory=True)
    with pytest.raises(ValueError):
        thunderstore_remote.remove_plugin(str(tmp_path / "jogo"), "deca", "VampireCommandFramework")
    assert outside.is_dir()
