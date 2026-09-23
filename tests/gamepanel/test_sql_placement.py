"""SQL de uma tabela mora no repositorio dela, e em lugar nenhum mais.

Este teste existe para o que ja aconteceu: o mesmo `SELECT * FROM servers WHERE id = ?`
estava em oito arquivos e a lista de colunas do `UPDATE` em mais quatro. Nada disso
quebra ao renomear uma coluna — quebra na PRIMEIRA VISITA a tela que usa a copia que
ficou para tras, em runtime, sem lint nem teste acusando. Foi por isso que as migrations
de rename precisaram ser escritas com tanto cuidado.

A regra e por TABELA, e nao "nenhum SQL fora de persistence": as tabelas que ainda nao
ganharam repositorio continuam com SQL onde estao, e entram aqui quando forem extraidas.
Uma lista que comeca completa e mentira; esta cresce junto com o trabalho.
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

# Tabela -> modulo que passa a ser o unico lugar com SQL dela.
OWNED = {"servers": "servers.py"}

STATEMENT = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(\w+)|DELETE\s+FROM\s+(\w+)", re.IGNORECASE)


def _python_files() -> list[Path]:
    return [p for p in sorted(PANEL.rglob("*.py")) if "__pycache__" not in p.parts]


def _code_only(source: str) -> str:
    """A fonte sem comentario e sem docstring.

    Sem isto o teste acusa a propria prosa que o explica: o `__init__.py` dos
    repositorios cita `SELECT * FROM servers WHERE id = ?` como exemplo do problema, e
    para um regex isso e SQL igual ao de verdade.
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
    saida = []
    for tok in tokenize.generate_tokens(io.StringIO(sem_docstring).readline):
        if tok.type != tokenize.COMMENT:
            saida.append(tok.string)
    return " ".join(saida)


def _tables_in(path: Path) -> set[str]:
    text = _code_only(path.read_text(encoding="utf-8"))
    return {(a or b).lower() for a, b in STATEMENT.findall(text) if (a or b)}


def test_a_varredura_encontra_sql():
    """Zero tabelas encontradas e o jeito silencioso de este teste parar de valer."""
    achadas = set()
    for path in _python_files():
        achadas |= _tables_in(path)
    assert "servers" in achadas, "a varredura de SQL nao esta encontrando nada"


@pytest.mark.parametrize(("table", "module"), sorted(OWNED.items()))
def test_a_tabela_so_tem_sql_no_repositorio_dela(table: str, module: str):
    dono = REPOSITORIES / module
    assert dono.exists(), f"o repositorio de `{table}` nao existe: {dono}"
    fora = sorted(
        p.relative_to(PANEL).as_posix()
        for p in _python_files()
        if p != dono and table in _tables_in(p)
        # O esquema e as migrations falam de TODA tabela por definicao.
        and p.parent.name != "persistence"
    )
    assert fora == [], (
        f"SQL da tabela `{table}` fora de `persistence/repositories/{module}`:\n  "
        + "\n  ".join(fora)
        + f"\n\nUse `from gamepanel.persistence.repositories import {table} as {table}_repo`.")
