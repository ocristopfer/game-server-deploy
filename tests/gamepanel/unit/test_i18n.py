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
    missing = i18n.missing_keys("en")
    assert missing == [], f"sem traducao em ingles: {missing}"


def test_nenhuma_chave_sobrando_no_ingles():
    left_over = sorted(set(i18n.CATALOGS["en"]) - set(i18n.CATALOGS["pt"]))
    assert left_over == [], f"chave que o portugues nao tem: {left_over}"


def test_nenhum_valor_vazio():
    for language, catalog in i18n.CATALOGS.items():
        empty_ones = sorted(c for c, v in catalog.items() if not v.strip())
        assert empty_ones == [], f"{language}: chave sem texto {empty_ones}"


def test_toda_chave_segue_a_convencao():
    """`area.assunto`, minusculo: a chave e identificador, nao texto de tela."""
    outside = sorted(c for c in i18n.CATALOGS["pt"]
                  if c != c.lower() or "." not in c or " " in c)
    assert outside == [], f"chave fora da convencao: {outside}"


def test_chave_com_marcacao_nao_passa_por_traducao_que_escapa():
    """`_()` escapa: `&mdash;` saia na tela como o texto `&mdash;` (Config do ETS2, console).

    Frase com entidade ou tag e para `_h()`, que confia no catalogo e so escapa os campos.
    """
    markup = {k for k, v in i18n.CATALOGS["pt"].items() if re.search(r"&\w+;|<\w", v)}
    templates = Path(panel.__file__).parent / "templates"
    found = []
    for path in templates.rglob("*"):
        if path.suffix not in (".html", ".jinja"):
            continue
        for key in re.findall(r"(?<![\w])_\(\s*['\"]([\w.]+)['\"]", path.read_text(encoding="utf-8")):
            if key in markup:
                found.append(f"{path.name}: {key}")
    assert found == [], f"use _h() nestas chaves: {found}"


def test_idiomas_oferecidos_tem_catalogo():
    for code, label in i18n.LANGUAGES:
        assert code in i18n.CATALOGS, f"{code} aparece no seletor e nao tem catalogo"
        assert label.strip()


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

@pytest.mark.parametrize(("header", "expected"), [
    ("en-US,en;q=0.9", "en"),
    ("en", "en"),
    ("pt-BR,pt;q=0.9,en;q=0.8", "pt"),
    ("fr-FR,fr;q=0.9,en;q=0.8", "en"),
    ("", "pt"),
    (None, "pt"),
    ("klingon", "pt"),
])
def test_le_a_preferencia_do_navegador(header, expected):
    assert i18n.from_header(header) == expected


# ---------------------------------------------------------- campos na frase

def test_campo_entra_no_lugar_do_marcador(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.ritmo", "a cada {n}s")
    assert i18n.translate("t.ritmo", "pt", n=15) == "a cada 15s"


def test_campo_a_mais_e_ignorado(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.simples", "sem marcador")
    assert i18n.translate("t.simples", "pt", n=15) == "sem marcador"


@pytest.mark.parametrize("phrase", [
    "faltou o {outro}",      # marcador sem campo: KeyError
    "chave {} solta",        # posicional sem argumento: IndexError
    "chave { torta",         # marcador mal formado: ValueError
])
def test_marcador_que_nao_casa_nao_derruba_a_tela(monkeypatch, phrase):
    """Frase e campo vem de lugares diferentes; a tela inteira nao pode cair por isso."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.torta", phrase)
    assert i18n.translate("t.torta", "pt", n=15) == phrase


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
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.rico", "servidor <strong>{name}</strong>")
    with panel.app.test_request_context("/"):
        output = str(panel.translate_html("t.rico", name="<script>x</script>"))
    assert output == "servidor <strong>&lt;script&gt;x&lt;/script&gt;</strong>"


def test_frase_encaixada_noutra_passa_inteira(monkeypatch):
    """Paragrafo que embute outro (`_h` dentro de `_h`) nao pode escapar duas vezes."""
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.fora", "ouvindo ({dentro})")
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.dentro", "<strong>{n}</strong> agora")
    with panel.app.test_request_context("/"):
        inside = panel.translate_html("t.dentro", n=3)
        assert str(panel.translate_html("t.fora", dentro=inside)) == "ouvindo (<strong>3</strong> agora)"


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

def _translation_calls(arvore: ast.AST) -> list[tuple[int, str, set[str]]]:
    """(linha, chave, campos) de cada `_('x', a=1)` / `Mensagem('x', a=1)` do modulo."""
    found_ones = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        target = no.func.id if isinstance(no.func, ast.Name) else getattr(no.func, "attr", "")
        # Os nomes de HOJE: com os de antes da traducao (traduzir, Mensagem) toda chamada
        # de `translate`/`Message` em Python passava ao largo deste teste.
        if target not in {"_", "_h", "translate", "translate_html", "Message",
                        "label_for_db"} or not no.args:
            continue
        key = no.args[0]
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            found_ones.append((no.lineno, key.value,
                            {k.arg for k in no.keywords if k.arg}))
    return found_ones


def test_todo_campo_passado_existe_como_marcador_na_frase():
    """O marcador e o kwarg tem de ter o mesmo nome, e nada avisa quando nao tem.

    `traduzir` engole o `KeyError` de proposito (frase e campo vem de lugares diferentes,
    e derrubar a tela por causa disso e caro demais) — o preco e que um campo com nome
    errado some em silencio, deixando `{name}` cru na tela. Este teste e quem cobra.
    Ja aconteceu tres vezes durante a traducao dos identificadores para ingles.
    """
    problems = []
    for file_path in sorted(Path(panel.__file__).parent.rglob("*.py")):
        if file_path.parent.name == "i18n":
            continue
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for line, key, fields in _translation_calls(tree):
            phrase = i18n.CATALOGS["pt"].get(key)
            if phrase is None:
                continue  # chave montada em tempo de execucao; outro teste cobre
            markers = set(re.findall(r"\{([a-z_]+)\}", phrase))
            left_over = fields - markers
            if left_over:
                problems.append(
                    f"{file_path.name}:{line} {key}: passa {sorted(left_over)}, "
                    f"a frase usa {sorted(markers)}")
    assert problems == [], "campo sem marcador correspondente:\n" + "\n".join(problems)


def test_nenhum_marcador_tem_o_nome_de_um_parametro_da_traducao():
    """`translate(key, language, **fields)`: um campo chamado `key` colide com o proprio
    parametro e a tela morre com "got multiple values for argument 'key'". Foi o 500 de
    Editar num jogo CURADO (`games/{key}.env`) - o teste da tela so abria um dinamico,
    que usa outra frase. A regra mora na frase, entao vale para template e Python juntos.
    """
    reserved = {"key", "language"}
    clashes = [f"{key}: {{{marker}}}"
               for key, phrase in i18n.CATALOGS["pt"].items()
               for marker in set(re.findall(r"\{([a-z_]+)\}", phrase)) & reserved]
    assert clashes == [], "marcador com nome reservado:\n" + "\n".join(clashes)


def test_os_dois_idiomas_usam_os_mesmos_marcadores():
    """Traducao que troca `{n}` por `{numero}` quebra so naquele idioma."""
    outside = []
    for key, phrase in i18n.CATALOGS["pt"].items():
        de_pt = set(re.findall(r"\{([a-z_]+)\}", phrase))
        de_en = set(re.findall(r"\{([a-z_]+)\}", i18n.CATALOGS["en"][key]))
        if de_pt != de_en:
            outside.append(f"{key}: pt={sorted(de_pt)} en={sorted(de_en)}")
    assert outside == [], "marcadores diferentes entre os idiomas:\n" + "\n".join(outside)


def test_campo_que_e_mensagem_vai_para_o_mesmo_idioma_da_frase(monkeypatch):
    """Frase montada de pedacos traduziveis nao pode sair metade em cada lingua.

    Aconteceu no rotulo do agendamento: a tela em ingles mostrava "todo sabado at
    03:00", porque o dia entrava pelo `str` da Message (sempre o idioma do deploy).
    """
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.when", "{day} as {time}")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.when", "{day} at {time}")
    monkeypatch.setitem(i18n.CATALOGS["pt"], "t.saturday", "todo sabado")
    monkeypatch.setitem(i18n.CATALOGS["en"], "t.saturday", "every Saturday")
    # O nome do kwarg E o marcador da frase: sao a mesma coisa vista dos dois lados, e
    # renomear um so faz a substituicao falhar CALADA (o `translate` engole o KeyError).
    built = i18n.Message("t.when", day=i18n.Message("t.saturday"), time="03:00")
    assert str(built) == "todo sabado as 03:00"
    assert i18n.translate(built, "en") == "every Saturday at 03:00"
