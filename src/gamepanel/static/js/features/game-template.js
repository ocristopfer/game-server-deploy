/* "Comecar de um modelo" no formulario de jogo novo.
 *
 * Escolher um modelo preenche os campos de uma vez (os valores vem na propria marcacao,
 * em data-values, montados no servidor a partir de modelos_de_jogo.py). Nada aqui decide
 * o que e valido: o broker valida tudo de novo quando o formulario e enviado.
 *
 * O selector nasce escondido: sem JavaScript ele nao teria o que fazer, e o formulario
 * continua completo sem ele.
 */
import { fillForm } from '../core/dom.js';

export const gameTemplate = {
  selector: 'select[data-game-template]',
  mount(select) {
    const form = select.form;
    if (!form) return;
    const dica = form.querySelector('[data-template-description]');
    const label = select.closest('label');
    if (label) label.hidden = false;

    select.addEventListener('change', () => {
      const opcao = select.selectedOptions[0];
      fillForm(form, JSON.parse(opcao.dataset.values || '{}'));
      if (dica) dica.textContent = opcao.dataset.description || '';
    });
  },
};
