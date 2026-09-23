/* Copiar para a area de transferencia.
 *
 * O alvo vem por selector em data-copy. No celular, marcar uma chave SSH de 80
 * caracteres com o dedo e um suplicio — este botao e o caminho normal, nao um luxo.
 */
export const copyToClipboard = {
  selector: '[data-copy]',
  mount(botao) {
    const target = document.querySelector(botao.dataset.copy);
    if (!target || !navigator.clipboard) return;
    botao.hidden = false;

    const label = botao.textContent;
    botao.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        botao.textContent = 'Copiado!';
      } catch {
        // Sem permissao (http sem TLS, por exemplo): o texto continua na tela para
        // ser selecionado a mao, entao isto e um aviso, nao um erro.
        botao.textContent = 'Nao consegui copyToClipboard';
      }
      setTimeout(() => { botao.textContent = label; }, 2000);
    });
  },
};
