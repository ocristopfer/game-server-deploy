"""Removing mods by name: which names get in, what the command looks like in each access mode."""
from __future__ import annotations

import inspect
import shlex

import pytest

from gamepanel.games.mods import profiles, removal, ue4ss_linux_remote, ue4ss_remote
from gamepanel.i18n import Message

ROOT = {"ssh_user": "root", "service": "dragonwilds.service"}
HELPER = {"ssh_user": "gamepanel", "service": "dragonwilds.service"}


@pytest.mark.parametrize("name", ["../x.pak", "a/b.pak", "..", ".", "", "x\n.pak", "x\\y.pak", "x" * 300 + ".pak"])
def test_nome_com_caminho_ou_estranho_e_recusado(name):
    with pytest.raises(ValueError):
        removal.targets(profiles.DRAGONWILDS, [name])


def test_extensao_que_o_perfil_nao_aceita_e_recusada():
    with pytest.raises(ValueError) as caught:
        removal.targets(profiles.DRAGONWILDS, ["script.sh"])
    assert isinstance(caught.value.args[0], Message)
    assert caught.value.args[0].key == "mods.bad_name"


def test_um_nome_ruim_recusa_o_lote_inteiro():
    """All or nothing: the good name in the same form does not go alone."""
    with pytest.raises(ValueError):
        removal.targets(profiles.DRAGONWILDS, ["Bom.pak", "../ruim.pak"])


def test_nada_marcado_e_recusado():
    with pytest.raises(ValueError) as caught:
        removal.targets(profiles.DRAGONWILDS, [])
    assert caught.value.args[0].key == "mods.remove_none_selected"


@pytest.mark.parametrize("ticked", ["Mod.pak", "Mod.utoc", "Mod.ucas"])
def test_mod_de_unreal_5_sai_com_os_tres_arquivos(ticked):
    """IoStore: the .pak alone does not load and the other two are dead weight, so the three go together."""
    pairs = removal.targets(profiles.DRAGONWILDS, [ticked])
    assert sorted(pairs) == [("f", "Mod.pak"), ("f", "Mod.ucas"), ("f", "Mod.utoc")]


def test_unreal_4_so_remove_o_pak():
    """Soulmask (UE 4.27) only takes .pak: a .utoc next to it would not be the mod's."""
    assert removal.targets(profiles.SOULMASK, ["Mod.pak"]) == [("f", "Mod.pak")]


def test_marcar_os_tres_nao_repete_o_mesmo_arquivo():
    pairs = removal.targets(profiles.DRAGONWILDS, ["Mod.pak", "Mod.utoc", "Mod.ucas"])
    assert len(pairs) == 3


def test_pasta_de_mod_so_onde_o_perfil_tem_mod_em_pasta():
    assert removal.targets(profiles.ENSHROUDED, [], ["MeuMod"]) == [("d", "MeuMod")]
    with pytest.raises(ValueError):
        removal.targets(profiles.DRAGONWILDS, [], ["MeuMod"])
    with pytest.raises(ValueError):
        removal.targets(profiles.ENSHROUDED, [], ["../MeuMod"])


def test_limite_de_nomes_por_vez(monkeypatch):
    monkeypatch.setattr(removal, "MAX_NAMES", 2)
    with pytest.raises(ValueError) as caught:
        removal.targets(profiles.ENSHROUDED, ["a.dll", "b.dll", "c.dll"])
    assert caught.value.args[0].key == "mods.remove_too_many"


def test_comando_no_modo_root_e_o_de_sempre_sem_sudo():
    cmd = removal.remove_command(ROOT, "/opt/game/RSDragonwilds/Content/Paks/~mods", [("f", "Mod.pak")])
    assert cmd.startswith("bash -c ")
    assert "sudo" not in cmd
    assert shlex.split(cmd)[-3:] == ["/opt/game/RSDragonwilds/Content/Paks/~mods", "f", "Mod.pak"]


def test_comando_no_modo_helper_roda_como_steam():
    cmd = removal.remove_command(HELPER, "/opt/game/mods", [("d", "Pasta Mod")])
    assert cmd.startswith("cd / && sudo -n -u steam -- bash -c ")
    assert shlex.split(cmd)[-3:] == ["/opt/game/mods", "d", "Pasta Mod"]


def test_o_bloco_de_remocao_lua_e_identico_nos_dois_ue4ss():
    """They run standalone in the CT and do not import each other: the copy has to be identical."""
    import re
    block = re.compile(r"# -+ Lua mod removal\n.*?# -+ end of the Lua mod removal\n", re.S)
    texts = {block.search(inspect.getsource(m)).group(0) for m in (ue4ss_remote, ue4ss_linux_remote)}  # type: ignore[union-attr]
    assert len(texts) == 1
