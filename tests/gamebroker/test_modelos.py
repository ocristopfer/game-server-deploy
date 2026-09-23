"""Os modelos do formulario 'Adicionar jogo' (admin/modelos_de_jogo.py) precisam passar no
validador do broker. Vivem no painel, mas o unico juiz que importa e este: um modelo que o
broker recusa e pior que nenhum, porque a pessoa acha que o erro foi dela."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from gamebroker.services.catalog import validate_dynamic

RAIZ = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "modelos_de_jogo", RAIZ / "src" / "gamepanel" / "games" / "catalog" / "templates.py"
)
modelos = importlib.util.module_from_spec(_spec)
sys.modules["modelos_de_jogo"] = modelos
_spec.loader.exec_module(modelos)


def _como_o_painel_monta(values: dict[str, str]) -> dict:
    """Espelha `_jogo_do_form` do painel: so converte tipos, sem validar nada."""
    data: dict = {}
    for campo in ("start_args", "config_path", "join_re", "leave_re", "player_source"):
        if values.get(campo):
            data[campo] = values[campo]
    for campo in ("game_port", "query_port", "memory_mb", "cores", "disk_gb"):
        if values.get(campo):
            data[campo] = int(values[campo])
    data["ports"] = [p for p in re.split(r"[\s,]+", values.get("ports", "").strip()) if p]
    for campo in ("config_files", "backup_paths"):
        data[campo] = [p.strip() for p in values.get(campo, "").replace(",", "\n").splitlines() if p.strip()]
    data["recipes"] = []
    data["shiftable"] = values.get("shiftable") == "1"
    return data


def _completo(modelo) -> dict:
    """O que a pessoa acrescenta a mao: identidade e app id (o resto vem do modelo)."""
    data = _como_o_painel_monta(modelo.values)
    data.update(key="meujogo", name="Meu Jogo", app_id=123456)
    return data


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_passa_no_validador_do_broker(modelo):
    game = validate_dynamic(_completo(modelo))
    assert game.key == "meujogo"


@pytest.mark.parametrize("modelo", modelos.TEMPLATES, ids=lambda m: m.key)
def test_modelo_que_anda_de_porta_tem_os_marcadores(modelo):
    if modelo.values.get("shiftable") == "1":
        assert "{PORT}" in modelo.values["start_args"]


def test_unreal_traz_o_padrao_de_log_dos_servidores_unreal():
    values = modelos.UNREAL_LINUX.values
    juncao = re.search(values["join_re"], "LogNet: Join succeeded: Zeca")
    assert juncao is not None
    assert juncao.group("name") == "Zeca"
    assert re.search(values["leave_re"], "LogNet: UNetConnection::Close: [UNetConnection] ...")


def test_unreal_deixa_o_nome_do_projeto_bem_visivel():
    """Um chute silencioso (uma pasta que parece certa) esconderia o erro; um nome de mentira
    obvio pede para ser trocado."""
    values = modelos.UNREAL_LINUX.values
    assert modelos.PROJECT in values["config_path"]
    assert modelos.PROJECT in values["backup_paths"]


def test_chaves_do_modelo_sao_campos_do_formulario_do_catalogo():
    html = (RAIZ / "src" / "gamepanel" / "templates" / "catalog.html").read_text(encoding="utf-8")
    campos = set(re.findall(r'name="([a-z_]+)"', html))
    for modelo in modelos.TEMPLATES:
        assert set(modelo.values) <= campos, set(modelo.values) - campos
