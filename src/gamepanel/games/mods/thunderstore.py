"""O lado do PAINEL dos mods do Thunderstore: o que a pessoa cola vira (namespace, nome).

Quem baixa e instala e o `thunderstore_remote.py`, dentro do CT. Aqui so se decide o que
foi pedido, e se a resposta e "nao sei", nada vai para o container: o nome vira pasta e URL
la dentro.

Aceita do jeito que o pacote circula: o link da pagina, o link de download, `autor/pacote`
e o nome completo do Thunderstore (`deca-VampireCommandFramework-0.11.0`).
"""
from __future__ import annotations

import re

# O mesmo charset que o instalador remoto confere de novo (thunderstore_remote.PART).
_PART = r"[A-Za-z0-9_]{1,64}"
_URL = re.compile(rf"thunderstore\.io/(?:c/[a-z0-9-]+/p|package(?:/download)?)/({_PART})/({_PART})(?:/|$)", re.ASCII)
_SLASH = re.compile(rf"^({_PART})/({_PART})$", re.ASCII)
_FULL = re.compile(rf"^({_PART})-({_PART})(?:-\d+\.\d+\.\d+)?$", re.ASCII)


def parse_package(text: str) -> tuple[str, str] | None:
    value = (text or "").strip()
    for pattern in (_URL, _SLASH, _FULL):
        found = pattern.search(value) if pattern is _URL else pattern.match(value)
        if found:
            return found.group(1), found.group(2)
    return None


def package_url(community: str, ns: str, name: str) -> str:
    return f"https://thunderstore.io/c/{community}/p/{ns}/{name}/"


def split_dir(plugin_dir: str) -> tuple[str, str] | None:
    """A pasta `ns-nome` que o instalador cria, de volta a (ns, nome)."""
    found = _FULL.match(plugin_dir or "")
    return (found.group(1), found.group(2)) if found else None
