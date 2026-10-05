"""`url_for(..., key=value)` is a pair with whoever READS that key on the other side.

A `url_for` kwarg that is not a route capture becomes a QUERY STRING, and someone has to
`request.args.get` it with the same name. The two sides live as text in different files
and no tool links them: if the name diverges, the link keeps answering 200 and the value
simply never arrives.

It already happened three times at once, all from renaming the wire name on one side only -
and all in `url_for` built in PYTHON, which is where the template check does not look:

- `url_for("players.setup", sid=sid, aba="http")` after the route started reading `tab`:
  the "usar esta API" button went back to the ports tab instead of the HTTP one;
- the same with `aba="log"`;
- `{"pasta": request.args["path"]}` in the file search redirect, with the route reading
  `folder`: the chosen folder was lost and the search went to the registration's config folder.
"""
from __future__ import annotations

import ast
from pathlib import Path

import gamepanel.app as panel

PANEL = Path(panel.__file__).parent
PY_FILES = [PANEL / "app.py", *sorted((PANEL / "blueprints").glob("*.py"))]

# Kwargs that are NOT query strings: route captures (Flask consumes them in the URL) and the names
# Flask itself defines. Recognized from the routes' list of captures, not by hand.
FLASK_OWN = {"_external", "_anchor", "_method", "_scheme", "filename"}
# `v=` in `url_for("static", ...)` exists to CHANGE the URL, not to be read: it is the mark
# that busts the browser cache when a static file changes. Nobody reads it on the server, and
# that is intended.
NOT_READ_ON_PURPOSE = {"v"}


def _route_captures() -> set[str]:
    """Every `<int:sid>`/`<tid>` declared in the registered routes: those vanish into the URL."""
    found: set[str] = set()
    for rule in panel.app.url_map.iter_rules():
        found |= set(rule.arguments)
    return found


def _read_keys() -> set[str]:
    """A name that some `request.args/form/files.get(...)` reads."""
    found: set[str] = set()
    for path in sorted(PANEL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "getlist") and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def _dict_keys_named(tree: ast.AST, name: str, filename: str) -> list[tuple[str, int, str]]:
    """Keys of the literal dict assigned to `name` (includes `x: dict = {...}`)."""
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if getattr(target, "id", None) != name:
            continue
        value = node.value
        # `{...} if cond else {...}`: both sides count.
        options = ([value.body, value.orelse] if isinstance(value, ast.IfExp) else [value])
        for option in options:
            if isinstance(option, ast.Dict):
                for key in option.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.append((filename, option.lineno, key.value))
    return found


def _url_for_kwargs() -> list[tuple[str, int, str]]:
    """(file, line, key) of each `url_for` kwarg and of each dict that feeds it."""
    found: list[tuple[str, int, str]] = []
    for path in PY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "url_for"):
                continue
            for kw in node.keywords:
                if kw.arg:
                    found.append((path.name, node.lineno, kw.arg))
                # `**extras`, where `extras` is a literal dict assigned in the file: the key
                # name lives in a string, which is exactly the case that slipped by. Resolves the
                # NAME, and not every dict in the file - the first version of this collected the
                # HTTP header dicts and the test flagged `Content-Length=`.
                elif isinstance(kw.value, ast.Name):
                    found += _dict_keys_named(tree, kw.value.id, path.name)
    return found


def test_a_varredura_encontra_os_url_for():
    assert len({k for _f, _l, k in _url_for_kwargs()}) >= 6
    assert len(_route_captures()) >= 5


def test_todo_kwarg_de_url_for_e_captura_de_rota_ou_alguem_o_LE():
    captures = _route_captures() | FLASK_OWN | NOT_READ_ON_PURPOSE
    read = _read_keys()
    orphans = sorted({f"{f}:{line} {key}=" for f, line, key in _url_for_kwargs()
                      if key not in captures and key not in read})
    assert orphans == [], (
        "kwarg de url_for que nao e captura de rota e ninguem le do outro lado — o link "
        "responde 200 e o valor nao chega:\n  " + "\n  ".join(orphans))


# ---------------------------------------------- endpoint names in the navigation

def test_todo_endpoint_citado_na_navegacao_existe():
    """`navigation.py` writes the endpoint name as TEXT, and nothing links it to the route.

    A name left over after the route died breaks nothing - the tab just never lights up for
    it - and stays there forever. That was the case of `files.search`, a vestigial route that
    redirected to the config search: no panel link called it, and `_ACTIVE_EXTRA` kept
    citing it. On top of that, it was BROKEN - it sent `pasta=` to a route that had started
    reading `folder`, so whoever had the old link silently lost the chosen folder.

    The opposite is also a defect, but of another kind: a new route nobody adds to the
    navigation opens with the wrong tab lit. That one is left out on purpose - some routes are
    NOT screens (`/api/...`, `/health`, `/sw.js`) and the list would become one exception per route.
    """
    from gamepanel import navigation as ui

    real = {rule.endpoint for rule in panel.app.url_map.iter_rules()}
    cited: set[str] = set()
    for names in ui._ACTIVE_EXTRA.values():
        cited |= set(names)
    for table in (ui._ALL_ITEMS,):
        cited |= {item.endpoint for item in table.values() if getattr(item, "endpoint", None)}
    dead = sorted(cited - real)
    assert dead == [], (
        "endpoint citado na navegacao que nao existe mais (a aba nunca acende por ele):\n  "
        + "\n  ".join(dead))
