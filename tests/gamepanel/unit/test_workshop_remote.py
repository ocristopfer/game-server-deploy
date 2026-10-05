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


# ------------------------------------------------------------------------------- ARK

ARK_UNIT = (
    "# /etc/systemd/system/ark-ascended.service\n[Service]\nUser=steam\n"
    'ExecStart=/usr/local/bin/win-run /opt/game/ShooterGame/Binaries/Win64/ArkAscendedServer.exe '
    '"TheIsland_WP?listen?Port=7777" -server -log -NoBattlEye\n'
)
ARK_BASE = ('/usr/local/bin/win-run /opt/game/ShooterGame/Binaries/Win64/ArkAscendedServer.exe '
            '"TheIsland_WP?listen?Port=7777" -server -log -NoBattlEye')


def _ark(tmp_path, unit_text: str = ARK_UNIT, monkeypatch=None) -> dict:
    ctx = _ctx(tmp_path)
    ctx.update(unit="ark-ascended.service", unit_text=unit_text)
    if monkeypatch is not None:
        dropin = tmp_path / "etc" / "ark-ascended.service.d" / wr.ARK_DROPIN
        monkeypatch.setattr(wr, "ark_dropin", lambda _ctx: str(dropin))
        monkeypatch.setattr(wr.os, "geteuid", lambda: 0, raising=False)
        monkeypatch.setattr(wr.subprocess, "run", lambda *a, **k: None)
    return ctx


def test_ark_le_o_comando_da_propria_unit_e_nunca_do_drop_in(tmp_path):
    """Reading our own drop-in back would freeze the command: a redeploy would never be seen."""
    text = (ARK_UNIT + "# /etc/systemd/system/ark-ascended.service.d/gamepanel-mods.conf\n[Service]\n"
            "ExecStart=\nExecStart=/velho -mods=1\n")
    assert wr.ark_base(_ark(tmp_path, text)) == ARK_BASE


def test_ark_tira_o_mods_que_alguem_pos_a_mao_e_mantem_as_aspas(tmp_path):
    unit = ARK_UNIT.replace("-NoBattlEye", "-mods=111111 -NoBattlEye")
    assert wr.ark_base(_ark(tmp_path, unit)) == ARK_BASE


def test_ark_grava_o_drop_in_com_o_comando_de_base(tmp_path, monkeypatch):
    ctx = _ark(tmp_path, monkeypatch=monkeypatch)
    wr.ark_set(ctx, ["928988", "929420"])
    text = _read(wr.ark_dropin(ctx))
    assert f"{wr.ARK_BASE_MARK}{ARK_BASE}\n" in text
    assert text.endswith(f"[Service]\nExecStart=\nExecStart={ARK_BASE} -mods=928988,929420\n")
    state = wr.ark_status(ctx)
    assert state["ids"] == ["928988", "929420"]
    assert state["base_changed"] is False


def test_ark_acusa_quando_um_redeploy_muda_o_comando(tmp_path, monkeypatch):
    ctx = _ark(tmp_path, monkeypatch=monkeypatch)
    wr.ark_set(ctx, ["928988"])
    ctx["unit_text"] = ARK_UNIT.replace("TheIsland_WP", "ScorchedEarth_WP")
    assert wr.ark_status(ctx)["base_changed"] is True


def test_ark_lista_vazia_apaga_o_drop_in(tmp_path, monkeypatch):
    ctx = _ark(tmp_path, monkeypatch=monkeypatch)
    wr.ark_set(ctx, ["928988"])
    wr.ark_set(ctx, [])
    assert not os.path.exists(wr.ark_dropin(ctx))


def test_ark_mostra_o_que_o_curseforge_ja_instalou(tmp_path, monkeypatch):
    ctx = _ark(tmp_path, monkeypatch=monkeypatch)
    wr.ark_set(ctx, ["928988", "929420"])
    _write(tmp_path / "game" / wr.ARK_MODS_DIR / "83374" / "928988_6570486" / "x.uasset", "")
    assert wr.ark_status(ctx)["installed"] == ["928988"]


def test_ark_sem_root_nao_escreve(tmp_path, monkeypatch):
    ctx = _ark(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(wr.os, "geteuid", lambda: 1000, raising=False)
    with pytest.raises(ValueError, match="root"):
        wr.ark_set(ctx, ["928988"])


# ------------------------------------------------------------------------------- Conan

def _conan(tmp_path, monkeypatch) -> tuple[dict, str]:
    """A Conan game folder and a holding folder under a prefix the test controls."""
    monkeypatch.setattr(wr, "STAGING_PREFIX", str(tmp_path / "staging-"))
    staging = tmp_path / "staging-abc"
    staging.mkdir()
    _write(tmp_path / "game" / wr.CONAN_SETTINGS, "[ServerSettings]\r\nMaxNudity=0\r\nServerModList=\r\n")
    return _ctx(tmp_path), str(staging)


def _downloaded(staging: str, item: str, *names: str) -> None:
    for name in names:
        _write(os.path.join(staging, item, name), name)


def test_conan_poe_os_arquivos_com_o_nome_original_e_monta_o_modlist_na_ordem(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    _downloaded(staging, "3750659229", "PIPPI_Resources.pak")
    _downloaded(staging, "880454836", "Pippi.pak", "Pippi.utoc", "Pippi.ucas")
    wr.conan_set(ctx, ["880454836", "3750659229"], staging)
    mods = tmp_path / "game" / wr.CONAN_MODS
    assert sorted(os.listdir(mods)) == sorted(
        [wr.CONAN_MARK, "modlist.txt", "PIPPI_Resources.pak", "Pippi.pak", "Pippi.utoc", "Pippi.ucas"])
    # Only the .pak goes into the list; .utoc/.ucas are found next to it by the game.
    assert _read(mods / "modlist.txt") == "*Pippi.pak\n*PIPPI_Resources.pak\n"
    # CRLF kept, and the setting turned on where it already was.
    settings = wr.read_text(str(tmp_path / "game" / wr.CONAN_SETTINGS), raw=True)
    assert settings == "[ServerSettings]\r\nMaxNudity=0\r\nServerModList=modlist.txt\r\n"
    assert not os.path.exists(staging)


def test_conan_tirar_um_mod_apaga_so_os_arquivos_dele(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    _downloaded(staging, "1", "A.pak")
    _downloaded(staging, "2", "B.pak")
    with pytest.raises(ValueError):  # IDs below 6 digits are not Workshop IDs; the plan uses them as-is
        wr.parse_items("conan", ["1"])
    wr.conan_set(ctx, ["1", "2"], staging)
    mods = tmp_path / "game" / wr.CONAN_MODS
    _write(mods / "hand.pak", "x")
    _write(mods / "modlist.txt", "*hand.pak\n*A.pak\n*B.pak\n")
    wr.conan_set(ctx, ["2"], "")
    kept = sorted(n for n in os.listdir(mods) if not n.endswith(wr.BACKUP_SUFFIX))
    assert kept == sorted([wr.CONAN_MARK, "modlist.txt", "B.pak", "hand.pak"])
    # The hand-installed mod stays first; the panel's own lines follow the list.
    assert _read(mods / "modlist.txt") == "*hand.pak\n*B.pak\n"


def test_conan_mod_que_nao_foi_baixado_nao_entra(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="not downloaded"):
        wr.conan_set(ctx, ["3750659229"], staging)
    assert not os.path.exists(tmp_path / "game" / wr.CONAN_MODS / "modlist.txt")


def test_conan_dois_mods_com_o_mesmo_arquivo_sao_recusados(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    _downloaded(staging, "3750659229", "Same.pak")
    _downloaded(staging, "880454836", "same.pak")
    with pytest.raises(ValueError, match="same name"):
        wr.conan_set(ctx, ["3750659229", "880454836"], staging)


def test_conan_pasta_de_espera_fora_do_prefixo_e_recusada(tmp_path, monkeypatch):
    ctx, _ = _conan(tmp_path, monkeypatch)
    for bad in (str(tmp_path / "game"), str(tmp_path / "staging-x" / ".." / "game")):
        with pytest.raises(ValueError, match="holding folder"):
            wr.conan_set(ctx, [], bad)


def test_conan_status_traz_o_que_o_servidor_recusou(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    _downloaded(staging, "3725018456", "Pippi.pak")
    wr.conan_set(ctx, ["3725018456"], staging)
    _write(tmp_path / "game" / wr.CONAN_LOG,
           "LogModManager: Error: Mod pak file: Z:/opt/game/ConanSandbox/Mods/Pippi.pak failed check and will "
           "be excluded. This could be due to an out of date or corrupted pak file. (Error: Mod is too old and "
           "needs to be updated for this game version)\n")
    state = wr.conan_status(ctx)
    assert state["installed"] == ["3725018456"]
    assert state["rejected"] == {"3725018456": "Mod is too old and needs to be updated for this game version"}
    assert state["modlist_off"] is False


def test_conan_settings_sem_a_chave_ganha_a_linha_na_secao():
    assert wr._settings_with_modlist("[ServerSettings]\nA=1\n") == "[ServerSettings]\nServerModList=modlist.txt\nA=1\n"
    assert wr._settings_with_modlist("") == "[ServerSettings]\nServerModList=modlist.txt\n"


def test_conan_fetch_tenta_de_novo_o_que_a_steamcmd_nao_entregou(tmp_path, monkeypatch):
    ctx, staging = _conan(tmp_path, monkeypatch)
    content = tmp_path / "home" / "Steam" / "steamapps" / "workshop" / "content" / wr.CONAN_APP
    calls: list[list[str]] = []

    def fake_steamcmd(_ctx, items):
        calls.append(list(items))
        if len(calls) == 1:
            return type("P", (), {"stdout": "Timeout downloading item"})()
        _write(content / items[0] / "Pippi.pak", "x")
        _write(content / items[0] / "readme.txt", "not for the server")
        return type("P", (), {"stdout": f"Success. Downloaded item {items[0]} to ..."})()

    monkeypatch.setattr(wr, "_steamcmd", fake_steamcmd)
    assert wr.conan_fetch(ctx, ["3725018456"], staging) == {"fetched": ["3725018456"]}
    assert calls == [["3725018456"], ["3725018456"]]
    assert os.listdir(os.path.join(staging, "3725018456")) == ["Pippi.pak"]
