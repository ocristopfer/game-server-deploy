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
- nome de arquivo (`compare.sh`, `components/ui.html`) — pela extensao, e conferido
  a parte: ver `test_todo_arquivo_citado_existe`, abaixo;
- modulo de fora (`re.ASCII`, `flask.g`) — pela ausencia de um modulo com esse nome aqui.

Variavel de ambiente, funcao de bash e chave de dado nao entram porque nao tem ponto.

O NOME DE ARQUIVO tem conferencia propria, e ela nasceu de oito nomes mortos de uma vez:
a doc mandava abrir conexao.py, ssh_install.py, servico.py, backends.py, test_gamefields.py,
instancias.html, catalogo.html e gameconf.py, todos renomeados ha commits. Todos passavam
justamente porque a regra acima os DESCARTA pela extensao — o filtro que evita o falso
positivo virou o buraco. E de quebra o teste achou `pyroject.toml`, um erro de digitacao
que estava ali desde que a secao foi escrita.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from gamepanel import i18n

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "CLAUDE.md"
PACKAGES = ("src/gamepanel", "src/gamebroker")

# `modulo.nome` ou `modulo.nome()`, dentro de crase. O modulo minusculo de proposito:
# `Classe.metodo` pode vir de biblioteca, e nao ha o que conferir.
CITATION = re.compile(r"`([a-z_][a-z_0-9]*)\.([A-Za-z_][\w]*)(?:\(\))?`")
EXTENSIONS = {"py", "sh", "ps1", "html", "jinja", "js", "css", "md", "env", "ini",
              "toml", "json", "yml", "service", "timer", "webmanifest", "db", "pub",
              "pem", "gz", "zst", "lock", "example", "txt", "log", "webp", "png", "svg"}

# So as extensoes de coisa que MORA no repositorio. `.env`, `.db`, `.pem` e `.gz` ficam de
# fora de proposito: sao arquivo de deploy, de dado ou de saida, criados fora daqui.
REPO_EXTENSIONS = ("py", "sh", "ps1", "html", "jinja", "js", "css", "md", "ini",
                   "toml", "json", "webmanifest", "service", "timer")
FILENAME = re.compile(r"`([A-Za-z0-9_./-]+\.(?:" + "|".join(REPO_EXTENSIONS) + r"))`")

# Arquivo citado que NAO existe na arvore, cada um por um motivo diferente.
NOT_A_FILE = {
    # Escrito DENTRO do tarball pelo empacotador; a doc explica isso na secao de versao,
    # e o `.gitignore` guarda o caso de ele escapar para a arvore.
    "_build.py",
}

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


def _repo_files() -> set[str]:
    """Todo caminho do repositorio, pelo caminho completo E pelo nome do arquivo.

    Pelos dois porque a doc cita das duas formas: `lib/ct-install.sh` com o caminho e
    `compare.sh` sozinho. Exigir o caminho completo obrigaria a reescrever a doc; aceitar
    so o nome deixaria passar um caminho errado. Aceitar os dois pega o que importa — o
    arquivo que deixou de existir.
    """
    found: set[str] = set()
    for path in ROOT.rglob("*"):
        parts = set(path.parts)
        if not path.is_file() or parts & {"__pycache__", ".git", ".venv", "node_modules", "dist"}:
            continue
        found.add(path.relative_to(ROOT).as_posix())
        found.add(path.name)
    return found


def _cited_files() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return sorted({
        m.group(1) for m in FILENAME.finditer(text)
        # `/sw.js` e `/static/sw.js` sao ROTA, nao caminho de arquivo; `src/*/_build.py` e
        # `provision-*-lxc.sh` sao padrao, e conferir glob so ensinaria a escrever glob.
        if not m.group(1).startswith("/") and "*" not in m.group(1)
        and m.group(1) not in NOT_A_FILE
    })


def test_a_varredura_encontra_arquivos_citados():
    assert len(_cited_files()) >= 40


def test_todo_arquivo_citado_existe():
    files = _repo_files()
    missing = [c for c in _cited_files()
               if c not in files and c.rsplit('/', 1)[-1] not in files]
    assert missing == [], (
        "arquivo citado no CLAUDE.md que nao existe na arvore (a doc manda abrir o que "
        "nao esta la):\n  " + "\n  ".join(missing))


def test_todo_nome_citado_ainda_existe():
    defined = _defined_names()
    missing = sorted(
        f"{module}.{name}" for module, name in _checkable() if name not in defined[module]
    )
    assert missing == [], (
        "nome citado no CLAUDE.md que sumiu do codigo (a doc manda procurar o que nao "
        "existe):\n  " + "\n  ".join(missing))


# --------------------------------------------------------------- rota citada

# `POST /account/language`, `GET /health`: a doc mandando CHAMAR uma rota. O metodo na
# frente e o que torna a citacao inequivoca -- sem ele, `/opt/gamepanel/gamepanel` e
# `/etc/gamebroker/broker.env` (caminho de disco) e `/v1/instancias` (rota do broker,
# citada como o nome ANTIGO numa frase historica) entrariam na conta e a lista de
# excecoes cresceria mais que a checagem.
CITED_ROUTE = re.compile(r"`(GET|POST|PUT|DELETE) (/[A-Za-z0-9/_.<>:-]*)`")


def _panel_rules() -> set[tuple[str, str]]:
    """(metodo, regra) de tudo que o painel serve, como o Flask registrou."""
    from gamepanel import app as panel

    found = set()
    for rule in panel.app.url_map.iter_rules():
        for method in rule.methods or ():
            found.add((method, str(rule.rule)))
    return found


def test_toda_rota_citada_com_metodo_ainda_existe():
    """Doc que manda chamar uma rota que nao existe mais custa uma sessao de depuracao.

    Foi o caso do `POST /account/idioma`: a rota virou `/account/language` na traducao
    dos identificadores, e a instrucao de "conferir uma tela nos dois idiomas" passou a
    devolver 404 calado -- quem a seguia concluia que o seletor de idioma tinha quebrado.
    A checagem de `modulo.nome` nao alcanca URL, e nenhuma outra olhava para ela.
    """
    rules = _panel_rules()
    text = DOC.read_text(encoding="utf-8")
    missing = []
    for method, path in CITED_ROUTE.findall(text):
        if (method, path) not in rules:
            same_path = sorted(m for m, p in rules if p == path)
            missing.append(f"{method} {path}"
                           + (f" (existe, mas so aceita {same_path})" if same_path
                              else " (nao existe rota nenhuma nesse caminho)"))
    assert not missing, "rota citada no CLAUDE.md que o painel nao serve:\n  " + "\n  ".join(missing)


def test_a_varredura_encontra_rotas_citadas():
    """Se o formato da citacao mudar, o teste acima passa a nao conferir nada."""
    found = CITED_ROUTE.findall(DOC.read_text(encoding="utf-8"))
    assert found, "nenhuma rota `METODO /caminho` encontrada no CLAUDE.md"
