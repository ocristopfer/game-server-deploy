/* Caixa de comando unico.
 *
 * Ctrl+Enter envia (Enter sozinho quebra linha: comando multilinha e valido) e as
 * setas percorrem o que ja foi rodado neste servidor. O historico chega num bloco
 * <script type="application/json"> — expressao de template no meio do codigo quebra
 * qualquer ferramenta que leia o arquivo como JavaScript de verdade.
 */
import { $ } from '../core/dom.js';

export const commandBox = {
  selector: '[data-console]',
  mount(form) {
    const field = $('#command', form);
    if (!field) return;

    let historico = [];
    const fonte = document.getElementById('historico-comandos');
    if (fonte) {
      try { historico = JSON.parse(fonte.textContent) || []; } catch { historico = []; }
    }
    let cursor = -1;

    field.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        form.requestSubmit();
        return;
      }
      if (ev.key === 'ArrowUp' && field.selectionStart === 0 && cursor + 1 < historico.length) {
        ev.preventDefault();
        cursor += 1;
        field.value = historico[cursor];
      } else if (ev.key === 'ArrowDown' && cursor > -1) {
        ev.preventDefault();
        cursor -= 1;
        field.value = cursor === -1 ? '' : historico[cursor];
      }
    });
  },
};
