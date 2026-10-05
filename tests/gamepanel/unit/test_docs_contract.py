"""`CLAUDE.md` cites code names; this test checks that they still exist.

This repository's doc is dense with proper names: `app.COMMANDS`, `ui.ACTIONS`,
`opnsense.busy_ports`. Every rename leaves a few behind, and the result is worse than a
missing doc - it is a doc that LIES, and sends the next person looking for a name that no
longer exists. Four such cases were found at once while writing this: the doc said to
look for taken_ports in opnsense, _limpar in the SSH installer, somente_banco in the broker
and menu_acao in the macros. The dead names are WITHOUT backticks here on purpose - with
them, this test's own doc would become a citation the test rejects.

The scope is narrow on purpose: only `module.name` inside backticks, where `module` really
is a module of these packages. Three forms have the SAME shape and are not references to
code, so they are left out:

- i18n key (`charts.players`) - recognized by existing in the catalog, not by a list;
- file name (`compare.sh`, `components/ui.html`) - by the extension, and checked
  separately: see `test_todo_arquivo_citado_existe`, below;
- outside module (`re.ASCII`, `flask.g`) - by the absence of a module with that name here.

Environment variables, bash functions and data keys do not count because they have no dot.

FILE NAMES have their own check, and it was born from eight dead names at once: the doc
said to open conexao.py, ssh_install.py, servico.py, backends.py, test_gamefields.py,
instancias.html, catalogo.html and gameconf.py, all renamed commits ago. They all passed
precisely because the rule above DISCARDS them by extension - the filter that avoids the
false positive became the hole. And as a bonus the test found `pyroject.toml`, a typo that
had been there since the section was written.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "CLAUDE.md"
PACKAGES = ("src/gamepanel", "src/gamebroker")

# `module.name` or `module.name()`, inside backticks. Lowercase module on purpose:
# `Class.method` may come from a library, and there is nothing to check.
CITATION = re.compile(r"`([a-z_][a-z_0-9]*)\.([A-Za-z_][\w]*)(?:\(\))?`")
EXTENSIONS = {"py", "sh", "ps1", "html", "jinja", "js", "css", "md", "env", "ini",
              "toml", "json", "yml", "service", "timer", "webmanifest", "db", "pub",
              "pem", "gz", "zst", "lock", "example", "txt", "log", "webp", "png", "svg"}

# Only extensions of things that LIVE in the repository. `.env`, `.db`, `.pem` and `.gz` are
# left out on purpose: they are deploy, data or output files, created outside of here.
REPO_EXTENSIONS = ("py", "sh", "ps1", "html", "jinja", "js", "css", "md", "ini",
                   "toml", "json", "webmanifest", "service", "timer")
FILENAME = re.compile(r"`([A-Za-z0-9_./-]+\.(?:" + "|".join(REPO_EXTENSIONS) + r"))`")

# Cited files that do NOT exist in the tree, each for a different reason.
NOT_A_FILE = {
    # Written INSIDE the tarball by the packager; the doc explains this in the version section,
    # and `.gitignore` guards the case of it escaping into the tree.
    "_build.py",
}

# SHAPE collisions, not name collisions. Each one has a different reason, which is why the list
# is short and hand-written instead of a generic rule that would let other things through.
NOT_CODE = {
    # `servers` and `jobs` are database tables as well as blueprint modules.
    "servers.broker_id", "jobs.broker_op",
    # `app` is the Flask object; `run` is its method, not the module's.
    "app.run",
    # The doc cites this one as a COUNTER-example ("servers.detail, not servers.server_detail").
    "servers.server_detail",
}


def _defined_names() -> dict[str, set[str]]:
    """module -> names it defines at the top level (function, class, constant)."""
    found: dict[str, set[str]] = {}
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            names: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Class methods are included too: the doc cites `instance_service._undo`, which is
            # a method of `Service` and not a top-level name.
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            found.setdefault(path.stem, set()).update(names)
    return found


def _citations() -> list[tuple[str, str]]:
    text = DOC.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in CITATION.finditer(text)]


def _checkable() -> list[tuple[str, str]]:
    defined = _defined_names()
    catalog = i18n.CATALOGS["pt"]
    return [
        (module, name) for module, name in _citations()
        if module in defined and name not in EXTENSIONS
        and f"{module}.{name}" not in catalog
        and f"{module}.{name}" not in NOT_CODE
    ]


def test_a_varredura_encontra_citacoes_de_codigo():
    """Zero checkable citations is the silent way for this test to stop meaning anything.

    The floor is low because the filter is strict: of the ~90 dotted citations in CLAUDE.md,
    most are i18n keys, file names or outside modules. What is left is what actually
    points to code from here.
    """
    assert len(_checkable()) >= 12


def _repo_files() -> set[str]:
    """Every repository path, by the full path AND by the file name.

    Both because the doc cites in both forms: `lib/ct-install.sh` with the path and
    `compare.sh` alone. Requiring the full path would force rewriting the doc; accepting
    only the name would let a wrong path through. Accepting both catches what matters - the
    file that no longer exists.
    """
    found: set[str] = set()
    for path in ROOT.rglob("*"):
        parts = set(path.parts)
        if not path.is_file() or parts & {"__pycache__", ".git", ".venv", "node_modules", "dist"}:
            continue
        found.add(path.relative_to(ROOT).as_posix())
        found.add(path.name)
    return found


def _cited_files() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return sorted({
        m.group(1) for m in FILENAME.finditer(text)
        # `/sw.js` and `/static/sw.js` are ROUTES, not file paths; `src/*/_build.py` and
        # `provision-*-lxc.sh` are patterns, and checking globs would only teach writing globs.
        if not m.group(1).startswith("/") and "*" not in m.group(1)
        and m.group(1) not in NOT_A_FILE
    })


def test_a_varredura_encontra_arquivos_citados():
    assert len(_cited_files()) >= 40


def test_todo_arquivo_citado_existe():
    files = _repo_files()
    missing = [c for c in _cited_files()
               if c not in files and c.rsplit('/', 1)[-1] not in files]
    assert missing == [], (
        "arquivo citado no CLAUDE.md que nao existe na arvore (a doc manda abrir o que "
        "nao esta la):\n  " + "\n  ".join(missing))


def test_todo_nome_citado_ainda_existe():
    defined = _defined_names()
    missing = sorted(
        f"{module}.{name}" for module, name in _checkable() if name not in defined[module]
    )
    assert missing == [], (
        "nome citado no CLAUDE.md que sumiu do codigo (a doc manda procurar o que nao "
        "existe):\n  " + "\n  ".join(missing))


# --------------------------------------------------------------- cited routes

# `POST /account/language`, `GET /health`: the doc telling you to CALL a route. The method in
# front is what makes the citation unambiguous -- without it, `/opt/gamepanel/gamepanel` and
# `/etc/gamebroker/broker.env` (disk paths) and `/v1/instancias` (broker route, cited by its
# OLD name in a historical sentence) would be counted and the exception list would grow
# bigger than the check.
CITED_ROUTE = re.compile(r"`(GET|POST|PUT|DELETE) (/[A-Za-z0-9/_.<>:-]*)`")


def _panel_rules() -> set[tuple[str, str]]:
    """(method, rule) of everything the panel serves, as Flask registered it."""
    from gamepanel import app as panel

    found = set()
    for rule in panel.app.url_map.iter_rules():
        for method in rule.methods or ():
            found.add((method, str(rule.rule)))
    return found


def test_toda_rota_citada_com_metodo_ainda_existe():
    """A doc telling you to call a route that no longer exists costs a debugging session.

    That was the case of `POST /account/idioma`: the route became `/account/language` in the
    identifier translation, and the instruction to "check a screen in both languages" started
    returning a silent 404 -- whoever followed it concluded that the language selector was broken.
    The `module.name` check does not reach URLs, and no other check looked at them.
    """
    rules = _panel_rules()
    text = DOC.read_text(encoding="utf-8")
    missing = []
    for method, path in CITED_ROUTE.findall(text):
        if (method, path) not in rules:
            same_path = sorted(m for m, p in rules if p == path)
            missing.append(f"{method} {path}"
                           + (f" (existe, mas so aceita {same_path})" if same_path
                              else " (nao existe rota nenhuma nesse caminho)"))
    assert not missing, "rota citada no CLAUDE.md que o painel nao serve:\n  " + "\n  ".join(missing)


def test_a_varredura_encontra_rotas_citadas():
    """If the citation format changes, the test above stops checking anything."""
    found = CITED_ROUTE.findall(DOC.read_text(encoding="utf-8"))
    assert found, "nenhuma rota `METODO /caminho` encontrada no CLAUDE.md"
