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

Frase com NUMERO ou NOME no meio nao se parte em pedacos: `traduzir` aceita campos e
os troca por `{nome}` dentro da frase. Partir era o caminho obvio e esta errado, porque
a ordem das palavras muda de um idioma para o outro — "a cada {n}s" e "every {n}s" ainda
combinam, mas nem sempre e assim, e um pedaco solto nao da contexto a quem traduz.

Pela mesma razao a frase pode trazer MARCACAO (`<strong>`, `<code>`): dividir o
paragrafo em cada `<strong>` deixaria metade dele em portugues na tela em ingles. O
catalogo e codigo deste repositorio, nao entrada de usuario, entao a frase e confiavel;
os CAMPOS que entram nela e que nao sao, e o `traduzir_html` do `app.py` os escapa.
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


class Mensagem(str):
    """Uma frase que lembra de QUE CHAVE ela veio.

    Existe para o texto que nasce longe da tela: o erro de validacao de
    `services/server_service.py`, o `QueryError` de `runtime/a2s.py`. Esse texto acaba em
    tres lugares com regras diferentes — a tela de quem clicou (idioma da pessoa), a
    coluna de saida de um job (gravada, idioma do deploy) e o log do processo — e um
    servico nao tem como saber em qual vai cair.

    E `str` de proposito, e nao um objeto a parte. Assim `str(exc)`, `f"{erro}"`,
    `"pedaco" in erro` e o `logging` continuam funcionando exatamente como antes, sem
    tocar em nenhum desses pontos; o que muda e que `traduzir` reconhece a classe e
    refaz a frase no idioma certo quando alguem pede. Esquecer de traduzir nao quebra
    nada: cai no idioma do deploy, que era o comportamento anterior.
    """

    chave: str
    campos: dict[str, object]

    def __new__(cls, chave: str, **campos: object) -> Mensagem:
        obj = super().__new__(cls, traduzir(chave, PADRAO, **campos))
        obj.chave = chave
        obj.campos = campos
        return obj

    def __repr__(self) -> str:
        return f"Mensagem({self.chave!r}, {self.campos!r})"


def traduzir(chave: str, idioma: str, **campos: object) -> str:
    """A frase daquela chave, com queda para o portugues e depois para a chave.

    Campo que a frase nao usa e ignorado, e `{marcador}` sem campo correspondente fica
    na tela como esta. Frase e campo vem de lugares diferentes (catalogo x rota), e
    derrubar a tela inteira por causa de um `{n}` que alguem esqueceu de passar e caro
    demais para o estrago: a frase truncada ja denuncia o defeito.
    """
    # Uma `Mensagem` ja traz consigo a chave e os campos de origem; traduzi-la de novo e
    # so refazer a frase no idioma pedido. Sem isto, o texto dela (que ja e str) seria
    # tratado como chave desconhecida e voltaria como esta, no idioma do deploy.
    if isinstance(chave, Mensagem):
        return traduzir(chave.chave, idioma, **{**chave.campos, **campos})
    # `get(chave, padrao)` e nao `get(chave) or padrao`: frase traduzida como texto
    # VAZIO e uma escolha (um rotulo que so existe em portugues, por exemplo) e tem de
    # vencer o portugues, em vez de cair nele por parecer ausente.
    pedido = CATALOGOS.get(idioma) or {}
    frase = pedido.get(chave, CATALOGOS[PADRAO].get(chave, chave))
    if not campos:
        return frase
    try:
        return frase.format(**campos)
    except (KeyError, IndexError, ValueError):
        return frase


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
