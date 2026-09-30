"""O instalador do Thunderstore que roda DENTRO do CT, exercitado aqui com zips de mentira
no formato dos pacotes reais (BepInExPack_V_Rising e VampireCommandFramework)."""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from gamepanel.games.mods import thunderstore_remote as ts


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


LOADER_ZIP = _zip({
    "icon.png": b"png", "README.md": b"leia", "manifest.json": b"{}",
    "BepInExPack_V_Rising/winhttp.dll": b"dll",
    "BepInExPack_V_Rising/doorstop_config.ini": b"[General]\nenabled = false\ntarget_assembly = x\n",
    "BepInExPack_V_Rising/BepInEx/core/BepInEx.Core.dll": b"core",
    "BepInExPack_V_Rising/dotnet/coreclr.dll": b"clr",
})
VCF_ZIP = _zip({"icon.png": b"png", "manifest.json": b"{}", "VampireCommandFramework.dll": b"vcf"})
KIT_ZIP = _zip({
    "manifest.json": b"{}", "plugins/KindredCommands.dll": b"kc",
    "config/KindredCommands.cfg": b"padrao",
    "../../../etc/passwd": b"invasor", "/root/.ssh/authorized_keys": b"invasor",
})

def _meta(full_name: str, deps: list[str], url: str) -> dict:
    _ns, name, version = full_name.split("-")
    return {"full_name": full_name, "name": name, "version_number": version,
            "dependencies": deps, "download_url": url}


LOADER = "BepInEx-BepInExPack_V_Rising-1.733.2"
VCF = "deca-VampireCommandFramework-0.11.0"
PACKAGES = {
    ("BepInEx", "BepInExPack_V_Rising"): (_meta(LOADER, [], "https://x/loader"), LOADER_ZIP),
    ("deca", "VampireCommandFramework"): (_meta(VCF, [LOADER], "https://x/vcf"), VCF_ZIP),
    ("odjit", "KindredCommands"): (_meta("odjit-KindredCommands-2.1.0", [LOADER, VCF], "https://x/kc"), KIT_ZIP),
}


def fake_fetch(url: str) -> bytes:
    for (ns, name), (meta, data) in PACKAGES.items():
        if url == ts.API.format(ns=ns, name=name):
            return json.dumps({"latest": meta}).encode()
        if url == meta["download_url"]:
            return data
    raise OSError(f"404 {url}")


@pytest.fixture
def game(tmp_path):
    env = tmp_path / "game-runtime.env"
    env.write_text("RUNTIME='proton'\nWINE_DLL_OVERRIDES='mscoree,mshtml='\nUSE_XVFB='1'\n", encoding="utf-8")
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    return str(game_dir), str(env)


def test_overrides_liga_o_winhttp_e_religa_o_mscoree():
    """Medido: com mscoree desligado o Wine recusava toda DLL .NET do BepInEx."""
    assert ts.fix_overrides("mscoree,mshtml=") == "mshtml=;winhttp=n,b"
    assert ts.fix_overrides("mscoree=") == "winhttp=n,b"
    assert ts.fix_overrides("mscoree,mshtml=;steam.exe=b") == "mshtml=;steam.exe=b;winhttp=n,b"


def test_overrides_e_idempotente():
    once = ts.fix_overrides("mscoree,mshtml=")
    assert ts.fix_overrides(once) == once
    assert ts.overrides_ok(once)
    assert not ts.overrides_ok("mscoree,mshtml=")


def test_carregador_vai_para_a_raiz_do_jogo_ligado_e_sem_console(game):
    game_dir, env = game
    result = ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    assert result["files"] == 4
    assert os.path.exists(os.path.join(game_dir, "winhttp.dll"))
    assert os.path.exists(os.path.join(game_dir, "BepInEx", "core", "BepInEx.Core.dll"))
    assert not os.path.exists(os.path.join(game_dir, "icon.png"))
    assert "enabled = true" in Path(os.path.join(game_dir, "doorstop_config.ini")).read_text()
    # Medido: o console ligado travava o servidor sob o X virtual.
    cfg = Path(os.path.join(game_dir, "BepInEx", "config", "BepInEx.cfg")).read_text()
    assert "[Logging.Console]\nEnabled = false" in cfg
    assert "WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'" in Path(env).read_text()
    assert "RUNTIME='proton'" in Path(env).read_text(), "o resto do arquivo nao pode mudar"


def test_console_desligado_mesmo_com_o_cfg_que_o_bepinex_ja_gerou(game, tmp_path):
    game_dir, env = game
    cfg = os.path.join(game_dir, "BepInEx", "config", "BepInEx.cfg")
    os.makedirs(os.path.dirname(cfg))
    Path(cfg).write_text("[Logging.Console]\n\n## liga o console\n# Setting type: Boolean\n"
                         "Enabled = true\n\n[Logging.Disk]\nEnabled = true\n")
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    text = Path(cfg).read_text()
    assert "[Logging.Console]\n\n## liga o console\n# Setting type: Boolean\nEnabled = false" in text
    assert "[Logging.Disk]\nEnabled = true" in text, "so o console muda"


def test_plugin_traz_as_dependencias_menos_o_proprio_bepinex(game):
    game_dir, _ = game
    result = ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch)
    assert [p["full_name"] for p in result["installed"]] == [
        "odjit-KindredCommands-2.1.0", "deca-VampireCommandFramework-0.11.0"]
    plugins = os.path.join(game_dir, "BepInEx", "plugins")
    assert sorted(os.listdir(plugins)) == ["deca-VampireCommandFramework", "odjit-KindredCommands"]
    assert os.path.exists(os.path.join(plugins, "odjit-KindredCommands", "KindredCommands.dll"))
    assert os.path.exists(os.path.join(game_dir, "BepInEx", "config", "KindredCommands.cfg"))


def test_zip_com_caminho_para_fora_nao_escreve_fora(game, tmp_path):
    game_dir, _ = game
    ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch)
    written = [os.path.join(r, f) for r, _, fs in os.walk(tmp_path) for f in fs]
    assert all(w.startswith(game_dir) or w.endswith("game-runtime.env") for w in written), written


def test_config_que_ja_existe_nao_e_sobrescrita(game):
    game_dir, _ = game
    cfg = os.path.join(game_dir, "BepInEx", "config", "KindredCommands.cfg")
    os.makedirs(os.path.dirname(cfg))
    Path(cfg).write_text("do dono do servidor")
    ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch)
    assert Path(cfg).read_text() == "do dono do servidor"


def test_status_mostra_carregador_plugins_e_ajuste_do_wine(game):
    game_dir, env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    st = ts.status(game_dir, env_path=env)
    assert st["loader_installed"] and st["enabled"] and st["overrides_ok"]
    assert st["loader"] == "BepInEx-BepInExPack_V_Rising-1.733.2"
    assert [(p["dir"], p["version"]) for p in st["plugins"]] == [("deca-VampireCommandFramework", "0.11.0")]


def test_redeploy_que_reescreve_o_runtime_aparece_no_status(game):
    game_dir, env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    Path(env).write_text("WINE_DLL_OVERRIDES='mscoree,mshtml='\n")
    assert not ts.status(game_dir, env_path=env)["overrides_ok"]


def test_desligar_e_religar(game):
    game_dir, env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    ts.set_enabled(game_dir, False)
    assert not ts.status(game_dir, env_path=env)["enabled"]
    ts.set_enabled(game_dir, True)
    assert ts.status(game_dir, env_path=env)["enabled"]


def test_remover_plugin(game):
    game_dir, _ = game
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    assert ts.remove_plugin(game_dir, "deca", "VampireCommandFramework") == {"removed": True}
    assert ts.status(game_dir)["plugins"] == []


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 65, "nome com espaco", "a;rm"])
def test_nome_invalido_e_recusado_antes_de_virar_caminho_ou_url(game, bad):
    game_dir, _ = game
    with pytest.raises(ValueError):
        ts.install_plugin(game_dir, bad, "VampireCommandFramework", fake_fetch)
    with pytest.raises(ValueError):
        ts.remove_plugin(game_dir, "deca", bad)


def test_main_termina_com_uma_linha_json(game, capsys, monkeypatch):
    game_dir, env = game
    monkeypatch.setattr(ts, "RUNTIME_ENV", env)
    assert ts.main(["status", game_dir, "BepInEx", "BepInExPack_V_Rising"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(last)["loader_installed"] is False
    assert ts.main(["plugin-remove", game_dir, "BepInEx", "BepInExPack_V_Rising", "../x", "y"]) == 1
    assert "error" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])
