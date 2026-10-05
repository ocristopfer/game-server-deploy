"""The custom loader installer (games/mods/custom_remote.py), run against a temporary game folder.

No internet and no ClamAV: the download is a fake `fetcher` and the antivirus a fake `scan`. What
is proven is the installer's DECISIONS: what an archive may not do (zip slip, links, bombs), what
it may not overwrite, that uninstall takes out only what the install created, and that the
environment goes in and out of steam's overlay only.
"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tarfile
import urllib.request
import zipfile

import pytest

from gamepanel.games.mods import custom_remote as cr

URL = "https://example.com/dl/loader.zip"


def _zip(files: dict[str, bytes], links: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


def _tar(add) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        add(tar)
    return buf.getvalue()


def _setup(**over) -> dict:
    data = {"loader_url": URL, "loader_dir": "bin", "mods_dir": "bin/mods", "extensions": [".dll", ".pak"],
            "wine": [], "preload": ""}
    data.update(over)
    return cr.load_setup(json.dumps(data))


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "game"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "Game.exe").write_bytes(b"jogo")
    return root


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    env_dir = tmp_path / "game-env"
    env_dir.mkdir()
    for name in ("service.env", "runtime.env"):
        (env_dir / name).write_text("# Written by the panel\n", encoding="utf-8")
    systemd = tmp_path / "systemd" / "jogo.service.d"
    systemd.mkdir(parents=True)
    (systemd / "gamepanel-env.conf").write_text("[Service]\n", encoding="utf-8")
    win_run = tmp_path / "win-run"
    win_run.write_text("# gamepanel-overlay\n", encoding="utf-8")
    monkeypatch.setattr(cr, "OVERLAY_DIR", str(env_dir))
    monkeypatch.setattr(cr, "OVERLAY_SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr(cr, "OVERLAY_WIN_RUN", str(win_run))
    runtime = tmp_path / "game-runtime.env"
    runtime.write_text("RUNTIME='proton'\nWINE_DLL_OVERRIDES='mscoree=;d3d11=n'\n", encoding="utf-8")
    return {"dir": env_dir, "runtime": str(runtime)}


def _install(game, setup, data, **kw):
    scanned: list = []
    result = cr.install_loader(str(game), setup, "jogo.service", fetcher=lambda url: data,
                               scan=scanned.append, **kw)
    return result, scanned


# ------------------------------------------------------------------ install and uninstall

def test_instala_o_pacote_depois_do_antivirus_e_marca_o_que_criou(game):
    data = _zip({"winhttp.dll": b"proxy", "BepInEx/core/BepInEx.dll": b"core"})
    result, scanned = _install(game, _setup(), data)
    assert result == {"installed": True, "files": 2}
    assert scanned == [[("loader.zip", data)]], "the antivirus sees the whole download, before unpacking"
    assert (game / "bin" / "winhttp.dll").read_bytes() == b"proxy"
    assert (game / "bin" / "mods").is_dir()
    mark = json.loads((game / "bin" / cr.MARK).read_text(encoding="utf-8"))
    assert mark["files"] == ["BepInEx/core/BepInEx.dll", "winhttp.dll"]
    assert mark["dirs"] == ["BepInEx", "BepInEx/core"]
    assert mark["complete"] is True


def test_sem_antivirus_nao_instala(game):
    with pytest.raises(ValueError):
        cr.install_loader(str(game), _setup(), fetcher=lambda url: _zip({"a.dll": b"x"}), scan=None)
    assert not (game / "bin" / "a.dll").exists()


def test_antivirus_que_recusa_nao_deixa_nada(game):
    def refuse(blobs):
        raise ValueError("o antivirus recusou o pacote")
    with pytest.raises(ValueError):
        cr.install_loader(str(game), _setup(), fetcher=lambda url: _zip({"a.dll": b"x"}), scan=refuse)
    assert sorted(os.listdir(game / "bin")) == ["Game.exe"]


def test_nao_sobrescreve_arquivo_do_jogo(game):
    """The panel could not give the game file back on uninstall: nothing is installed."""
    with pytest.raises(ValueError, match="overwrite 1 file"):
        _install(game, _setup(), _zip({"Game.exe": b"trocado", "novo.dll": b"x"}))
    assert (game / "bin" / "Game.exe").read_bytes() == b"jogo"
    assert not (game / "bin" / "novo.dll").exists()


def test_reinstalar_pode_sobrescrever_o_proprio(game):
    _install(game, _setup(), _zip({"a.dll": b"v1"}))
    _install(game, _setup(), _zip({"a.dll": b"v2"}))
    assert (game / "bin" / "a.dll").read_bytes() == b"v2"


def test_desinstalar_tira_so_o_que_criou(game):
    (game / "bin" / "BepInEx").mkdir()
    (game / "bin" / "BepInEx" / "do-jogo.txt").write_text("fica", encoding="utf-8")
    _install(game, _setup(), _zip({"winhttp.dll": b"p", "BepInEx/core/x.dll": b"c", "doorstop/d.dll": b"d"}))
    (game / "bin" / "doorstop" / "criado-depois.txt").write_text("vai junto", encoding="utf-8")
    result = cr.uninstall_loader(str(game), _setup())
    assert result["uninstalled"] is True
    assert sorted(os.listdir(game / "bin")) == ["BepInEx", "Game.exe", "mods"]
    # BepInEx existed before: it stays, with the game's file; only the folder the install created inside it goes.
    assert os.listdir(game / "bin" / "BepInEx") == ["do-jogo.txt"]


def test_desinstalar_sem_marcador_nao_apaga_nada(game):
    assert cr.uninstall_loader(str(game), _setup()) == {"uninstalled": False, "removed": 0}
    assert (game / "bin" / "Game.exe").exists()


def test_arquivo_unico_vira_um_arquivo_com_o_nome_do_link(game):
    setup = _setup(loader_url="https://example.com/dl/version.dll")
    _install(game, setup, b"MZ-dll")
    assert (game / "bin" / "version.dll").read_bytes() == b"MZ-dll"


def test_tar_gz_tambem(game):
    def add(tar):
        info = tarfile.TarInfo("lib/loader.so")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"elf"))
    _install(game, _setup(loader_url="https://example.com/l.tar.gz"), _tar(add))
    assert (game / "bin" / "lib" / "loader.so").read_bytes() == b"elf"


# ------------------------------------------------------------------ what an archive may not do

@pytest.mark.parametrize("name", ["../fora.dll", "/etc/cron.d/x", "a/../../fora.dll", "C:/x.dll", "..\\fora.dll"])
def test_zip_slip_e_recusado_antes_de_escrever(game, name):
    with pytest.raises(ValueError, match="unsafe path"):
        _install(game, _setup(), _zip({"ok.dll": b"x", name: b"x"}))
    assert not (game / "bin" / "ok.dll").exists()
    assert not (game / "fora.dll").exists()


def test_link_dentro_do_zip_e_recusado(game):
    with pytest.raises(ValueError, match="link"):
        _install(game, _setup(), _zip({"ok.dll": b"x"}, links=("passwd",)))


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_link_ou_dispositivo_no_tar_e_recusado(game, kind):
    def add(tar):
        info = tarfile.TarInfo("evil")
        info.type = kind
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(ValueError, match="not a file or folder"):
        _install(game, _setup(loader_url="https://example.com/l.tar.gz"), _tar(add))


def test_bomba_de_descompressao_e_recusada(game, monkeypatch):
    monkeypatch.setattr(cr, "MAX_UNPACKED", 1000)
    with pytest.raises(ValueError, match="unpacks to more"):
        _install(game, _setup(), _zip({"zeros.pak": b"\0" * 5000}))
    assert not (game / "bin" / "zeros.pak").exists()


def test_pacote_com_entradas_demais_e_recusado(game, monkeypatch):
    monkeypatch.setattr(cr, "MAX_MEMBERS", 3)
    with pytest.raises(ValueError, match="entries"):
        _install(game, _setup(), _zip({f"{i}.dll": b"x" for i in range(5)}))


def test_download_grande_demais_e_cortado(monkeypatch):
    class Big:
        def __init__(self):
            self.left = 5

        def read(self, n):
            self.left -= 1
            return b"x" * 10 if self.left > 0 else b""

        def geturl(self):
            return URL

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, req, timeout=None):
            return Big()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *h: Opener())
    with pytest.raises(ValueError, match="larger than"):
        cr.fetch(URL, limit=25)


def test_redirecionamento_para_http_e_recusado():
    handler = cr._HttpsOnly()
    req = urllib.request.Request(URL)
    with pytest.raises(ValueError, match="non-https"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://example.com/x.zip")


def test_link_http_nem_e_baixado():
    with pytest.raises(ValueError):
        cr.fetch("http://example.com/x.zip")


def _can_symlink(tmp_path) -> bool:
    try:
        os.symlink(tmp_path, tmp_path / "probe", target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    os.remove(tmp_path / "probe")
    return True


def test_pasta_que_sai_do_jogo_por_um_link_e_recusada(game, tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("este sistema nao cria links simbolicos sem privilegio")
    outside = tmp_path / "fora"
    outside.mkdir()
    os.symlink(outside, game / "bin" / "mods", target_is_directory=True)
    with pytest.raises(ValueError, match="leaves the game folder"):
        cr.list_mods(str(game), _setup())
    with pytest.raises(ValueError, match="leaves the game folder"):
        cr.remove_mods(str(game), _setup(), ["f", "x.dll"])


# ------------------------------------------------------------------ environment, in the overlay

# The LD_PRELOAD value is the library's real path, and a Windows one (drive letter, backslashes) is not something the
# overlay's character set takes: in the CT it is always a POSIX path. The container run covers it.
@pytest.mark.skipif(sys.platform == "win32", reason="caminho POSIX no LD_PRELOAD; roda no container")
def test_ambiente_entra_no_overlay_e_sai_na_desinstalacao(game, overlay):
    setup = _setup(wine=["winhttp=n,b", "mscoree=n"], preload="bin/lib/loader.so")
    data = _zip({"winhttp.dll": b"p", "lib/loader.so": b"elf"})
    _install(game, setup, data, overlay=True, env_path=overlay["runtime"])
    runtime = (overlay["dir"] / "runtime.env").read_text(encoding="utf-8")
    service = (overlay["dir"] / "service.env").read_text(encoding="utf-8")
    # The game's own d3d11 stays; mscoree is replaced by ours (one entry per DLL).
    assert "WINE_DLL_OVERRIDES='d3d11=n;winhttp=n,b;mscoree=n'" in runtime
    assert f"LD_PRELOAD='{os.path.realpath(game / 'bin' / 'lib' / 'loader.so')}'" in service
    cr.uninstall_loader(str(game), setup, overlay=True, env_path=overlay["runtime"])
    assert "WINE_DLL_OVERRIDES" not in (overlay["dir"] / "runtime.env").read_text(encoding="utf-8")
    assert "LD_PRELOAD" not in (overlay["dir"] / "service.env").read_text(encoding="utf-8")


def _runtime(overlay) -> str:
    return (overlay["dir"] / "runtime.env").read_text(encoding="utf-8")


def test_override_trocado_volta_ao_do_jogo_e_reinstalar_nao_empilha(game, overlay):
    """The game's own `mscoree=` comes back on uninstall, and a reinstall with other settings
    replaces the old entries instead of stacking them (or recording ours as the game's)."""
    data = _zip({"winhttp.dll": b"p"})
    _install(game, _setup(wine=["winhttp=n,b", "mscoree=n"]), data, overlay=True, env_path=overlay["runtime"])
    assert "WINE_DLL_OVERRIDES='d3d11=n;winhttp=n,b;mscoree=n'" in _runtime(overlay)
    _install(game, _setup(wine=["winhttp=n,b"]), data, overlay=True, env_path=overlay["runtime"])
    assert "WINE_DLL_OVERRIDES='mscoree=;d3d11=n;winhttp=n,b'" in _runtime(overlay)
    cr.uninstall_loader(str(game), _setup(), overlay=True, env_path=overlay["runtime"])
    assert "WINE_DLL_OVERRIDES" not in _runtime(overlay), "/etc/game-runtime.env is in charge again"


def test_ambiente_no_modo_root_e_recusado_antes_de_baixar(game):
    fetched: list = []
    with pytest.raises(ValueError, match="helper mode"):
        cr.install_loader(str(game), _setup(wine=["winhttp=n,b"]), fetcher=fetched.append, scan=lambda b: None)
    assert fetched == []


def test_override_do_wine_em_jogo_nativo_e_recusado(game, overlay, tmp_path):
    with pytest.raises(ValueError, match="Wine/Proton"):
        _install(game, _setup(wine=["winhttp=n,b"]), _zip({"a.dll": b"x"}), overlay=True,
                 env_path=str(tmp_path / "nao-existe.env"))


def test_ld_preload_que_nao_veio_no_pacote_deixa_a_instalacao_incompleta(game, overlay):
    setup = _setup(preload="bin/nao-veio.so")
    with pytest.raises(ValueError, match="not a file"):
        _install(game, setup, _zip({"a.dll": b"x"}), overlay=True, env_path=overlay["runtime"])
    mark = json.loads((game / "bin" / cr.MARK).read_text(encoding="utf-8"))
    assert mark["complete"] is False and mark["files"] == ["a.dll"], "what got in can still be uninstalled"
    assert cr.status(str(game), setup, "jogo.service", True, overlay["runtime"])["loader_complete"] is False


# ------------------------------------------------------------------ mods: place, list, remove

@pytest.fixture
def incoming(tmp_path, monkeypatch):
    folder = tmp_path / "gamepanel-incoming-abcdef0123456789"
    folder.mkdir()
    monkeypatch.setattr(cr, "INCOMING", __import__("re").compile(r".*gamepanel-incoming-[0-9a-f]{16}"))
    return folder


def test_coloca_o_envio_verificado_na_pasta_de_mods(game, incoming):
    (incoming / "Mod.pak").write_bytes(b"pak")
    assert cr.place(str(game), _setup(), str(incoming)) == {"placed": ["Mod.pak"]}
    assert (game / "bin" / "mods" / "Mod.pak").read_bytes() == b"pak"
    assert not incoming.exists(), "the holding folder always goes"


def test_envio_com_extensao_errada_nao_entra(game, incoming):
    (incoming / "x.sh").write_bytes(b"#!/bin/sh")
    with pytest.raises(ValueError):
        cr.place(str(game), _setup(), str(incoming))
    assert not (game / "bin" / "mods" / "x.sh").exists()
    assert not incoming.exists()


def test_pasta_de_espera_fora_do_padrao_e_recusada(game, tmp_path):
    with pytest.raises(ValueError):
        cr.place(str(game), _setup(), str(tmp_path))


def test_lista_e_remove_pelo_nome(game):
    mods = game / "bin" / "mods"
    (mods / "PastaMod").mkdir(parents=True)
    (mods / "a.dll").write_bytes(b"a")
    (mods / "notas.txt").write_text("nao e mod", encoding="utf-8")
    listed = cr.list_mods(str(game), _setup())
    assert [m["name"] for m in listed] == ["PastaMod", "a.dll"]
    assert cr.remove_mods(str(game), _setup(), ["f", "a.dll", "d", "PastaMod"]) == {"removed": ["a.dll", "PastaMod"]}
    assert os.listdir(mods) == ["notas.txt"]


@pytest.mark.parametrize("pair", [["f", "../Game.exe"], ["f", "notas.txt"], ["x", "a.dll"], ["d", ".."], ["f"]])
def test_remover_recusa_nome_ruim(game, pair):
    (game / "bin" / "mods").mkdir()
    with pytest.raises(ValueError):
        cr.remove_mods(str(game), _setup(), pair)
    assert (game / "bin" / "Game.exe").exists()


def test_arquivo_x_pasta_trocados_nao_apaga(game):
    (game / "bin" / "mods" / "a.dll").mkdir(parents=True)
    with pytest.raises(ValueError, match="file vs folder"):
        cr.remove_mods(str(game), _setup(), ["f", "a.dll"])
    assert (game / "bin" / "mods" / "a.dll").is_dir()


def test_main_devolve_uma_linha_json(game, capsys):
    setup = json.dumps({"loader_url": URL, "loader_dir": "bin", "mods_dir": "bin/mods", "extensions": [".dll"]})
    assert cr.main(["--setup", setup, "status", str(game)]) == 0
    state = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert state["loader_installed"] is False and state["mods"] == []
    assert cr.main(["--setup", "{\"mods_dir\": \"../x\"}", "status", str(game)]) == 1
    assert "error" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])
