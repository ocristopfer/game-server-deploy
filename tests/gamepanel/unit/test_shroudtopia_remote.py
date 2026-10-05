"""Shroudtopia, the Enshrouded mod loader (games/mods/shroudtopia_remote.py).

It runs INSIDE the CT; here it runs against a temporary folder and a fake GitHub, with the zip
in the same format as version 0.1.1, which was proven on CT 303.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from gamepanel.games.mods import shroudtopia_remote as sr

RELEASE = {"tag_name": "0.1.1", "assets": [{
    "name": "Shroudtopia-0.1.1.zip",
    "browser_download_url": "https://github.com/s0t7x/shroudtopia/releases/download/0.1.1/Shroudtopia-0.1.1.zip",
}]}


def official_zip() -> bytes:
    """What the official zip ships: the loader and the EXAMPLE mods (with cheats on)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("winmm.dll", b"MZ-proxy")
        z.writestr("shroudtopia.dll", b"MZ-loader")
        z.writestr("shroudtopia.json", json.dumps({"mods": {"basics": {"no_fall_damage": True}}}))
        z.writestr("mods/basics_mod/basics_mod.dll", b"MZ-cheat")
        z.writestr("mods/ChatCommands.dll", b"MZ-chat")
    return buf.getvalue()


def fetcher(url: str) -> bytes:
    return json.dumps(RELEASE).encode() if url == sr.RELEASES else official_zip()


@pytest.fixture
def game(tmp_path):
    env = tmp_path / "game-runtime.env"
    env.write_text("RUNTIME='proton'\nWINE_DLL_OVERRIDES='mscoree,mshtml='\n", encoding="utf-8")
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    return game_dir, env


def test_liga_o_winmm_sem_mexer_no_que_o_jogo_ja_tinha():
    """Measured: without winmm=n,b Wine uses its own winmm and the loader never runs."""
    assert sr.with_winmm("mscoree,mshtml=") == "mscoree,mshtml=;winmm=n,b"
    assert sr.with_winmm("mscoree,mshtml=;winmm=n,b") == "mscoree,mshtml=;winmm=n,b"
    assert sr.without_winmm("mscoree,mshtml=;winmm=n,b") == "mscoree,mshtml="


def test_instala_o_carregador_e_nao_os_mods_de_exemplo(game):
    """The examples ship with cheats on: installing the loader must not change the game."""
    game_dir, env = game
    result = sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    assert result["version"] == "0.1.1"
    assert (game_dir / "winmm.dll").read_bytes() == b"MZ-proxy"
    assert (game_dir / "shroudtopia.dll").exists()
    assert list((game_dir / "mods").iterdir()) == []
    config = json.loads((game_dir / "shroudtopia.json").read_text(encoding="utf-8"))
    assert config["mods"] == {}
    assert "WINE_DLL_OVERRIDES='mscoree,mshtml=;winmm=n,b'" in env.read_text(encoding="utf-8")


def test_reinstalar_preserva_a_config_do_dono(game):
    game_dir, env = game
    (game_dir / "shroudtopia.json").write_text('{"mods": {"meu": {"active": true}}}', encoding="utf-8")
    sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    assert "meu" in (game_dir / "shroudtopia.json").read_text(encoding="utf-8")


def test_desligar_tira_o_winmm_e_o_status_ve(game):
    game_dir, env = game
    sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    assert sr.status(str(game_dir), env_path=str(env))["enabled"] is True
    sr.set_enabled(str(env), False)
    state = sr.status(str(game_dir), env_path=str(env))
    assert state["enabled"] is False
    assert state["loader_installed"] is True


def test_status_lista_os_mods_e_o_fim_do_log(game):
    game_dir, env = game
    sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    (game_dir / "mods" / "flight.dll").write_bytes(b"MZ")
    (game_dir / "mods" / "basics_mod").mkdir()
    (game_dir / "mods" / "leia-me.txt").write_text("x", encoding="utf-8")
    lines = [f"linha {i}" for i in range(40)] + ["(basics) class NoResourceCostAddress not found"]
    (game_dir / "shroudtopia.log").write_text("\n".join(lines), encoding="utf-8")
    state = sr.status(str(game_dir), env_path=str(env))
    assert [m["name"] for m in state["mods"]] == ["basics_mod", "flight.dll"]
    assert len(state["log"]) == sr.LOG_TAIL
    assert state["log"][-1].endswith("not found")


def test_download_so_de_github(game):
    """The link comes from the API response: an asset pointing to another host is refused."""
    game_dir, env = game
    bad = {"tag_name": "x", "assets": [{"name": "Shroudtopia-9.zip",
                                        "browser_download_url": "https://evil.example/s.zip"}]}
    with pytest.raises(ValueError):
        sr.install_loader(str(game_dir), fetcher=lambda u: json.dumps(bad).encode(), env_path=str(env))


def test_zip_sem_o_carregador_e_recusado(game):
    game_dir, env = game
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.md", "nada")
    with pytest.raises(ValueError, match=r"winmm.dll"):
        sr.install_loader(str(game_dir), env_path=str(env),
                          fetcher=lambda u: json.dumps(RELEASE).encode() if u == sr.RELEASES else buf.getvalue())


# ------------------------------------------------------------------ chosen version

OLD_RELEASE = {"tag_name": "v0.1.0", "assets": [{
    "name": "Shroudtopia-0.1.0.zip",
    "browser_download_url": "https://github.com/s0t7x/shroudtopia/releases/download/v0.1.0/Shroudtopia-0.1.0.zip",
}]}


def tagged_fetcher(url: str) -> bytes:
    """Fake GitHub with 0.1.1 without "v" in the tag and 0.1.0 with it: the author was not consistent."""
    if url == sr.RELEASE_TAG.format(tag="0.1.1"):
        return json.dumps(RELEASE).encode()
    if url == sr.RELEASE_TAG.format(tag="v0.1.0"):
        return json.dumps(OLD_RELEASE).encode()
    if url.startswith("https://api.github.com/"):
        raise OSError(f"404 {url}")
    return fetcher(url)


@pytest.mark.parametrize(("version", "tag"), [("0.1.1", "0.1.1"), ("0.1.0", "v0.1.0")])
def test_versao_escolhida_acha_a_tag_com_ou_sem_v(game, version, tag):
    game_dir, env = game
    result = sr.install_loader(str(game_dir), fetcher=tagged_fetcher, env_path=str(env), version=version)
    assert result["version"] == tag
    st = sr.status(str(game_dir), env_path=str(env))
    assert (st["loader_version"], st["loader_pinned"]) == (tag, True)


def test_sem_versao_e_a_mais_recente_e_nao_fixa(game):
    game_dir, env = game
    sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    assert not sr.status(str(game_dir), env_path=str(env))["loader_pinned"]


def test_versao_que_nao_existe_falha_sem_tocar_no_jogo(game):
    game_dir, env = game
    with pytest.raises(ValueError, match="nao tem a versao"):
        sr.install_loader(str(game_dir), fetcher=tagged_fetcher, env_path=str(env), version="9.9.9")
    assert not (game_dir / "winmm.dll").exists()


@pytest.mark.parametrize("bad", ["latest", "0.1", "../0.1.1", "0.1.1/x"])
def test_versao_invalida_nao_vira_url(game, bad):
    game_dir, env = game
    with pytest.raises(ValueError, match="versao invalida"):
        sr.install_loader(str(game_dir), fetcher=tagged_fetcher, env_path=str(env), version=bad)


def test_desinstalar_tira_o_carregador_os_mods_dele_e_o_winmm(game):
    game_dir, env = game
    (game_dir / "enshrouded_server.exe").write_bytes(b"jogo")
    sr.install_loader(str(game_dir), fetcher=fetcher, env_path=str(env))
    (game_dir / "mods" / "MeuMod.dll").write_bytes(b"mod")
    sr.uninstall_loader(str(game_dir), env_path=str(env))
    assert sorted(p.name for p in game_dir.iterdir()) == ["enshrouded_server.exe"]
    assert "winmm=n,b" not in env.read_text(encoding="utf-8")
