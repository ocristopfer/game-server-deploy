"""Texto de tela nao pode nascer literal: `translate` devolveria a frase como esta.

A cascata do `i18n` e "idioma pedido -> pt -> a propria chave". Uma frase inteira passada
ao `translate` nao e chave de nada, entao ela sai IGUAL — e a tela em ingles mostra
portugues, sem erro, sem log e sem nenhum outro teste reclamando: o `test_i18n.py` confere
as CHAMADAS de `_()`/`_h()`, nao o que uma funcao devolveu.

Ja aconteceu duas vezes. Primeiro nas duas frases de senha e no rotulo `broker-jogo` do
historico. Depois em mais dezesseis, achadas contra o container ao vivo: com a tela em
ingles, o 403 de operador dizia "restrita" e a rota inexistente dizia "Pagina nao
encontrada". As barreiras (`abort`), os erros de formulario (`errors.append`) e os flashes
eram todos literais.

O teste olha para as tres portas por onde texto entra na tela e cobra CHAVE, nunca frase:
`abort(codigo, ...)`, `errors.append(...)` e `flash(...)`. Chamada com `Message(...)`,
`translate(...)` ou variavel passa; literal com espaco, nao.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[2]
SCREEN_FILES = [ROOT / "src/gamepanel/app.py",
                *sorted((ROOT / "src/gamepanel/blueprints").glob("*.py"))]

# Onde o texto chega a PESSOA. `_log_broker_action` e `notify` ficam de fora: o primeiro
# grava a saida de um job (idioma do deploy, de proposito — ver `label_for_db`) e o
# segundo monta o aviso do canal, que segue a mesma regra.
DOORS = {"abort", "flash", "append"}


def _sentences() -> list[tuple[str, int, str]]:
    """Literais com espaco que entram por uma das portas. Espaco e o sinal: uma chave de
    catalogo (`error.admin_only`) nunca tem, uma frase sempre tem."""
    found: list[tuple[str, int, str]] = []
    for path in SCREEN_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name not in DOORS:
                continue
            # `errors.append` e a porta; `log.append`/`lines.append` nao sao tela.
            if name == "append" and getattr(node.func, "value", None) is not None:
                target = getattr(node.func.value, "id", "")
                if target not in ("errors", "failures"):
                    continue
            for arg in node.args:
                # `abort(403, ...)`: o codigo e o primeiro argumento e nao e texto.
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and " " in arg.value:
                    found.append((path.name, node.lineno, arg.value))
                # f-string com frase dentro conta igual: ela tambem nao e chave.
                if isinstance(arg, ast.JoinedStr):
                    text = "".join(v.value for v in arg.values
                                   if isinstance(v, ast.Constant) and isinstance(v.value, str))
                    if " " in text.strip():
                        found.append((path.name, node.lineno, text))
    return found


def test_nenhuma_frase_literal_chega_a_tela():
    leftover = sorted({f"{f}:{n} {text[:60]!r}" for f, n, text in _sentences()})
    assert leftover == [], (
        "frase literal indo para a tela; ela sai igual no idioma de quem olha. Ponha em "
        "pt.py/en.py e use i18n.Message(chave):\n  " + "\n  ".join(leftover))


def test_a_varredura_olha_para_os_arquivos_de_tela():
    """Zero arquivos e o jeito silencioso de este teste parar de valer."""
    assert len(SCREEN_FILES) >= 15


@pytest.mark.parametrize("key", [
    "error.not_found", "error.admin_only", "error.terminal_disabled",
    "error.broker_disabled", "flash.server_duplicate", "flash.username_invalid",
    "flash.schedule_bad_interval", "error.upload_too_large",
])
def test_as_chaves_das_barreiras_existem_nos_DOIS_idiomas(key: str):
    """Chave sem par sai na tela como `error.admin_only`, que e barulhento mas feio."""
    assert key in i18n.CATALOGS["pt"]
    assert key in i18n.CATALOGS["en"]
