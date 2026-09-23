/* Editor de texto da tela de Arquivos.
 *
 * Tres comportamentos: Tab indenta em vez de pular de campo, Ctrl+S salva, e sair
 * com alteracoes pendentes pergunta antes.
 */
import { $ } from '../core/dom.js';
import { warnBeforeLeaving } from '../core/dirty.js';

export const fileEditor = {
  selector: '[data-editor]',
  mount(form) {
    const area = $('#content', form);
    const pos = $('#editor-pos', form);
    if (!area) return;

    const original = area.value;
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

    function mostrarPosicao() {
      if (!pos) return;
      const upTo = area.value.slice(0, area.selectionStart);
      const line = upTo.split('\n').length;
      const column = upTo.length - upTo.lastIndexOf('\n');
      pos.textContent = `linha ${line}, coluna ${column}` +
        (area.value === original ? '' : ' - alterado');
    }
    ['keyup', 'click', 'input'].forEach((ev) => area.addEventListener(ev, mostrarPosicao));
    mostrarPosicao();

    form.addEventListener('submit', release);
  },
};
