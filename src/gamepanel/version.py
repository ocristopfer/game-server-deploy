"""Que versao do painel esta rodando, e de que commit ela saiu.

O valor de verdade e gravado por `tools/build-release.py` num `_build.py` que existe SO
dentro do tarball — nunca na arvore de trabalho. Assim `git status` continua limpo
depois de empacotar, e o que roda em producao carrega a identidade do artefato que foi
publicado, em vez de uma que alguem se lembrou de editar a mao.

Sem esse arquivo (ou seja: rodando do repositorio), a versao e a do `VERSION` da raiz
com a marca `+dev`. A marca importa — ela e o que diferencia "o painel do CT esta na
0.1.0" de "alguem esta olhando a propria maquina".
"""
from __future__ import annotations

import os
from typing import NamedTuple

DEV_SUFFIX = "+dev"
UNKNOWN = "0.0.0"
VERSION_FILE = "VERSION"
SEARCH_LEVELS = 4


class Build(NamedTuple):
    """A identidade do que esta rodando."""

    version: str
    commit: str
    built_at: str

    @property
    def is_dev(self) -> bool:
        return self.version.endswith(DEV_SUFFIX)

    def as_public(self) -> dict[str, str]:
        return {"version": self.version, "commit": self.commit, "built_at": self.built_at}


def version_from_repo(start: str, levels: int = SEARCH_LEVELS) -> str:
    """Le o `VERSION` da raiz do repositorio, subindo pastas a partir de `start`.

    Sobe em vez de fixar `../../VERSION` porque o pacote tambem e montado em
    `/opt/gamepanel/gamepanel` no container de desenvolvimento, onde a raiz do
    repositorio esta em outro lugar. Nao achar nao e erro: e so um painel sem versao
    declarada, e o `UNKNOWN` diz exatamente isso.
    """
    folder = os.path.dirname(os.path.abspath(start))
    for _ in range(levels):
        candidate = os.path.join(folder, VERSION_FILE)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    return fh.read().strip() or UNKNOWN
            except OSError:
                break
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return UNKNOWN


def _current() -> Build:
    # `_build` guarda texto puro, e nao um `Build` pronto: importar o tipo daqui faria
    # este modulo depender de quem depende dele, e o import ficaria circular.
    try:
        # Nao existe na arvore: o empacotador o escreve dentro do tarball.
        from gamepanel import _build  # type: ignore[attr-defined]
    except ImportError:
        return Build(version_from_repo(__file__) + DEV_SUFFIX, "", "")
    return Build(_build.VERSION, _build.COMMIT, _build.BUILT_AT)


BUILD = _current()
__version__ = BUILD.version
