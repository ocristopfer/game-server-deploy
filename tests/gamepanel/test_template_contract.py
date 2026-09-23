"""O contrato entre o `app.py` e os templates: quem passa e quem le.

Este arquivo existe por causa de um defeito real. Durante a traducao dos identificadores
para ingles, um `render_template(instancias=...)` virou `instances=...` e o
`instances.html` passou a renderizar uma lista VAZIA -- sem erro, sem 500, sem nada no
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


def _arquivos_que_renderizam() -> list[Path]:
    """`app.py` mais todo blueprint — e ali que os `render_template` moram hoje.

    Varrer so o `app.py`, como este teste fazia, deixou de cobrir coisa alguma no dia em
    que as rotas sairam dele: o teste continuava verde com zero chamadas encontradas.
    Por isso a lista e derivada da PASTA, e nao escrita a mao.
    """
    raiz = Path(panel.__file__).parent
    return [raiz / "app.py", *sorted((raiz / "blueprints").glob("*.py"))]


def _passados_pelo_app() -> list[tuple[str, str, str]]:
    """(template, nome do kwarg, onde) de cada `render_template` do painel."""
    passados = []
    for arquivo in _arquivos_que_renderizam():
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if not (isinstance(no, ast.Call) and getattr(no.func, "id", "") == "render_template"
                    and no.args):
                continue
            alvo = no.args[0]
            template = alvo.value if isinstance(alvo, ast.Constant) else "?"
            for kw in no.keywords:
                if kw.arg:
                    passados.append((template, kw.arg, f"{arquivo.name}:{no.lineno}"))
    return passados


def test_a_varredura_encontra_os_render_template_de_verdade():
    """Guarda do proprio teste: zero chamadas e o jeito silencioso de ele parar de valer."""
    passados = _passados_pelo_app()
    assert len(passados) > 50, f"so {len(passados)} kwargs encontrados - a varredura quebrou?"
    assert len({onde.split(":")[0] for _t, _n, onde in passados}) > 10


def test_todo_kwarg_de_render_template_tem_quem_o_leia():
    lidos = _lidos_pelos_templates()
    orfaos = [
        f"{onde} {template} passa '{name}', que nenhum template le"
        for template, name, onde in _passados_pelo_app()
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
