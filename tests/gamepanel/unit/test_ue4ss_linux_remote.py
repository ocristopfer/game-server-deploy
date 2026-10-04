"""UE4SS nativo de Linux (games/mods/ue4ss_linux_remote.py), o port XarminaEu/ue4ss-linux.

Roda DENTRO do CT; aqui contra uma pasta temporaria, um GitHub falso com o tar.gz no formato
da v3.0.2 (so o libUE4SS.so dentro) e o systemd trocado por uma pasta.
"""
from __future__ import annotations

import hashlib
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


# ------------------------------------------------------------------ modo fork (Dragonwilds)

FORK_LIB = b"\x7fELF-fork"
FORK_LAYOUTS = {"VTableLayout.ini": b"[UObjectBase]\n__vecDelDtor\n", "MemberVariableLayout.ini": b"[UObject]\n"}
GOOD_ADDRESSES = "[Addresses]\nGUObjectArray = 0xDE3A500\nFNameConstructor = 0x4E072B0\nGNatives = 0xDE38B70\n"


def fork_fetcher(files: dict[str, bytes] | None = None, sums: dict[str, bytes] | None = None):
    """GitHub falso do release do fork; `sums` permite um SHA256SUMS que nao bate."""
    files = files if files is not None else {"libUE4SS.so": FORK_LIB, **FORK_LAYOUTS}
    sums_of = sums if sums is not None else files
    sums_text = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in sums_of.items()).encode()
    base = "https://github.com/ocristopfer/ue4ss-linux/releases/download/dragonwilds-v1/"
    assets = {**files, "SHA256SUMS": sums_text}

    def fetch(url: str) -> bytes:
        if "api.github.com" in url:
            assert url.endswith("/releases/tags/dragonwilds-v1")
            return json.dumps({"tag_name": "dragonwilds-v1", "assets": [
                {"name": n, "browser_download_url": base + n} for n in assets]}).encode()
        return assets[url.rsplit("/", 1)[1]]
    return fetch


@pytest.fixture
def dragonwilds(game, monkeypatch):
    exe_dir, _, _ = game
    (exe_dir / "RSDragonwildsServer-Linux-Shipping").write_bytes(b"\x7fELF")
    (exe_dir / "RSDragonwildsServer-Linux-Shipping.sym").write_bytes(b"sym")
    generated: list[str] = []

    def fake_generate(path, script):
        generated.append(ul.find_executable(path))
        return GOOD_ADDRESSES
    monkeypatch.setattr(ul, "generate_addresses", fake_generate)
    return exe_dir, generated


FORK = ul.Fork("dragonwilds-v1", "5.6", "print('gerador')")


def test_fork_instala_o_so_os_layouts_e_os_enderecos(dragonwilds):
    exe_dir, generated = dragonwilds
    scanned: list[list[str]] = []
    result = ul.install_loader(str(exe_dir), "dragonwilds.service", fetcher=fork_fetcher(),
                               scan=lambda blobs: scanned.append([n for n, _ in blobs]), fork=FORK)
    assert result["version"] == "dragonwilds-v1"
    assert (exe_dir / "libUE4SS.so").read_bytes() == FORK_LIB
    for name, data in FORK_LAYOUTS.items():
        assert (exe_dir / name).read_bytes() == data
    assert "GNatives = 0xDE38B70" in (exe_dir / "UE4SS_Addresses.ini").read_text(encoding="utf-8")
    settings = (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert "[EngineVersionOverride]\nMajorVersion = 5\nMinorVersion = 6" in settings
    # O antivirus ve o pacote INTEIRO de uma vez, e o executavel achado e o que tem .sym.
    assert scanned == [["MemberVariableLayout.ini", "VTableLayout.ini", "libUE4SS.so"]]
    assert generated[0].endswith("RSDragonwildsServer-Linux-Shipping")


def test_fork_preserva_a_config_do_dono_e_so_acrescenta_o_motor(dragonwilds):
    exe_dir, _ = dragonwilds
    (exe_dir / "UE4SS-settings.ini").write_text("[General]\nMeuAjuste = 1\n", encoding="utf-8")
    ul.install_loader(str(exe_dir), "dragonwilds.service", fetcher=fork_fetcher(), fork=FORK)
    ul.install_loader(str(exe_dir), "dragonwilds.service", fetcher=fork_fetcher(), fork=FORK)
    settings = (exe_dir / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert "MeuAjuste = 1" in settings
    assert settings.count("[EngineVersionOverride]") == 1


def test_fork_com_hash_que_nao_bate_nao_instala_nada(dragonwilds):
    exe_dir, _ = dragonwilds
    lying = {"libUE4SS.so": b"outro binario", **FORK_LAYOUTS}
    with pytest.raises(ValueError, match="SHA256SUMS"):
        ul.install_loader(str(exe_dir), "dragonwilds.service", fetcher=fork_fetcher(sums=lying), fork=FORK)
    assert not (exe_dir / "libUE4SS.so").exists()


def test_fork_sem_arquivo_no_release_e_recusado(dragonwilds):
    exe_dir, _ = dragonwilds
    with pytest.raises(ValueError, match="VTableLayout"):
        ul.install_loader(str(exe_dir), "dragonwilds.service",
                          fetcher=fork_fetcher(files={"libUE4SS.so": FORK_LIB}), fork=FORK)


def test_fork_nao_aceita_versao_escolhida(dragonwilds):
    exe_dir, _ = dragonwilds
    with pytest.raises(ValueError, match="tag fixa"):
        ul.install_loader(str(exe_dir), "dragonwilds.service", "3.0.2", fetcher=fork_fetcher(), fork=FORK)


def test_enderecos_sem_gnatives_sao_recusados():
    """Com o GNatives chutado pelo port, todo hook nativo derruba o servidor (medido)."""
    with pytest.raises(ValueError, match="GNatives"):
        ul.check_addresses("[Addresses]\nGUObjectArray = 0x1\nFNameConstructor = 0x2\n; GNatives = nao achado\n")
    ul.check_addresses(GOOD_ADDRESSES)


def test_servidor_sem_sym_nao_recebe_o_so(game):
    """Os enderecos vem ANTES do download: sem .sym nada e baixado nem ligado."""
    exe_dir, root, _ = game
    (exe_dir / "RSDragonwildsServer-Linux-Shipping").write_bytes(b"\x7fELF")
    with pytest.raises(ValueError, match=r"\.sym"):
        ul.install_loader(str(exe_dir), "dragonwilds.service",
                          fetcher=lambda u: pytest.fail("baixou sem enderecos"), fork=FORK)
    assert not (root / "systemd").exists()


@pytest.mark.parametrize(("tag", "engine", "script"), [
    ("", "5.6", "x"), ("../x", "5.6", "x"), ("dragonwilds-v1", "5", "x"), ("dragonwilds-v1", "5.6", "")])
def test_argumentos_do_fork_sao_conferidos(tag, engine, script):
    with pytest.raises(ValueError):
        ul.Fork(tag, engine, script)
