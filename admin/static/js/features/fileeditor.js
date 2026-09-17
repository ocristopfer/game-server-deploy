/* Editor de texto da tela de Arquivos.
 *
 * Tres comportamentos: Tab indenta em vez de pular de campo, Ctrl+S salva, e sair
 * com alteracoes pendentes pergunta antes.
 */
import { $ } from '../core/dom.js';
import { avisarAoSair } from '../core/dirty.js';

export const editorDeArquivo = {
  seletor: '[data-editor]',
  montar(form) {
    const area = $('#content', form);
    const pos = $('#editor-pos', form);
    if (!area) return;

    const original = area.value;
    const liberar = avisarAoSair(() => area.value !== original);

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
      const ate = area.value.slice(0, area.selectionStart);
      const linha = ate.split('\n').length;
      const coluna = ate.length - ate.lastIndexOf('\n');
      pos.textContent = `linha ${linha}, coluna ${coluna}` +
        (area.value === original ? '' : ' - alterado');
    }
    ['keyup', 'click', 'input'].forEach((ev) => area.addEventListener(ev, mostrarPosicao));
    mostrarPosicao();

    form.addEventListener('submit', liberar);
  },
};
