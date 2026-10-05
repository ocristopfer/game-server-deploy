"""UE4SS de jogo Unreal Linux nativo (games/mods/ue4ss_linux_remote.py): o oficial para Linux.

Roda DENTRO do CT; aqui contra uma pasta temporaria, um GitHub falso com os arquivos do release
(no formato do linux-v1) e o systemd trocado por uma pasta.
"""
from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from gamepanel.games.mods import ue4ss_linux_remote as ul

LIB = b"\x7fELF-ue4ss"
SETTINGS = b"[Debug]\nConsoleEnabled = 0\nGuiConsoleEnabled = 0\n"
TEMPLATE = "[UObjectBase]\n; void* __vecDelDtor(uint32)\n__vecDelDtor\n"


def tar_of(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def release_assets(**overrides: bytes) -> dict[str, bytes]:
    files = {
        "libUE4SS.so": LIB,
        "UE4SS-settings.ini": SETTINGS,
        "ue4ss-mods-shared.tar.gz": tar_of({"shared/UEHelpers/UEHelpers.lua": b"return {}"}),
        "VTableLayoutTemplates.tar.gz": tar_of({"VTableLayoutTemplates/VTableLayout_5_06_Template.ini":
                                                TEMPLATE.encode()}),
    }
    files.update(overrides)
    return files


def gh(files: dict[str, bytes] | None = None, sums: dict[str, bytes] | None = None):
    """GitHub falso do release; `sums` permite um SHA256SUMS que nao bate."""
    files = files if files is not None else release_assets()
    sums_of = sums if sums is not None else files
    sums_text = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in sums_of.items()).encode()
    base = "https://github.com/ocristopfer/RE-UE4SS/releases/download/linux-v1/"
    assets = {**files, "SHA256SUMS": sums_text}

    def fetch(url: str) -> bytes:
        if "api.github.com" in url:
            assert url.endswith("/repos/ocristopfer/RE-UE4SS/releases/tags/linux-v1")
            return json.dumps({"tag_name": "linux-v1", "assets": [
                {"name": n, "browser_download_url": base + n} for n in assets]}).encode()
        return assets[url.rsplit("/", 1)[1]]
    return fetch


RELEASE = ul.Release("linux-v1", "5.6", "print('gerador')")


@pytest.fixture
def game(tmp_path, monkeypatch):
    exe_dir = tmp_path / "Pal" / "Binaries" / "Linux"
    exe_dir.mkdir(parents=True)
    (exe_dir / "PalServer-Linux-Shipping").write_bytes(b"\x7fELF")
    reloads: list[int] = []
    monkeypatch.setattr(ul, "SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr(ul, "_daemon_reload", lambda: reloads.append(1))
    return exe_dir, tmp_path, reloads


def test_instala_no_layout_oficial_com_ld_preload_no_drop_in(game):
    exe_dir, root, reloads = game
    scanned: list[list[str]] = []
    result = ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh(),
                               scan=lambda blobs: scanned.append([n for n, _ in blobs]))
    assert result["version"] == "linux-v1"
    ue4ss = exe_dir / "ue4ss"
    assert (ue4ss / "libUE4SS.so").read_bytes() == LIB
    assert (ue4ss / "UE4SS-settings.ini").read_bytes() == SETTINGS
    assert (ue4ss / "Mods" / "shared" / "UEHelpers" / "UEHelpers.lua").read_bytes() == b"return {}"
    assert (ue4ss / "Mods" / "mods.txt").read_text(encoding="utf-8") == ""
    dropin = (root / "systemd" / "palworld.service.d" / "gamepanel-ue4ss.conf").read_text(encoding="utf-8")
    assert f"Environment=LD_PRELOAD={exe_dir.as_posix()}/ue4ss/libUE4SS.so" in dropin.replace("\\", "/")
    assert reloads == [1]
    # O antivirus ve o release INTEIRO de uma vez, antes de qualquer coisa ser gravada.
    assert scanned == [sorted(release_assets())]
    # Sem .sym (o Palworld): nenhum arquivo gerado - o layout do motor vem embutido.
    assert not (ue4ss / "VTableLayout.ini").exists()


def test_reinstalar_preserva_config_e_mods_do_dono_e_troca_o_shared(game):
    exe_dir, _, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    ue4ss = exe_dir / "ue4ss"
    (ue4ss / "UE4SS-settings.ini").write_text("[General]\nMeuAjuste = 1\n", encoding="utf-8")
    (ue4ss / "Mods" / "mods.txt").write_text("MeuMod : 1\n", encoding="utf-8")
    (ue4ss / "Mods" / "shared" / "sobra.lua").write_text("velho", encoding="utf-8")
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    assert "MeuAjuste" in (ue4ss / "UE4SS-settings.ini").read_text(encoding="utf-8")
    assert (ue4ss / "Mods" / "mods.txt").read_text(encoding="utf-8") == "MeuMod : 1\n"
    assert not (ue4ss / "Mods" / "shared" / "sobra.lua").exists()


def test_status_lista_os_mods_sem_o_shared_e_desligar_apaga_o_drop_in(game):
    exe_dir, _, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    mods = exe_dir / "ue4ss" / "Mods"
    (mods / "Probe").mkdir()
    (mods / "mods.txt").write_text("﻿Probe : 1\n", encoding="utf-8")
    state = ul.status(str(exe_dir), "palworld.service")
    assert state["enabled"] is True
    assert state["loader_version"] == "linux-v1"
    assert state["mods"] == [{"name": "Probe", "enabled": True}]
    ul.set_enabled(str(exe_dir), "palworld.service", False)
    assert ul.status(str(exe_dir), "palworld.service")["enabled"] is False
    assert (exe_dir / "ue4ss" / "libUE4SS.so").exists()


def test_hash_que_nao_bate_nao_instala_nada(game):
    exe_dir, root, _ = game
    lying = release_assets(**{"libUE4SS.so": b"outro binario"})
    with pytest.raises(ValueError, match="SHA256SUMS"):
        ul.install_loader(str(exe_dir), "palworld.service", RELEASE,
                          fetcher=gh(files=release_assets(), sums=lying))
    assert not (exe_dir / "ue4ss").exists()
    assert not (root / "systemd").exists()


def test_release_sem_um_dos_arquivos_e_recusado(game):
    exe_dir, _, _ = game
    files = release_assets()
    del files["ue4ss-mods-shared.tar.gz"]
    with pytest.raises(ValueError, match="ue4ss-mods-shared"):
        ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh(files=files))


@pytest.mark.parametrize("bad", ["../fora.lua", "/etc/passwd", "shared/../../fora.lua", "outra/coisa.lua"])
def test_pacote_do_shared_com_caminho_torto_e_recusado(game, bad):
    exe_dir, _, _ = game
    files = release_assets(**{"ue4ss-mods-shared.tar.gz": tar_of({bad: b"x"})})
    with pytest.raises(ValueError, match="caminho inesperado"):
        ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh(files=files))


@pytest.mark.parametrize("unit", ["", "palworld", "../x.service", "a b.service"])
def test_servico_conferido_antes_de_baixar(game, unit):
    exe_dir, _, _ = game
    with pytest.raises(ValueError, match="servico"):
        ul.install_loader(str(exe_dir), unit, RELEASE, fetcher=lambda u: pytest.fail("baixou antes de conferir"))


def test_sem_antivirus_nao_instala(tmp_path, capsys):
    assert ul.main(["--unit", "palworld.service", "--release", "linux-v1", "--engine", "5.1",
                    "loader-install", str(tmp_path)]) == 1
    assert "antivirus" in capsys.readouterr().out


@pytest.mark.parametrize(("tag", "engine"), [("", "5.6"), ("../x", "5.6"), ("linux-v1", "5"), ("linux-v1", "")])
def test_argumentos_do_release_sao_conferidos(tag, engine):
    with pytest.raises(ValueError):
        ul.Release(tag, engine, "x")


def test_template_tem_o_nome_do_ue4ss():
    assert ul.Release("linux-v1", "5.6", "").template_name == "VTableLayout_5_06_Template.ini"
    assert ul.Release("linux-v1", "5.1", "").template_name == "VTableLayout_5_01_Template.ini"


# ------------------------------------------------------------------ servidor com .sym (Dragonwilds)

GENERATED = {
    "VTableLayout.ini": "; Gerado pelo painel (ue_sym_layout.py) ...\n[AActor]\n__vecDelDtor\nBeginPlay\n",
    "UE4SS_Signatures/GNatives.lua": "function Register()\n    return \"48 89\"\nend\n",
}


@pytest.fixture
def dragonwilds(game, monkeypatch):
    exe_dir, root, _ = game
    (exe_dir / "PalServer-Linux-Shipping").unlink()
    (exe_dir / "RSDragonwildsServer-Linux-Shipping").write_bytes(b"\x7fELF")
    (exe_dir / "RSDragonwildsServer-Linux-Shipping.sym").write_bytes(b"sym")
    calls: list[tuple[str, str]] = []

    def fake_generate(executable, script, template):
        calls.append((executable, template))
        return dict(GENERATED)
    monkeypatch.setattr(ul, "generate_symfiles", fake_generate)
    return exe_dir, root, calls


def test_com_sym_grava_o_layout_e_as_assinaturas_deste_executavel(dragonwilds):
    exe_dir, _, calls = dragonwilds
    ul.install_loader(str(exe_dir), "dragonwilds.service", RELEASE, fetcher=gh())
    ue4ss = exe_dir / "ue4ss"
    assert (ue4ss / "VTableLayout.ini").read_text(encoding="utf-8") == GENERATED["VTableLayout.ini"]
    assert (ue4ss / "UE4SS_Signatures" / "GNatives.lua").exists()
    # O gerador recebe o executavel que tem o .sym e o template DA VERSAO do motor do perfil.
    assert calls[0][0].endswith("RSDragonwildsServer-Linux-Shipping")
    assert calls[0][1] == TEMPLATE
    state = ul.status(str(exe_dir), "dragonwilds.service")
    assert state["sym_files"] == sorted(GENERATED)


def test_motor_sem_template_no_release_nao_instala(dragonwilds):
    exe_dir, root, _ = dragonwilds
    with pytest.raises(ValueError, match="VTableLayout_5_03_Template"):
        ul.install_loader(str(exe_dir), "dragonwilds.service", ul.Release("linux-v1", "5.3", "x"), fetcher=gh())
    assert not (root / "systemd").exists()


def test_com_sym_sem_o_gerador_nao_instala(dragonwilds):
    exe_dir, _, _ = dragonwilds
    with pytest.raises(ValueError, match="gerador"):
        ul.install_loader(str(exe_dir), "dragonwilds.service", ul.Release("linux-v1", "5.6", ""), fetcher=gh())


def test_gerador_que_devolve_arquivo_inesperado_e_recusado(tmp_path, monkeypatch):
    class Proc:
        returncode = 0
        stdout = json.dumps({"files": {"../../etc/x": "y"}, "report": []})
        stderr = ""
    monkeypatch.setattr(ul.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(ValueError, match="inesperados"):
        ul.generate_symfiles(str(tmp_path / "exe"), "script", TEMPLATE)


def test_reinstalar_sem_sym_apaga_so_o_que_o_painel_gerou(dragonwilds, monkeypatch):
    exe_dir, _, _ = dragonwilds
    ul.install_loader(str(exe_dir), "dragonwilds.service", RELEASE, fetcher=gh())
    (exe_dir / "RSDragonwildsServer-Linux-Shipping.sym").unlink()
    ul.install_loader(str(exe_dir), "dragonwilds.service", RELEASE, fetcher=gh())
    assert not (exe_dir / "ue4ss" / "VTableLayout.ini").exists()
    assert not (exe_dir / "ue4ss" / "UE4SS_Signatures" / "GNatives.lua").exists()
    # Um ini escrito a mao (sem o cabecalho do painel) fica.
    (exe_dir / "ue4ss" / "VTableLayout.ini").write_text("[UObject]\nMeu\n", encoding="utf-8")
    ul.install_loader(str(exe_dir), "dragonwilds.service", RELEASE, fetcher=gh())
    assert (exe_dir / "ue4ss" / "VTableLayout.ini").exists()


def test_migra_a_instalacao_do_fork_antigo(dragonwilds):
    exe_dir, _, _ = dragonwilds
    for name in ("libUE4SS.so", "UE4SS_Addresses.ini", "MemberVariableLayout.ini", "UE4SS-settings.ini"):
        (exe_dir / name).write_text("velho", encoding="utf-8")
    (exe_dir / ".gamepanel-ue4ss-linux.json").write_text('{"version": "dragonwilds-v2"}', encoding="utf-8")
    (exe_dir / "Mods" / "AdditionalStorageSlotsLua" / "scripts").mkdir(parents=True)
    (exe_dir / "Mods" / "mods.txt").write_text("AdditionalStorageSlotsLua : 1\n", encoding="utf-8")
    assert ul.status(str(exe_dir), "dragonwilds.service")["old_layout"] is True
    ul.install_loader(str(exe_dir), "dragonwilds.service", RELEASE, fetcher=gh())
    mods = exe_dir / "ue4ss" / "Mods"
    assert (mods / "AdditionalStorageSlotsLua" / "scripts").is_dir()
    assert (mods / "mods.txt").read_text(encoding="utf-8") == "AdditionalStorageSlotsLua : 1\n"
    for name in ("libUE4SS.so", "UE4SS_Addresses.ini", "MemberVariableLayout.ini", "UE4SS-settings.ini",
                 ".gamepanel-ue4ss-linux.json"):
        assert not (exe_dir / name).exists(), name
    # O executavel e o .sym do jogo nao sao do fork: ficam.
    assert (exe_dir / "RSDragonwildsServer-Linux-Shipping").exists()
    assert ul.status(str(exe_dir), "dragonwilds.service")["old_layout"] is False


def test_sem_a_marca_do_fork_antigo_nada_ao_lado_do_executavel_e_mexido(game):
    exe_dir, _, _ = game
    (exe_dir / "libUE4SS.so").write_text("de outra pessoa", encoding="utf-8")
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    assert (exe_dir / "libUE4SS.so").read_text(encoding="utf-8") == "de outra pessoa"


def test_desinstalar_apaga_a_pasta_ue4ss_e_o_drop_in(game):
    exe_dir, root, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    (exe_dir / "ue4ss" / "Mods" / "MeuMod").mkdir()
    result = ul.uninstall_loader(str(exe_dir), "palworld.service")
    assert result["removed"] == ["ue4ss"]
    assert not (exe_dir / "ue4ss").exists()
    assert not (root / "systemd" / "palworld.service.d" / "gamepanel-ue4ss.conf").exists()
    assert (exe_dir / "PalServer-Linux-Shipping").exists()
    state = ul.status(str(exe_dir), "palworld.service")
    assert state["loader_installed"] is False
    assert state["enabled"] is False


def test_desinstalar_tambem_limpa_a_sobra_do_fork_antigo(game):
    exe_dir, _, _ = game
    (exe_dir / "libUE4SS.so").write_text("velho", encoding="utf-8")
    (exe_dir / "Mods" / "Velho").mkdir(parents=True)
    (exe_dir / ".gamepanel-ue4ss-linux.json").write_text("{}", encoding="utf-8")
    ul.uninstall_loader(str(exe_dir), "palworld.service")
    assert sorted(p.name for p in exe_dir.iterdir()) == ["PalServer-Linux-Shipping"]


# ------------------------------------------------------------------ servidor sem .sym, com o pacote de referencia

PACK = '{"version": "4.27", "reference": "Squad 44", "signatures": {}, "sections": {}}'
LAYOUT = {
    "VTableLayout.ini": "; Gerado pelo painel (ue_linux_layout.py) ...\n[AGameModeBase]\n__vecDelDtor\n",
    "MemberVariableLayout.ini": ("; Gerado pelo painel (ue_linux_layout.py) ...\n"
                                 "[FUObjectArray]\nUObjectCreateListeners = 128\n"),
    "UE4SS_Signatures/GMalloc.lua": "function Register()\n    return \"48 8B 3D ?? ?? ?? ??\"\nend\n",
}


def with_packs(**packs: str) -> dict[str, bytes]:
    return release_assets(**{"LinuxReferencePacks.tar.gz": tar_of(
        {f"LinuxReferencePacks/{n}": t.encode() for n, t in packs.items()})})


@pytest.fixture
def the_front(game, monkeypatch):
    """O The Front: binario sem -Linux- no nome, sem .sym, motor 4.27."""
    exe_dir, root, _ = game
    (exe_dir / "PalServer-Linux-Shipping").unlink()
    (exe_dir / "TheFrontServer").write_bytes(b"\x7fELF" + b"\0" * 4096)
    (exe_dir / "libsteam_api.so").write_bytes(b"\x7fELF" + b"\0" * 9000)
    (exe_dir / "TheFrontServer.sh").write_bytes(b"#!/bin/sh\n" + b"#" * 9000)
    calls: list[tuple[str, str, bool]] = []

    def fake_layout(executable, script, pack, with_sym):
        calls.append((executable, pack, with_sym))
        return dict(LAYOUT)
    monkeypatch.setattr(ul, "generate_layout", fake_layout)
    return exe_dir, root, calls


def test_sem_sym_gera_pelo_pacote_da_versao_e_o_drop_in_nomeia_o_executavel(the_front):
    exe_dir, root, calls = the_front
    release = ul.Release("linux-v1", "4.27", "gerador-sym", "gerador-pacote")
    ul.install_loader(str(exe_dir), "the-front.service", release, fetcher=gh(with_packs(**{"pack-4.27.json": PACK})))
    # O executavel e o maior ELF da pasta: nem a .so (maior) nem o script de partida contam.
    assert calls == [(str(exe_dir / "TheFrontServer"), PACK, False)]
    ue4ss = exe_dir / "ue4ss"
    assert (ue4ss / "MemberVariableLayout.ini").read_text(encoding="utf-8") == LAYOUT["MemberVariableLayout.ini"]
    assert (ue4ss / "UE4SS_Signatures" / "GMalloc.lua").exists()
    # Sem -Linux- no nome o UE4SS nao iniciaria: o drop-in diz qual e o processo do jogo.
    dropin = (root / "systemd" / "the-front.service.d" / "gamepanel-ue4ss.conf").read_text(encoding="utf-8")
    assert "Environment=UE4SS_TARGET_EXE=TheFrontServer" in dropin
    # Religar depois de desligar mantem o nome (vem da marca da instalacao).
    ul.set_enabled(str(exe_dir), "the-front.service", False)
    ul.set_enabled(str(exe_dir), "the-front.service", True)
    assert "UE4SS_TARGET_EXE=TheFrontServer" in (
        root / "systemd" / "the-front.service.d" / "gamepanel-ue4ss.conf").read_text(encoding="utf-8")


def test_executavel_com_linux_no_nome_nao_ganha_target_exe(game):
    exe_dir, root, _ = game
    ul.install_loader(str(exe_dir), "palworld.service", RELEASE, fetcher=gh())
    dropin = (root / "systemd" / "palworld.service.d" / "gamepanel-ue4ss.conf").read_text(encoding="utf-8")
    assert "UE4SS_TARGET_EXE" not in dropin


def test_versao_sem_pacote_instala_com_o_layout_embutido(the_front, capsys):
    exe_dir, _, calls = the_front
    release = ul.Release("linux-v1", "5.1", "gerador-sym", "gerador-pacote")
    ul.install_loader(str(exe_dir), "pavlov.service", release, fetcher=gh(with_packs(**{"pack-4.27.json": PACK})))
    assert calls == []
    assert "layout embutido" in capsys.readouterr().out
    assert not (exe_dir / "ue4ss" / "VTableLayout.ini").exists()


def test_com_sym_e_pacote_o_que_veio_do_sym_vence(dragonwilds, monkeypatch):
    exe_dir, _, _ = dragonwilds
    layout_calls: list[bool] = []

    def fake_layout(executable, script, pack, with_sym):
        layout_calls.append(with_sym)
        return {"VTableLayout.ini": "; Gerado pelo painel (ue_linux_layout.py) - perde\n",
                "UE4SS_Signatures/GMalloc.lua": "-- do pacote\n"}
    monkeypatch.setattr(ul, "generate_layout", fake_layout)
    release = ul.Release("linux-v1", "5.6", "gerador-sym", "gerador-pacote")
    ul.install_loader(str(exe_dir), "dragonwilds.service", release, fetcher=gh(with_packs(**{"pack-5.6.json": PACK})))
    ue4ss = exe_dir / "ue4ss"
    assert layout_calls == [True]   # com .sym o gerador do pacote so faz os globais
    assert (ue4ss / "VTableLayout.ini").read_text(encoding="utf-8") == GENERATED["VTableLayout.ini"]
    assert (ue4ss / "UE4SS_Signatures" / "GMalloc.lua").read_text(encoding="utf-8") == "-- do pacote\n"


def test_reinstalar_apaga_o_member_layout_gerado_mas_nao_o_escrito_a_mao(the_front):
    exe_dir, _, _ = the_front
    release = ul.Release("linux-v1", "4.27", "x", "y")
    ul.install_loader(str(exe_dir), "the-front.service", release, fetcher=gh(with_packs(**{"pack-4.27.json": PACK})))
    ue4ss = exe_dir / "ue4ss"
    ul.remove_generated(str(ue4ss))
    assert not (ue4ss / "MemberVariableLayout.ini").exists()
    (ue4ss / "MemberVariableLayout.ini").write_text("[FUObjectArray]\nObjObjects = 16\n", encoding="utf-8")
    ul.remove_generated(str(ue4ss))
    assert (ue4ss / "MemberVariableLayout.ini").exists()


def test_nome_do_pacote_segue_a_versao_do_motor():
    assert ul.Release("linux-v2", "4.27", "").pack_name == "pack-4.27.json"
    assert ul.Release("linux-v2", "5.07", "").pack_name == "pack-5.7.json"
