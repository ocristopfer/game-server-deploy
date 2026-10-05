/* "Start from a template" in the new game form.
 *
 * Picking a template fills the fields at once (the values come in the markup itself,
 * in data-values, built on the server from modelos_de_jogo.py). Nothing here decides
 * what is valid: the broker validates everything again when the form is submitted.
 *
 * The selector is born hidden: without JavaScript it would have nothing to do, and the form
 * stays complete without it.
 */
import { fillForm } from '../core/dom.js';

export const gameTemplate = {
  selector: 'select[data-game-template]',
  mount(select) {
    const form = select.form;
    if (!form) return;
    const hint = form.querySelector('[data-template-description]');
    const label = select.closest('label');
    if (label) label.hidden = false;

    select.addEventListener('change', () => {
      const option = select.selectedOptions[0];
      fillForm(form, JSON.parse(option.dataset.values || '{}'));
      if (hint) hint.textContent = option.dataset.description || '';
    });
  },
};
