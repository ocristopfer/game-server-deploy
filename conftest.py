"""Bootstrap de import para o pytest.

Insere src/ no sys.path ANTES de qualquer teste importar `gamepanel`/`gamebroker`,
sem depender de `uv sync` (instalacao editavel). O container de dev do painel
(docker/panel/Dockerfile) so tem python3 e python3-pytest do apt - nem pip, nem uv -
entao esse import precisa resolver so por sys.path, do mesmo jeito nos dois lugares
(a maquina de dev com `.venv` e o container).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
