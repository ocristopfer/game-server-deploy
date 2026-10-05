"""Path of the LIVE code on the CT: always under `current`, never the package directly in APP_DIR.

Since a release became one folder per version, the code the CT runs lives in
`/opt/<pacote>/current/<pacote>/`. `/opt/<pacote>/<pacote>/` is the PREVIOUS layout, and after
the migration it simply no longer exists on the CT.

This had already gone stale in three places at once, and none of them fails visibly:

- the shortcut probe of `deploy-admin.ps1` (`test -f .../gamepanel/app.py`) started failing
  ALWAYS, and every incremental deploy silently became a full provisioning --
  which goes through Proxmox, runs apt and resets the admin password every time;
- the server registration at the end of `deploy-game.ps1` kept pointing to a file that
  does not exist: the deploy prints "painel nao encontrado" and moves on WITHOUT registering (the
  comment there records that this had already happened once, when the code moved to `src/`);
- the docs said to run `python3 /opt/gamepanel/gamepanel/app.py --reset-2fa`, which is the
  emergency exit for whoever is locked OUT of the panel -- the worst time to find out that
  the path changed.

No tool links a path written inside a shell string to the layout the installer
produces, and none of the three has a syntax error.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# `/opt/gamepanel/gamepanel`, `/opt/gamebroker/gamebroker`: the package DIRECTLY in APP_DIR.
OLD_LAYOUT = re.compile(r"/opt/(gamepanel|gamebroker)/\1(?:/|\b)")

SCANNED = ("deploy/**/*.ps1", "deploy/**/*.sh", "lib/*.sh", "CLAUDE.md", "README.md")

# The panel in DOCKER has no per-version release: `Dockerfile.prod` copies the package into
# the image and the container is replaced whole instead of gaining a version folder.
# There the previous layout is the right one. What exempts a line is MENTIONING docker -- in the
# line or in the file name, and not a hand-written list of files, which would go stale just like
# the path this test guards. The name counts because the line that invokes the container does not
# repeat the word (`"exec", $PanelContainer, ...`): the one that says it is `deploy-docker.ps1`.
DOCKER_WORDS = ("docker", "compose", "dockerfile", "bind mount")


def _offenders() -> list[str]:
    found: list[str] = []
    for pattern in SCANNED:
        for path in sorted(REPO.glob(pattern)):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                if not OLD_LAYOUT.search(line):
                    continue
                relative = path.relative_to(REPO).as_posix()
                haystack = (line + " " + relative).lower()
                if any(word in haystack for word in DOCKER_WORDS):
                    continue
                found.append(f"{relative}:{number}: {line.strip()[:100]}")
    return found


def test_a_varredura_encontra_os_caminhos_do_docker():
    """If the pattern stops matching, the test above passes without checking anything.

    The old path EXISTS on purpose in the Docker deploy, so it serves as a control:
    finding zero occurrences anywhere means the expression broke.
    """
    every = []
    for pattern in SCANNED:
        for path in sorted(REPO.glob(pattern)):
            every += OLD_LAYOUT.findall(path.read_text(encoding="utf-8"))
    assert every, "a expressao do layout antigo nao casa mais nada: ela ainda esta certa?"


def test_nenhum_script_de_deploy_aponta_para_o_layout_antigo():
    offenders = _offenders()
    assert not offenders, (
        "caminho do layout ANTERIOR ao release por versao (o codigo vivo esta sob"
        " `current/`):\n  " + "\n  ".join(offenders))
