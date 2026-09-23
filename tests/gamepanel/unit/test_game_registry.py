"""O registro de adapters de jogo: nenhum fica de fora, nenhum colide.

Acrescentar um jogo e criar um modulo em `games/adapters/` e uma linha em
`registry.ADAPTERS`. Esquecer a linha nao da erro: a tela do jogo continua caindo no
editor generico, que funciona — e por isso ninguem percebe. Este teste percebe.
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
    """Zero adapters e o jeito silencioso de este teste parar de valer."""
    assert len(_modules_on_disk()) >= 5


@pytest.mark.parametrize("name", _modules_on_disk())
def test_o_adapter_expoe_o_contrato(name: str):
    """`FILENAME` (que arquivo ele reconhece) e `FIELDS` (o que ele sabe sobre ele)."""
    module = importlib.import_module(f"gamepanel.games.adapters.{name}")
    assert hasattr(module, "FILENAME"), f"{name} nao declara FILENAME"
    assert hasattr(module, "FIELDS"), f"{name} nao declara FIELDS"
    assert module.FIELDS, f"{name} tem catalogo vazio"
    assert all(isinstance(v, FieldSpec) for v in module.FIELDS.values())


def test_dois_adapters_nao_disputam_o_mesmo_arquivo():
    """O primeiro da lista venceria, e o segundo viraria codigo morto silencioso."""
    conflitos = []
    for i, first in enumerate(registry.ADAPTERS):
        for second in registry.ADAPTERS[i + 1:]:
            exemplo = first.FILENAME.pattern.strip("^$").replace("\\", "")
            if second.FILENAME.match(exemplo):
                conflitos.append(f"{first.__name__} x {second.__name__} em {exemplo}")
    assert conflitos == []


def test_arquivo_desconhecido_cai_no_editor_generico():
    """Jogo sem adapter nao fica de fora do painel: ele edita o arquivo como texto."""
    assert registry.catalog_for("config_de_um_jogo_novo.ini") == {}
    assert registry.describe("config_de_um_jogo_novo.ini", "qualquer") is None


def test_o_caminho_completo_resolve_pelo_nome_do_arquivo():
    """O painel passa o caminho como o container o devolveu."""
    assert registry.describe("/opt/game/Config/serverDZ.cfg", "hostname") is not None
