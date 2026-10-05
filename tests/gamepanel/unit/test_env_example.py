"""`.env.example` has to pass bash `source`.

It is not read only by PowerShell: the three `provision-*-lxc.sh` `source` an environment
file in `load_env_file`, and whoever runs provisioning by hand passes their own `.env`
(copied from this example) directly.

The defect that prompted this file: `UPDATE_SCHEDULE=*-*-* 06:00:00`, unquoted. To bash
that is not a value with a space -- it is the assignment `UPDATE_SCHEDULE=*-*-*` followed
by the COMMAND `06:00:00`. Two consequences, both silent: the variable gets half the value
(a systemd schedule with no time), and the nonexistent command returns 127 -- which, with
the provisioning scripts' `set -Eeuo pipefail`, aborts the deploy at the FIRST step.

It is the same rule CLAUDE.md already enforces for `games/*.env`, here at the root.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# KEY=value, only what bash would read as an assignment at the start of the line.
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _value_as_bash_sees_it(raw: str) -> str:
    """Strips the end-of-line comment, which bash discards before anything else.

    Only a `#` preceded by a space (or at the start) counts as a comment: `VALOR#1` is a
    value, not a value with a comment -- which is why the check cannot be a `split('#')`.
    """
    without_comment = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0]
    return without_comment.strip()


def test_nenhum_valor_do_exemplo_tem_espaco_sem_aspas():
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    broken: list[str] = []
    for number, line in enumerate(lines, start=1):
        match = ASSIGNMENT.match(line)
        if not match:
            continue
        value = _value_as_bash_sees_it(match.group(2))
        if not value or value[0] in "\"'":
            continue
        if re.search(r"\s", value):
            broken.append(f'linha {number}: {match.group(1)}={value!r}')
    assert not broken, (
        "valor com espaco e sem aspas: o bash le o resto como COMANDO e o provisionamento"
        " morre com 127 no load_env_file.\n  " + "\n  ".join(broken))
