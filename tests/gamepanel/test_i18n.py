"""Idioma da tela (gamepanel.i18n).

O que importa aqui nao e a traducao em si, e o comportamento em volta dela: chave que
ninguem cadastrou nao pode sumir da tela, idioma desconhecido nao pode virar 500, e os
catalogos nao podem sair de sincronia sem alguem perceber.
"""
from __future__ import annotations

import pytest

from gamepanel import app as panel
from gamepanel import i18n

# ------------------------------------------------------------ catalogos

def test_os_dois_catalogos_tem_as_mesmas_chaves():
    """Chave so em portugues e uma tela meio traduzida esperando para acontecer."""
    faltando = i18n.chaves_faltando("en")
    assert faltando == [], f"sem traducao em ingles: {faltando}"


def test_nenhuma_chave_sobrando_no_ingles():
    sobrando = sorted(set(i18n.CATALOGOS["en"]) - set(i18n.CATALOGOS["pt"]))
    assert sobrando == [], f"chave que o portugues nao tem: {sobrando}"


def test_nenhum_valor_vazio():
    for idioma, catalogo in i18n.CATALOGOS.items():
        vazias = sorted(c for c, v in catalogo.items() if not v.strip())
        assert vazias == [], f"{idioma}: chave sem texto {vazias}"


def test_toda_chave_segue_a_convencao():
    """`area.assunto`, minusculo: a chave e identificador, nao texto de tela."""
    fora = sorted(c for c in i18n.CATALOGOS["pt"]
                  if c != c.lower() or "." not in c or " " in c)
    assert fora == [], f"chave fora da convencao: {fora}"


def test_idiomas_oferecidos_tem_catalogo():
    for codigo, rotulo in i18n.IDIOMAS:
        assert codigo in i18n.CATALOGOS, f"{codigo} aparece no seletor e nao tem catalogo"
        assert rotulo.strip()


# ------------------------------------------------------------- traduzir

def test_traduz_para_o_idioma_pedido():
    assert i18n.traduzir("nav.servers", "en") == "Servers"
    assert i18n.traduzir("nav.servers", "pt") == "Servidores"


def test_chave_desconhecida_volta_como_chave():
    """Aparecer 'nav.inexistente' na tela e feio - e e exatamente o ponto: da para ver."""
    assert i18n.traduzir("nav.inexistente", "en") == "nav.inexistente"


def test_idioma_desconhecido_cai_no_portugues():
    assert i18n.traduzir("nav.servers", "klingon") == "Servidores"


def test_chave_sem_traducao_cai_no_portugues(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGOS, "en", {})
    assert i18n.traduzir("nav.servers", "en") == "Servidores"


# -------------------------------------------------------- idioma_valido

@pytest.mark.parametrize("bruto", ["", "  ", None, "klingon", "pt-BR", "EN"])
def test_idioma_invalido_vira_o_padrao(bruto):
    assert i18n.idioma_valido(bruto) == i18n.PADRAO


@pytest.mark.parametrize("bruto", ["pt", "en", " en "])
def test_idioma_valido_passa(bruto):
    assert i18n.idioma_valido(bruto) == bruto.strip()


# ------------------------------------------------------ Accept-Language

@pytest.mark.parametrize(("cabecalho", "esperado"), [
    ("en-US,en;q=0.9", "en"),
    ("en", "en"),
    ("pt-BR,pt;q=0.9,en;q=0.8", "pt"),
    ("fr-FR,fr;q=0.9,en;q=0.8", "en"),
    ("", "pt"),
    (None, "pt"),
    ("klingon", "pt"),
])
def test_le_a_preferencia_do_navegador(cabecalho, esperado):
    assert i18n.do_cabecalho(cabecalho) == esperado


# ---------------------------------------------------------- campos na frase

def test_campo_entra_no_lugar_do_marcador(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.ritmo", "a cada {n}s")
    assert i18n.traduzir("t.ritmo", "pt", n=15) == "a cada 15s"


def test_campo_a_mais_e_ignorado(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.simples", "sem marcador")
    assert i18n.traduzir("t.simples", "pt", n=15) == "sem marcador"


@pytest.mark.parametrize("frase", [
    "faltou o {outro}",      # marcador sem campo: KeyError
    "chave {} solta",        # posicional sem argumento: IndexError
    "chave { torta",         # marcador mal formado: ValueError
])
def test_marcador_que_nao_casa_nao_derruba_a_tela(monkeypatch, frase):
    """Frase e campo vem de lugares diferentes; a tela inteira nao pode cair por isso."""
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.torta", frase)
    assert i18n.traduzir("t.torta", "pt", n=15) == frase


def test_a_frase_do_idioma_pedido_e_que_recebe_o_campo(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.ritmo", "a cada {n}s")
    monkeypatch.setitem(i18n.CATALOGOS["en"], "t.ritmo", "every {n}s")
    assert i18n.traduzir("t.ritmo", "en", n=15) == "every 15s"


# ------------------------------------------------- frase com marcacao (_h)

def test_frase_com_marcacao_chega_inteira_na_tela(monkeypatch):
    """A frase vem do catalogo, que e codigo daqui: a marcacao dela e para valer."""
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.rico", "avisa na <strong>mudanca</strong>")
    with panel.app.test_request_context("/"):
        assert str(panel.traduzir_html("t.rico")) == "avisa na <strong>mudanca</strong>"


def test_campo_que_vem_de_fora_e_escapado(monkeypatch):
    """O campo NAO e do catalogo; sem escape, um nome de servidor viraria marcacao."""
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.rico", "servidor <strong>{nome}</strong>")
    with panel.app.test_request_context("/"):
        saida = str(panel.traduzir_html("t.rico", nome="<script>x</script>"))
    assert saida == "servidor <strong>&lt;script&gt;x&lt;/script&gt;</strong>"


def test_frase_encaixada_noutra_passa_inteira(monkeypatch):
    """Paragrafo que embute outro (`_h` dentro de `_h`) nao pode escapar duas vezes."""
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.fora", "ouvindo ({dentro})")
    monkeypatch.setitem(i18n.CATALOGOS["pt"], "t.dentro", "<strong>{n}</strong> agora")
    with panel.app.test_request_context("/"):
        dentro = panel.traduzir_html("t.dentro", n=3)
        assert str(panel.traduzir_html("t.fora", dentro=dentro)) == "ouvindo (<strong>3</strong> agora)"
