"""Each bucket of the suite has to RUN ON ITS OWN. That is what gives the short cycle.

`unit/` takes 28 s and `integration/` takes 126 s: the split exists so you edit with the
fast bucket and leave the slow one for before publishing. If an `integration/` file imports
a `unit/` file by NAME, that works in the full suite - pytest puts the folder of every file
it collects on `sys.path`, and `unit/` was collected first - and blows up with
`ModuleNotFoundError` as soon as someone runs only `integration/`. Measured before the
split, in a separate experiment; it is why `FakeRunner` moved out of
`test_ssh_installer.py` into `fake_ssh.py`.

A double shared by more than one file lives next to `conftest.py`, which is the folder
pytest always inserts into `sys.path`. That is what `fake_http.py` and `fake_ssh.py` do.
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
    """Every `import X` / `from X import ...` of a BARE name (no dot), at any level.

    Includes imports inside functions: `test_integration.py` did exactly that, and a lazy
    import blows up at test time instead of at collection - later and more confusing.
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
    """If a `fake_*.py` lands inside a bucket, only that bucket can reach it."""
    misplaced = [f"{b.parent.name}/{b.name}/{p.name}"
                 for b in BUCKETS for p in b.glob("fake_*.py")]
    assert misplaced == [], "dobre dentro de um balde:\n  " + "\n  ".join(misplaced)
