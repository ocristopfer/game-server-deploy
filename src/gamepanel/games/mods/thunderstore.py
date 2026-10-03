"""O lado do PAINEL dos mods do Thunderstore: o que a pessoa cola vira (namespace, nome).

Quem baixa e instala e o `thunderstore_remote.py`, dentro do CT. Aqui so se decide o que
foi pedido, e se a resposta e "nao sei", nada vai para o container: o nome vira pasta e URL
la dentro.

Aceita do jeito que o pacote circula: o link da pagina, o link de download, `autor/pacote`
e o nome completo do Thunderstore (`deca-VampireCommandFramework-0.11.0`). Quando o texto
colado ja traz a versao (o nome completo, o link de download ou o de uma versao), ela vem
junto: quem colou o nome com versao quer AQUELA versao, e nao a mais nova.
"""
from __future__ import annotations

import re

# O mesmo charset que o instalador remoto confere de novo (thunderstore_remote.PART).
_PART = r"[A-Za-z0-9_]{1,64}"
# Versao do Thunderstore e sempre major.minor.patch (o site recusa outra forma). Conferida
# aqui e de novo no CT (thunderstore_remote.VERSION): ela vira parte da URL da API.
_VERSION = r"\d{1,9}\.\d{1,9}\.\d{1,9}"
VERSION = re.compile(rf"^{_VERSION}$", re.ASCII)
_URL = re.compile(rf"thunderstore\.io/(?:c/[a-z0-9-]+/p|package(?:/download)?)/({_PART})/({_PART})"
                  rf"(?:/v)?(?:/({_VERSION}))?(?:/|$)", re.ASCII)
_SLASH = re.compile(rf"^({_PART})/({_PART})$", re.ASCII)
_FULL = re.compile(rf"^({_PART})-({_PART})(?:-({_VERSION}))?$", re.ASCII)


def parse_package(text: str) -> tuple[str, str, str] | None:
    """(namespace, nome, versao); versao vazia = a mais nova."""
    value = (text or "").strip()
    for pattern in (_URL, _SLASH, _FULL):
        found = pattern.search(value) if pattern is _URL else pattern.match(value)
        if found:
            version = found.group(3) if pattern is not _SLASH else None
            return found.group(1), found.group(2), version or ""
    return None


def parse_version(text: str) -> str | None:
    """A versao digitada no formulario: vazia = a mais nova; None = invalida (nada roda)."""
    value = (text or "").strip().lstrip("vV")
    if not value:
        return ""
    return value if VERSION.match(value) else None


def package_url(community: str, ns: str, name: str) -> str:
    return f"https://thunderstore.io/c/{community}/p/{ns}/{name}/"


def split_dir(plugin_dir: str) -> tuple[str, str] | None:
    """A pasta `ns-nome` que o instalador cria, de volta a (ns, nome)."""
    found = _FULL.match(plugin_dir or "")
    # A pasta nunca leva versao: `ns-nome-1.0.0` nao e pasta que o instalador cria.
    return (found.group(1), found.group(2)) if found and not found.group(3) else None
