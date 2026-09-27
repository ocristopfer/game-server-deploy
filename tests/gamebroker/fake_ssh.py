"""Dobre do executor de SSH, ao lado do `fake_http.py`.

Estava DENTRO de `test_ssh_installer.py`, e dois outros arquivos o importavam por nome
(`from test_ssh_installer import FakeRunner`). Isso passa enquanto a suite roda inteira —
o pytest pos a pasta do arquivo coletado no `sys.path` — e QUEBRA na hora em que alguem
roda so uma parte dela. Medido: com os testes divididos em `unit/` e `integration/`, rodar
so `integration/` da `ModuleNotFoundError`, e e justo para isso que a divisao existe.

Dobre compartilhado por mais de um arquivo mora ao lado do `conftest.py`, que e a pasta que
o pytest sempre poe no `sys.path` — e o que o `fake_http.py` ja fazia.
"""
from __future__ import annotations

from pathlib import Path

BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIExemploExemploExemploExemplo"
PUBLIC_KEY = f"ssh-ed25519 {BLOB} broker@teste"


class FakeRunner:
    """Registra cada command. `saidas` mapeia um trecho do command remoto a (codigo, linhas)."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], float]] = []
        self.outputs: dict[str, tuple[int, list[str]]] = {}
        self.first_ssh_failures = 0
        self.env_visto = ""

    def run(self, argv, on_line, timeout, cancel=None):
        self.calls.append((list(argv), timeout))
        self.cancel_seen = cancel
        if argv[0] == "scp":
            self.env_visto = Path(argv[-2]).read_text(encoding="utf-8")  # o arquivo existe AGORA
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
