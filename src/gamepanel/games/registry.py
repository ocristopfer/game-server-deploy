"""Qual adapter vale para qual arquivo de configuracao.

A escolha e pelo NOME do arquivo, e nao pelo jogo cadastrado no servidor: e o mesmo
criterio que o painel ja usa para escolher o leitor (ini, json, cfg), e funciona
inclusive num servidor cujo jogo ninguem declarou.
"""
from __future__ import annotations

from gamepanel.games.adapters import dayz, dragonwilds, enshrouded, icarus, palworld
from gamepanel.games.base import FieldSpec

# A ordem nao importa: os padroes sao nomes de arquivo distintos. A lista e explicita —
# e nao uma varredura da pasta — para quem ler saber, sem rodar nada, quais jogos tem
# tela propria. O teste cobra que ela nao fique para tras.
ADAPTERS = (dragonwilds, enshrouded, palworld, icarus, dayz)


def catalog_for(filename: str) -> dict[str, FieldSpec]:
    """Catalogo do arquivo, ou vazio quando o jogo ainda nao foi mapeado."""
    name = (filename or "").strip().rsplit("/", 1)[-1]
    for adapter in ADAPTERS:
        if adapter.FILENAME.match(name):
            return adapter.FIELDS
    return {}


def describe(filename: str, key: str) -> FieldSpec | None:
    """Descricao de um campo, ou None quando ele nao esta mapeado.

    A busca e so pelo nome da chave: o mesmo campo aparece em secoes diferentes
    (`userGroups[0].password` e `userGroups[1].password`, por exemplo) e a descricao
    vale para os dois.
    """
    catalog = catalog_for(filename)
    if not catalog:
        return None
    return catalog.get((key or "").strip())
