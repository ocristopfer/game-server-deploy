"""Oxide (uMod) no Rust (games/mods/oxide_remote.py).

Roda DENTRO do CT; aqui contra uma pasta temporaria e um GitHub falso, com o zip no formato
da 2.0.7801 (so RustDedicated_Data/Managed/, sobrescrevendo DLL do jogo).
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from gamepanel.games.mods import oxide_remote as ox

MANAGED = "RustDedicated_Data/Managed"


def oxide_zip(tag: str = "2.0.7801") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{MANAGED}/Assembly-CSharp.dll", f"OXIDE-PATCHED {tag}".encode())
        z.writestr(f"{MANAGED}/Oxide.Rust.dll", f"OXIDE {tag}".encode())
    return buf.getvalue()


def fetcher_for(tag: str = "2.0.7801"):
    def fetcher(url: str) -> bytes:
        if "api.github.com" in url:
            return json.dumps({"tag_name": tag, "assets": [{
                "name": "Oxide.Rust-linux.zip",
                "browser_download_url": f"https://github.com/OxideMod/Oxide.Rust/releases/download/{tag}/Oxide.Rust-linux.zip",
            }]}).encode()
        return oxide_zip(tag)
    return fetcher


@pytest.fixture
def rust(tmp_path):
    managed = tmp_path / MANAGED
    managed.mkdir(parents=True)
    (managed / "Assembly-CSharp.dll").write_bytes(b"JOGO ORIGINAL")
    return tmp_path


def test_instala_guardando_o_que_o_oxide_sobrescreve(rust):
    result = ox.install_loader(str(rust), fetcher=fetcher_for())
    assert result["version"] == "2.0.7801"
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes().startswith(b"OXIDE-PATCHED")
    assert (rust / ox.STATE_DIR / ox.ORIGINAL / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO ORIGINAL"
    assert (rust / "oxide" / "plugins").is_dir()
    state = ox.status(str(rust))
    assert state["enabled"] is True
    assert state["wiped"] is False


def test_desligar_devolve_o_jogo_original_e_religar_poe_o_oxide(rust):
    ox.install_loader(str(rust), fetcher=fetcher_for())
    ox.set_enabled(str(rust), False)
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO ORIGINAL"
    # Arquivo que o jogo nao tinha (o Oxide.Rust.dll) sai.
    assert not (rust / MANAGED / "Oxide.Rust.dll").exists()
    assert ox.status(str(rust))["enabled"] is False
    ox.set_enabled(str(rust), True)
    assert ox.status(str(rust))["enabled"] is True


def test_reinstalar_com_o_oxide_ligado_nao_perde_o_original(rust):
    """Com o Oxide ligado, o que esta na pasta e o Oxide: ele nao pode virar o 'original'."""
    ox.install_loader(str(rust), fetcher=fetcher_for())
    ox.install_loader(str(rust), fetcher=fetcher_for("2.0.7802"))
    ox.set_enabled(str(rust), False)
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO ORIGINAL"


def test_atualizacao_do_rust_que_apaga_parte_do_oxide_aparece(rust):
    ox.install_loader(str(rust), fetcher=fetcher_for())
    # O SteamCMD devolve a DLL do jogo (versao nova) e deixa o resto.
    (rust / MANAGED / "Assembly-CSharp.dll").write_bytes(b"JOGO NOVO")
    state = ox.status(str(rust))
    assert state["wiped"] is True
    assert state["enabled"] is False
    # Reinstalar guarda o jogo NOVO como original.
    ox.install_loader(str(rust), fetcher=fetcher_for())
    ox.set_enabled(str(rust), False)
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO NOVO"


def test_pasta_que_nao_e_de_rust_e_recusada(tmp_path):
    with pytest.raises(ValueError, match="Rust"):
        ox.install_loader(str(tmp_path), fetcher=fetcher_for())


def test_lista_plugins_cs(rust):
    ox.install_loader(str(rust), fetcher=fetcher_for())
    (rust / "oxide" / "plugins" / "Kits.cs").write_text("// plugin", encoding="utf-8")
    (rust / "oxide" / "plugins" / "leia.txt").write_text("x", encoding="utf-8")
    assert [p["name"] for p in ox.status(str(rust))["mods"]] == ["Kits.cs"]


def test_sem_antivirus_nao_instala(rust, capsys):
    assert ox.main(["loader-install", str(rust)]) == 1
    assert "antivirus" in capsys.readouterr().out


def test_desinstalar_devolve_o_jogo_e_apaga_oxide_e_estado(rust):
    ox.install_loader(str(rust), fetcher=fetcher_for())
    (rust / "oxide" / "plugins" / "MeuPlugin.cs").write_text("// plugin", encoding="utf-8")
    result = ox.uninstall_loader(str(rust))
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO ORIGINAL"
    assert not (rust / MANAGED / "Oxide.Rust.dll").exists()
    assert not (rust / "oxide").exists()
    assert not (rust / ox.STATE_DIR).exists()
    assert (result["restored"], result["removed"], result["kept"]) == (1, 1, 0)


def test_desinstalar_depois_de_update_do_rust_nao_volta_a_dll_velha(rust):
    """O backup e da versao velha do jogo: devolve-lo por cima da nova estragaria o servidor."""
    ox.install_loader(str(rust), fetcher=fetcher_for())
    (rust / MANAGED / "Assembly-CSharp.dll").write_bytes(b"JOGO NOVO")
    result = ox.uninstall_loader(str(rust))
    assert (rust / MANAGED / "Assembly-CSharp.dll").read_bytes() == b"JOGO NOVO"
    assert result["kept"] == 1
