"""Phase 6: the mod installers in helper mode write steam's overlay, never root's files.

On a server where the panel logs in without root (helper mode) the installers run as steam with
`--overlay`. Whatever a loader needs in the game's environment goes to two files steam owns in a
folder root owns (/etc/gamepanel/game-env, prepared by lib/ct-panel-access.sh): service.env, read
by the game unit through EnvironmentFile=, and runtime.env, read by win-run after
/etc/game-runtime.env. These tests point the overlay at a temporary folder and check what each
installer writes there - and that the root files stay untouched.
"""
from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

import pytest

from gamepanel.games.mods import (
    shroudtopia_remote,
    thunderstore_remote,
    ue4ss_linux_remote,
    ue4ss_remote,
    workshop_remote,
)

REPO = Path(__file__).resolve().parents[3]
OVERLAY_USERS = (thunderstore_remote, shroudtopia_remote, ue4ss_remote, ue4ss_linux_remote, workshop_remote)
BLOCK = re.compile(r"# -+ steam overlay \(helper mode\)\n.*?# -+ end of the steam overlay\n", re.S)


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """A prepared CT: both overlay files, the unit's env drop-in and a win-run with the hook."""
    env_dir = tmp_path / "game-env"
    env_dir.mkdir()
    for name in ("service.env", "runtime.env"):
        (env_dir / name).write_text("# Escrito pelo painel\n", encoding="utf-8")
    systemd = tmp_path / "systemd"
    for unit in ("palworld.service", "valheim.service"):
        (systemd / f"{unit}.d").mkdir(parents=True)
        (systemd / f"{unit}.d" / "gamepanel-env.conf").write_text("[Service]\n", encoding="utf-8")
    win_run = tmp_path / "win-run"
    win_run.write_text("#!/bin/bash\n# gamepanel-overlay: ...\n", encoding="utf-8")
    for module in OVERLAY_USERS:
        monkeypatch.setattr(module, "OVERLAY_DIR", str(env_dir))
        monkeypatch.setattr(module, "OVERLAY_SYSTEMD_DIR", str(systemd))
        monkeypatch.setattr(module, "OVERLAY_WIN_RUN", str(win_run))
    return {"dir": env_dir, "systemd": systemd, "win_run": win_run, "tmp": tmp_path}


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]


def _base_env(tmp_path: Path, overrides: str) -> str:
    env = tmp_path / "game-runtime.env"
    env.write_text(f"RUNTIME='proton'\nWINE_DLL_OVERRIDES='{overrides}'\n", encoding="utf-8")
    return str(env)


# ------------------------------------------------------------------ the shared block

def test_o_bloco_do_overlay_e_identico_em_todos_os_instaladores():
    """They run standalone in the CT and do not import each other: the copy has to be identical."""
    blocks = {m.__name__: BLOCK.search(inspect.getsource(m)) for m in OVERLAY_USERS}
    assert all(blocks.values()), [n for n, b in blocks.items() if not b]
    texts = {b.group(0) for b in blocks.values() if b}
    assert len(texts) == 1


def test_overlay_set_troca_no_lugar_remove_e_mantem_comentario(overlay):
    m = thunderstore_remote
    m.overlay_set("service.env", "LD_PRELOAD", "/a.so")
    m.overlay_set("service.env", "X_Y", "1")
    m.overlay_set("service.env", "LD_PRELOAD", "/b.so")
    text = (overlay["dir"] / "service.env").read_text(encoding="utf-8")
    assert text == "# Escrito pelo painel\nLD_PRELOAD='/b.so'\nX_Y='1'\n"
    assert m.overlay_get("service.env", "LD_PRELOAD") == "/b.so"
    m.overlay_set("service.env", "LD_PRELOAD", None)
    assert m.overlay_get("service.env", "LD_PRELOAD") is None
    assert _lines(overlay["dir"] / "service.env") == ["X_Y='1'"]


@pytest.mark.parametrize("value", ["a'b", "$(id)", "`id`", "a\nb", 'x"y', "a\\b"])
def test_overlay_recusa_valor_que_escaparia_das_aspas(overlay, value):
    with pytest.raises(ValueError, match="invalido"):
        thunderstore_remote.overlay_set("runtime.env", "WINE_DLL_OVERRIDES", value)


def test_overlay_nao_cria_o_arquivo_que_falta(overlay):
    """steam cannot create files in the folder (root's): a missing file means an unprepared CT."""
    (overlay["dir"] / "runtime.env").unlink()
    with pytest.raises(ValueError, match="migrate-ct"):
        shroudtopia_remote.overlay_set("runtime.env", "WINE_DLL_OVERRIDES", "winmm=n,b")
    assert not (overlay["dir"] / "runtime.env").exists()


# ------------------------------------------------------------------ Wine loaders

@pytest.mark.parametrize(("module", "group"), [(shroudtopia_remote, "winmm=n,b"), (ue4ss_remote, "dwmapi=n,b")])
def test_carregador_do_wine_liga_e_desliga_pelo_overlay_sem_tocar_na_base(overlay, module, group):
    env = _base_env(overlay["tmp"], "mscoree,mshtml=")
    before = Path(env).read_text(encoding="utf-8")
    module.set_enabled(env, True, overlay=True)
    assert Path(env).read_text(encoding="utf-8") == before, "a base e do root: o steam nao escreve la"
    assert _lines(overlay["dir"] / "runtime.env") == [f"WINE_DLL_OVERRIDES='mscoree,mshtml=;{group}'"]
    assert module.is_enabled(env, overlay=True)
    assert not module.is_enabled(env), "o modo root continua lendo so a base"
    module.set_enabled(env, False, overlay=True)
    # Back to the base value: the overlay has no line, and /etc/game-runtime.env is in charge again.
    assert _lines(overlay["dir"] / "runtime.env") == []
    assert not module.is_enabled(env, overlay=True)


def test_shroudtopia_convertido_desliga_mesmo_com_o_grupo_na_base(overlay):
    """A CT whose base still has winmm=n,b (written as root, never converted) can still be turned
    off: the overlay sets the whole value, and win-run reads it after the base."""
    env = _base_env(overlay["tmp"], "mscoree,mshtml=;winmm=n,b")
    shroudtopia_remote.set_enabled(env, False, overlay=True)
    assert _lines(overlay["dir"] / "runtime.env") == ["WINE_DLL_OVERRIDES='mscoree,mshtml='"]
    assert not shroudtopia_remote.is_enabled(env, overlay=True)


def test_carregador_do_wine_recusa_win_run_sem_o_gancho(overlay):
    env = _base_env(overlay["tmp"], "mscoree,mshtml=")
    overlay["win_run"].write_text("#!/bin/bash\n. /etc/game-runtime.env\n", encoding="utf-8")
    assert "win-run" in shroudtopia_remote.overlay_problem(env)
    assert shroudtopia_remote.status(str(overlay["tmp"]), env, overlay=True)["overlay_problem"]
    assert shroudtopia_remote.status(str(overlay["tmp"]), env)["overlay_problem"] == ""


def test_bepinex_do_proton_no_overlay_e_a_volta_ao_original(overlay):
    env = _base_env(overlay["tmp"], "mscoree,mshtml=")
    ts = thunderstore_remote
    old = ts.effective_overrides(env, True)
    ts.store_overrides(env, True, ts.fix_overrides(old))
    assert _lines(overlay["dir"] / "runtime.env") == ["WINE_DLL_OVERRIDES='mshtml=;winhttp=n,b'"]
    assert ts.overrides_ok(ts.effective_overrides(env, True))
    # Uninstall with the original recorded in the mark: the overlay line goes, the base was never touched.
    game_dir = overlay["tmp"] / "game"
    (game_dir / "BepInEx").mkdir(parents=True)
    (game_dir / "BepInEx" / ts.MARK).write_text('{"overrides_before": "mscoree,mshtml="}', encoding="utf-8")
    ts.uninstall_loader(str(game_dir), env_path=env, overlay=True)
    assert _lines(overlay["dir"] / "runtime.env") == []
    assert "WINE_DLL_OVERRIDES='mscoree,mshtml='" in Path(env).read_text(encoding="utf-8")


# ------------------------------------------------------------------ native Linux loaders

def test_bepinex_linux_no_overlay_escreve_as_variaveis_do_doorstop(overlay, monkeypatch):
    ts = thunderstore_remote
    monkeypatch.setattr(ts, "SYSTEMD_DIR", str(overlay["systemd"]))
    monkeypatch.setattr(ts, "_daemon_reload", lambda: pytest.fail("o overlay nao precisa de daemon-reload"))
    ts.set_linux_enabled("/opt/game", "valheim.service", True, overlay=True)
    assert _lines(overlay["dir"] / "service.env") == [
        "DOORSTOP_ENABLED='1'",
        "DOORSTOP_TARGET_ASSEMBLY='/opt/game/BepInEx/core/BepInEx.Preloader.dll'",
        "LD_LIBRARY_PATH='/opt/game/doorstop_libs:/opt/game/linux64'",
        "LD_PRELOAD='/opt/game/doorstop_libs/libdoorstop_x64.so'",
    ]
    assert not os.path.exists(ts.dropin_path("valheim.service", str(overlay["systemd"])))
    ts.set_linux_enabled("/opt/game", "valheim.service", False, overlay=True)
    assert _lines(overlay["dir"] / "service.env") == []


def test_drop_in_do_modo_root_continua_byte_a_byte():
    assert thunderstore_remote.dropin_text("/opt/game") == (
        "[Service]\n"
        "Environment=DOORSTOP_ENABLED=1\n"
        "Environment=DOORSTOP_TARGET_ASSEMBLY=/opt/game/BepInEx/core/BepInEx.Preloader.dll\n"
        "Environment=LD_LIBRARY_PATH=/opt/game/doorstop_libs:/opt/game/linux64\n"
        "Environment=LD_PRELOAD=/opt/game/doorstop_libs/libdoorstop_x64.so\n")


def test_ue4ss_linux_no_overlay_liga_desliga_e_nomeia_o_executavel(overlay, monkeypatch):
    ul = ue4ss_linux_remote
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(overlay["systemd"]))
    monkeypatch.setattr(ul, "_daemon_reload", lambda: pytest.fail("o overlay nao precisa de daemon-reload"))
    exe_dir = "/opt/game/TheFront/Binaries/Linux"
    ul.set_enabled(exe_dir, "palworld.service", True, "TheFrontServer", overlay=True)
    assert _lines(overlay["dir"] / "service.env") == [
        f"LD_PRELOAD='{exe_dir}/ue4ss/libUE4SS.so'", "UE4SS_TARGET_EXE='TheFrontServer'"]
    assert ul.status(str(overlay["tmp"]), "palworld.service", overlay=True)["overlay_problem"] == ""
    ul.set_enabled(exe_dir, "palworld.service", False, overlay=True)
    assert _lines(overlay["dir"] / "service.env") == []
    assert not (overlay["systemd"] / "palworld.service.d" / ul.DROPIN).exists()


def test_ue4ss_linux_status_le_o_overlay(overlay, monkeypatch):
    ul = ue4ss_linux_remote
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(overlay["systemd"]))
    exe_dir = str(overlay["tmp"]).replace("\\", "/")
    ul.overlay_set("service.env", "LD_PRELOAD", "/x/ue4ss/libUE4SS.so")
    assert not ul.status(exe_dir, "palworld.service", overlay=True)["enabled"]


def test_drop_in_antigo_do_root_e_um_problema_no_modo_helper(overlay, monkeypatch):
    """The root installer's drop-in, left behind on a CT migrated before phase 6: steam cannot
    remove it, so turning the loader off from the screen would only LOOK like it worked."""
    ul = ue4ss_linux_remote
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(overlay["systemd"]))
    (overlay["systemd"] / "palworld.service.d" / ul.DROPIN).write_text("[Service]\n", encoding="utf-8")
    assert "como root" in ul.overlay_problem("palworld.service")
    assert ul.main(["--overlay", "--unit", "palworld.service", "loader-disable", "/opt/x"]) == 1


def test_servico_que_nao_le_o_overlay_e_um_problema(overlay, monkeypatch):
    ul = ue4ss_linux_remote
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(overlay["systemd"]))
    assert "nao le o ambiente" in ul.overlay_problem("outro.service")


# ------------------------------------------------------------------ ARK

def _ark_ctx(tmp_path: Path, exec_start: str) -> dict:
    return {"unit": "ark.service", "game_dir": str(tmp_path), "overlay": True,
            "unit_text": f"# /etc/systemd/system/ark.service\n[Service]\nExecStart={exec_start}\n"}


def test_lista_do_ark_no_modo_helper_vira_argumento_do_win_run(overlay):
    ctx = _ark_ctx(overlay["tmp"], "/usr/local/bin/win-run /opt/game/ArkAscendedServer.exe TheIsland_WP")
    workshop_remote.ark_set(ctx, ["928988", "929420"])
    assert _lines(overlay["dir"] / "runtime.env") == ["GAMEPANEL_EXTRA_ARGS='-mods=928988,929420'"]
    status = workshop_remote.ark_status(ctx)
    assert status["ids"] == ["928988", "929420"] and status["problem"] == ""
    workshop_remote.ark_set(ctx, [])
    assert _lines(overlay["dir"] / "runtime.env") == []


def test_ark_que_nao_passa_pelo_win_run_e_recusado_no_modo_helper(overlay):
    ctx = _ark_ctx(overlay["tmp"], "/opt/game/start-ark.sh")
    assert workshop_remote.ark_status(ctx)["problem"] == "no_win_run"
    with pytest.raises(ValueError, match="no_win_run"):
        workshop_remote.ark_set(ctx, ["928988"])


# ------------------------------------------------------------------ the root side, as text

def _bash_function(name: str) -> str:
    text = (REPO / "lib" / "ct-panel-access.sh").read_text(encoding="utf-8")
    found = re.search(rf"^{name}\(\) {{\n  cat <<'EOF'\n(.*?)^EOF\n}}", text, re.S | re.M)
    assert found, name
    return found.group(1)


def test_win_run_novo_e_o_migrado_tem_o_mesmo_gancho():
    """ct-phases.sh writes win-run for a new CT; ct-panel-access.sh inserts the hook into an old one.
    The two texts are one decision: a CT must read runtime.env the same way whichever way it came."""
    hook = _bash_function("gp_render_win_run_hook")
    phases = (REPO / "lib" / "ct-phases.sh").read_text(encoding="utf-8")
    assert 'exe="$1"; shift\n' + hook in phases
    assert ue4ss_remote.OVERLAY_HOOK in hook
    assert f"{ue4ss_remote.OVERLAY_DIR}/{ue4ss_remote.OVERLAY_RUNTIME}" in hook


def test_os_caminhos_do_overlay_sao_os_mesmos_dos_dois_lados():
    text = (REPO / "lib" / "ct-panel-access.sh").read_text(encoding="utf-8")
    m = thunderstore_remote
    assert f"GP_ENV_DIR={m.OVERLAY_DIR}\n" in text
    assert f"GP_SERVICE_ENV={m.OVERLAY_DIR}/{m.OVERLAY_SERVICE}\n" in text
    assert f"GP_RUNTIME_OVERLAY={m.OVERLAY_DIR}/{m.OVERLAY_RUNTIME}\n" in text
    assert f"GP_ENV_DROPIN={m.OVERLAY_DROPIN}\n" in text
    assert f"GP_WIN_RUN={m.OVERLAY_WIN_RUN}\n" in text
    # The same character set on both sides: what the panel writes, the root side accepts on conversion.
    assert "GP_ENV_VALUE_RE='^[A-Za-z0-9_./:,;=@+ -]*$'" in text
    assert m.OVERLAY_VALUE.pattern == r"[A-Za-z0-9_./:,;=@+ -]{0,4096}"
