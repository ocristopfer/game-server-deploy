"""Screen text must not be born a literal: `translate` would return the sentence as is.

The `i18n` cascade is "requested language -> pt -> the key itself". A whole sentence passed
to `translate` is not a key of anything, so it comes out UNCHANGED - and the English screen
shows Portuguese, with no error, no log and no other test complaining: `test_i18n.py` checks
the CALLS of `_()`/`_h()`, not what a function returned.

It has already happened twice. First in the two password sentences and the history label
`broker-jogo`. Then in sixteen more, found against the live container: with the screen in
English, the operator 403 said "restrita" and the nonexistent route said "Pagina nao
encontrada". The barriers (`abort`), the form errors (`errors.append`) and the flashes were
all literals.

The test looks at the three doors through which text reaches the screen and demands a KEY,
never a sentence: `abort(codigo, ...)`, `errors.append(...)` and `flash(...)`. A call with
`Message(...)`, `translate(...)` or a variable passes; a literal with a space does not.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[3]
SCREEN_FILES = [ROOT / "src/gamepanel/app.py",
                *sorted((ROOT / "src/gamepanel/blueprints").glob("*.py"))]

# Where the text reaches the PERSON. `_log_broker_action` and `notify` are left out: the first
# writes a job's output (in the deploy language, on purpose - see `label_for_db`) and the
# second builds the channel notice, which follows the same rule.
DOORS = {"abort", "flash", "append"}


def _sentences() -> list[tuple[str, int, str]]:
    """Literals with a space that come in through one of the doors. The space is the signal: a
    catalog key (`error.admin_only`) never has one, a sentence always does."""
    found: list[tuple[str, int, str]] = []
    for path in SCREEN_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in DOORS:
                continue
            # `errors.append` is the door; `log.append`/`lines.append` are not screen.
            if name == "append" and getattr(node.func, "value", None) is not None:
                target = getattr(node.func.value, "id", "")
                if target not in ("errors", "failures"):
                    continue
            for arg in node.args:
                # `abort(403, ...)`: the code is the first argument and is not text.
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and " " in arg.value:
                    found.append((path.name, node.lineno, arg.value))
                # An f-string with a sentence inside counts the same: it is not a key either.
                if isinstance(arg, ast.JoinedStr):
                    text = "".join(v.value for v in arg.values
                                   if isinstance(v, ast.Constant) and isinstance(v.value, str))
                    if " " in text.strip():
                        found.append((path.name, node.lineno, text))
    return found


def test_nenhuma_frase_literal_chega_a_tela():
    leftover = sorted({f"{f}:{n} {text[:60]!r}" for f, n, text in _sentences()})
    assert leftover == [], (
        "frase literal indo para a tela; ela sai igual no idioma de quem olha. Ponha em "
        "pt.py/en.py e use i18n.Message(chave):\n  " + "\n  ".join(leftover))


def test_a_varredura_olha_para_os_arquivos_de_tela():
    """Zero files is the silent way for this test to stop meaning anything."""
    assert len(SCREEN_FILES) >= 15


@pytest.mark.parametrize("key", [
    "error.not_found", "error.admin_only", "error.terminal_disabled",
    "error.broker_disabled", "flash.server_duplicate", "flash.username_invalid",
    "flash.schedule_bad_interval", "error.upload_too_large",
])
def test_as_chaves_das_barreiras_existem_nos_DOIS_idiomas(key: str):
    """A key without its pair shows on screen as `error.admin_only`, which is loud but ugly."""
    assert key in i18n.CATALOGS["pt"]
    assert key in i18n.CATALOGS["en"]
