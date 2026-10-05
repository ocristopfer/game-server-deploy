"""Workshop via the config: the script that runs in the CT, against fake folders with each game's layout.

The formats were measured on real servers (Docker): here it is proven that writing replaces only
the LIST and leaves the rest of the config as it was.
"""
from __future__ import annotations

import json
import os

import pytest

from gamepanel.games.mods import workshop
from gamepanel.games.mods import workshop_remote as wr


def _write(path, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return str(path)


def _read(path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _cluster(tmp_path):
    return tmp_path / "home" / ".klei" / "DoNotStarveTogether" / "Cluster_1"


def _ctx(tmp_path, *args: str, workdir: str = "") -> dict:
    return {"game_dir": str(tmp_path / "game"), "args": list(args), "user": "ninguem-de-proposito",
            "home": str(tmp_path / "home"), "workdir": workdir}


# ------------------------------------------------------------------------------- service

def test_exec_args_le_o_ultimo_execstart_e_tira_o_prefixo():
    unit = ("[Service]\nExecStart=/opt/game/a -x 1\n# drop-in\n[Service]\nExecStart=\n"
            "ExecStart=-/opt/game/b \"-servername\" 'meu servidor'\n")
    assert wr.exec_args(unit) == ["/opt/game/b", "-servername", "meu servidor"]


def test_arg_after_aceita_espaco_igual_e_qualquer_caixa():
    args = ["x", "-ServerName", "abc", "-config=/c.json"]
    assert wr.arg_after(args, "-servername") == "abc"
    assert wr.arg_after(args, "-config") == "/c.json"
    assert wr.arg_after(args, "-cachedir") == ""


# ------------------------------------------------------------------------------- DST

OVERRIDES = """-- comentario { com chave
return {
  ["workshop-378160973"] = { enabled = true, configuration_options = { scale = "1}", x = [[ } ]] } },
  ["localmod"] = { enabled = false }, -- } no comentario
  ["workshop-999999"] = { enabled = true },
}
"""

SETUP = """--There are two functions here
\t--ServerModSetup("350811795")
ServerModSetup("999999")
"""


def _dst(tmp_path) -> dict:
    cluster = _cluster(tmp_path)
    _write(cluster / "Master" / "server.ini", "[NETWORK]\n")
    _write(cluster / "Caves" / "server.ini", "[NETWORK]\n")
    _write(cluster / "Master" / "modoverrides.lua", OVERRIDES)
    _write(tmp_path / "game" / "mods" / "dedicated_server_mods_setup.lua", SETUP)
    return _ctx(tmp_path, "/opt/game/bin64/dst", "-cluster", "Cluster_1", "-shard", "Master")


def test_lua_entries_pula_chave_dentro_de_string_e_comentario():
    entries = wr.lua_entries(OVERRIDES)
    assert list(entries) == ["workshop-378160973", "localmod", "workshop-999999"]
    assert entries["workshop-378160973"].endswith('x = [[ } ]] } }')


def test_dst_troca_a_lista_e_guarda_as_opcoes_de_quem_fica(tmp_path):
    ctx = _dst(tmp_path)
    wr.dst_set(ctx, ["666155465", "378160973"])
    setup = _read(tmp_path / "game" / "mods" / "dedicated_server_mods_setup.lua")
    # The commented example line stays; the line of the removed mod does not.
    assert '--ServerModSetup("350811795")' in setup
    assert 'ServerModSetup("999999")' not in setup
    assert setup.endswith('ServerModSetup("666155465")\nServerModSetup("378160973")\n')
    master = _read(_cluster(tmp_path) / "Master" / "modoverrides.lua")
    assert 'scale = "1}"' in master
    assert '["localmod"] = { enabled = false }' in master
    assert "999999" not in master
    assert '["workshop-666155465"] = { enabled = true }' in master
    # The shard that had no modoverrides gets one, otherwise the mod is not enabled in the caves.
    caves = _read(_cluster(tmp_path) / "Caves" / "modoverrides.lua")
    assert '["workshop-378160973"] = { enabled = true }' in caves
    assert os.path.exists(str(_cluster(tmp_path) / "Master"
                              / "modoverrides.lua") + wr.BACKUP_SUFFIX)


def test_dst_status_acusa_mod_fora_do_setup(tmp_path):
    ctx = _dst(tmp_path)
    _write(tmp_path / "game" / "mods" / "dedicated_server_mods_setup.lua", "-- update do jogo zerou\n")
    ugc = tmp_path / "game" / "ugc_mods" / "Cluster_1" / "Master" / "content"
    _write(ugc / "322330" / "378160973" / "modmain.lua", "")
    state = wr.dst_status(ctx)
    assert state["ids"] == ["378160973", "999999"]
    assert state["installed"] == ["378160973"]
    assert state["setup_missing"] == ["378160973", "999999"]
    assert state["problem"] == ""


def test_dst_sem_cluster_nao_escreve_nada(tmp_path):
    ctx = _ctx(tmp_path)
    assert wr.dst_status(ctx)["problem"] == "no_cluster"
    with pytest.raises(ValueError, match="cluster"):
        wr.dst_set(ctx, ["666155465"])
    assert not os.path.exists(tmp_path / "game" / "mods")


# ------------------------------------------------------------------------------- Zomboid

INI = "PVP=true\nMods=\nMap=Muldraugh, KY\nWorkshopItems=\nPublic=false\n"


def test_zomboid_escreve_as_duas_listas_no_ini_do_servername(tmp_path):
    ctx = _ctx(tmp_path, "/opt/game/start-server.sh", "-servername", "painel")
    _write(tmp_path / "home" / "Zomboid" / "Server" / "painel.ini", INI)
    wr.zomboid_set(ctx, ["2875848298", "2169435993"], "BB_CommonSense;modoptions")
    text = _read(tmp_path / "home" / "Zomboid" / "Server" / "painel.ini")
    assert text == ("PVP=true\nMods=BB_CommonSense;modoptions\nMap=Muldraugh, KY\n"
                    "WorkshopItems=2875848298;2169435993\nPublic=false\n")


def test_zomboid_status_mostra_os_mods_que_o_item_trouxe(tmp_path):
    ctx = _ctx(tmp_path)  # no -servername: servertest, the game's default
    _write(tmp_path / "home" / "Zomboid" / "Server" / "servertest.ini", "WorkshopItems=2875848298\nMods=\n")
    content = tmp_path / "game" / "steamapps" / "workshop" / "content" / "108600" / "2875848298" / "mods"
    _write(content / "CommonSense" / "mod.info", "name=Common Sense\nid=BB_CommonSense\n")
    _write(content / "CommonSense" / "42.0" / "mod.info", "name=Common Sense\nid=BB_CommonSense\n")
    state = wr.zomboid_status(ctx)
    assert state["available"] == {"2875848298": ["BB_CommonSense"]}
    assert state["installed"] == ["2875848298"]


def test_zomboid_sem_ini_pede_para_subir_antes(tmp_path):
    ctx = _ctx(tmp_path)
    assert wr.zomboid_status(ctx)["problem"] == "no_config"
    with pytest.raises(ValueError, match="suba o servidor"):
        wr.zomboid_set(ctx, ["2875848298"], "")


# ------------------------------------------------------------------------------- Unturned

def test_unturned_troca_so_file_ids(tmp_path):
    ctx = _ctx(tmp_path, "/opt/game/Unturned_Headless.x86_64", "+InternetServer/meu")
    path = _write(tmp_path / "game" / "Servers" / "meu" / "WorkshopDownloadConfig.json",
                  json.dumps({"File_IDs": [1], "Query_Cache_Max_Age_Seconds": 600}))
    wr.unturned_set(ctx, ["1753134636"])
    assert json.loads(_read(path)) == {"File_IDs": [1753134636], "Query_Cache_Max_Age_Seconds": 600}


def test_unturned_sem_nome_usa_a_unica_pasta_e_com_duas_recusa(tmp_path):
    ctx = _ctx(tmp_path, "/opt/game/Unturned_Headless.x86_64")
    _write(tmp_path / "game" / "Servers" / "a" / "Config.txt", "")
    assert wr.unturned_dir(ctx).endswith(os.path.join("Servers", "a"))
    _write(tmp_path / "game" / "Servers" / "b" / "Config.txt", "")
    assert wr.unturned_status(ctx)["problem"] == "no_server_name"
    with pytest.raises(ValueError, match="InternetServer"):
        wr.unturned_set(ctx, ["1753134636"])


# ------------------------------------------------------------------------------- Reforger

def test_reforger_le_o_config_relativo_ao_workdir_e_guarda_a_versao(tmp_path):
    game = tmp_path / "game"
    path = _write(game / "config.json", json.dumps({"game": {"name": "x", "mods": [
        {"modId": "5965550F24A0C152", "name": "Where Am I", "version": "1.2.0"},
        {"modId": "AAAAAAAAAAAAAAAA", "name": "Sai"}]}, "a2s": {"port": 17777}}))
    ctx = _ctx(tmp_path, "/opt/game/ArmaReforgerServer", "-config", "config.json", "-profile",
               str(game / "profiles"), workdir=str(game))
    wr.reforger_set(ctx, wr.parse_items("reforger", ["5965550f24a0c152", "59727DAE364DEADB=WeaponSwitching"]))
    data = json.loads(_read(path))
    assert data["a2s"] == {"port": 17777}
    assert data["game"]["mods"] == [
        {"modId": "5965550F24A0C152", "name": "Where Am I", "version": "1.2.0"},
        {"modId": "59727DAE364DEADB", "name": "WeaponSwitching"}]
    _write(game / "profiles" / "addons" / "WhereAmI_5965550F24A0C152" / "addon.gproj", "")
    state = wr.reforger_status(ctx)
    assert state["installed"] == ["5965550F24A0C152"]


def test_reforger_sem_config_no_comando_nao_tem_onde_escrever(tmp_path):
    ctx = _ctx(tmp_path, "/opt/game/ArmaReforgerServer", "-profile", "/opt/game/profiles/server")
    assert wr.reforger_status(ctx)["problem"] == "no_config_arg"
    with pytest.raises(ValueError, match="-config"):
        wr.reforger_set(ctx, [("5965550F24A0C152", "")])


# ------------------------------------------------------------------------------- input

@pytest.mark.parametrize(("fmt", "item"), [
    ("dst", "12345"), ("dst", "1234567; rm -rf /"), ("zomboid", "../1234567"),
    ("reforger", "5965550F24A0C15"), ("reforger", "5965550F24A0C152=a\nb"),
])
def test_item_invalido_e_recusado_no_ct(fmt, item):
    with pytest.raises(ValueError):
        wr.parse_items(fmt, [item])


def test_main_responde_erro_em_json_sem_escrever(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(wr, "unit_text", lambda unit: "")
    assert wr.main(["--unit", "x.service", "zomboid", "set", str(tmp_path), "--mods", "a;b", "nao-e-id"]) == 1
    assert "error" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_main_recusa_mods_do_zomboid_com_caractere_de_shell(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(wr, "unit_text", lambda unit: "")
    _write(tmp_path / "home" / "Zomboid" / "Server" / "servertest.ini", INI)
    monkeypatch.setattr(wr, "home_of", lambda user: str(tmp_path / "home"))
    assert wr.main(["zomboid", "set", str(tmp_path / "game"), "2875848298", "--mods", "a$(x)"]) == 1
    assert _read(tmp_path / "home" / "Zomboid" / "Server" / "servertest.ini") == INI


# ------------------------------------------------------------------------------- panel

def test_guid_colado_de_varios_jeitos():
    text = ("5965550F24A0C152 Where Am I\n"
            "https://reforger.armaplatform.com/workshop/59727DAE364DEADB-WeaponSwitching\n"
            "[14:00] fulano: 5965550f24a0c152 repetido\n"
            "1234 nao e GUID\nABCDEF0123456789=com igual")
    assert workshop.parse_guids(text) == [("5965550F24A0C152", "Where Am I"),
                                          ("59727DAE364DEADB", "WeaponSwitching"),
                                          ("ABCDEF0123456789", "com igual")]
