/* Copiar para a area de transferencia.
 *
 * O alvo vem por seletor em data-copiar. No celular, marcar uma chave SSH de 80
 * caracteres com o dedo e um suplicio — este botao e o caminho normal, nao um luxo.
 */
export const copiar = {
  seletor: '[data-copiar]',
  montar(botao) {
    const alvo = document.querySelector(botao.dataset.copiar);
    if (!alvo || !navigator.clipboard) return;
    botao.hidden = false;

    const rotulo = botao.textContent;
    botao.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(alvo.textContent.trim());
        botao.textContent = 'Copiado!';
      } catch {
        // Sem permissao (http sem TLS, por exemplo): o texto continua na tela para
        // ser selecionado a mao, entao isto e um aviso, nao um erro.
        botao.textContent = 'Nao consegui copiar';
      }
      setTimeout(() => { botao.textContent = rotulo; }, 2000);
    });
  },
};
