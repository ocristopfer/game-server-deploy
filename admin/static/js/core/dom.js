/* Nucleo — atalhos de DOM.
 *
 * Nada de framework: sao quatro funcoes que tiram o ruido de querySelector das
 * features e centralizam o unico jeito seguro de montar uma celula de tabela com
 * texto que veio do container.
 */

export const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
export const $$ = (seletor, raiz = document) => Array.from(raiz.querySelectorAll(seletor));

/* Cria um elemento. `texto` entra sempre por textContent — nunca por innerHTML —
 * porque quase todo texto que o painel mostra (nome de jogador, caminho de arquivo,
 * linha de log) veio de fora e nao pode virar marcacao. */
export function criar(tag, { classe = '', texto = '', attrs = {} } = {}) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (texto !== '') el.textContent = texto;
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/* Troca o conteudo de um elemento por uma lista de filhos, de uma vez so. */
export function repor(alvo, filhos) {
  alvo.replaceChildren(...filhos);
  return alvo;
}
