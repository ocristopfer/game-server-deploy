/* Formulario de configuracao do jogo.
 *
 * Tres comportamentos independentes, montados so se o elemento correspondente
 * existir na tela. Nenhum deles e a unica forma de fazer a coisa: sem JavaScript o
 * formulario continua listando, salvando e aceitando duas chaves novas.
 */
import { $, $$ } from '../core/dom.js';
import { warnBeforeLeaving } from '../core/dirty.js';

/* Filtro por nome: com o Palworld sao ~50 chaves numa linha so do .ini. */
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

/* "+ outra linha": clona a ultima linha de chave nova e renumera os campos. */
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
      // O id do bloco e o "for" do rotulo tem de andar junto com o indice: clonados
      // como estao, a linha nova repetiria o id da anterior e o rotulo apontaria
      // para o campo errado.
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

/* Aviso de alteracao pendente, o mesmo do editor de texto. */
export const dirtyConfig = {
  selector: '[data-config-form]',
  mount(form) {
    const mark = $('#conf-changed', form);
    let dirty = false;
    const release = warnBeforeLeaving(() => dirty);

    form.addEventListener('input', () => {
      dirty = true;
      if (mark) mark.textContent = 'ha alteracoes nao salvas';
    });
    form.addEventListener('submit', release);
  },
};
