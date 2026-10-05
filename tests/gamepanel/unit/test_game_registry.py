"""The game adapter registry: none left out, none colliding.

Adding a game means creating a module in `games/adapters/` and a line in
`registry.ADAPTERS`. Forgetting the line raises no error: the game screen keeps falling back
to the generic editor, which works - and that is why nobody notices. This test notices.
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

from gamepanel.games import adapters, registry
from gamepanel.games.base import FieldSpec


def _modules_on_disk() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(adapters.__path__)
                  if not m.name.startswith("_"))


def test_todo_adapter_da_pasta_esta_no_registro():
    na_pasta = set(_modules_on_disk())
    registrados = {a.__name__.rsplit(".", 1)[-1] for a in registry.ADAPTERS}
    assert na_pasta == registrados, (
        f"fora do registro: {sorted(na_pasta - registrados)}; "
        f"registrado e inexistente: {sorted(registrados - na_pasta)}")


def test_a_varredura_encontra_adapters():
    """Zero adapters is the silent way for this test to stop meaning anything."""
    assert len(_modules_on_disk()) >= 5


@pytest.mark.parametrize("name", _modules_on_disk())
def test_o_adapter_expoe_o_contrato(name: str):
    """`FILENAME` (which file it recognizes) and `FIELDS` (what it knows about that file)."""
    module = importlib.import_module(f"gamepanel.games.adapters.{name}")
    assert hasattr(module, "FILENAME"), f"{name} nao declara FILENAME"
    assert hasattr(module, "FIELDS"), f"{name} nao declara FIELDS"
    assert module.FIELDS, f"{name} tem catalogo vazio"
    assert all(isinstance(v, FieldSpec) for v in module.FIELDS.values())


def test_dois_adapters_nao_disputam_o_mesmo_arquivo():
    """The first in the list would win, and the second would become silent dead code."""
    conflitos = []
    for i, first in enumerate(registry.ADAPTERS):
        for second in registry.ADAPTERS[i + 1:]:
            exemplo = first.FILENAME.pattern.strip("^$").replace("\\", "")
            if second.FILENAME.match(exemplo):
                conflitos.append(f"{first.__name__} x {second.__name__} em {exemplo}")
    assert conflitos == []


def test_arquivo_desconhecido_cai_no_editor_generico():
    """A game without an adapter is not left out of the panel: it edits the file as text."""
    assert registry.catalog_for("config_de_um_jogo_novo.ini") == {}
    assert registry.describe("config_de_um_jogo_novo.ini", "qualquer") is None


def test_o_caminho_completo_resolve_pelo_nome_do_arquivo():
    """The panel passes the path as the container returned it."""
    assert registry.describe("/opt/game/Config/serverDZ.cfg", "hostname") is not None
