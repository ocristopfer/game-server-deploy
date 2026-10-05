"""The contract between template, CSS and JavaScript: who writes and who reads.

Same family of defect that `test_template_contract.py` guards, and for the same reason:
the name exists as TEXT on both sides and no tool links the two.

- a class only in `class=` is a style that never arrives - the screen opens crooked, with 200;
- a class only in the `.css` is a dead rule, which the next person tries to "use";
- a `data-*` only in the template is behavior that never mounts, with no error in the console;
- a `data-*` only in the JavaScript is a feature that never finds any element.

None of the four shows up in a route test (the page answers 200) nor in the lint.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gamepanel import app as panel

PANEL = Path(panel.__file__).parent
TEMPLATES = PANEL / "templates"
CSS_DIR = PANEL / "static" / "css"
JS_DIR = PANEL / "static" / "js"

CLASS_ATTR = re.compile(r"""class=["']([^"']*)["']""")
# `{{ 'x' if cond }}` inside class=: what is left after removing the Jinja braces.
JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
CSS_RULE = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
DATA_ATTR = re.compile(r"data-([a-z][a-z0-9-]*)")

# Classes born in JavaScript or coming from a server value, so they never appear
# literally in any `class=`. Each one is a decision, not a generic exception.
CLASSES_SEM_TEMPLATE = {
    # State that the JS turns on and off.
    "on", "off", "ok", "warn", "hot", "cold", "open", "js",
    # Reset utilities, applied to raw elements.
    "html",
}


# `{% set classes = classes + ['btn--block'] %}` - the FULL name, and not a prefix
# built with `~`: this one the test can check against the CSS.
SET_CLASS = re.compile(r"""\+\s*\[["']([\w-]+)["']\]""")


def _templates() -> list[Path]:
    return sorted(p for p in TEMPLATES.rglob("*") if p.suffix in (".html", ".jinja"))


def classes_in_templates() -> dict[str, str]:
    """Class -> first template that uses it.

    The Jinja goes out BEFORE looking for `class=`: `class="menu{{ ' ' ~ classe if classe }}"`
    has a single quote inside the attribute, and a regex that only counts quotes would close
    in the middle of the expression and collect `menu{{` as if it were a class.
    """
    found: dict[str, str] = {}
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        clean = JINJA_EXPR.sub(" ", text)
        for attr in CLASS_ATTR.findall(clean):
            for name in attr.split():
                found.setdefault(name, path.name)
        # Class built as a LIST in the Jinja itself: `{% set classes = classes +
        # ['btn--block'] %}`. It never appears in a `class=`, so the `JINJA_EXPR.sub`
        # above erases it along with the rest of the expression - and that is how `btn--bloco`
        # survived without any CSS rule. Every `block=true` button in the panel (login,
        # account, forms) stopped filling the full width of the card and nothing
        # flagged it: the HTML comes out whole, the page answers 200 and the class simply
        # matches no rule.
        for name in SET_CLASS.findall(text):
            found.setdefault(name, path.name)
    return found


def class_prefixes_in_templates() -> set[str]:
    """Prefixes of classes BUILT at runtime: `'btn--' ~ variante` becomes `btn--`.

    Without this, every variation (`btn--danger`, `btn--sm`, ...) would look like a dead
    rule: the full name exists nowhere in the template.
    """
    prefixes: set[str] = set()
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        prefixes |= set(re.findall(r"""["']([\w-]*--)["']\s*~""", text))
        prefixes |= set(re.findall(r"""["']([\w-]*-)["']\s*~""", text))
    return prefixes


def names_seen_anywhere() -> set[str]:
    """Every loose identifier in templates and JavaScript.

    For the "dead rule" direction it is enough for the name to APPEAR: it can reach `class=`
    through a macro argument, a `{% set %}` or a `classList.add`. Being strict here would
    only produce hand-written exceptions, which is what this test exists to avoid.
    """
    names: set[str] = set()
    for path in [*_templates(), *sorted(JS_DIR.rglob("*.js"))]:
        names |= set(re.findall(r"[\w-]+", path.read_text(encoding="utf-8")))
    return names


def classes_in_css() -> set[str]:
    names: set[str] = set()
    for path in sorted(CSS_DIR.glob("*.css")):
        names |= set(CSS_RULE.findall(path.read_text(encoding="utf-8")))
    return names


def _js_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.rglob("*.js")))


def classes_in_js() -> set[str]:
    text = _js_text()
    names = set()
    # `classList.add('x')`, `classList.toggle('x', cond)`, `querySelector('.x')`
    for chunk in re.findall(r"classList\.\w+\(([^)]*)\)", text):
        names |= set(re.findall(r"""["']([\w-]+)["']""", chunk))
    for chunk in re.findall(r"""["']\.([\w-]+)["']""", text):
        names.add(chunk)
    return names


def data_in_templates() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _templates():
        for name in DATA_ATTR.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, path.name)
    return found


def data_in_js() -> set[str]:
    text = _js_text()
    names = set(re.findall(r"\[data-([a-z][a-z0-9-]*)\]", text))
    # `el.dataset.jobUrl` -> data-job-url
    for camel in re.findall(r"dataset\.([a-zA-Z][a-zA-Z0-9]*)", text):
        names.add(re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), camel))
    return names


def test_toda_classe_usada_num_template_tem_regra_no_css():
    """A class without a rule is a style that never arrives: the screen opens crooked, and answers 200."""
    styled = classes_in_css() | classes_in_js()
    orphans = sorted(
        f"{name} (em {where})"
        for name, where in classes_in_templates().items()
        if name not in styled
    )
    assert orphans == [], "classe usada sem regra de CSS:\n  " + "\n  ".join(orphans)


def test_toda_regra_de_css_tem_quem_a_use():
    """A dead rule is worse than useless: the next person reads it as if it were in use."""
    used = names_seen_anywhere() | CLASSES_SEM_TEMPLATE
    prefixes = tuple(class_prefixes_in_templates())
    dead = sorted(
        name for name in classes_in_css()
        if name not in used and not (prefixes and name.startswith(prefixes))
    )
    assert dead == [], "regra de CSS que ninguem usa:\n  " + "\n  ".join(dead)


def test_todo_data_lido_pelo_javascript_existe_em_algum_template():
    """A feature looking for a nonexistent `data-*` never mounts, and says nothing."""
    written = set(data_in_templates())
    orphans = sorted(name for name in data_in_js() if name not in written)
    assert orphans == [], "data-* que o JS procura e nenhum template escreve:\n  " + "\n  ".join(orphans)


@pytest.mark.parametrize("feature", [
    "confirmAction", "dropdownMenu", "chart", "followLog", "watchJob",
])
def test_o_app_js_registra_a_feature_que_o_modulo_exporta(feature):
    """`app.js` links a feature to an element by NAME: exporting without registering is the
    same as not existing."""
    app_js = (JS_DIR / "app.js").read_text(encoding="utf-8")
    assert feature in app_js


# `server_detail.html` reads `metrics.X` directly. An `X` the meter does not deliver raises
# nothing: it vanishes from the screen and the page answers 200. That is how `metrics.cores`
# became `metrics.colors` in a rename and the core count vanished without breaking any test.
#
# The list of fields is NOT written here: it comes from `parse_metrics` itself, so it does
# not become one more copy that ages silently.
METRICS_SAMPLE = """sample|1000|100000|0|0|0|0|0|0
sample|2000|200000|0|0|0|0|0|0
cores|4
cpumax|400
tick|100
load|0.5
boot|1000
meminfo|MemTotal|1000
meminfo|MemAvailable|500
meminfo|SwapTotal|0
meminfo|SwapFree|0
disk|/|1000|500
proc|123|4096
"""


def _meter_fields() -> set[str]:
    from gamepanel.runtime import metrics_probe

    return set(metrics_probe.parse_metrics(METRICS_SAMPLE))


def test_a_tela_de_servidor_le_so_campos_que_o_medidor_entrega():
    html = (TEMPLATES / "server_detail.html").read_text(encoding="utf-8")
    read_ones = set(re.findall(r"metrics\.([a-z_]+)", html))
    # `error` appears when the reading FAILS, so it is not in the good sample.
    missing = sorted(read_ones - _meter_fields() - {"error"})
    assert missing == [], f"a tela le campo que o medidor nao entrega: {missing}"


def test_o_medidor_ainda_entrega_o_numero_de_nucleos():
    """`cores` is the colliding word: CPU cores in English, colors in Portuguese. An
    automatic rename once swapped one for the other on both sides."""
    assert "cores" in _meter_fields()


# ---------------------------------------------------- CSS tokens (custom properties)

CSS_VAR_DEF = re.compile(r"^\s*(--[\w-]+)\s*:", re.M)
CSS_VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")

# Names BORN outside the CSS. `--safe-*` comes from `env(safe-area-inset-*)` via an `@supports`
# that builds the name; the two full screens (terminal and console) write the height from JS.
VARS_SEM_DEFINICAO: set[str] = set()
VARS_SEM_USO = {
    # Defined only so the notch `@supports` can swap the value; the usage is the fallback itself.
    "--safe-top", "--safe-bottom", "--safe-left", "--safe-right",
}


def _all_css_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(CSS_DIR.rglob("*.css")))


def css_vars_defined() -> set[str]:
    return set(CSS_VAR_DEF.findall(_all_css_text()))


def css_vars_used() -> set[str]:
    text = _all_css_text() + _js_text()
    for path in _templates():
        text += path.read_text(encoding="utf-8")
    return set(CSS_VAR_USE.findall(text))


def test_todo_token_de_css_definido_e_usado():
    """A dead token is the same trap as a dead rule, and it escaped this file.

    `--sombra-1` stayed defined in `tokens.css` without a single `var(--sombra-1)` in the
    repository: whoever read the list of shadows would think three levels were available.
    """
    dead = sorted(css_vars_defined() - css_vars_used() - VARS_SEM_USO)
    assert dead == [], "token de CSS definido e nunca usado:\n  " + "\n  ".join(dead)


def test_todo_token_de_css_usado_esta_definido():
    """`var(--name-that-does-not-exist)` is not an error for any browser: the property
    simply does not apply, and the screen opens without the color, the spacing or the radius."""
    orphans = sorted(css_vars_used() - css_vars_defined() - VARS_SEM_DEFINICAO)
    assert orphans == [], "var(--x) sem definicao em tokens.css:\n  " + "\n  ".join(orphans)


# ---------------------------------------------------------- raw values outside tokens.css

RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# `color-mix(... , #fff)` and `#000` are mixing OPERANDS - "lighten this", not a theme
# color. Recognized by their shape, and not by a list that would age.
MIX_OPERAND = {"#fff", "#000", "#ffffff", "#000000"}
# Raw colors that are a PHYSICAL REQUIREMENT, with the reason in the CSS itself. There are
# two, and each would break in a different way if it became a token.
COLOR_OUTSIDE_TOKENS = {
    # The QR needs a white background for the camera to lock onto it; a token would follow
    # dark mode and no reader would find the code.
    "components.css": {"#fff"},
    # Terminal foreground, which follows the ANSI palette of `terminal.js` (protocol,
    # not theme).
    "pages.css": {"#c9d3de"},
}


def test_cor_crua_so_em_tokens_css():
    """A color hand-written in a component does not follow the theme and is not in the palette.

    The exception is not a list of names that ages: it is `color-mix(..., #fff)`, recognized
    by its shape, plus two colors with a PHYSICAL reason written in the file itself.
    """
    leftover = []
    for path in sorted(CSS_DIR.rglob("*.css")):
        if path.name == "tokens.css":
            continue
        allowed = MIX_OPERAND | COLOR_OUTSIDE_TOKENS.get(path.name, set())
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("/*", 1)[0]
            for color in RAW_COLOR.findall(code):
                if color.lower() not in allowed:
                    leftover.append(f"{path.name}:{i} {color}")
    assert leftover == [], (
        "cor crua fora de tokens.css (ela nao acompanha o tema):\n  " + "\n  ".join(leftover))


def test_todo_estado_tem_o_par_de_cor_de_texto():
    """`--ok` had a border and no text, and `.flash.ok` made do with a loose hex."""
    tokens = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    for state in ("ok", "err"):
        assert f"--{state}-text:" in tokens, f"falta --{state}-text em tokens.css"
        assert f"--{state}-line:" in tokens, f"falta --{state}-line em tokens.css"


# ------------------------------------------- the meter thresholds, in BOTH places

def test_o_limite_de_cor_da_barra_e_o_mesmo_no_python_e_no_javascript():
    """The bar is drawn on the SERVER and updated by JS: two owners of the same number.

    The panel renders the bar with the `level` filter from `app.py` and then `format.js`
    rewrites it on every meter reading. If the thresholds diverge, the color changes on
    reload and not on the moving meter (or the opposite) - no error, no log, just a screen
    that contradicts itself. There is no build step in this repository to share the
    constant between Python and JavaScript, so the link is this test.
    """
    js = (JS_DIR / "core" / "format.js").read_text(encoding="utf-8")
    found = [int(n) for n in re.findall(r"pct >= (\d+)\)", js)]
    assert found, "o `level` do format.js deixou de comparar pct com um limite"
    assert found == [panel.GAUGE_HOT, panel.GAUGE_WARN], (
        f"limites do JS {found} x do Python [{panel.GAUGE_HOT}, {panel.GAUGE_WARN}]")
