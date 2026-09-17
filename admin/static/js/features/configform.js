/* Formulario de configuracao do jogo.
 *
 * Tres comportamentos independentes, montados so se o elemento correspondente
 * existir na tela. Nenhum deles e a unica forma de fazer a coisa: sem JavaScript o
 * formulario continua listando, salvando e aceitando duas chaves novas.
 */
import { $, $$ } from '../core/dom.js';
import { avisarAoSair } from '../core/dirty.js';

/* Filtro por nome: com o Palworld sao ~50 chaves numa linha so do .ini. */
export const filtroDeConfig = {
  seletor: '[data-filtro-config]',
  montar(busca) {
    const itens = $$('.conf-item');
    const secoes = $$('.conf-sec');
    const vazio = $('#conf-vazio');
    if (!itens.length) return;

    busca.addEventListener('input', () => {
      const termo = busca.value.trim().toLowerCase();
      itens.forEach((el) => {
        el.hidden = termo !== '' && !el.dataset.key.includes(termo);
      });
      let visiveis = 0;
      secoes.forEach((sec) => {
        const tem = $$('.conf-item', sec).some((el) => !el.hidden);
        sec.hidden = !tem;
        if (tem) visiveis += 1;
      });
      if (vazio) vazio.hidden = visiveis > 0;
    });
  },
};

/* "+ outra linha": clona a ultima linha de chave nova e renumera os campos. */
export const maisLinhasDeConfig = {
  seletor: '[data-config-mais]',
  montar(botao) {
    const novas = $('#conf-novas');
    const total = $('input[name="n"]');
    if (!novas || !total) return;
    botao.hidden = false;

    botao.addEventListener('click', () => {
      const modelo = novas.lastElementChild.cloneNode(true);
      const i = Number.parseInt(total.value, 10);
      modelo.querySelectorAll('[name]').forEach((campo) => {
        campo.name = campo.name.replace(/\.\d+$/, `.${i}`);
        if (campo.tagName !== 'SELECT') campo.value = '';
      });
      // O id do bloco e o "for" do rotulo tem de andar junto com o indice: clonados
      // como estao, a linha nova repetiria o id da anterior e o rotulo apontaria
      // para o campo errado.
      const bloco = modelo.querySelector('select');
      const rotulo = modelo.querySelector('label[for]');
      if (bloco) {
        bloco.id = `sec-${i}`;
        if (rotulo) rotulo.htmlFor = bloco.id;
      }
      novas.appendChild(modelo);
      total.value = String(i + 1);
    });
  },
};

/* Aviso de alteracao pendente, o mesmo do editor de texto. */
export const configSuja = {
  seletor: '[data-config-form]',
  montar(form) {
    const marca = $('#conf-mudou', form);
    let sujo = false;
    const liberar = avisarAoSair(() => sujo);

    form.addEventListener('input', () => {
      sujo = true;
      if (marca) marca.textContent = 'ha alteracoes nao salvas';
    });
    form.addEventListener('submit', liberar);
  },
};
