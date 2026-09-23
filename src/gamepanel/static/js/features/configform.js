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
    const itens = $$('.conf-item');
    const sections = $$('.conf-section');
    const empty = $('#conf-vazio');
    if (!itens.length) return;

    busca.addEventListener('input', () => {
      const termo = busca.value.trim().toLowerCase();
      itens.forEach((el) => {
        el.hidden = termo !== '' && !el.dataset.key.includes(termo);
      });
      let visiveis = 0;
      sections.forEach((sec) => {
        const tem = $$('.conf-item', sec).some((el) => !el.hidden);
        sec.hidden = !tem;
        if (tem) visiveis += 1;
      });
      if (empty) empty.hidden = visiveis > 0;
    });
  },
};

/* "+ outra linha": clona a ultima linha de chave nova e renumera os campos. */
export const moreConfigRows = {
  selector: '[data-config-more]',
  mount(button) {
    const novas = $('#conf-novas');
    const total = $('input[name="n"]');
    if (!novas || !total) return;
    button.hidden = false;

    button.addEventListener('click', () => {
      const modelo = novas.lastElementChild.cloneNode(true);
      const i = Number.parseInt(total.value, 10);
      modelo.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace(/\.\d+$/, `.${i}`);
        if (field.tagName !== 'SELECT') field.value = '';
      });
      // O id do bloco e o "for" do rotulo tem de andar junto com o indice: clonados
      // como estao, a linha nova repetiria o id da anterior e o rotulo apontaria
      // para o campo errado.
      const block = modelo.querySelector('select');
      const label = modelo.querySelector('label[for]');
      if (block) {
        block.id = `sec-${i}`;
        if (label) label.htmlFor = block.id;
      }
      novas.appendChild(modelo);
      total.value = String(i + 1);
    });
  },
};

/* Aviso de alteracao pendente, o mesmo do editor de texto. */
export const dirtyConfig = {
  selector: '[data-config-form]',
  mount(form) {
    const marca = $('#conf-mudou', form);
    let dirty = false;
    const release = warnBeforeLeaving(() => dirty);

    form.addEventListener('input', () => {
      dirty = true;
      if (marca) marca.textContent = 'ha alteracoes nao salvas';
    });
    form.addEventListener('submit', release);
  },
};
