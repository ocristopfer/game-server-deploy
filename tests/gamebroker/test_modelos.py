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


def _como_o_painel_monta(valores: dict[str, str]) -> dict:
    """Espelha `_jogo_do_form` do painel: so converte tipos, sem validar nada."""
    dados: dict = {}
    for campo in ("start_args", "config_path", "join_re", "leave_re", "player_source"):
        if valores.get(campo):
            dados[campo] = valores[campo]
    for campo in ("porta_jogo", "porta_query", "memoria_mb", "cores", "disco_gb"):
        if valores.get(campo):
            dados[campo] = int(valores[campo])
    dados["portas"] = [p for p in re.split(r"[\s,]+", valores.get("portas", "").strip()) if p]
    for campo in ("config_files", "backup_paths"):
        dados[campo] = [p.strip() for p in valores.get(campo, "").replace(",", "\n").splitlines() if p.strip()]
    dados["receitas"] = []
    dados["deslocavel"] = valores.get("deslocavel") == "1"
    return dados


def _completo(modelo) -> dict:
    """O que a pessoa acrescenta a mao: identidade e app id (o resto vem do modelo)."""
    dados = _como_o_painel_monta(modelo.valores)
    dados.update(chave="meujogo", nome="Meu Jogo", app_id=123456)
    return dados


@pytest.mark.parametrize("modelo", modelos.MODELOS, ids=lambda m: m.chave)
def test_modelo_passa_no_validador_do_broker(modelo):
    jogo = validate_dynamic(_completo(modelo))
    assert jogo.key == "meujogo"


@pytest.mark.parametrize("modelo", modelos.MODELOS, ids=lambda m: m.chave)
def test_modelo_que_anda_de_porta_tem_os_marcadores(modelo):
    if modelo.valores.get("deslocavel") == "1":
        assert "{PORT}" in modelo.valores["start_args"]


def test_unreal_traz_o_padrao_de_log_dos_servidores_unreal():
    valores = modelos.UNREAL_LINUX.valores
    juncao = re.search(valores["join_re"], "LogNet: Join succeeded: Zeca")
    assert juncao is not None
    assert juncao.group("name") == "Zeca"
    assert re.search(valores["leave_re"], "LogNet: UNetConnection::Close: [UNetConnection] ...")


def test_unreal_deixa_o_nome_do_projeto_bem_visivel():
    """Um chute silencioso (uma pasta que parece certa) esconderia o erro; um nome de mentira
    obvio pede para ser trocado."""
    valores = modelos.UNREAL_LINUX.valores
    assert modelos.PROJETO in valores["config_path"]
    assert modelos.PROJETO in valores["backup_paths"]


def test_chaves_do_modelo_sao_campos_do_formulario_do_catalogo():
    html = (RAIZ / "src" / "gamepanel" / "templates" / "catalogo.html").read_text(encoding="utf-8")
    campos = set(re.findall(r'name="([a-z_]+)"', html))
    for modelo in modelos.MODELOS:
        assert set(modelo.valores) <= campos, set(modelo.valores) - campos
