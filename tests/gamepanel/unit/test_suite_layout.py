"""Cada balde da suite tem de RODAR SOZINHO. E isso que da o ciclo curto.

`unit/` leva 28 s e `integration/` leva 126 s: a divisao existe para editar com o balde
rapido e deixar o lento para antes de publicar. Se um arquivo de `integration/` importar
por NOME um arquivo de `unit/`, isso funciona na suite inteira — o pytest poe no `sys.path`
a pasta de cada arquivo que coleta, e `unit/` foi coletado primeiro — e estoura com
`ModuleNotFoundError` na hora em que alguem roda so `integration/`. Medido antes da
divisao, num experimento a parte; e a razao de `FakeRunner` ter saido de dentro de
`test_ssh_installer.py` para o `fake_ssh.py`.

Dobre compartilhado por mais de um arquivo mora ao lado do `conftest.py`, que e a pasta que
o pytest sempre insere no `sys.path`. E o que `fake_http.py` e `fake_ssh.py` fazem.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parents[2]
BUCKETS = [TESTS / pkg / bucket
           for pkg in ("gamepanel", "gamebroker") for bucket in ("unit", "integration")]


def _test_modules() -> set[str]:
    return {p.stem for bucket in BUCKETS for p in bucket.glob("test_*.py")}


def _imports_of(path: Path) -> set[str]:
    """Todo `import X` / `from X import ...` de nome SOLTO (sem ponto), em qualquer nivel.

    Inclui import dentro de funcao: `test_integration.py` fazia exatamente isso, e um
    import preguicoso estoura na hora do teste em vez da coleta — mais tarde e mais confuso.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_a_varredura_encontra_os_baldes():
    assert len(BUCKETS) == 4
    assert all(b.is_dir() for b in BUCKETS), [str(b) for b in BUCKETS if not b.is_dir()]
    assert len(_test_modules()) >= 40


def test_nenhum_teste_importa_outro_arquivo_de_teste():
    modules = _test_modules()
    leftover = []
    for bucket in BUCKETS:
        for path in sorted(bucket.glob("test_*.py")):
            for name in sorted(_imports_of(path) & modules - {path.stem}):
                leftover.append(f"{path.parent.name}/{path.name} importa {name}")
    assert leftover == [], (
        "arquivo de teste importando outro: funciona na suite inteira e quebra rodando so um "
        "balde. Mova o que e compartilhado para um dobre ao lado do conftest.py:\n  "
        + "\n  ".join(leftover))


def test_o_dobre_compartilhado_mora_ao_lado_do_conftest():
    """Se um `fake_*.py` cair dentro de um balde, so aquele balde o alcanca."""
    misplaced = [f"{b.parent.name}/{b.name}/{p.name}"
                 for b in BUCKETS for p in b.glob("fake_*.py")]
    assert misplaced == [], "dobre dentro de um balde:\n  " + "\n  ".join(misplaced)
