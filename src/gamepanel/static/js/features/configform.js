/* Game configuration form.
 *
 * Three independent behaviors, mounted only if the matching element
 * exists on the screen. None of them is the only way to do the thing: without JavaScript the
 * form still lists, saves and accepts two new keys.
 */
import { $, $$ } from '../core/dom.js';
import { warnBeforeLeaving } from '../core/dirty.js';

/* Filter by name: with Palworld there are ~50 keys on a single .ini line. */
export const configFilter = {
  selector: '[data-config-filter]',
  mount(busca) {
    const items = $$('.conf-item');
    const sections = $$('.conf-section');
    const empty = $('#conf-empty');
    if (!items.length) return;

    busca.addEventListener('input', () => {
      const term = busca.value.trim().toLowerCase();
      items.forEach((el) => {
        el.hidden = term !== '' && !el.dataset.key.includes(term);
      });
      let visible = 0;
      sections.forEach((sec) => {
        const has = $$('.conf-item', sec).some((el) => !el.hidden);
        sec.hidden = !has;
        if (has) visible += 1;
      });
      if (empty) empty.hidden = visible > 0;
    });
  },
};

/* "+ another row": clones the last new-key row and renumbers the fields. */
export const moreConfigRows = {
  selector: '[data-config-more]',
  mount(button) {
    const extraRows = $('#conf-new-rows');
    const total = $('input[name="n"]');
    if (!extraRows || !total) return;
    button.hidden = false;

    button.addEventListener('click', () => {
      const clone = extraRows.lastElementChild.cloneNode(true);
      const i = Number.parseInt(total.value, 10);
      clone.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace(/\.\d+$/, `.${i}`);
        if (field.tagName !== 'SELECT') field.value = '';
      });
      // The block id and the label's "for" must follow the index: cloned
      // as they are, the new row would repeat the previous row's id and the label would point
      // to the wrong field.
      const block = clone.querySelector('select');
      const label = clone.querySelector('label[for]');
      if (block) {
        block.id = `sec-${i}`;
        if (label) label.htmlFor = block.id;
      }
      extraRows.appendChild(clone);
      total.value = String(i + 1);
    });
  },
};

/* Pending changes warning, the same as the text editor's. */
export const dirtyConfig = {
  selector: '[data-config-form]',
  mount(form) {
    const mark = $('#conf-changed', form);
    let dirty = false;
    const release = warnBeforeLeaving(() => dirty);

    form.addEventListener('input', () => {
      dirty = true;
      if (mark) mark.textContent = form.dataset.labelUnsaved || 'ha alteracoes nao salvas';
    });
    form.addEventListener('submit', release);
  },
};
