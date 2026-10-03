"""UE4SS nativo de Linux (games/mods/ue4ss_linux_remote.py), o port XarminaEu/ue4ss-linux.

Roda DENTRO do CT; aqui contra uma pasta temporaria, um GitHub falso com o tar.gz no formato
da v3.0.2 (so o libUE4SS.so dentro) e o systemd trocado por uma pasta.
"""
from __future__ import annotations

import io
import json
import tarfile

import pytest

from gamepanel.games.mods import ue4ss_linux_remote as ul


def release_tar(lib: bytes = b"\x7fELF-ue4ss") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("libUE4SS.so")
        info.size = len(lib)
        tar.addfile(info, io.BytesIO(lib))
    return buf.getvalue()


def fetcher(url: str) -> bytes:
    if "api.github.com" in url:
        return json.dumps({"tag_name": "v3.0.2", "assets": [{
            "name": "ue4ss-linux-v3.0.2.tar.gz",
            "browser_download_url": "https://github.com/XarminaEu/ue4ss-linux/releases/download/v3.0.2/"
                                    "ue4ss-linux-v3.0.2.tar.gz"}]}).encode()
    return release_tar()


@pytest.fixture
def game(tmp_path, monkeypatch):
    exe_dir = tmp_path / "Pal" / "Binaries" / "Linux"
    exe_dir.mkdir(parents=True)
    reloads: list[int] = []
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr(ul, "_daemon_reload", lambda: reloads.append(1))
    # ldd/apt nao existem aqui: o .so falso nao pede biblioteca nenhuma.
    monkeypatch.setattr(ul, "_ensure_libs", lambda path: None)
    return exe_dir, tmp_path, reloads


def test_instala_por_ld_preload_num_drop_in_do_servico(game):
    exe_dir, root, reloads = game
    result = ul.install_loader(str(exe_dir), "palworld.service", fetcher=fetcher)
    assert result["version"] == "v3.0.2"
    assert (exe_dir / "libUE4SS.so").read_bytes() == b"\x7fELF-ue4ss"
    dropin = (root / "systemd" / "palworld.service.d" / "gamepanel-ue4ss.conf").read_text(encoding="utf-8")
    assert f"Environment=LD_PRELOAD={exe_dir.as_posix()}/libUE4SS.so" in dropin.replace("\\", "/")
    settings = (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert "GuiConsoleEnabled = 0" in settings
    assert (exe_dir / "Mods" / "mods.txt").exists()
    assert reloads == [1]


def test_reinstalar_preserva_config_e_mods_do_dono(game):
    exe_dir, _, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", fetcher=fetcher)
    (exe_dir / "UE4SS-settings.ini").write_text("[General]\nMeuAjuste = 1\n", encoding="utf-8")
    (exe_dir / "Mods" / "mods.txt").write_text("MeuMod : 1\n", encoding="utf-8")
    ul.install_loader(str(exe_dir), "palworld.service", fetcher=fetcher)
    assert "MeuAjuste" in (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert (exe_dir / "Mods" / "mods.txt").read_text(encoding="utf-8") == "MeuMod : 1\n"


def test_desligar_apaga_o_drop_in_e_o_status_ve(game):
    exe_dir, _, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", fetcher=fetcher)
    (exe_dir / "Mods" / "Probe").mkdir()
    (exe_dir / "Mods" / "mods.txt").write_text("﻿Probe : 1\n", encoding="utf-8")
    state = ul.status(str(exe_dir), "palworld.service")
    assert state["enabled"] is True
    assert state["mods"] == [{"name": "Probe", "enabled": True}]
    ul.set_enabled(str(exe_dir), "palworld.service", False)
    assert ul.status(str(exe_dir), "palworld.service")["enabled"] is False
    assert (exe_dir / "libUE4SS.so").exists()


def test_pacote_sem_a_biblioteca_e_recusado(game):
    exe_dir, _, _ = game
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("readme.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))

    def fetch_bad(url):
        return fetcher(url) if "api.github.com" in url else buf.getvalue()
    with pytest.raises(ValueError, match="libUE4SS"):
        ul.install_loader(str(exe_dir), "palworld.service", fetcher=fetch_bad)


@pytest.mark.parametrize("unit", ["", "palworld", "../x.service", "a b.service"])
def test_servico_conferido_antes_de_baixar(game, unit):
    exe_dir, _, _ = game
    with pytest.raises(ValueError, match="servico"):
        ul.install_loader(str(exe_dir), unit, fetcher=lambda u: pytest.fail("baixou antes de conferir"))


def test_sem_antivirus_nao_instala(tmp_path, capsys):
    assert ul.main(["--unit", "palworld.service", "loader-install", str(tmp_path)]) == 1
    assert "antivirus" in capsys.readouterr().out
