"""Idioma da tela: o painel fala portugues por padrao e pode falar outro.

Catalogo em dicionario Python, sem dependencia e sem passo de build. A alternativa
padrao (Flask-Babel + gettext) existe no apt do Debian, mas pede compilar `.po` em
`.mo` — e este repo nao tem build: o painel em producao so recebe arquivos e sobe. Pela
mesma razao o TOTP e o QR code aqui sao codigo proprio (ver CLAUDE.md).

Cada frase tem uma CHAVE neutra (`nav.servers`, `action.start`) e um catalogo por
idioma. Assim os dois idiomas sao simetricos — `pt.py` nao e "o original" e `en.py` a
"traducao", os dois sao dados do mesmo jeito — e mudar a redacao em portugues nao
obriga a mexer no catalogo ingles.

A busca cai em cascata: idioma pedido -> portugues -> a propria chave. O ultimo degrau
e de proposito: chave que ninguem cadastrou aparece na tela como `nav.servers`, e isso
e barulhento o suficiente para ser consertado — melhor do que sumir em silencio.

Traduz-se o que a PESSOA le. Log tecnico, nome de excecao e identificador de codigo sao
ingles e ficam fora daqui.
"""
from __future__ import annotations

from gamepanel.i18n import en, pt

PADRAO = "pt"

CATALOGOS: dict[str, dict[str, str]] = {
    "pt": pt.MENSAGENS,
    "en": en.MENSAGENS,
}

# O que a tela oferece, na ordem em que aparece no seletor.
IDIOMAS: tuple[tuple[str, str], ...] = (
    ("pt", "Portugues (Brasil)"),
    ("en", "English"),
)


def idioma_valido(bruto: str | None) -> str:
    """Devolve um idioma que existe; qualquer outra coisa vira o padrao."""
    escolhido = (bruto or "").strip()
    return escolhido if escolhido in CATALOGOS else PADRAO


def traduzir(chave: str, idioma: str) -> str:
    """A frase daquela chave, com queda para o portugues e depois para a chave."""
    pedido = CATALOGOS.get(idioma)
    if pedido and chave in pedido:
        return pedido[chave]
    return CATALOGOS[PADRAO].get(chave, chave)


def do_cabecalho(accept_language: str | None) -> str:
    """Le o Accept-Language do navegador. So para quem ainda nao escolheu nada.

    Implementacao curta de proposito: interessa saber se o navegador prefere um idioma
    que o painel FALA, e nao ordenar a lista inteira com peso. `pt-BR` conta como
    portugues; `en-US` conta como ingles.
    """
    for parte in (accept_language or "").split(","):
        etiqueta = parte.split(";")[0].strip().lower()
        if not etiqueta:
            continue
        base = etiqueta.split("-")[0]
        if base in CATALOGOS:
            return base
    return PADRAO


def chaves_faltando(idioma: str) -> list[str]:
    """Chaves que o portugues tem e este idioma nao. Usado pelo teste."""
    return sorted(set(CATALOGOS[PADRAO]) - set(CATALOGOS.get(idioma, {})))
