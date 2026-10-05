/* Text editor of the Files screen.
 *
 * Three behaviors: Tab indents instead of jumping to the next field, Ctrl+S saves, and leaving
 * with pending changes asks first.
 */
import { $ } from '../core/dom.js';
import { warnBeforeLeaving } from '../core/dirty.js';
import { fillText } from '../core/format.js';

export const fileEditor = {
  selector: '[data-editor]',
  mount(form) {
    const area = $('#content', form);
    const pos = $('#editor-pos', form);
    if (!area) return;

    const original = area.value;
    // Phrases from the template (data-label-*), already in the viewer's language. The
    // fallback carries no words: text written here would be Portuguese on the English screen.
    const position = form.dataset.labelPosition || '{line}:{column}';
    const changed = form.dataset.labelChanged || '';
    const release = warnBeforeLeaving(() => area.value !== original);

    area.addEventListener('keydown', (ev) => {
      if (ev.key === 'Tab') {
        ev.preventDefault();
        area.setRangeText('\t', area.selectionStart, area.selectionEnd, 'end');
      } else if (ev.key === 's' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        form.requestSubmit();
      }
    });

    function showPosition() {
      if (!pos) return;
      const upTo = area.value.slice(0, area.selectionStart);
      const line = upTo.split('\n').length;
      const column = upTo.length - upTo.lastIndexOf('\n');
      pos.textContent = fillText(position, { line, column }) +
        (area.value === original ? '' : changed);
    }
    ['keyup', 'click', 'input'].forEach((ev) => area.addEventListener(ev, showPosition));
    showPosition();

    form.addEventListener('submit', release);
  },
};
