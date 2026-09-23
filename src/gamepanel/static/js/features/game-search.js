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
  mount(bloco) {
    const field = bloco.querySelector('[data-search-field]');
    const list = bloco.querySelector('[data-search-results]');
    const form = bloco.closest('form');
    if (!field || !list || !form) return;
    bloco.hidden = false;

    let espera = null;
    let pedido = 0;

    const show = (filhos) => reset(list, filhos);

    const escolher = (achado) => {
      fillForm(form, achado.valores);
      const notice = createEl('p', {
        classe: 'flash ok',
        text: `${achado.nome}: campos preenchidos. Confira antes de enviar.`,
      });
      const observacoes = achado.avisos.map((text) => createEl('p', { classe: 'muted small', text }));
      show([notice, ...observacoes]);
    };

    const buscar = async () => {
      const text = field.value.trim();
      if (!text) { show([]); return; }
      const este = ++pedido;
      try {
        const data = await readJSON(`${bloco.dataset.url}?q=${encodeURIComponent(texto)}`);
        if (este !== pedido) return; // chegou depois de uma consulta mais nova: descarta
        if (!data.resultados.length) {
          show([createEl('p', {
            classe: 'muted small',
            text: 'Nada no catalogo do LinuxGSM. Preencha a mao (o App ID esta no SteamDB).',
          })]);
          return;
        }
        show(data.resultados.map((achado) => {
          const botao = createEl('button', {
            classe: 'btn btn--ghost btn--sm',
            text: `${achado.nome} · app ${achado.appid}`,
            attrs: { type: 'button' },
          });
          botao.addEventListener('click', () => escolher(achado));
          return botao;
        }));
      } catch (failure) {
        if (este === pedido) {
          show([createEl('p', { classe: 'muted small', text: `Nao consegui buscar: ${erro.message}` })]);
        }
      }
    };

    field.addEventListener('input', () => {
      clearTimeout(espera);
      espera = setTimeout(buscar, ESPERA_MS);
    });
    // Enter dentro do campo enviaria o formulario inteiro (e criaria um jogo pela metade).
    field.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      clearTimeout(espera);
      buscar();
    });
  },
};
