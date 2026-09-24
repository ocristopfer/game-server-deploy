"""`url_for(..., chave=valor)` e um par com quem LE aquela chave do outro lado.

O kwarg de `url_for` que nao e captura de rota vira QUERY STRING, e alguem tem de
`request.args.get` com o mesmo nome. Os dois lados vivem como texto em arquivos diferentes
e nenhuma ferramenta os liga: se o nome divergir, o link continua respondendo 200 e o valor
simplesmente nao chega.

Ja aconteceu tres vezes de uma vez, todas por renomear o nome de fio com um lado so — e
todas em `url_for` montado em PYTHON, que e por onde a conferencia de template nao olha:

- `url_for("players.setup", sid=sid, aba="http")` depois de a rota passar a ler `tab`:
  o botao "usar esta API" voltava para a aba de portas em vez da de HTTP;
- o mesmo com `aba="log"`;
- `{"pasta": request.args["path"]}` no redirect da busca de arquivos, com a rota lendo
  `folder`: a pasta escolhida era perdida e a busca ia para a pasta de config do cadastro.
"""
from __future__ import annotations

import ast
from pathlib import Path

import gamepanel.app as panel

PANEL = Path(panel.__file__).parent
PY_FILES = [PANEL / "app.py", *sorted((PANEL / "blueprints").glob("*.py"))]

# Kwarg que NAO e query string: captura de rota (o Flask a consome na URL) e os nomes que
# o proprio Flask define. Reconhecidos pela lista de capturas das rotas, nao a mao.
FLASK_OWN = {"_external", "_anchor", "_method", "_scheme", "filename"}
# `v=` no `url_for("static", ...)` existe para MUDAR a URL, nao para ser lido: e a marca
# que descarta o cache do navegador quando um estatico muda. Ninguem a le no servidor, e e
# isso mesmo.
NOT_READ_ON_PURPOSE = {"v"}


def _route_captures() -> set[str]:
    """Todo `<int:sid>`/`<tid>` declarado nas rotas registradas: esses somem na URL."""
    found: set[str] = set()
    for rule in panel.app.url_map.iter_rules():
        found |= set(rule.arguments)
    return found


def _read_keys() -> set[str]:
    """Nome que algum `request.args/form/files.get(...)` le."""
    found: set[str] = set()
    for path in sorted(PANEL.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "getlist") and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


def _dict_keys_named(tree: ast.AST, name: str, filename: str) -> list[tuple[str, int, str]]:
    """Chaves do dict literal atribuido a `name` (inclui `x: dict = {...}`)."""
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if getattr(target, "id", None) != name:
            continue
        value = node.value
        # `{...} if cond else {...}`: os dois lados contam.
        options = ([value.body, value.orelse] if isinstance(value, ast.IfExp) else [value])
        for option in options:
            if isinstance(option, ast.Dict):
                for key in option.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.append((filename, option.lineno, key.value))
    return found


def _url_for_kwargs() -> list[tuple[str, int, str]]:
    """(arquivo, linha, chave) de cada kwarg de `url_for` e de cada dict que o alimenta."""
    found: list[tuple[str, int, str]] = []
    for path in PY_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "url_for"):
                continue
            for kw in node.keywords:
                if kw.arg:
                    found.append((path.name, node.lineno, kw.arg))
                # `**extras`, onde `extras` e um dict literal atribuido no arquivo: o nome
                # da chave vive numa string, que e justo o caso que passou batido. Resolve o
                # NOME, e nao todo dict do arquivo — a primeira versao disto colheu os
                # dicionarios de cabecalho HTTP e o teste acusou `Content-Length=`.
                elif isinstance(kw.value, ast.Name):
                    found += _dict_keys_named(tree, kw.value.id, path.name)
    return found


def test_a_varredura_encontra_os_url_for():
    assert len({k for _f, _l, k in _url_for_kwargs()}) >= 6
    assert len(_route_captures()) >= 5


def test_todo_kwarg_de_url_for_e_captura_de_rota_ou_alguem_o_LE():
    captures = _route_captures() | FLASK_OWN | NOT_READ_ON_PURPOSE
    read = _read_keys()
    orphans = sorted({f"{f}:{line} {key}=" for f, line, key in _url_for_kwargs()
                      if key not in captures and key not in read})
    assert orphans == [], (
        "kwarg de url_for que nao e captura de rota e ninguem le do outro lado — o link "
        "responde 200 e o valor nao chega:\n  " + "\n  ".join(orphans))


# ---------------------------------------------- nome de endpoint na navegacao

def test_todo_endpoint_citado_na_navegacao_existe():
    """`navigation.py` escreve o nome do endpoint como TEXTO, e nada o liga a rota.

    Um nome que sobrou depois de a rota morrer nao quebra nada — a aba so nunca acende por
    ele — e fica ali para sempre. Foi o caso de `files.search`, uma rota vestigial que
    redirecionava para a busca de configuracao: nenhum link do painel a chamava, e o
    `_ACTIVE_EXTRA` continuava citando-a. De quebra, ela estava QUEBRADA — mandava
    `pasta=` para uma rota que passou a ler `folder`, entao quem tivesse o link antigo
    perdia a pasta escolhida em silencio.

    O contrario tambem e defeito, mas de outro tipo: rota nova que ninguem poe na
    navegacao abre com a aba errada acesa. Esse fica de fora de proposito — ha rota que
    NAO e tela (`/api/...`, `/health`, `/sw.js`) e a lista viraria uma excecao por rota.
    """
    from gamepanel import navigation as ui

    real = {rule.endpoint for rule in panel.app.url_map.iter_rules()}
    cited: set[str] = set()
    for names in ui._ACTIVE_EXTRA.values():
        cited |= set(names)
    for table in (ui._ALL_ITEMS,):
        cited |= {item.endpoint for item in table.values() if getattr(item, "endpoint", None)}
    dead = sorted(cited - real)
    assert dead == [], (
        "endpoint citado na navegacao que nao existe mais (a aba nunca acende por ele):\n  "
        + "\n  ".join(dead))
