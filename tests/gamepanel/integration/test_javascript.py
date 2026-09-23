"""O JavaScript do painel parseia, importa e MONTA.

Ate aqui o front nao tinha rede nenhuma. Um `const` renomeado pela metade, um import
apontando para arquivo que mudou de nome, um metodo que virou outro nome so de um lado:
nada disso aparece no servidor. A pagina responde 200, o HTML chega inteiro, e o erro
fica no console de quem abriu a tela — e o `app.js` ainda o engole de proposito, para
uma feature quebrada nao levar as outras junto.

Tres defeitos reais que este arquivo pegou, todos nascidos de renomeacao:

- o `Poller` passou a expor `start()` e as features continuaram chamando `.iniciar()`;
- `readJSON(url, opcoes)` ficou lendo `options.headers` — uma troca atravessou a
  fronteira de uma aspa e reescreveu codigo;
- `shortList` usava `rotulo` numa linha e `label` na seguinte.

Isto nao testa comportamento: testa que o modulo carrega e que o `mount` nao estoura.
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

# O bastante do navegador para um modulo CHEGAR ao fim do arquivo e um `mount` rodar.
# Nao pretende simular o DOM: se um modulo precisar de mais que isto no escopo do
# modulo, ele esta fazendo trabalho no import em vez de no `mount`, que e o contrato.
STUBS = r"""
function makeEl(tag = 'div') {
  const node = {
    tagName: String(tag).toUpperCase(), dataset: {}, style: {}, hidden: false,
    value: '', textContent: '', innerHTML: '', checked: false, disabled: false,
    children: [], attributes: {}, files: [], options: [], selectedIndex: 0,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, dispatchEvent(){ return true; },
    appendChild(c){ this.children.push(c); return c; }, append(){}, prepend(){},
    remove(){}, replaceChildren(){}, insertAdjacentHTML(){},
    setAttribute(k, v){ this.attributes[k] = v; },
    getAttribute(k){ return this.attributes[k] ?? null; },
    removeAttribute(k){ delete this.attributes[k]; },
    hasAttribute(k){ return k in this.attributes; },
    closest(){ return null; }, focus(){}, blur(){}, submit(){}, click(){},
    scrollIntoView(){}, select(){},
    getBoundingClientRect(){ return { top: 0, left: 0, width: 100, height: 100 }; },
    querySelector(){ return makeEl(); }, querySelectorAll(){ return []; },
    cloneNode(){ return makeEl(tag); },
  };
  node.parentNode = null;
  return node;
}
globalThis.makeEl = makeEl;

globalThis.window = {
  addEventListener(){}, removeEventListener(){},
  matchMedia(){ return { matches: false, addEventListener(){} }; },
  location: { href: 'http://localhost/', pathname: '/' },
  // `display-mode: standalone` e como o painel sabe que ja foi instalado.
  navigator: { standalone: false },
  setTimeout, clearTimeout, setInterval, clearInterval,
};
globalThis.fetch = async () => ({
  ok: true, status: 200, json: async () => ({}), text: async () => '',
});
globalThis.document = {
  addEventListener(){}, removeEventListener(){},
  querySelectorAll(){ return []; }, querySelector(){ return null; },
  getElementById(){ return null; }, createElement(tag){ return makeEl(tag); },
  documentElement: { classList: { add(){}, remove(){} } },
  body: { dataset: {}, classList: { add(){}, remove(){} } },
  hidden: false, visibilityState: 'visible',
};
Object.defineProperty(globalThis, 'navigator', {
  value: {
    // `register` devolve um ServiceWorkerRegistration, nao um objeto vazio: o pwa.js
    // escuta `updatefound` nele.
    serviceWorker: {
      addEventListener(){}, controller: null,
      register(){ return Promise.resolve({ addEventListener(){}, installing: null, waiting: null }); },
    },
    clipboard: { writeText(){ return Promise.resolve(); } },
    standalone: false,
  },
  configurable: true,
});
"""

MOUNT_BODY = r"""
const mod = await import(APP_URL);
const features = mod.FEATURES;
if (!features || !features.length) {
  console.log('app.js nao exporta FEATURES');
  process.exit(1);
}
const bad = [];
for (const feature of features) {
  if (typeof feature?.mount !== 'function' || typeof feature?.selector !== 'string') {
    bad.push(JSON.stringify(feature) + ': nao segue o contrato {selector, mount}');
    continue;
  }
  try { feature.mount(makeEl()); }
  catch (e) { bad.push(feature.selector + ': ' + String(e.message).split('\n')[0]); }
}
// Uma volta do Poller roda em outro tick: sem esperar, um erro dentro dela escaparia.
await new Promise((resolve) => setTimeout(resolve, 80));
if (bad.length) { console.log(bad.join('\n')); process.exit(1); }
"""

IMPORT_BODY = r"""
const bad = [];
for (const url of URLS) {
  try { await import(url); }
  catch (e) { bad.push(url.split('/').pop() + ': ' + String(e.message).split('\n')[0]); }
}
if (bad.length) { console.log(bad.join('\n')); process.exit(1); }
"""


def _js_files() -> list[Path]:
    return sorted(JS_DIR.rglob("*.js"))


def _run_node(tmp_path: Path, name: str, script: str) -> subprocess.CompletedProcess:
    runner = tmp_path / name
    runner.write_text(script, encoding="utf-8")
    return subprocess.run([NODE, str(runner)], capture_output=True, text=True, check=False)


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
    script = STUBS + "const URLS = " + repr(urls).replace("'", '"') + ";\n" + IMPORT_BODY
    done = _run_node(tmp_path, "import-all.mjs", script)
    assert done.returncode == 0, done.stdout + done.stderr


@sem_node
def test_toda_feature_monta_sem_estourar(tmp_path):
    """Feature que estoura no `mount` deixa a tela viva e MUDA: o `app.js` loga e segue."""
    app_url = (JS_DIR / "app.js").resolve().as_uri()
    script = STUBS + 'const APP_URL = "' + app_url + '";\n' + MOUNT_BODY
    done = _run_node(tmp_path, "mount-all.mjs", script)
    assert done.returncode == 0, done.stdout + done.stderr
