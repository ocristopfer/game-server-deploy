"""O contrato entre template, CSS e JavaScript: quem escreve e quem le.

Mesma familia de defeito que o `test_template_contract.py` guarda, e pelo mesmo motivo:
o nome existe como TEXTO dos dois lados e nenhuma ferramenta liga os dois.

- uma classe so no `class=` e estilo que nunca chega — a tela abre torta, com 200;
- uma classe so no `.css` e regra morta, que a proxima pessoa tenta "usar";
- um `data-*` so no template e comportamento que nao monta, sem erro no console;
- um `data-*` so no JavaScript e uma feature que nunca encontra elemento nenhum.

Nenhum dos quatro aparece em teste de rota (a pagina responde 200) nem no lint.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gamepanel import app as panel

PANEL = Path(panel.__file__).parent
TEMPLATES = PANEL / "templates"
CSS_DIR = PANEL / "static" / "css"
JS_DIR = PANEL / "static" / "js"

CLASS_ATTR = re.compile(r"""class=["']([^"']*)["']""")
# `{{ 'x' if cond }}` dentro do class=: o que sobra depois de tirar as chaves do Jinja.
JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
CSS_RULE = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
DATA_ATTR = re.compile(r"data-([a-z][a-z0-9-]*)")

# Classes que nascem no JavaScript ou vem de um valor do servidor, entao nao aparecem
# literais em nenhum `class=`. Cada uma e uma decisao, nao uma excecao generica.
CLASSES_SEM_TEMPLATE = {
    # Estado que o JS liga e desliga.
    "on", "off", "ok", "warn", "hot", "cold", "open", "js",
    # Utilitarias do reset, aplicadas a elemento cru.
    "html",
}


# `{% set classes = classes + ['btn--block'] %}` — nome COMPLETO, e nao um prefixo
# montado com `~`: este o teste consegue conferir contra o CSS.
SET_CLASS = re.compile(r"""\+\s*\[["']([\w-]+)["']\]""")


def _templates() -> list[Path]:
    return sorted(p for p in TEMPLATES.rglob("*") if p.suffix in (".html", ".jinja"))


def classes_in_templates() -> dict[str, str]:
    """Classe -> primeiro template que a usa.

    O Jinja sai ANTES de procurar o `class=`: `class="menu{{ ' ' ~ classe if classe }}"`
    tem aspa simples dentro do atributo, e um regex que so conta aspas fecharia no meio
    da expressao e colheria `menu{{` como se fosse uma classe.
    """
    found: dict[str, str] = {}
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        clean = JINJA_EXPR.sub(" ", text)
        for attr in CLASS_ATTR.findall(clean):
            for name in attr.split():
                found.setdefault(name, path.name)
        # Classe montada por LISTA no proprio Jinja: `{% set classes = classes +
        # ['btn--block'] %}`. Ela nunca aparece num `class=`, entao o `JINJA_EXPR.sub`
        # acima a apaga junto com o resto da expressao — e era assim que `btn--bloco`
        # sobrevivia sem nenhuma regra de CSS. Todo botao `block=true` do painel (login,
        # conta, formularios) deixou de ocupar a largura inteira do cartao e nada
        # acusou: o HTML sai inteiro, a pagina responde 200 e a classe simplesmente
        # nao casa com regra nenhuma.
        for name in SET_CLASS.findall(text):
            found.setdefault(name, path.name)
    return found


def class_prefixes_in_templates() -> set[str]:
    """Prefixos de classe MONTADA em runtime: `'btn--' ~ variante` vira `btn--`.

    Sem isto, toda variacao (`btn--danger`, `btn--sm`, ...) pareceria regra morta: o
    nome completo nao existe em lugar nenhum do template.
    """
    prefixes: set[str] = set()
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        prefixes |= set(re.findall(r"""["']([\w-]*--)["']\s*~""", text))
        prefixes |= set(re.findall(r"""["']([\w-]*-)["']\s*~""", text))
    return prefixes


def names_seen_anywhere() -> set[str]:
    """Todo identificador solto de template e JavaScript.

    Para a direcao "regra morta" basta o nome APARECER: ele pode chegar ao `class=` por
    um argumento de macro, por um `{% set %}` ou por um `classList.add`. Ser rigoroso
    aqui so produziria excecao escrita a mao, que e o que este teste existe para evitar.
    """
    names: set[str] = set()
    for path in [*_templates(), *sorted(JS_DIR.rglob("*.js"))]:
        names |= set(re.findall(r"[\w-]+", path.read_text(encoding="utf-8")))
    return names


def classes_in_css() -> set[str]:
    names: set[str] = set()
    for path in sorted(CSS_DIR.glob("*.css")):
        names |= set(CSS_RULE.findall(path.read_text(encoding="utf-8")))
    return names


def _js_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(JS_DIR.rglob("*.js")))


def classes_in_js() -> set[str]:
    text = _js_text()
    names = set()
    # `classList.add('x')`, `classList.toggle('x', cond)`, `querySelector('.x')`
    for chunk in re.findall(r"classList\.\w+\(([^)]*)\)", text):
        names |= set(re.findall(r"""["']([\w-]+)["']""", chunk))
    for chunk in re.findall(r"""["']\.([\w-]+)["']""", text):
        names.add(chunk)
    return names


def data_in_templates() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _templates():
        for name in DATA_ATTR.findall(path.read_text(encoding="utf-8")):
            found.setdefault(name, path.name)
    return found


def data_in_js() -> set[str]:
    text = _js_text()
    names = set(re.findall(r"\[data-([a-z][a-z0-9-]*)\]", text))
    # `el.dataset.jobUrl` -> data-job-url
    for camel in re.findall(r"dataset\.([a-zA-Z][a-zA-Z0-9]*)", text):
        names.add(re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), camel))
    return names


def test_toda_classe_usada_num_template_tem_regra_no_css():
    """Classe sem regra e estilo que nunca chega: a tela abre torta, e responde 200."""
    styled = classes_in_css() | classes_in_js()
    orphans = sorted(
        f"{name} (em {where})"
        for name, where in classes_in_templates().items()
        if name not in styled
    )
    assert orphans == [], "classe usada sem regra de CSS:\n  " + "\n  ".join(orphans)


def test_toda_regra_de_css_tem_quem_a_use():
    """Regra morta e pior que inutil: a proxima pessoa a le como se estivesse em uso."""
    used = names_seen_anywhere() | CLASSES_SEM_TEMPLATE
    prefixes = tuple(class_prefixes_in_templates())
    dead = sorted(
        name for name in classes_in_css()
        if name not in used and not (prefixes and name.startswith(prefixes))
    )
    assert dead == [], "regra de CSS que ninguem usa:\n  " + "\n  ".join(dead)


def test_todo_data_lido_pelo_javascript_existe_em_algum_template():
    """Feature que procura um `data-*` inexistente nunca monta, e nao diz nada."""
    written = set(data_in_templates())
    orphans = sorted(name for name in data_in_js() if name not in written)
    assert orphans == [], "data-* que o JS procura e nenhum template escreve:\n  " + "\n  ".join(orphans)


@pytest.mark.parametrize("feature", [
    "confirmAction", "dropdownMenu", "chart", "followLog", "watchJob",
])
def test_o_app_js_registra_a_feature_que_o_modulo_exporta(feature):
    """`app.js` liga feature a elemento pelo NOME: exportar e nao registrar e o mesmo
    que nao existir."""
    app_js = (JS_DIR / "app.js").read_text(encoding="utf-8")
    assert feature in app_js


# O `server_detail.html` le `metrics.X` direto. `X` que o medidor nao entrega nao levanta
# nada: some da tela e a pagina responde 200. Foi assim que `metrics.cores` virou
# `metrics.colors` numa renomeacao e o numero de nucleos sumiu sem quebrar teste nenhum.
#
# A lista de campos NAO e escrita aqui: sai do proprio `parse_metrics`, para nao virar
# mais uma copia que envelhece em silencio.
METRICS_SAMPLE = """sample|1000|100000|0|0|0|0|0|0
sample|2000|200000|0|0|0|0|0|0
cores|4
cpumax|400
tick|100
load|0.5
boot|1000
meminfo|MemTotal|1000
meminfo|MemAvailable|500
meminfo|SwapTotal|0
meminfo|SwapFree|0
disk|/|1000|500
proc|123|4096
"""


def _meter_fields() -> set[str]:
    from gamepanel.runtime import metrics_probe

    return set(metrics_probe.parse_metrics(METRICS_SAMPLE))


def test_a_tela_de_servidor_le_so_campos_que_o_medidor_entrega():
    html = (TEMPLATES / "server_detail.html").read_text(encoding="utf-8")
    read_ones = set(re.findall(r"metrics\.([a-z_]+)", html))
    # `error` nasce quando a leitura FALHA, entao nao esta na amostra boa.
    missing = sorted(read_ones - _meter_fields() - {"error"})
    assert missing == [], f"a tela le campo que o medidor nao entrega: {missing}"


def test_o_medidor_ainda_entrega_o_numero_de_nucleos():
    """`cores` e a palavra que colide: nucleos em ingles, cores em portugues. Uma
    renomeacao automatica ja trocou uma pela outra nos dois lados."""
    assert "cores" in _meter_fields()


# ---------------------------------------------------- tokens de CSS (custom properties)

CSS_VAR_DEF = re.compile(r"^\s*(--[\w-]+)\s*:", re.M)
CSS_VAR_USE = re.compile(r"var\(\s*(--[\w-]+)")

# Nome que NASCE fora do CSS. `--safe-*` vem do `env(safe-area-inset-*)` por um `@supports`
# que monta o nome; as duas telas cheias (terminal e console) escrevem a altura pelo JS.
VARS_SEM_DEFINICAO: set[str] = set()
VARS_SEM_USO = {
    # Definida so para o `@supports` de notch trocar o valor; o uso e o proprio fallback.
    "--safe-top", "--safe-bottom", "--safe-left", "--safe-right",
}


def _all_css_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(CSS_DIR.rglob("*.css")))


def css_vars_defined() -> set[str]:
    return set(CSS_VAR_DEF.findall(_all_css_text()))


def css_vars_used() -> set[str]:
    text = _all_css_text() + _js_text()
    for path in _templates():
        text += path.read_text(encoding="utf-8")
    return set(CSS_VAR_USE.findall(text))


def test_todo_token_de_css_definido_e_usado():
    """Token morto e a mesma armadilha da regra morta, e escapava deste arquivo.

    `--sombra-1` ficou definida em `tokens.css` sem um unico `var(--sombra-1)` no
    repositorio: quem lesse a lista de sombras acharia que ha tres degraus disponiveis.
    """
    dead = sorted(css_vars_defined() - css_vars_used() - VARS_SEM_USO)
    assert dead == [], "token de CSS definido e nunca usado:\n  " + "\n  ".join(dead)


def test_todo_token_de_css_usado_esta_definido():
    """`var(--nome-que-nao-existe)` nao e erro para navegador nenhum: a propriedade
    simplesmente nao aplica, e a tela abre sem a cor, sem o espaco ou sem o raio."""
    orphans = sorted(css_vars_used() - css_vars_defined() - VARS_SEM_DEFINICAO)
    assert orphans == [], "var(--x) sem definicao em tokens.css:\n  " + "\n  ".join(orphans)


# ---------------------------------------------------------- valor cru fora de tokens.css

RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")
# `color-mix(... , #fff)` e `#000` sao OPERANDO de mistura — "clareia isto", nao uma cor
# de tema. Reconhecidos pela forma, e nao por uma lista que envelheceria.
MIX_OPERAND = {"#fff", "#000", "#ffffff", "#000000"}
# Cor crua que e REQUISITO FISICO, com o motivo no proprio CSS. Sao duas, e cada uma
# quebraria de um jeito diferente se virasse token.
COLOR_OUTSIDE_TOKENS = {
    # O QR precisa de fundo branco para a camera travar nele; um token seguiria o modo
    # escuro e nenhum leitor acharia o codigo.
    "components.css": {"#fff"},
    # Primeiro plano do terminal, que acompanha a paleta ANSI do `terminal.js` (protocolo,
    # nao tema).
    "pages.css": {"#c9d3de"},
}


def test_cor_crua_so_em_tokens_css():
    """Cor escrita a mao num componente nao acompanha o tema e nao aparece na paleta.

    A excecao nao e uma lista de nomes que envelhece: e `color-mix(..., #fff)`, que se
    reconhece pela forma, mais duas cores com motivo FISICO escrito no proprio arquivo.
    """
    leftover = []
    for path in sorted(CSS_DIR.rglob("*.css")):
        if path.name == "tokens.css":
            continue
        allowed = MIX_OPERAND | COLOR_OUTSIDE_TOKENS.get(path.name, set())
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("/*", 1)[0]
            for color in RAW_COLOR.findall(code):
                if color.lower() not in allowed:
                    leftover.append(f"{path.name}:{i} {color}")
    assert leftover == [], (
        "cor crua fora de tokens.css (ela nao acompanha o tema):\n  " + "\n  ".join(leftover))


def test_todo_estado_tem_o_par_de_cor_de_texto():
    """`--ok` tinha borda e nao tinha texto, e o `.flash.ok` resolvia com um hex solto."""
    tokens = (CSS_DIR / "tokens.css").read_text(encoding="utf-8")
    for state in ("ok", "err"):
        assert f"--{state}-text:" in tokens, f"falta --{state}-text em tokens.css"
        assert f"--{state}-line:" in tokens, f"falta --{state}-line em tokens.css"


# ------------------------------------------- os limites do medidor, nos DOIS lugares

def test_o_limite_de_cor_da_barra_e_o_mesmo_no_python_e_no_javascript():
    """A barra e desenhada no SERVIDOR e atualizada pelo JS: dois donos do mesmo numero.

    O painel renderiza a barra com o filtro `level` do `app.py` e depois o `format.js` a
    reescreve a cada leitura de medidor. Se os limites divergirem, a cor muda no
    recarregamento e nao no medidor que se move (ou o contrario) — sem erro, sem log, so
    uma tela que se contradiz. Nao ha passo de build neste repositorio para compartilhar a
    constante entre Python e JavaScript, entao a ligacao e este teste.
    """
    js = (JS_DIR / "core" / "format.js").read_text(encoding="utf-8")
    found = [int(n) for n in re.findall(r"pct >= (\d+)\)", js)]
    assert found, "o `level` do format.js deixou de comparar pct com um limite"
    assert found == [panel.GAUGE_HOT, panel.GAUGE_WARN], (
        f"limites do JS {found} x do Python [{panel.GAUGE_HOT}, {panel.GAUGE_WARN}]")
