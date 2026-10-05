"""The systemd unit's entry point checked against what the package actually exports.

gunicorn receives the callable as TEXT (`gamebroker.wsgi:create_app_from_env()`), written
inside a shell heredoc. Nothing ties that text to the function: renaming the function leaves
the unit pointing at a name that does not exist, and whoever finds out is gunicorn in the CT,
with `Failed to find attribute` and exit 4.

The cost is not "the deploy fails". The unit is rewritten BEFORE any health check, so the
deploy takes down a service that was running and can no longer bring it back -- and, if
provisioning aborts before reaching the unit, not even the next deploy comes up.

The sandbox (`docker/ct-sandbox/broker.sh`) also checks this, but needs Docker; this one
always runs. And the check there did a `grep` of a literal COPY of the name: it agreed with
the script and stayed green with both wrong. Here the question is asked of the code.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# `package.module:function` or `'package.module:function()'`: gunicorn accepts both forms and
# the repo uses one per service (the panel exposes the ready object, the broker a factory).
APP_SPEC = re.compile(
    r"'?([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)+):([A-Za-z_]\w*)(?:\(\))?'?\s*$")

# provisioning script -> the folder where its package lives in the tree
PROVISIONERS = {
    "deploy/broker/provision-broker-lxc.sh": "src",
    "deploy/admin/provision-admin-lxc.sh": "src",
}


def _exec_start_entry_points(text: str) -> list[tuple[str, str]]:
    """(dotted module, name) of each `ExecStart=` in the file.

    The scan is tied to ExecStart on purpose: a loose `module:name` also shows up in
    COMMENTS -- this file and the provisioning script itself cite the old name when
    explaining the defect --, and checking a citation in prose would make the guard
    complain about text.
    """
    lines = text.splitlines()
    found: list[tuple[str, str]] = []
    for number, line in enumerate(lines):
        if not line.startswith("ExecStart="):
            continue
        # The unit continues the line with a trailing backslash; join everything before reading.
        pieces, index = [line], number
        while lines[index].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            pieces.append(lines[index])
        joined = " ".join(p.rstrip().removesuffix("\\").strip() for p in pieces)
        match = APP_SPEC.search(joined)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def _top_level_names(module: pathlib.Path) -> set[str]:
    """Names the module defines at top level, via the AST.

    Via the AST and not by importing: `gamepanel.app` opens the database and starts a thread
    on import, and all we want to know here is whether the NAME exists.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


def test_o_callable_da_unit_existe_no_pacote():
    missing: list[str] = []
    checked: list[str] = []
    for script, root in PROVISIONERS.items():
        text = (REPO / script).read_text(encoding="utf-8")
        for dotted, name in _exec_start_entry_points(text):
            checked.append(f"{dotted}:{name}")
            module = (REPO / root / pathlib.Path(*dotted.split("."))).with_suffix(".py")
            if not module.exists():
                missing.append(f"{script}: o modulo {dotted} nao existe ({module})")
            elif name not in _top_level_names(module):
                missing.append(f"{script}: {dotted}:{name} nao existe em {module.name}")
    # BOTH services must show up: the panel's has neither parentheses nor quotes, and a
    # regex designed only for the broker left it out without anything complaining.
    assert len(checked) == len(PROVISIONERS), (
        f"esperava um ponto de entrada por provisionamento, achei {checked}")
    assert not missing, ("ponto de entrada da unit que o pacote nao tem:\n  "
                         + "\n  ".join(missing))
