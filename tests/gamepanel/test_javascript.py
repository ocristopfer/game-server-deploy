"""O JavaScript do painel ao menos PARSEIA e IMPORTA.

Ate aqui o front nao tinha rede nenhuma: um `const` renomeado pela metade, um import
apontando para arquivo que mudou de nome ou um erro de sintaxe so apareciam no console
do navegador de quem abrisse a tela — a pagina continua respondendo 200, o HTML chega
inteiro e nada no servidor reclama.

Isto nao testa comportamento: testa que o modulo carrega. E o degrau que faltava, e
pega justamente a classe de defeito que uma renomeacao em massa produz.

Precisa do `node` no PATH; sem ele os testes sao PULADOS, porque producao nao tem node
e o painel nao depende dele para nada.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gamepanel import app as panel

JS_DIR = Path(panel.__file__).parent / "static" / "js"
NODE = shutil.which("node")
sem_node = pytest.mark.skipif(NODE is None, reason="node nao esta no PATH")

# O bastante do navegador para um modulo CHEGAR ao fim do arquivo. Nao pretende simular
# o DOM: se um modulo precisar de mais que isto no escopo do modulo, ele esta fazendo
# trabalho no import em vez de no `mount`, que e o contrato das features.
STUBS = """
globalThis.window = {
  addEventListener(){}, matchMedia(){ return { matches: false, addEventListener(){} }; },
  location: {}, navigator: {},
};
globalThis.document = {
  addEventListener(){}, querySelectorAll(){ return []; }, querySelector(){ return null; },
  getElementById(){ return null; },
  documentElement: { classList: { add(){}, remove(){} } }, body: { dataset: {} },
};
Object.defineProperty(globalThis, 'navigator', {
  value: { serviceWorker: { addEventListener(){}, register(){ return Promise.resolve({}); } } },
  configurable: true,
});
"""


def _js_files() -> list[Path]:
    return sorted(JS_DIR.rglob("*.js"))


def test_a_varredura_encontra_os_modulos():
    """Zero arquivos e o jeito silencioso de este teste parar de valer."""
    assert len(_js_files()) > 15


@sem_node
@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_o_modulo_parseia(path: Path):
    done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr


@sem_node
def test_todo_modulo_importa_sem_referencia_solta(tmp_path):
    """Import quebrado nao da erro no servidor: a tela abre e o comportamento some."""
    urls = [p.resolve().as_uri() for p in _js_files()]
    runner = tmp_path / "import-all.mjs"
    runner.write_text(
        STUBS
        + "const urls = " + repr(urls).replace("'", '"') + ";\n"
        + """
let bad = [];
for (const url of urls) {
  try { await import(url); }
  catch (e) { bad.push(url.split('/').pop() + ': ' + e.message.split('\\n')[0]); }
}
if (bad.length) { console.log(bad.join('\\n')); process.exit(1); }
""",
        encoding="utf-8",
    )
    done = subprocess.run([NODE, str(runner)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
