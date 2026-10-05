"""The panel's JavaScript parses, imports and MOUNTS.

Until now the front end had no safety net at all. A half-renamed `const`, an import pointing
to a file that changed name, a method that got a new name on one side only: none of that
shows up on the server. The page answers 200, the HTML arrives whole, and the error stays in
the console of whoever opened the screen - and `app.js` even swallows it on purpose, so one
broken feature does not take the others down with it.

Three real defects this file caught, all born from renaming:

- `Poller` started exposing `start()` and the features kept calling `.iniciar()`;
- `readJSON(url, opcoes)` kept reading `options.headers` - a replacement crossed the
  boundary of a quote and rewrote code;
- `shortList` used `rotulo` on one line and `label` on the next.

This does not test behavior: it tests that the module loads and that `mount` does not blow
up. It needs `node` on PATH; without it the tests are SKIPPED, because production has no
node and the panel does not depend on it for anything.
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

# Just enough browser for a module to REACH the end of the file and for a `mount` to run.
# It does not try to simulate the DOM: if a module needs more than this at module scope,
# it is doing work at import time instead of in `mount`, which is the contract.
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
    """Zero files is the silent way for this test to stop meaning anything."""
    assert len(_js_files()) > 15


@sem_node
@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_o_modulo_parseia(path: Path):
    done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr


@sem_node
def test_todo_modulo_importa_sem_referencia_solta(tmp_path):
    """A broken import raises no error on the server: the screen opens and the behavior vanishes."""
    urls = [p.resolve().as_uri() for p in _js_files()]
    script = STUBS + "const URLS = " + repr(urls).replace("'", '"') + ";\n" + IMPORT_BODY
    done = _run_node(tmp_path, "import-all.mjs", script)
    assert done.returncode == 0, done.stdout + done.stderr


@sem_node
def test_toda_feature_monta_sem_estourar(tmp_path):
    """A feature that blows up in `mount` leaves the screen alive and MUTE: `app.js` logs and moves on."""
    app_url = (JS_DIR / "app.js").resolve().as_uri()
    script = STUBS + 'const APP_URL = "' + app_url + '";\n' + MOUNT_BODY
    done = _run_node(tmp_path, "mount-all.mjs", script)
    assert done.returncode == 0, done.stdout + done.stderr
