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
        limpo = JINJA_EXPR.sub(" ", path.read_text(encoding="utf-8"))
        for attr in CLASS_ATTR.findall(limpo):
            for name in attr.split():
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


def _campos_do_medidor() -> set[str]:
    from gamepanel.runtime import metrics_probe

    return set(metrics_probe.parse_metrics(METRICS_SAMPLE))


def test_a_tela_de_servidor_le_so_campos_que_o_medidor_entrega():
    html = (TEMPLATES / "server_detail.html").read_text(encoding="utf-8")
    lidos = set(re.findall(r"metrics\.([a-z_]+)", html))
    # `error` nasce quando a leitura FALHA, entao nao esta na amostra boa.
    faltando = sorted(lidos - _campos_do_medidor() - {"error"})
    assert faltando == [], f"a tela le campo que o medidor nao entrega: {faltando}"


def test_o_medidor_ainda_entrega_o_numero_de_nucleos():
    """`cores` e a palavra que colide: nucleos em ingles, cores em portugues. Uma
    renomeacao automatica ja trocou uma pela outra nos dois lados."""
    assert "cores" in _campos_do_medidor()
