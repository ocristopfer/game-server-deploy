/* Menu suspenso.
 *
 * O elemento e um <details>: ele abre, fecha e navega pelo teclado sem uma linha de
 * JavaScript. O que falta para parecer um menu de aplicativo e so isto — fechar ao
 * clicar fora, fechar no Esc e nunca deixar dois abertos ao mesmo tempo.
 */
import { $$ } from '../core/dom.js';

function closeOthers(menu) {
  $$('details.menu[open]').forEach((outro) => {
    if (outro !== menu) outro.open = false;
  });
}

let boundToDocument = false;

function bindDocumentOnce() {
  if (boundToDocument) return;
  boundToDocument = true;

  document.addEventListener('click', (ev) => {
    $$('details.menu[open]').forEach((menu) => {
      if (!menu.contains(ev.target)) menu.open = false;
    });
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape') return;
    const openState = document.querySelector('details.menu[open]');
    if (!openState) return;
    openState.open = false;
    openState.querySelector('summary')?.focus();
  });
}

export const dropdownMenu = {
  selector: 'details.menu',
  mount(menu) {
    bindDocumentOnce();
    menu.addEventListener('toggle', () => { if (menu.open) closeOthers(menu); });
  },
};
