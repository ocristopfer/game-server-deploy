"""Test double for the SSH runner, next to `fake_http.py`.

It used to live INSIDE `test_ssh_installer.py`, and two other files imported it by name
(`from test_ssh_installer import FakeRunner`). That passes while the whole suite runs -
pytest put the collected file's folder on `sys.path` - and BREAKS as soon as someone runs
only part of it. Measured: with the tests split into `unit/` and `integration/`, running
only `integration/` gives `ModuleNotFoundError`, and that is exactly what the split is for.

A double shared by more than one file lives next to `conftest.py`, the folder pytest always
puts on `sys.path` - which is what `fake_http.py` already did.
"""
from __future__ import annotations

from pathlib import Path

BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIExemploExemploExemploExemplo"
PUBLIC_KEY = f"ssh-ed25519 {BLOB} broker@teste"


class FakeRunner:
    """Records each command. `saidas` maps a chunk of the remote command to (code, lines)."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], float]] = []
        self.outputs: dict[str, tuple[int, list[str]]] = {}
        self.first_ssh_failures = 0
        self.env_visto = ""

    def run(self, argv, on_line, timeout, cancel=None):
        self.calls.append((list(argv), timeout))
        self.cancel_seen = cancel
        if argv[0] == "scp":
            self.env_visto = Path(argv[-2]).read_text(encoding="utf-8")  # the file exists NOW
        command = argv[-1] if argv[0] == "ssh" else " ".join(argv)
        if argv[0] == "ssh" and command == "true" and self.first_ssh_failures > 0:
            self.first_ssh_failures -= 1
            return 255
        for chunk_of, (code, lines) in self.outputs.items():
            if chunk_of in command:
                for line in lines:
                    if on_line is not None:
                        on_line(line)
                return code
        if on_line is not None and "ct-install.sh" in command:
            for line in ("[10:00:00] instalando", "[10:00:09] INSTALACAO CONCLUIDA: Meu Jogo"):
                on_line(line)
        return 0

    def commands(self) -> list[str]:
        return [a[-1] if a[0] == "ssh" else "scp" for a, _ in self.calls]
