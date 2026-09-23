"""O `CLAUDE.md` cita nome de codigo; este teste cobra que ele ainda exista.

A doc deste repositorio e densa de nomes proprios: `app.COMMANDS`, `ui.ACTIONS`,
`opnsense.busy_ports`. Cada renomeacao deixa alguns para tras, e o resultado e pior que
doc faltando — e doc que MENTE, e manda a proxima pessoa procurar um nome que nao existe
mais. Quatro casos assim foram encontrados de uma vez ao escrever isto: a doc mandava
procurar taken_ports no opnsense, _limpar no instalador por SSH, somente_banco no broker
e menu_acao nos macros. Os nomes mortos ficam SEM crase aqui de proposito — com ela, a
propria doc deste teste viraria uma citacao que o teste reprova.

O escopo e estreito de proposito: so `modulo.nome` dentro de crase, onde `modulo` e de
fato um modulo destes pacotes. Tres formas tem o MESMO formato e nao sao referencia a
codigo, entao saem:

- chave de i18n (`charts.players`) — reconhecida por existir no catalogo, nao por lista;
- nome de arquivo (`compare.sh`, `components/ui.html`) — pela extensao;
- modulo de fora (`re.ASCII`, `flask.g`) — pela ausencia de um modulo com esse nome aqui.

Variavel de ambiente, funcao de bash e chave de dado nao entram porque nao tem ponto.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "CLAUDE.md"
PACKAGES = ("src/gamepanel", "src/gamebroker")

# `modulo.nome` ou `modulo.nome()`, dentro de crase. O modulo minusculo de proposito:
# `Classe.metodo` pode vir de biblioteca, e nao ha o que conferir.
CITATION = re.compile(r"`([a-z_][a-z_0-9]*)\.([A-Za-z_][\w]*)(?:\(\))?`")
EXTENSIONS = {"py", "sh", "ps1", "html", "jinja", "js", "css", "md", "env", "ini",
              "toml", "json", "yml", "service", "timer", "webmanifest", "db", "pub",
              "pem", "gz", "zst", "lock", "example", "txt", "log", "webp", "png", "svg"}

# Colisoes de FORMATO, nao de nome. Cada uma tem um motivo diferente, e por isso a lista
# e curta e escrita a mao em vez de uma regra generica que deixaria passar outras coisas.
NOT_CODE = {
    # `servers` e `jobs` sao tabela do banco alem de modulo de blueprint.
    "servers.broker_id", "jobs.broker_op",
    # `app` e o objeto Flask; `run` e metodo dele, nao do modulo.
    "app.run",
    # A doc cita este como CONTRA-exemplo ("servers.detail, nao servers.server_detail").
    "servers.server_detail",
}


def _defined_names() -> dict[str, set[str]]:
    """modulo -> nomes que ele define no topo (funcao, classe, constante)."""
    found: dict[str, set[str]] = {}
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            names: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Metodo de classe entra junto: a doc cita `instance_service._undo`, que e
            # metodo do `Service` e nao nome de topo.
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
            found.setdefault(path.stem, set()).update(names)
    return found


def _citations() -> list[tuple[str, str]]:
    text = DOC.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2)) for m in CITATION.finditer(text)]


def _checkable() -> list[tuple[str, str]]:
    defined = _defined_names()
    catalog = i18n.CATALOGS["pt"]
    return [
        (module, name) for module, name in _citations()
        if module in defined and name not in EXTENSIONS
        and f"{module}.{name}" not in catalog
        and f"{module}.{name}" not in NOT_CODE
    ]


def test_a_varredura_encontra_citacoes_de_codigo():
    """Zero citacoes conferiveis e o jeito silencioso de este teste parar de valer.

    O piso e baixo porque o filtro e severo: das ~90 citacoes com ponto do CLAUDE.md,
    a maioria e chave de i18n, nome de arquivo ou modulo de fora. O que sobra e o que
    de fato aponta para codigo daqui.
    """
    assert len(_checkable()) >= 12


def test_todo_nome_citado_ainda_existe():
    defined = _defined_names()
    missing = sorted(
        f"{module}.{name}" for module, name in _checkable() if name not in defined[module]
    )
    assert missing == [], (
        "nome citado no CLAUDE.md que sumiu do codigo (a doc manda procurar o que nao "
        "existe):\n  " + "\n  ".join(missing))
