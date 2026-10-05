"""The custom mod setup (games/mods/custom.py): what the form may store, and the profile it becomes."""
from __future__ import annotations

import json

import pytest

from gamepanel.games.mods import custom, custom_remote, profiles

GOOD = {"loader_url": "https://github.com/autor/loader/releases/download/v1/loader.zip",
        "loader_dir": "Binaries/Win64", "mods_dir": "Binaries/Win64/mods", "extensions": ".dll .pak",
        "wine_overrides": "winhttp=n,b", "ld_preload": ""}


def _parse(**over):
    return custom.parse({**GOOD, **over})


def _keys(problems):
    return [p.key for p in problems]


def test_configuracao_boa_vira_setup_normalizado():
    setup, problems = _parse(loader_dir="Binaries//Win64/", mods_dir="Binaries\\Win64\\mods")
    assert problems == []
    assert setup is not None
    assert setup.loader_dir == "Binaries/Win64"
    assert setup.mods_dir == "Binaries/Win64/mods"
    assert setup.extensions == (".dll", ".pak")
    assert setup.wine == ("winhttp=n,b",)


@pytest.mark.parametrize("url", [
    "http://github.com/x.zip",            # plain http: anyone on the way can swap it
    "file:///etc/passwd",
    "https://user:pass@host/x.zip",       # credentials in the link end up in the job log
    "https:///x.zip",
    "https://host/x y.zip",
    "https://host/" + "a" * 600,
    "ftp://host/x.zip",
])
def test_link_que_nao_e_https_limpo_e_recusado(url):
    setup, problems = _parse(loader_url=url)
    assert setup is None
    assert "mods.custom_bad_url" in _keys(problems)


@pytest.mark.parametrize("folder", ["/opt/game/mods", "../mods", "mods/../../etc", "./mods", "mods/.hidden",
                                    "a/" * 20 + "b", "mods;rm -rf", "mo$ds", "C:/x"])
def test_pasta_absoluta_com_ponto_ponto_ou_estranha_e_recusada(folder):
    setup, problems = _parse(mods_dir=folder)
    assert setup is None
    assert "mods.custom_bad_mods_dir" in _keys(problems)


def test_pasta_de_mods_e_obrigatoria_e_a_do_carregador_nao():
    assert "mods.custom_bad_mods_dir" in _keys(_parse(mods_dir="")[1])
    setup, problems = _parse(loader_dir="")
    assert problems == [] and setup is not None and setup.loader_dir == ""


def test_pasta_com_til_espaco_e_parenteses_passa():
    """What game folders are really called: ~mods (Unreal), "My Mods", "Mods (1)"."""
    setup, _ = _parse(mods_dir="Content/Paks/~mods", loader_dir="My Mods (1)")
    assert setup is not None and setup.mods_dir == "Content/Paks/~mods"


def test_extensoes_vazias_voltam_ao_padrao_e_sem_ponto_ganham_ponto():
    assert _parse(extensions="")[0].extensions == custom.DEFAULT_EXTENSIONS  # type: ignore[union-attr]
    assert _parse(extensions="PAK, dll;lua")[0].extensions == (".pak", ".dll", ".lua")  # type: ignore[union-attr]


@pytest.mark.parametrize("ext", [".sh", "so", ".exe", ".py"])
def test_script_e_executavel_nunca_entram(ext):
    setup, problems = _parse(extensions=f".pak {ext}")
    assert setup is None
    assert _keys(problems) == ["mods.custom_blocked_ext"]


@pytest.mark.parametrize("ext", [".p/k", ".muito-longa-demais", ". "])
def test_extensao_invalida(ext):
    assert "mods.custom_bad_ext" in _keys(_parse(extensions=ext)[1])


@pytest.mark.parametrize("wine", ["winhttp", "winhttp=x", "a=n,b;" * 9, "winhttp=n,b winhttp=b", "x=$(id)"])
def test_override_do_wine_fora_do_formato_e_recusado(wine):
    assert "mods.custom_bad_wine" in _keys(_parse(wine_overrides=wine)[1])


def test_override_do_wine_vazio_e_desligado_sao_validos():
    assert _parse(wine_overrides="mscoree= winhttp=n,b")[0].wine == ("mscoree=", "winhttp=n,b")  # type: ignore[union-attr]


@pytest.mark.parametrize("preload", ["/opt/game/lib.so", "../lib.so", "lib.txt", "dir with space/lib.so",
                                     "a:b.so", "~lib.so"])
def test_ld_preload_relativo_e_so(preload):
    assert "mods.custom_bad_preload" in _keys(_parse(ld_preload=preload)[1])


def test_ambiente_sem_carregador_nao_tem_quando_entrar_nem_sair():
    setup, problems = _parse(loader_url="", wine_overrides="winhttp=n,b")
    assert setup is None
    assert _keys(problems) == ["mods.custom_overlay_needs_loader"]


def test_todos_os_problemas_de_uma_vez():
    _, problems = custom.parse({"loader_url": "http://x", "mods_dir": "/abs", "extensions": ".sh"})
    assert set(_keys(problems)) == {"mods.custom_bad_url", "mods.custom_bad_mods_dir", "mods.custom_blocked_ext"}


def test_json_guardado_ida_e_volta():
    setup, _ = _parse()
    assert setup is not None
    assert custom.from_json(setup.to_json()) == setup


@pytest.mark.parametrize("stored", ["", "nao e json", "[]",
                                    json.dumps({"mods_dir": "/etc", "extensions": [".dll"]}),
                                    json.dumps({"mods_dir": "mods", "extensions": [".sh"]}),
                                    json.dumps({"mods_dir": "mods", "loader_url": "http://x/y.zip"})])
def test_linha_do_banco_editada_a_mao_nao_vale(stored):
    """The row is re-validated on every read: what the form would refuse never reaches the CT."""
    assert custom.from_json(stored) is None


def test_perfil_do_setup():
    setup, _ = _parse(loader_dir="Binaries/Win64", mods_dir="Mods")
    assert setup is not None
    profile = custom.profile(setup)
    assert profile.kind == profiles.KIND_CUSTOM
    assert profile.folder == "/opt/game/Mods"
    assert profile.loader_dir == "/opt/game/Binaries/Win64"
    assert profile.scan_paths == ("/opt/game/Mods", "/opt/game/Binaries/Win64")
    assert profile.accepts("x.dll") and not profile.accepts("x.sh")
    assert profile.folder_mods and not profile.proven
    assert profile.sources == (("mods.source_custom_loader", GOOD["loader_url"]),)


def test_sem_pasta_do_carregador_a_verificacao_nao_varre_o_jogo_inteiro():
    setup, _ = _parse(loader_dir="")
    assert setup is not None
    assert custom.profile(setup).scan_paths == ("/opt/game/Binaries/Win64/mods",)


@pytest.mark.parametrize("name", ["URL_MAX", "REL_MAX", "REL_DEPTH", "MAX_EXTENSIONS", "MAX_WINE",
                                  "BLOCKED_EXTENSIONS"])
def test_regras_do_painel_e_do_ct_sao_as_mesmas(name):
    """custom_remote runs in the CT and cannot import custom: the copies must not drift."""
    assert getattr(custom, name) == getattr(custom_remote, name)


@pytest.mark.parametrize("name", ["URL_CHARS", "SEGMENT", "PRELOAD_SEGMENT", "EXTENSION", "WINE_ENTRY"])
def test_expressoes_do_painel_e_do_ct_sao_as_mesmas(name):
    assert getattr(custom, name).pattern == getattr(custom_remote, name).pattern


def test_o_ct_recusa_a_mesma_configuracao_que_o_painel():
    setup, _ = _parse()
    assert setup is not None
    loaded = custom_remote.load_setup(setup.to_json())
    assert loaded["mods_dir"] == setup.mods_dir and loaded["wine"] == list(setup.wine)
    for bad in ({"mods_dir": "../x"}, {"mods_dir": "m", "loader_url": "http://x/y"},
                {"mods_dir": "m", "extensions": [".so"]}, {"mods_dir": "m", "preload": "x.txt"},
                {"mods_dir": "m", "wine": ["x=$(id)"]}):
        with pytest.raises(ValueError):
            custom_remote.load_setup(json.dumps(bad))
