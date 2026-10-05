"""The contract between `app.py` and the templates: who passes and who reads.

This file exists because of a real defect. While translating the identifiers into
English, a `render_template(instancias=...)` became `instances=...` and
`instances.html` started rendering an EMPTY list -- no error, no 500, nothing in the
log. Jinja treats a missing variable as undefined and moves on, so the only clue
was the blank screen.

No route test caught it (the page answers 200), nor did mypy, because the name only
exists as text on both sides.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from jinja2 import meta

from gamepanel import app as panel


def _read_by_templates() -> dict[str, str]:
    """Name -> first template that reads it. Uses the panel's REAL environment.

    A bare `Environment()` does not even parse these files: they use the panel's own filters
    (`filesize`, `duration`, `level`, `ident`), and Jinja fails at compile time when it does
    not recognise them.
    """
    read_ones: dict[str, str] = {}
    # `app.template_folder` is relative ("templates"): resolved from the working
    # directory it finds nothing, and the test would pass believing nobody reads anything.
    root = Path(panel.__file__).parent / panel.app.template_folder
    for file_path in sorted(root.rglob("*.html")):
        source = file_path.read_text(encoding="utf-8")
        for name in meta.find_undeclared_variables(panel.app.jinja_env.parse(source)):
            read_ones.setdefault(name, file_path.name)
    return read_ones


def _files_that_render() -> list[Path]:
    """`app.py` plus every blueprint - that is where the `render_template` calls live today.

    Scanning only `app.py`, as this test used to, stopped covering anything the day the
    routes moved out of it: the test stayed green with zero calls found.
    That is why the list is derived from the FOLDER, and not written by hand.
    """
    root = Path(panel.__file__).parent
    return [root / "app.py", *sorted((root / "blueprints").glob("*.py"))]


def _passed_by_the_app() -> list[tuple[str, str, str]]:
    """(template, kwarg name, where) of every `render_template` in the panel."""
    passed = []
    for file_path in _files_that_render():
        for no in ast.walk(ast.parse(file_path.read_text(encoding="utf-8"))):
            if not (isinstance(no, ast.Call) and getattr(no.func, "id", "") == "render_template"
                    and no.args):
                continue
            target = no.args[0]
            template = target.value if isinstance(target, ast.Constant) else "?"
            for kw in no.keywords:
                if kw.arg:
                    passed.append((template, kw.arg, f"{file_path.name}:{no.lineno}"))
    return passed


def test_a_varredura_encontra_os_render_template_de_verdade():
    """Guard for the test itself: zero calls is the silent way for it to stop meaning anything."""
    passed = _passed_by_the_app()
    assert len(passed) > 50, f"so {len(passed)} kwargs encontrados - a varredura quebrou?"
    assert len({where_clause.split(":")[0] for _t, _n, where_clause in passed}) > 10


def test_todo_kwarg_de_render_template_tem_quem_o_leia():
    read_ones = _read_by_templates()
    orphans = [
        f"{where_clause} {template} passa '{name}', que nenhum template le"
        for template, name, where_clause in _passed_by_the_app()
        # The `.jinja` ones (service worker, manifest) are not part of the `*.html` scan.
        if name not in read_ones and not template.endswith(".jinja")
    ]
    assert orphans == [], "kwarg sem leitor (a tela fica vazia, sem erro):\n" + "\n".join(orphans)


@pytest.mark.parametrize("name", ["csrf_token", "_", "_h", "url_for", "is_admin"])
def test_o_contexto_global_cobre_o_que_todo_template_usa(name):
    """These come from the `context_processor`, not from a `render_template` - and missing one
    of them does not show up on a single screen: it shows up on all of them."""
    with panel.app.test_request_context("/"):
        assert name in panel.app.jinja_env.globals or name in _context()


def _context() -> dict:
    together: dict = {}
    for f in panel.app.template_context_processors[None]:
        together.update(f())
    return together
