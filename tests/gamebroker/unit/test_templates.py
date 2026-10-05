"""The 'Add game' form templates (admin/modelos_de_jogo.py) must pass the broker's
validator. They live in the panel, but the only judge that matters is this one: a template
the broker rejects is worse than none, because the person thinks the mistake was theirs."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from gamebroker.services.catalog import validate_dynamic

RAIZ = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "modelos_de_jogo", RAIZ / "src" / "gamepanel" / "games" / "catalog" / "templates.py"
)
modelos = importlib.util.module_from_spec(_spec)
sys.modules["modelos_de_jogo"] = modelos
_spec.loader.exec_module(modelos)


def _as_the_panel_builds(values: dict[str, str]) -> dict:
    """Mirrors the panel's `_jogo_do_form`: only converts types, validates nothing."""
    data: dict = {}
    for field in ("start_args", "start_script", "config_path", "join_re", "leave_re", "player_source",
                  "platform"):
        if values.get(field):
            data[field] = values[field]
    for field in ("game_port", "query_port", "memory_mb", "cores", "disk_gb"):
        if values.get(field):
            data[field] = int(values[field])
    data["ports"] = [p for p in re.split(r"[\s,]+", values.get("ports", "").strip()) if p]
    for field in ("config_files", "backup_paths"):
        data[field] = [p.strip() for p in values.get(field, "").replace(",", "\n").splitlines() if p.strip()]
    # Ignoring the recipes let the Windows template pass with no runtime at all: the broker only
    # rejects "windows without proton/wine" if both arrive together, as they do from the screen.
    data["recipes"] = values.get("recipes", "").split()
    data["shiftable"] = values.get("shiftable") == "1"
    return data


def _complete(modelo) -> dict:
    """What the person adds by hand: identity and app id (the rest comes from the template)."""
    data = _as_the_panel_builds(modelo.values)
    data.update(key="meujogo", name="Meu Jogo", app_id=123456)
    return data


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_passa_no_validador_do_broker(modelo):
    game = validate_dynamic(_complete(modelo))
    assert game.key == "meujogo"


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_que_anda_de_porta_tem_os_marcadores(modelo):
    if modelo.values.get("shiftable") == "1":
        assert "{PORT}" in modelo.values["start_args"]


def test_unreal_traz_o_padrao_de_log_dos_servidores_unreal():
    values = modelos.UNREAL_LINUX.values
    joined = re.search(values["join_re"], "LogNet: Join succeeded: Zeca")
    assert joined is not None
    assert joined.group("name") == "Zeca"
    assert re.search(values["leave_re"], "LogNet: UNetConnection::Close: [UNetConnection] ...")


def test_unreal_deixa_o_nome_do_projeto_bem_visivel():
    """A silent guess (a folder that looks right) would hide the mistake; an obviously fake
    name asks to be replaced."""
    values = modelos.UNREAL_LINUX.values
    assert modelos.PROJECT in values["config_path"]
    assert modelos.PROJECT in values["backup_paths"]


def test_chaves_do_modelo_sao_campos_do_formulario_do_catalogo():
    # The fields live in the include, which "add" and "edit" share.
    templates = RAIZ / "src" / "gamepanel" / "templates"
    html = "".join((templates / name).read_text(encoding="utf-8")
                   for name in ("catalog.html", "components/game_form.html"))
    fields = set(re.findall(r'name="([a-z_]+)"', html))
    for template_of in modelos.TEMPLATES:
        assert set(template_of.values) <= fields, set(template_of.values) - fields


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_de_windows_prefere_proton(modelo):
    """Repository rule: a Windows-only server runs under Proton (fsync/ntsync); plain wine only
    when Proton provably fails, and that is not a decision for a generic template."""
    if modelo.values.get("platform") == "windows":
        assert "proton" in modelo.values["recipes"].split()
        assert "wine" not in modelo.values["recipes"].split()


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_diz_todos_os_campos_para_limpar_o_anterior(modelo):
    """Switching from the Windows template to a Linux one must uncheck Proton and reset the platform."""
    assert {"platform", "recipes", "start_script", "query_port", "shiftable"} <= set(modelo.values)


def test_ha_modelo_para_os_motores_mais_comuns():
    keys = {m.key for m in modelos.TEMPLATES}
    assert {"unreal-linux", "unreal-windows", "unity-linux", "unity-windows", "source"} <= keys


def test_rotulo_e_descricao_de_todo_modelo_estao_nos_dois_idiomas():
    from gamepanel.i18n import en, pt
    for modelo in modelos.TEMPLATES:
        for key in (modelo.label_key, modelo.description_key):
            assert key in pt.MESSAGES, key
            assert key in en.MESSAGES, key


def test_source_traz_o_padrao_de_log_do_srcds():
    values = {m.key: m for m in modelos.TEMPLATES}["source"].values
    joined = re.search(values["join_re"], 'Client "Zeca" connected (10.0.0.5:27005).')
    assert joined is not None
    assert joined.group("name") == "Zeca"
    left = re.search(values["leave_re"], "Dropped Zeca from server (Disconnect by user.)")
    assert left is not None
    assert left.group("name") == "Zeca"
