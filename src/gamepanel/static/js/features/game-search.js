/* Busca de jogo (nome ou App ID) no formulario "Adicionar jogo".
 *
 * Digitar consulta /api/catalogo/sugestoes (uma lista fixa, gerada do LinuxGSM e guardada no
 * repositorio: o painel nao vai a internet). Clicar num resultado preenche os campos. E so
 * sugestao — o broker valida tudo de novo no envio.
 *
 * Nasce escondido: sem JavaScript nao ha o que fazer, e o formulario continua completo.
 */
import { readJSON } from '../core/http.js';
import { createEl, reset, fillForm } from '../core/dom.js';

const ESPERA_MS = 250;

export const gameSearch = {
  selector: '[data-game-search]',
  mount(block) {
    const field = block.querySelector('[data-search-field]');
    const list = block.querySelector('[data-search-results]');
    const form = block.closest('form');
    if (!field || !list || !form) return;
    block.hidden = false;

    let espera = null;
    let pedido = 0;

    const show = (children) => reset(list, children);

    const choose = (found) => {
      fillForm(form, found.values);
      const notice = createEl('p', {
        className: 'flash ok',
        text: `${found.name}: campos preenchidos. Confira antes de enviar.`,
      });
      const notes = found.avisos.map((text) => createEl('p', { className: 'muted small', text }));
      show([notice, ...notes]);
    };

    const search = async () => {
      const text = field.value.trim();
      if (!text) { show([]); return; }
      const este = ++pedido;
      try {
        const data = await readJSON(`${block.dataset.url}?q=${encodeURIComponent(text)}`);
        if (este !== pedido) return; // chegou depois de uma consulta mais nova: descarta
        if (!data.resultados.length) {
          show([createEl('p', {
            className: 'muted small',
            text: 'Nada no catalogo do LinuxGSM. Preencha a mao (o App ID esta no SteamDB).',
          })]);
          return;
        }
        show(data.resultados.map((found) => {
          const button = createEl('button', {
            className: 'btn btn--ghost btn--sm',
            text: `${found.name} · app ${found.appid}`,
            attrs: { type: 'button' },
          });
          button.addEventListener('click', () => choose(found));
          return button;
        }));
      } catch (failure) {
        if (este === pedido) {
          show([createEl('p', { className: 'muted small', text: `Nao consegui buscar: ${failure.message}` })]);
        }
      }
    };

    field.addEventListener('input', () => {
      clearTimeout(espera);
      espera = setTimeout(search, ESPERA_MS);
    });
    // Enter dentro do campo enviaria o formulario inteiro (e criaria um jogo pela metade).
    field.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      clearTimeout(espera);
      search();
    });
  },
};
