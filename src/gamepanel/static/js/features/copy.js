/* Copiar para a area de transferencia.
 *
 * O alvo vem por selector em data-copy. No celular, marcar uma chave SSH de 80
 * caracteres com o dedo e um suplicio — este botao e o caminho normal, nao um luxo.
 */
export const copyToClipboard = {
  selector: '[data-copy]',
  mount(button) {
    const target = document.querySelector(button.dataset.copy);
    if (!target || !navigator.clipboard) return;
    button.hidden = false;

    const label = button.textContent;
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        button.textContent = 'Copiado!';
      } catch {
        // Sem permissao (http sem TLS, por exemplo): o texto continua na tela para
        // ser selecionado a mao, entao isto e um aviso, nao um erro.
        button.textContent = 'Nao consegui copyToClipboard';
      }
      setTimeout(() => { button.textContent = label; }, 2000);
    });
  },
};
