"""O contrato entre o `app.py` e os templates: quem passa e quem le.

Este arquivo existe por causa de um defeito real. Durante a traducao dos identificadores
para ingles, um `render_template(instancias=...)` virou `instances=...` e o
`instancias.html` passou a renderizar uma lista VAZIA -- sem erro, sem 500, sem nada no
log. Jinja trata variavel ausente como indefinida e segue em frente, entao a unica pista
era a tela em branco.

Nenhum teste de rota pegava isso (a pagina responde 200), e nem o mypy, porque o nome so
existe como texto dos dois lados.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from jinja2 import meta

from gamepanel import app as panel


def _lidos_pelos_templates() -> dict[str, str]:
    """Nome -> primeiro template que o le. Usa o ambiente DE VERDADE do painel.

    Um `Environment()` cru nem parseia estes arquivos: eles usam os filtros proprios
    (`filesize`, `duration`, `level`, `ident`), e o Jinja falha na compilacao ao nao
    reconhece-los.
    """
    lidos: dict[str, str] = {}
    # `app.template_folder` e relativo ("templates"): resolvido a partir do diretorio
    # de trabalho ele nao acha nada, e o teste passaria achando que ninguem le nada.
    raiz = Path(panel.__file__).parent / panel.app.template_folder
    for arquivo in sorted(raiz.rglob("*.html")):
        fonte = arquivo.read_text(encoding="utf-8")
        for name in meta.find_undeclared_variables(panel.app.jinja_env.parse(fonte)):
            lidos.setdefault(name, arquivo.name)
    return lidos


def _passados_pelo_app() -> list[tuple[str, str, int]]:
    """(template, nome do kwarg, linha) de cada `render_template` do `app.py`."""
    fonte = Path(panel.__file__).read_text(encoding="utf-8")
    passados = []
    for no in ast.walk(ast.parse(fonte)):
        if not (isinstance(no, ast.Call) and getattr(no.func, "id", "") == "render_template"
                and no.args):
            continue
        alvo = no.args[0]
        template = alvo.value if isinstance(alvo, ast.Constant) else "?"
        for kw in no.keywords:
            if kw.arg:
                passados.append((template, kw.arg, no.lineno))
    return passados


def test_todo_kwarg_de_render_template_tem_quem_o_leia():
    lidos = _lidos_pelos_templates()
    orfaos = [
        f"app.py:{line} {template} passa '{name}', que nenhum template le"
        for template, name, line in _passados_pelo_app()
        # O `.jinja` (service worker, manifest) nao entra na varredura de `*.html`.
        if name not in lidos and not template.endswith(".jinja")
    ]
    assert orfaos == [], "kwarg sem leitor (a tela fica vazia, sem erro):\n" + "\n".join(orfaos)


@pytest.mark.parametrize("name", ["csrf_token", "_", "_h", "url_for", "is_admin"])
def test_o_contexto_global_cobre_o_que_todo_template_usa(name):
    """Estes vem do `context_processor`, nao de um `render_template` — e a falta de um
    deles nao aparece numa tela so: aparece em todas."""
    with panel.app.test_request_context("/"):
        assert name in panel.app.jinja_env.globals or name in _contexto()


def _contexto() -> dict:
    junto: dict = {}
    for f in panel.app.template_context_processors[None]:
        junto.update(f())
    return junto
