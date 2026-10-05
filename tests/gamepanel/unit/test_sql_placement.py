"""A table's SQL lives in its repository, and nowhere else.

This test exists for what already happened: the same `SELECT * FROM servers WHERE id = ?`
was in eight files and the `UPDATE` column list in four more. None of that breaks when a
column is renamed - it breaks on the FIRST VISIT to the screen that uses the copy left
behind, at runtime, with no lint or test flagging it. That is why the rename migrations
had to be written so carefully.

The rule is per TABLE, not "no SQL outside persistence": a new table that has not got a
repository yet keeps its SQL where it is, and enters here when it is extracted. A list that
starts out complete is a lie; this one grows along with the work - today it covers the
panel's seven tables.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from gamepanel import app as panel

PANEL = Path(panel.__file__).parent
REPOSITORIES = PANEL / "persistence" / "repositories"

# Table -> the module that becomes the only place with SQL for it.
OWNED = {
    "servers": "servers.py",
    "jobs": "jobs.py",
    "schedules": "schedules.py",
    "webhooks": "alerts.py",
    "alert_log": "alerts.py",
    "samples": "samples.py",
    "settings": "settings.py",
    "users": "users.py",
    "passkeys": "passkeys.py",
}

STATEMENT = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)|DELETE\s+FROM\s+(\w+)", re.IGNORECASE)


def _python_files() -> list[Path]:
    return [p for p in sorted(PANEL.rglob("*.py")) if "__pycache__" not in p.parts]


def _code_only(source: str) -> str:
    """The source without comments and without docstrings.

    Without this the test flags the very prose that explains it: the repositories'
    `__init__.py` quotes `SELECT * FROM servers WHERE id = ?` as an example of the problem,
    and to a regex that is SQL just like the real thing.
    """
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    fora = {(n.lineno, n.end_lineno) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and id(n) in docstrings}
    lines = source.splitlines()
    for first, last in fora:
        for i in range(first - 1, (last or first)):
            lines[i] = ""
    sem_docstring = chr(10).join(lines)
    output = []
    for tok in tokenize.generate_tokens(io.StringIO(sem_docstring).readline):
        if tok.type != tokenize.COMMENT:
            output.append(tok.string)
    return " ".join(output)


def _tables_in(path: Path) -> set[str]:
    text = _code_only(path.read_text(encoding="utf-8"))
    return {(a or b).lower() for a, b in STATEMENT.findall(text) if (a or b)}


def test_a_varredura_encontra_sql():
    """Zero tables found is the silent way for this test to stop meaning anything."""
    achadas = set()
    for path in _python_files():
        achadas |= _tables_in(path)
    assert "servers" in achadas, "a varredura de SQL nao esta encontrando nada"


@pytest.mark.parametrize(("table", "module"), sorted(OWNED.items()))
def test_a_tabela_so_tem_sql_no_repositorio_dela(table: str, module: str):
    owner = REPOSITORIES / module
    assert owner.exists(), f"o repositorio de `{table}` nao existe: {owner}"
    fora = sorted(
        p.relative_to(PANEL).as_posix()
        for p in _python_files()
        if p != owner and table in _tables_in(p)
        # The schema and the migrations talk about EVERY table by definition.
        and p.parent.name != "persistence"
    )
    assert fora == [], (
        f"SQL da tabela `{table}` fora de `persistence/repositories/{module}`:\n  "
        + "\n  ".join(fora)
        + f"\n\nUse `from gamepanel.persistence.repositories import {table} as {table}_repo`.")
