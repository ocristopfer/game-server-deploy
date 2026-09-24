"""O ponto de entrada da unit systemd contra o que o pacote de fato exporta.

O gunicorn recebe o callable como TEXTO (`gamebroker.wsgi:create_app_from_env()`), escrito
dentro de um heredoc de shell. Nada liga esse texto a funcao: renomear a funcao deixa a
unit apontando para um nome que nao existe, e quem descobre e o gunicorn no CT, com
`Failed to find attribute` e exit 4.

O custo nao e "o deploy falha". A unit e reescrita ANTES de qualquer teste de saude, entao
o deploy derruba um servico que estava no ar e nao consegue mais levanta-lo -- e, se o
provisionamento aborta antes de chegar na unit, nem o deploy seguinte sobe.

O sandbox (`docker/ct-sandbox/broker.sh`) tambem confere isso, mas pede Docker; este roda
sempre. E a checagem de la fazia `grep` de uma COPIA literal do nome: ela concordava com o
script e ficava verde com os dois errados. Aqui a pergunta e feita ao codigo.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]

# `pacote.modulo:funcao` ou `'pacote.modulo:funcao()'`: o gunicorn aceita as duas formas e o
# repo usa uma em cada servico (o painel expoe o objeto pronto, o broker uma fabrica).
APP_SPEC = re.compile(
    r"'?([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)+):([A-Za-z_]\w*)(?:\(\))?'?\s*$")

# provisionamento -> a pasta onde o pacote dele mora na arvore
PROVISIONERS = {
    "deploy/broker/provision-broker-lxc.sh": "src",
    "deploy/admin/provision-admin-lxc.sh": "src",
}


def _exec_start_entry_points(text: str) -> list[tuple[str, str]]:
    """(modulo pontilhado, nome) de cada `ExecStart=` do arquivo.

    A varredura e amarrada ao ExecStart de proposito: `modulo:nome` solto aparece tambem
    em COMENTARIO -- este arquivo e o proprio provisionamento citam o nome velho ao
    explicar o defeito --, e conferir citacao em prosa faria o guard reclamar de texto.
    """
    lines = text.splitlines()
    found: list[tuple[str, str]] = []
    for number, line in enumerate(lines):
        if not line.startswith("ExecStart="):
            continue
        # A unit continua a linha com uma barra invertida no fim; junta tudo antes de ler.
        pieces, index = [line], number
        while lines[index].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            pieces.append(lines[index])
        joined = " ".join(p.rstrip().removesuffix("\\").strip() for p in pieces)
        match = APP_SPEC.search(joined)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def _top_level_names(module: pathlib.Path) -> set[str]:
    """Nomes que o modulo define no topo, pelo AST.

    Pelo AST e nao importando: `gamepanel.app` abre banco e sobe thread no import, e o
    que se quer saber aqui e so se o NOME existe.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


def test_o_callable_da_unit_existe_no_pacote():
    missing: list[str] = []
    checked: list[str] = []
    for script, root in PROVISIONERS.items():
        text = (REPO / script).read_text(encoding="utf-8")
        for dotted, name in _exec_start_entry_points(text):
            checked.append(f"{dotted}:{name}")
            module = (REPO / root / pathlib.Path(*dotted.split("."))).with_suffix(".py")
            if not module.exists():
                missing.append(f"{script}: o modulo {dotted} nao existe ({module})")
            elif name not in _top_level_names(module):
                missing.append(f"{script}: {dotted}:{name} nao existe em {module.name}")
    # Os DOIS servicos tem de aparecer: o do painel nao tem parenteses nem aspas, e uma
    # regex pensada so para o broker o deixava de fora sem que nada reclamasse.
    assert len(checked) == len(PROVISIONERS), (
        f"esperava um ponto de entrada por provisionamento, achei {checked}")
    assert not missing, ("ponto de entrada da unit que o pacote nao tem:\n  "
                         + "\n  ".join(missing))
