"""UE4SS, the mod loader for Unreal games under Proton (games/mods/ue4ss_remote.py).

It runs INSIDE the CT; here it runs against a temporary folder and a fake GitHub, with the zip
in the v3.0.1 format (everything loose, next to the executable).
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from gamepanel.games.mods import ue4ss_remote as ur

RELEASE = {"tag_name": "v3.0.1", "assets": [
    {"name": "zDEV-UE4SS_v3.0.1.zip",
     "browser_download_url": "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/v3.0.1/zDEV-UE4SS_v3.0.1.zip"},
    {"name": "UE4SS_v3.0.1.zip",
     "browser_download_url": "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/v3.0.1/UE4SS_v3.0.1.zip"},
]}
FACTORY_MODS = """CheatManagerEnablerMod : 1
ActorDumperMod : 0
ConsoleEnablerMod : 1
BPModLoaderMod : 1
BPML_GenericFunctions : 1
; Built-in keybinds, do not move up!
Keybinds : 1
"""
FACTORY_SETTINGS = "[Debug]\nConsoleEnabled = 1\nGuiConsoleEnabled = 1\nGuiConsoleVisible = 1\nGraphicsAPI = opengl\n"


def official_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dwmapi.dll", b"MZ-proxy")
        z.writestr("UE4SS.dll", b"MZ-core")
        z.writestr("UE4SS-settings.ini", FACTORY_SETTINGS)
        z.writestr("Mods/mods.txt", FACTORY_MODS)
        z.writestr("Mods/BPModLoaderMod/Scripts/main.lua", "-- bp")
        z.writestr("Mods/CheatManagerEnablerMod/Scripts/main.lua", "-- cheat")
        z.writestr("README.md", "leia")
    return buf.getvalue()


def fetched(urls: list[str]):
    def fetcher(url: str) -> bytes:
        urls.append(url)
        return json.dumps(RELEASE).encode() if "api.github.com" in url else official_zip()
    return fetcher


@pytest.fixture
def game(tmp_path):
    env = tmp_path / "game-runtime.env"
    env.write_text("RUNTIME='proton'\nWINE_DLL_OVERRIDES='mscoree,mshtml='\n", encoding="utf-8")
    exe_dir = tmp_path / "Icarus" / "Binaries" / "Win64"
    exe_dir.mkdir(parents=True)
    return exe_dir, env


def test_liga_a_dwmapi_sem_mexer_no_que_o_jogo_ja_tinha():
    """Without dwmapi=n,b Wine uses its own dwmapi and UE4SS never runs."""
    assert ur.with_dwmapi("mscoree,mshtml=") == "mscoree,mshtml=;dwmapi=n,b"
    assert ur.with_dwmapi("mscoree,mshtml=;dwmapi=n,b") == "mscoree,mshtml=;dwmapi=n,b"
    assert ur.without_dwmapi("mscoree,mshtml=;dwmapi=n,b") == "mscoree,mshtml="


def test_baixa_o_zip_normal_e_nunca_o_de_debug(game):
    """zDEV opens a console and a window: on a headless server, the open console already froze V Rising."""
    exe_dir, env = game
    urls: list[str] = []
    ur.install_loader(str(exe_dir), fetcher=fetched(urls), env_path=str(env))
    assert urls[-1].endswith("/UE4SS_v3.0.1.zip")


def test_primeira_instalacao_sem_console_e_sem_mod_de_trapaca(game):
    exe_dir, env = game
    result = ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    assert result["version"] == "v3.0.1"
    assert (exe_dir / "dwmapi.dll").read_bytes() == b"MZ-proxy"
    assert not (exe_dir / "README.md").exists()
    settings = (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert "ConsoleEnabled = 0" in settings
    assert "GuiConsoleEnabled = 0" in settings
    assert "GuiConsoleVisible = 0" in settings
    flags = ur.enabled_mods((exe_dir / "Mods" / "mods.txt").read_text(encoding="utf-8"))
    assert flags == {"CheatManagerEnablerMod": False, "ActorDumperMod": False, "ConsoleEnablerMod": False,
                     "BPModLoaderMod": True, "BPML_GenericFunctions": True, "Keybinds": False}
    assert "dwmapi=n,b" in env.read_text(encoding="utf-8")


def test_reinstalar_preserva_a_config_e_o_mods_txt_do_dono(game):
    exe_dir, env = game
    ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    (exe_dir / "UE4SS-settings.ini").write_text("[Debug]\nConsoleEnabled = 0\nMeuAjuste = 7\n", encoding="utf-8")
    (exe_dir / "Mods" / "mods.txt").write_text("MeuMod : 1\nBPModLoaderMod : 1\n", encoding="utf-8")
    ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    assert "MeuAjuste = 7" in (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert (exe_dir / "Mods" / "mods.txt").read_text(encoding="utf-8").startswith("MeuMod : 1")


def test_status_lista_mods_com_o_que_esta_ligado_e_o_fim_do_log(game):
    exe_dir, env = game
    ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    (exe_dir / "UE4SS.log").write_text("\n".join(f"linha {i}" for i in range(30)), encoding="utf-8")
    state = ur.status(str(exe_dir), env_path=str(env))
    assert state["loader_installed"] is True
    assert state["enabled"] is True
    assert {m["name"]: m["enabled"] for m in state["mods"]} == {
        "BPModLoaderMod": True, "CheatManagerEnablerMod": False}
    assert len(state["log"]) == ur.LOG_TAIL


def test_desligar_tira_a_dwmapi(game):
    exe_dir, env = game
    ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    ur.set_enabled(str(env), False)
    assert ur.status(str(exe_dir), env_path=str(env))["enabled"] is False


def test_pasta_do_executavel_que_nao_existe_e_recusada(tmp_path):
    """A profile pointing to the wrong place must not scatter DLLs in an arbitrary folder."""
    with pytest.raises(ValueError, match="nao existe"):
        ur.install_loader(str(tmp_path / "nada"), fetcher=fetched([]))


def test_download_so_de_github(game):
    exe_dir, env = game
    bad = {"tag_name": "v9", "assets": [{"name": "UE4SS_v9.0.0.zip", "browser_download_url": "https://evil.example/u.zip"}]}
    with pytest.raises(ValueError):
        ur.install_loader(str(exe_dir), fetcher=lambda u: json.dumps(bad).encode(), env_path=str(env))


def experimental_zip() -> bytes:
    """The experimental layout: only the proxy loose, the rest in ue4ss/ (and mods.txt with a BOM)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dwmapi.dll", b"MZ-proxy")
        z.writestr("ue4ss/UE4SS.dll", b"MZ-core")
        z.writestr("ue4ss/UE4SS-settings.ini", FACTORY_SETTINGS)
        z.writestr("ue4ss/Mods/mods.txt", "﻿" + FACTORY_MODS)
        z.writestr("ue4ss/Mods/BPModLoaderMod/Scripts/main.lua", "-- bp")
        z.writestr("ue4ss/LICENSE", "mit")
    return buf.getvalue()


def test_padrao_e_a_experimental_que_nao_quebra_a_steam(game):
    """Measured on Icarus: with v3.0.1 the server's Steam came up with AppId 0 and A2S disappeared."""
    exe_dir, env = game
    urls: list[str] = []

    def fetcher(url: str) -> bytes:
        urls.append(url)
        if "api.github.com" in url:
            return json.dumps({"tag_name": "experimental-latest", "assets": [{
                "name": "UE4SS_v3.0.1-1152-ge3ba1016.zip",
                "browser_download_url": "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/"
                                        "experimental-latest/UE4SS_v3.0.1-1152-ge3ba1016.zip"}]}).encode()
        return experimental_zip()

    ur.install_loader(str(exe_dir), fetcher=fetcher, env_path=str(env))
    assert urls[0].endswith("/releases/tags/experimental-latest")
    assert (exe_dir / "dwmapi.dll").exists()
    assert (exe_dir / "ue4ss" / "UE4SS.dll").exists()
    assert not (exe_dir / "ue4ss" / "LICENSE").exists()
    assert "GuiConsoleEnabled = 0" in (exe_dir / "ue4ss" / "UE4SS-settings.ini").read_text(encoding="utf-8")
    mods_txt = (exe_dir / "ue4ss" / "Mods" / "mods.txt").read_text(encoding="utf-8")
    # The BOM stuck to the first mod's name: "CheatManagerEnablerMod" preceded by U+FEFF is not the real mod.
    assert not mods_txt.startswith("﻿")
    assert ur.enabled_mods(mods_txt)["CheatManagerEnablerMod"] is False
    state = ur.status(str(exe_dir), env_path=str(env))
    assert state["loader_installed"] is True
    assert [m["name"] for m in state["mods"]] == ["BPModLoaderMod"]


# ------------------------------------------------------------------ uninstall

def test_desinstalar_tira_o_ue4ss_e_a_dwmapi_e_deixa_o_jogo(game):
    exe_dir, env = game
    (exe_dir / "Icarus-Win64-Shipping.exe").write_bytes(b"jogo")
    ur.install_loader(str(exe_dir), fetcher=fetched([]), env_path=str(env))
    result = ur.uninstall_loader(str(exe_dir), env_path=str(env))
    assert set(result["removed"]) >= {"dwmapi.dll", "UE4SS.dll", "Mods", "UE4SS-settings.ini"}
    assert sorted(p.name for p in exe_dir.iterdir()) == ["Icarus-Win64-Shipping.exe"]
    assert "dwmapi=n,b" not in env.read_text(encoding="utf-8")
    assert "WINE_DLL_OVERRIDES='mscoree,mshtml='" in env.read_text(encoding="utf-8")


def test_desinstalar_instalacao_antiga_da_experimental_sem_lista(game):
    exe_dir, env = game
    (exe_dir / "Icarus-Win64-Shipping.exe").write_bytes(b"jogo")
    (exe_dir / "dwmapi.dll").write_bytes(b"MZ-proxy")
    (exe_dir / "ue4ss" / "Mods").mkdir(parents=True)
    (exe_dir / ur.MARK).write_text(json.dumps({"version": "experimental-latest"}), encoding="utf-8")
    ur.uninstall_loader(str(exe_dir), env_path=str(env))
    assert sorted(p.name for p in exe_dir.iterdir()) == ["Icarus-Win64-Shipping.exe"]
