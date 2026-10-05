/* Dropdown menu.
 *
 * The element is a <details>: it opens, closes and navigates by keyboard without a line of
 * JavaScript. What is missing to feel like an app menu is just this - closing on an
 * outside click, closing on Esc and never leaving two open at the same time.
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
