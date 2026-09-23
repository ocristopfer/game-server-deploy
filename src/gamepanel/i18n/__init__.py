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

DEFAULT = "pt"

CATALOGS: dict[str, dict[str, str]] = {
    "pt": pt.MESSAGES,
    "en": en.MESSAGES,
}

# O que a tela oferece, na ordem em que aparece no seletor.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("pt", "Portugues (Brasil)"),
    ("en", "English"),
)


def valid_language(raw: str | None) -> str:
    """Devolve um idioma que existe; qualquer outra coisa vira o padrao."""
    chosen = (raw or "").strip()
    return chosen if chosen in CATALOGS else DEFAULT


class Message(str):
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

    key: str
    fields: dict[str, object]

    def __new__(cls, key: str, **fields: object) -> Message:
        obj = super().__new__(cls, translate(key, DEFAULT, **fields))
        obj.key = key
        obj.fields = fields
        return obj

    def __repr__(self) -> str:
        return f"Mensagem({self.key!r}, {self.fields!r})"


def translate(key: str, language: str, **fields: object) -> str:
    """A frase daquela chave, com queda para o portugues e depois para a chave.

    Campo que a frase nao usa e ignorado, e `{marcador}` sem campo correspondente fica
    na tela como esta. Frase e campo vem de lugares diferentes (catalogo x rota), e
    derrubar a tela inteira por causa de um `{n}` que alguem esqueceu de passar e caro
    demais para o estrago: a frase truncada ja denuncia o defeito.
    """
    # Uma `Mensagem` ja traz consigo a chave e os campos de origem; traduzi-la de novo e
    # so refazer a frase no idioma pedido. Sem isto, o texto dela (que ja e str) seria
    # tratado como chave desconhecida e voltaria como esta, no idioma do deploy.
    if isinstance(key, Message):
        return translate(key.key, language, **{**key.fields, **fields})
    # `get(chave, padrao)` e nao `get(chave) or padrao`: frase traduzida como texto
    # VAZIO e uma escolha (um rotulo que so existe em portugues, por exemplo) e tem de
    # vencer o portugues, em vez de cair nele por parecer ausente.
    wanted = CATALOGS.get(language) or {}
    phrase = wanted.get(key, CATALOGS[DEFAULT].get(key, key))
    if not fields:
        return phrase
    # Campo que TAMBEM e uma `Message` vai para o mesmo idioma da frase que o recebe.
    # Sem isto ele entraria pelo `str`, que e sempre o idioma do deploy, e a frase sairia
    # metade traduzida: "todo sabado at 03:00" foi exatamente o que apareceu na tela.
    ready = {
        name: translate(value, language) if isinstance(value, Message) else value
        for name, value in fields.items()
    }
    try:
        return phrase.format(**ready)
    except (KeyError, IndexError, ValueError):
        return phrase


def from_header(accept_language: str | None) -> str:
    """Le o Accept-Language do navegador. So para quem ainda nao escolheu nada.

    Implementacao curta de proposito: interessa saber se o navegador prefere um idioma
    que o painel FALA, e nao ordenar a lista inteira com peso. `pt-BR` conta como
    portugues; `en-US` conta como ingles.
    """
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if not tag:
            continue
        base = tag.split("-")[0]
        if base in CATALOGS:
            return base
    return DEFAULT


def missing_keys(language: str) -> list[str]:
    """Chaves que o portugues tem e este idioma nao. Usado pelo teste."""
    return sorted(set(CATALOGS[DEFAULT]) - set(CATALOGS.get(language, {})))
