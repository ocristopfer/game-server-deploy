"""Import bootstrap for pytest.

Inserts src/ into sys.path BEFORE any test imports `gamepanel`/`gamebroker`, without
depending on `uv sync` (editable install). The panel dev container
(docker/panel/Dockerfile) only has python3 and python3-pytest from apt - neither pip nor
uv - so this import has to resolve through sys.path alone, the same way in both places
(the dev machine with `.venv` and the container).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
