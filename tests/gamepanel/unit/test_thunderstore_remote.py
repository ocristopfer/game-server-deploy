"""The Thunderstore installer that runs INSIDE the CT, exercised here with fake zips in the
format of the real packages (BepInExPack_V_Rising and VampireCommandFramework)."""
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


# Old versions, served only by the API's version route: the newest is still the one in PACKAGES.
VCF_OLD = "deca-VampireCommandFramework-0.10.4"
KC_OLD = "odjit-KindredCommands-2.0.0"
LOADER_OLD = "BepInEx-BepInExPack_V_Rising-1.691.3"
OLD_VCF_ZIP = _zip({"VampireCommandFramework.dll": b"vcf-velho"})
VERSIONS = {
    ("deca", "VampireCommandFramework", "0.10.4"): (_meta(VCF_OLD, [LOADER], "https://x/vcf-old"), OLD_VCF_ZIP),
    ("odjit", "KindredCommands", "2.0.0"): (_meta(KC_OLD, [LOADER, VCF_OLD], "https://x/kc-old"), KIT_ZIP),
    ("BepInEx", "BepInExPack_V_Rising", "1.691.3"): (_meta(LOADER_OLD, [], "https://x/loader-old"), LOADER_ZIP),
}
for (_ns, _name), (_m, _d) in PACKAGES.items():
    VERSIONS[(_ns, _name, _m["version_number"])] = (_m, _d)


def fake_fetch(url: str) -> bytes:
    for (ns, name), (meta, _data) in PACKAGES.items():
        if url == ts.API.format(ns=ns, name=name):
            return json.dumps({"latest": meta}).encode()
    for (ns, name, version), (meta, data) in VERSIONS.items():
        if url == ts.API_VERSION.format(ns=ns, name=name, version=version):
            return json.dumps(meta).encode()
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
    """Measured: with mscoree disabled, Wine rejected every .NET DLL of BepInEx."""
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
    # Measured: the console turned on froze the server under the virtual X.
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


# ------------------------------------------------------------------ chosen version

def test_sem_versao_continua_a_mais_nova_e_nao_fixa(game):
    game_dir, env = game
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    [plugin] = ts.status(game_dir, env_path=env)["plugins"]
    assert (plugin["version"], plugin["pinned"]) == ("0.11.0", False)


def test_versao_fixada_traz_as_dependencias_na_versao_que_ela_pede(game):
    """Whoever pins 2.0.0 wants the set the author tested, not the newest dependency."""
    game_dir, env = game
    result = ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch, version="2.0.0")
    assert [p["full_name"] for p in result["installed"]] == [KC_OLD, VCF_OLD]
    st = {p["dir"]: p for p in ts.status(game_dir, env_path=env)["plugins"]}
    assert st["deca-VampireCommandFramework"]["version"] == "0.10.4"
    assert all(p["pinned"] for p in st.values())


def test_trocar_a_versao_de_um_mod_ja_instalado_substitui_por_inteiro(game):
    """The server already running 0.11.0 goes back to 0.10.4 with no file left over from the other."""
    game_dir, env = game
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch, version="0.10.4")
    dll = Path(game_dir, "BepInEx", "plugins", "deca-VampireCommandFramework", "VampireCommandFramework.dll")
    assert dll.read_bytes() == b"vcf-velho"
    # And back to the newest, with no version.
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    assert dll.read_bytes() == b"vcf"
    assert not ts.status(game_dir, env_path=env)["plugins"][0]["pinned"]


def test_versao_que_nao_existe_falha_sem_instalar_nada(game):
    game_dir, _ = game
    with pytest.raises(OSError):
        ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch, version="9.9.9")
    assert not os.path.exists(os.path.join(game_dir, "BepInEx", "plugins"))


def test_api_que_devolve_outra_versao_e_recusada(game):
    """Asked for 0.10.4 and got 0.11.0: installing anyway would lie on the screen."""
    game_dir, _ = game

    def wrong(url):
        if url == ts.API_VERSION.format(ns="deca", name="VampireCommandFramework", version="0.10.4"):
            return json.dumps(PACKAGES[("deca", "VampireCommandFramework")][0]).encode()
        return fake_fetch(url)
    with pytest.raises(ValueError, match="nao tem"):
        ts.install_plugin(game_dir, "deca", "VampireCommandFramework", wrong, version="0.10.4")


@pytest.mark.parametrize("bad", ["latest", "1.2", "../1.2.3", "1.2.3/x", "1.2.3;rm"])
def test_versao_invalida_nao_vira_url(game, bad):
    game_dir, env = game
    with pytest.raises(ValueError):
        ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch, version=bad)
    with pytest.raises(ValueError):
        ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env, version=bad)


def test_carregador_em_versao_escolhida(game):
    game_dir, env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env, version="1.691.3")
    st = ts.status(game_dir, env_path=env)
    assert (st["loader"], st["loader_pinned"]) == (LOADER_OLD, True)


def test_main_passa_a_versao_adiante(game, capsys, monkeypatch):
    game_dir, _ = game
    calls: list = []
    monkeypatch.setattr(ts, "install_plugin", lambda *a, **kw: calls.append((a, kw)) or {"installed": []})
    monkeypatch.setattr(ts, "install_loader", lambda *a, **kw: calls.append((a, kw)) or {})
    monkeypatch.setattr(ts, "_chown", lambda path: None)
    scan, base = ["--scan", "true"], [game_dir, "BepInEx", "BepInExPack_V_Rising"]
    assert ts.main([*scan, "plugin-install", *base, "deca", "VampireCommandFramework", "0.10.4"]) == 0
    assert ts.main([*scan, "plugin-install", *base, "deca", "VampireCommandFramework"]) == 0
    assert ts.main([*scan, "loader-install", *base, "1.691.3"]) == 0
    assert ts.main([*scan, "loader-install", *base]) == 0
    assert [kw["version"] for _, kw in calls] == ["0.10.4", "", "1.691.3", ""]


# ------------------------------------------------------------------ antivirus

def test_verifica_o_pacote_e_as_dependencias_de_uma_vez_antes_de_gravar(game):
    game_dir, _ = game
    seen: list = []
    ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch, scan=lambda blobs: seen.append(blobs))
    assert len(seen) == 1, "uma verificacao so, com tudo"
    assert [name for name, _ in seen[0]] == ["odjit-KindredCommands-2.1.0", "deca-VampireCommandFramework-0.11.0"]


def test_dependencia_recusada_nao_deixa_nada_instalado(game):
    """Writing the main mod and rejecting the dependency would leave a half-installed mod."""
    game_dir, _ = game

    def refuse(blobs):
        if any(b"vcf" in data for _, data in blobs):
            raise ValueError("o antivirus recusou o pacote: nada foi instalado")
    with pytest.raises(ValueError, match="antivirus"):
        ts.install_plugin(game_dir, "odjit", "KindredCommands", fake_fetch, scan=refuse)
    assert not os.path.exists(os.path.join(game_dir, "BepInEx"))


def test_carregador_recusado_nao_toca_no_jogo_nem_no_wine(game):
    game_dir, env = game

    def refuse(blobs):
        raise ValueError("o antivirus recusou o pacote: nada foi instalado")
    with pytest.raises(ValueError):
        ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env, scan=refuse)
    assert os.listdir(game_dir) == []
    assert "mscoree,mshtml=" in Path(env).read_text()


# ------------------------------------------------------------------ native Linux (Valheim)

def test_linux_nativo_liga_o_bepinex_por_drop_in_e_nao_mexe_no_wine(tmp_path, monkeypatch):
    """The variables are those of BepInExPack_Valheim's start_server_bepinex.sh, with absolute paths."""
    reloads: list[int] = []
    monkeypatch.setattr(ts, "SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr(ts, "_daemon_reload", lambda: reloads.append(1))
    ts.set_linux_enabled("/opt/game", "valheim.service", True)
    text = (tmp_path / "systemd" / "valheim.service.d" / "gamepanel-bepinex.conf").read_text(encoding="utf-8")
    assert "Environment=DOORSTOP_ENABLED=1" in text
    assert "Environment=DOORSTOP_TARGET_ASSEMBLY=/opt/game/BepInEx/core/BepInEx.Preloader.dll" in text
    assert "Environment=LD_PRELOAD=/opt/game/doorstop_libs/libdoorstop_x64.so" in text
    assert ts.status(str(tmp_path), unit="valheim.service")["enabled"] is True
    ts.set_linux_enabled("/opt/game", "valheim.service", False)
    assert ts.status(str(tmp_path), unit="valheim.service")["enabled"] is False
    # Without daemon-reload, systemd keeps the old environment.
    assert reloads == [1, 1]


@pytest.mark.parametrize("unit", ["", "x", "../etc.service", "a b.service", "valheim"])
def test_servico_do_drop_in_e_conferido(unit):
    with pytest.raises(ValueError):
        ts.dropin_path(unit)


# ------------------------------------------------------------------ uninstall

def test_desinstalar_tira_so_o_que_o_pacote_criou_e_devolve_o_wine(game):
    game_dir, env = game
    # From the game: it existed before, it must not go (nor the game's own dotnet, if it has one).
    Path(game_dir, "VRisingServer.exe").write_bytes(b"jogo")
    Path(game_dir, "dotnet").mkdir()
    Path(game_dir, "dotnet", "do-jogo.dll").write_bytes(b"jogo")
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    ts.install_plugin(game_dir, "deca", "VampireCommandFramework", fake_fetch)
    result = ts.uninstall_loader(game_dir, env_path=env)
    assert sorted(result["removed"]) == ["BepInEx", "doorstop_config.ini", "winhttp.dll"]
    assert not Path(game_dir, "BepInEx").exists()  # the plugins live there and go along
    assert Path(game_dir, "VRisingServer.exe").read_bytes() == b"jogo"
    assert Path(game_dir, "dotnet", "do-jogo.dll").exists()
    # WINE_DLL_OVERRIDES goes back to what it was (with mscoree disabled, as the game's .env set it).
    assert "WINE_DLL_OVERRIDES='mscoree,mshtml='" in Path(env).read_text()
    assert "RUNTIME='proton'" in Path(env).read_text()


def test_desinstalar_instalacao_antiga_sem_lista_usa_os_nomes_do_bepinex(game):
    game_dir, env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=env)
    mark = Path(game_dir, "BepInEx", ts.MARK)
    mark.write_text(json.dumps({"full_name": LOADER, "version": "1.733.2"}), encoding="utf-8")
    Path(game_dir, "VRisingServer.exe").write_bytes(b"jogo")
    ts.uninstall_loader(game_dir, env_path=env)
    assert not Path(game_dir, "BepInEx").exists()
    assert not Path(game_dir, "winhttp.dll").exists()
    assert Path(game_dir, "VRisingServer.exe").exists()
    # With no previous value recorded, only winhttp goes.
    assert "WINE_DLL_OVERRIDES='mshtml='" in Path(env).read_text()


def test_marca_com_caminho_nao_apaga_fora_da_raiz(game, tmp_path):
    game_dir, env = game
    outside = tmp_path / "fora.txt"
    outside.write_text("fica", encoding="utf-8")
    Path(game_dir, "BepInEx").mkdir()
    Path(game_dir, "BepInEx", ts.MARK).write_text(json.dumps({"files": ["../fora.txt", "/etc", ".."]}),
                                                   encoding="utf-8")
    ts.uninstall_loader(game_dir, env_path=env)
    assert outside.read_text(encoding="utf-8") == "fica"


def test_desinstalar_no_linux_apaga_o_drop_in(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr(ts, "_daemon_reload", lambda: None)
    game_dir = tmp_path / "valheim"
    game_dir.mkdir()
    ts.install_loader(str(game_dir), "BepInEx", "BepInExPack_V_Rising", fake_fetch,
                      env_path=str(tmp_path / "nao-existe.env"), unit="valheim.service")
    assert ts.status(str(game_dir), unit="valheim.service")["enabled"] is True
    ts.uninstall_loader(str(game_dir), env_path=str(tmp_path / "nao-existe.env"), unit="valheim.service")
    assert ts.status(str(game_dir), unit="valheim.service")["enabled"] is False
    assert not (game_dir / "BepInEx").exists()


def test_main_desinstala(game, capsys):
    game_dir, _env = game
    ts.install_loader(game_dir, "BepInEx", "BepInExPack_V_Rising", fake_fetch, env_path=_env)
    assert ts.main(["loader-uninstall", game_dir, "BepInEx", "BepInExPack_V_Rising"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["uninstalled"] is True
