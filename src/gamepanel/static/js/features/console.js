/* Single-command box.
 *
 * Ctrl+Enter sends (Enter alone breaks the line: a multiline command is valid) and the
 * arrows walk through what was already run on this server. The history arrives in a
 * <script type="application/json"> block - a template expression in the middle of code breaks
 * any tool that reads the file as real JavaScript.
 */
import { $ } from '../core/dom.js';

export const commandBox = {
  selector: '[data-console]',
  mount(form) {
    const field = $('#command', form);
    if (!field) return;

    let history = [];
    const source = document.getElementById('historico-comandos');
    if (source) {
      try { history = JSON.parse(source.textContent) || []; } catch { history = []; }
    }
    let cursor = -1;

    field.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        form.requestSubmit();
        return;
      }
      if (ev.key === 'ArrowUp' && field.selectionStart === 0 && cursor + 1 < history.length) {
        ev.preventDefault();
        cursor += 1;
        field.value = history[cursor];
      } else if (ev.key === 'ArrowDown' && cursor > -1) {
        ev.preventDefault();
        cursor -= 1;
        field.value = cursor === -1 ? '' : history[cursor];
      }
    });
  },
};
