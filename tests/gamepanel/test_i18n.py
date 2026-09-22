"""Idioma da tela (gamepanel.i18n).

O que importa aqui nao e a traducao em si, e o comportamento em volta dela: chave que
ninguem cadastrou nao pode sumir da tela, idioma desconhecido nao pode virar 500, e os
catalogos nao podem sair de sincronia sem alguem perceber.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from gamepanel import app as panel
from gamepanel import i18n

# ------------------------------------------------------------ catalogos

def test_os_dois_catalogos_tem_as_mesmas_chaves():
    """Chave so em portugues e uma tela meio traduzida esperando para acontecer."""
    faltando = i18n.missing_keys("en")
    assert faltando == [], f"sem traducao em ingles: {faltando}"


def test_nenhuma_chave_sobrando_no_ingles():
    sobrando = sorted(set(i18n.CATALOGS["en"]) - set(i18n.CATALOGS["pt"]))
    assert sobrando == [], f"chave que o portugues nao tem: {sobrando}"


def test_nenhum_valor_vazio():
    for idioma, catalogo in i18n.CATALOGS.items():
        vazias = sorted(c for c, v in catalogo.items() if not v.strip())
        assert vazias == [], f"{idioma}: chave sem texto {vazias}"


def test_toda_chave_segue_a_convencao():
    """`area.assunto`, minusculo: a chave e identificador, nao texto de tela."""
    fora = sorted(c for c in i18n.CATALOGS["pt"]
                  if c != c.lower() or "." not in c or " " in c)
    assert fora == [], f"chave fora da convencao: {fora}"


def test_idiomas_oferecidos_tem_catalogo():
    for codigo, rotulo in i18n.LANGUAGES:
        assert codigo in i18n.CATALOGS, f"{codigo} aparece no seletor e nao tem catalogo"
        assert rotulo.strip()


# ------------------------------------------------------------- traduzir

def test_traduz_para_o_idioma_pedido():
    assert i18n.translate("nav.servers", "en") == "Servers"
    assert i18n.translate("nav.servers", "pt") == "Servidores"


def test_chave_desconhecida_volta_como_chave():
    """Aparecer 'nav.inexistente' na tela e feio - e e exatamente o ponto: da para ver."""
    assert i18n.translate("nav.inexistente", "en") == "nav.inexistente"


def test_idioma_desconhecido_cai_no_portugues():
    assert i18n.translate("nav.servers", "klingon") == "Servidores"


def test_chave_sem_traducao_cai_no_portugues(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS, "en", {})
    assert i18n.translate("nav.servers", "en") == "Servidores"


# -------------------------------------------------------- idioma_valido

@pytest.mark.parametrize("raw", ["", "  ", None, "klingon", "pt-BR", "EN"])
def test_idioma_invalido_vira_o_padrao(raw):
    assert i18n.valid_language(raw) == i18n.DEFAULT


@pytest.mark.parametrize("raw", ["pt", "en", " en "])
def test_idioma_valido_passa(raw):
    assert i18n.valid_language(raw) == raw.strip()


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
    assert i18n.from_header(cabecalho) == esperado


# ---------------------------------------------------------- campos na frase

def test_campo_entra_no_lugar_do_marcador(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.ritmo", "a cada {n}s")
    assert i18n.translate("t.ritmo", "pt", n=15) == "a cada 15s"


def test_campo_a_mais_e_ignorado(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.simples", "sem marcador")
    assert i18n.translate("t.simples", "pt", n=15) == "sem marcador"


@pytest.mark.parametrize("frase", [
    "faltou o {outro}",      # marcador sem campo: KeyError
    "chave {} solta",        # posicional sem argumento: IndexError
    "chave { torta",         # marcador mal formado: ValueError
])
def test_marcador_que_nao_casa_nao_derruba_a_tela(monkeypatch, frase):
    """Frase e campo vem de lugares diferentes; a tela inteira nao pode cair por isso."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.torta", frase)
    assert i18n.translate("t.torta", "pt", n=15) == frase


def test_a_frase_do_idioma_pedido_e_que_recebe_o_campo(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.ritmo", "a cada {n}s")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.ritmo", "every {n}s")
    assert i18n.translate("t.ritmo", "en", n=15) == "every 15s"


# ------------------------------------------------- frase com marcacao (_h)

def test_frase_com_marcacao_chega_inteira_na_tela(monkeypatch):
    """A frase vem do catalogo, que e codigo daqui: a marcacao dela e para valer."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.rico", "avisa na <strong>mudanca</strong>")
    with panel.app.test_request_context("/"):
        assert str(panel.translate_html("t.rico")) == "avisa na <strong>mudanca</strong>"


def test_campo_que_vem_de_fora_e_escapado(monkeypatch):
    """O campo NAO e do catalogo; sem escape, um nome de servidor viraria marcacao."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.rico", "servidor <strong>{nome}</strong>")
    with panel.app.test_request_context("/"):
        saida = str(panel.translate_html("t.rico", nome="<script>x</script>"))
    assert saida == "servidor <strong>&lt;script&gt;x&lt;/script&gt;</strong>"


def test_frase_encaixada_noutra_passa_inteira(monkeypatch):
    """Paragrafo que embute outro (`_h` dentro de `_h`) nao pode escapar duas vezes."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.fora", "ouvindo ({dentro})")
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.dentro", "<strong>{n}</strong> agora")
    with panel.app.test_request_context("/"):
        dentro = panel.translate_html("t.dentro", n=3)
        assert str(panel.translate_html("t.fora", dentro=dentro)) == "ouvindo (<strong>3</strong> agora)"


# ---------------------------------------------- fora de pedido (monitor, relogio)

def test_traduzir_fora_de_pedido_usa_o_padrao_do_deploy():
    """O monitor roda em thread propria: sem este caminho, um alerta traduzido
    derrubaria a volta inteira com "Working outside of application context"."""
    assert panel.current_language() == panel.DEFAULT_LANG
    assert panel.translate("nav.servers") == i18n.CATALOGS[panel.DEFAULT_LANG]["nav.servers"]


def test_idioma_padrao_vem_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.setattr(panel, "DEFAULT_LANG", "en")
    assert panel.translate("nav.servers") == "Servers"


# ---------------------------------------------- Mensagem (texto que sabe a chave)

def test_mensagem_e_uma_str_comum_no_idioma_do_deploy(monkeypatch):
    """Todo consumidor de hoje (log, str(exc), f-string, `in`) tem de seguir valendo."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.erro", "porta {n} invalida")
    m = i18n.Message("t.erro", n=70000)
    assert isinstance(m, str)
    assert str(m) == "porta 70000 invalida"
    assert "invalida" in m
    assert f"deu ruim: {m}" == "deu ruim: porta 70000 invalida"


def test_mensagem_traduzida_refaz_a_frase_no_idioma_pedido(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.erro", "porta {n} invalida")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.erro", "port {n} is invalid")
    assert i18n.translate(i18n.Message("t.erro", n=70000), "en") == "port 70000 is invalid"


def test_str_solta_nao_vira_frase_traduzida(monkeypatch):
    """Texto que nao veio de uma chave passa inteiro, em vez de sumir na cascata."""
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.erro", "port is invalid")
    assert i18n.translate("porta 70000 invalida", "en") == "porta 70000 invalida"


def test_repr_da_mensagem_mostra_a_chave(monkeypatch):
    """Num assert que falha, ver a chave vale mais do que ver a frase."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.erro", "porta {n} invalida")
    assert repr(i18n.Message("t.erro", n=1)) == "Mensagem('t.erro', {'n': 1})"


# ------------------------------------- o campo passado casa com o marcador da frase

def _chamadas_de_traducao(arvore: ast.AST) -> list[tuple[int, str, set[str]]]:
    """(linha, chave, campos) de cada `_('x', a=1)` / `Mensagem('x', a=1)` do modulo."""
    achadas = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func.id if isinstance(no.func, ast.Name) else getattr(no.func, "attr", "")
        if alvo not in {"_", "_h", "traduzir", "traduzir_html", "Mensagem",
                        "rotulo_para_o_banco"} or not no.args:
            continue
        chave = no.args[0]
        if isinstance(chave, ast.Constant) and isinstance(chave.value, str):
            achadas.append((no.lineno, chave.value,
                            {k.arg for k in no.keywords if k.arg}))
    return achadas


def test_todo_campo_passado_existe_como_marcador_na_frase():
    """O marcador e o kwarg tem de ter o mesmo nome, e nada avisa quando nao tem.

    `traduzir` engole o `KeyError` de proposito (frase e campo vem de lugares diferentes,
    e derrubar a tela por causa disso e caro demais) — o preco e que um campo com nome
    errado some em silencio, deixando `{name}` cru na tela. Este teste e quem cobra.
    Ja aconteceu tres vezes durante a traducao dos identificadores para ingles.
    """
    problemas = []
    for arquivo in sorted(Path(panel.__file__).parent.rglob("*.py")):
        if arquivo.parent.name == "i18n":
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for linha, chave, campos in _chamadas_de_traducao(arvore):
            frase = i18n.CATALOGS["pt"].get(chave)
            if frase is None:
                continue  # chave montada em tempo de execucao; outro teste cobre
            marcadores = set(re.findall(r"\{([a-z_]+)\}", frase))
            sobrando = campos - marcadores
            if sobrando:
                problemas.append(
                    f"{arquivo.name}:{linha} {chave}: passa {sorted(sobrando)}, "
                    f"a frase usa {sorted(marcadores)}")
    assert problemas == [], "campo sem marcador correspondente:\n" + "\n".join(problemas)


def test_os_dois_idiomas_usam_os_mesmos_marcadores():
    """Traducao que troca `{n}` por `{numero}` quebra so naquele idioma."""
    fora = []
    for chave, frase in i18n.CATALOGS["pt"].items():
        de_pt = set(re.findall(r"\{([a-z_]+)\}", frase))
        de_en = set(re.findall(r"\{([a-z_]+)\}", i18n.CATALOGS["en"][chave]))
        if de_pt != de_en:
            fora.append(f"{chave}: pt={sorted(de_pt)} en={sorted(de_en)}")
    assert fora == [], "marcadores diferentes entre os idiomas:\n" + "\n".join(fora)


def test_campo_que_e_mensagem_vai_para_o_mesmo_idioma_da_frase(monkeypatch):
    """Frase montada de pedacos traduziveis nao pode sair metade em cada lingua.

    Aconteceu no rotulo do agendamento: a tela em ingles mostrava "todo sabado at
    03:00", porque o dia entrava pelo `str` da Message (sempre o idioma do deploy).
    """
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.quando", "{dia} as {hora}")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.quando", "{dia} at {hora}")
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.sabado", "todo sabado")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.sabado", "every Saturday")
    montada = i18n.Message("t.quando", dia=i18n.Message("t.sabado"), hora="03:00")
    assert str(montada) == "todo sabado as 03:00"
    assert i18n.translate(montada, "en") == "every Saturday at 03:00"
