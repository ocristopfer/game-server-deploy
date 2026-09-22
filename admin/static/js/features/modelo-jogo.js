/* "Comecar de um modelo" no formulario de jogo novo.
 *
 * Escolher um modelo preenche os campos de uma vez (os valores vem na propria marcacao,
 * em data-valores, montados no servidor a partir de modelos_de_jogo.py). Nada aqui decide
 * o que e valido: o broker valida tudo de novo quando o formulario e enviado.
 *
 * O seletor nasce escondido: sem JavaScript ele nao teria o que fazer, e o formulario
 * continua completo sem ele.
 */
import { preencherFormulario } from '../core/dom.js';

export const modeloDeJogo = {
  seletor: 'select[data-modelo-jogo]',
  montar(select) {
    const formulario = select.form;
    if (!formulario) return;
    const dica = formulario.querySelector('[data-modelo-descricao]');
    const rotulo = select.closest('label');
    if (rotulo) rotulo.hidden = false;

    select.addEventListener('change', () => {
      const opcao = select.selectedOptions[0];
      preencherFormulario(formulario, JSON.parse(opcao.dataset.valores || '{}'));
      if (dica) dica.textContent = opcao.dataset.descricao || '';
    });
  },
};
