/* Nucleo — atalhos de DOM.
 *
 * Nada de framework: sao quatro funcoes que tiram o ruido de querySelector das
 * features e centralizam o unico jeito seguro de mount uma celula de tabela com
 * texto que veio do container.
 */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* Cria um elemento. `texto` entra sempre por textContent — nunca por innerHTML —
 * porque quase todo texto que o painel mostra (nome de jogador, caminho de arquivo,
 * linha de log) veio de fora e nao pode virar marcacao. */
export function createEl(tag, { className = '', text = '', attrs = {} } = {}) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== '') el.textContent = text;
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/* Troca o conteudo de um elemento por uma lista de filhos, de uma vez so. */
export function reset(target, children) {
  target.replaceChildren(...children);
  return target;
}

/* Preenche campos de um formulario a partir de { nome: valor }. Caixa de marcar liga com
 * '1' e desliga com qualquer outra coisa; nome que o formulario nao tem e ignorado. */
export function fillForm(form, values) {
  Object.entries(values).forEach(([name, value]) => {
    const field = form.elements[name];
    if (!field) return;
    if (field.type === 'checkbox') field.checked = value === '1';
    else field.value = value;
  });
}
