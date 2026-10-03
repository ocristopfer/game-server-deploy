"""Mods do Satisfactory pelo ficsit.app (games/mods/sml_remote.py).

Roda DENTRO do CT; aqui ele roda contra uma pasta temporaria e uma API falsa, no formato que
a api.ficsit.app devolveu de verdade para o SML 3.12.0 (alvos, sha256, dependencias).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from gamepanel.games.mods import sml_remote as sr


def plugin_zip(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{name}.uplugin", json.dumps({"VersionName": "x"}))
        z.writestr(f"Binaries/Linux/lib{name}.so", b"ELF")
    return buf.getvalue()


PACKAGES = {name: plugin_zip(name) for name in ("SML", "RefinedPower", "RefinedRDLib")}


def version(name: str, number: str, deps=(), targets=("Windows", "LinuxServer"), wrong_hash=False) -> dict:
    data = PACKAGES[name]
    digest = "0" * 64 if wrong_hash else hashlib.sha256(data).hexdigest()
    return {"id": f"{name}-{number}", "version": number, "game_version": ">=1",
            "targets": [{"targetName": t, "link": f"/v1/version/{name}-{number}/{t}/download", "hash": digest}
                        for t in targets],
            "dependencies": [{"mod_reference": d, "condition": c, "optional": o} for d, c, o in deps]}


def api(catalog: dict, downloads: list[str]):
    def fetcher(url: str, body: bytes | None = None) -> bytes:
        if body is not None:
            ref = json.loads(body)["variables"]["ref"]
            mod = {"mod_reference": ref, "versions": catalog[ref]} if ref in catalog else None
            return json.dumps({"data": {"getModByReference": mod}}).encode()
        downloads.append(url)
        return PACKAGES[url.split("/v1/version/")[1].split("-")[0]]
    return fetcher


CATALOG = {
    "SML": [version("SML", "4.0.0"), version("SML", "3.12.0"), version("SML", "3.11.3")],
    "RefinedRDLib": [version("RefinedRDLib", "2026.3.44", deps=[("SML", "^3.11.0", False)])],
    "RefinedPower": [version("RefinedPower", "2026.3.28", deps=[("RefinedRDLib", "^2026.3.0", False),
                                                                  ("SML", "^3.12.0", False),
                                                                  ("OptionalThing", "*", True)])],
}


@pytest.mark.parametrize(("have", "cond", "ok"), [
    ("3.12.0", "^3.11.0", True), ("4.0.0", "^3.11.0", False), ("0.5.0", "^0.4.0", False),
    ("1.2.3", ">=1.2.0 <2.0.0", True), ("1.2.9", "~1.2.0", True), ("1.3.0", "~1.2.0", False),
    ("1.0.0", "1.0.0", True), ("1.0.1", "1.0.0", False), ("9.9.9", "", True), ("lixo", "*", False),
])
def test_condicao_de_dependencia(have, cond, ok):
    assert sr.satisfies(have, cond) is ok


def test_dependencia_na_versao_que_a_condicao_pede_e_opcional_fica_de_fora():
    """^3.12.0 nao aceita o SML 4.0.0, mesmo sendo o mais novo."""
    plan = dict((name, v["version"]) for name, v in sr.resolve("RefinedPower", fetcher=api(CATALOG, [])))
    assert plan == {"RefinedPower": "2026.3.28", "RefinedRDLib": "2026.3.44", "SML": "3.12.0"}


def test_versao_sem_pacote_de_servidor_linux_e_pulada():
    catalog = {"SML": [version("SML", "3.13.0", targets=("Windows",)), version("SML", "3.12.0")]}
    [(_, picked)] = sr.resolve("SML", fetcher=api(catalog, []))
    assert picked["version"] == "3.12.0"


def test_instala_cada_mod_na_sua_pasta_e_verifica_tudo_antes(tmp_path):
    scanned: list[str] = []
    downloads: list[str] = []
    result = sr.install(str(tmp_path), "RefinedPower", fetcher=api(CATALOG, downloads),
                        scan=lambda blobs: scanned.extend(n for n, _ in blobs))
    assert [m["mod"] for m in result["installed"]] == ["RefinedPower", "RefinedRDLib", "SML"]
    assert all("/LinuxServer/download" in u for u in downloads)
    assert scanned == ["RefinedPower-2026.3.28", "RefinedRDLib-2026.3.44", "SML-3.12.0"]
    assert (tmp_path / "FactoryGame" / "Mods" / "SML" / "SML.uplugin").exists()
    state = sr.status(str(tmp_path))
    assert state["loader_installed"] is True
    assert state["loader_version"] == "3.12.0"
    assert [m["name"] for m in state["mods"]] == ["RefinedPower", "RefinedRDLib"]


def test_pacote_que_nao_confere_com_o_sha256_nao_chega_ao_antivirus(tmp_path):
    catalog = {"SML": [version("SML", "3.12.0", wrong_hash=True)]}
    scanned: list = []
    with pytest.raises(ValueError, match="sha256"):
        sr.install(str(tmp_path), "SML", fetcher=api(catalog, []), scan=scanned.append)
    assert scanned == []
    assert not (tmp_path / "FactoryGame").exists()


def test_antivirus_que_recusa_nao_deixa_nada_instalado(tmp_path):
    def refuse(blobs):
        raise ValueError("o antivirus recusou o pacote: nada foi instalado")
    with pytest.raises(ValueError, match="antivirus"):
        sr.install(str(tmp_path), "RefinedPower", fetcher=api(CATALOG, []), scan=refuse)
    assert not (tmp_path / "FactoryGame" / "Mods").exists()


def test_remover_e_pela_referencia_e_nada_fora_da_pasta_de_mods(tmp_path):
    sr.install(str(tmp_path), "SML", fetcher=api(CATALOG, []))
    assert sr.remove(str(tmp_path), "SML") == {"removed": True}
    with pytest.raises(ValueError):
        sr.remove(str(tmp_path), "../../etc")


def test_mod_que_o_ficsit_app_nao_conhece(tmp_path):
    with pytest.raises(ValueError, match="nao conhece"):
        sr.install(str(tmp_path), "NaoExiste", fetcher=api(CATALOG, []))


def test_sem_antivirus_nao_instala(tmp_path, capsys):
    assert sr.main(["mod-install", str(tmp_path), "SML"]) == 1
    assert "antivirus" in capsys.readouterr().out
