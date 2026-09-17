/* Confirmacao antes de uma acao sem volta.
 *
 * Antes, cada tela escrevia `onsubmit="return confirm('Apagar {{ nome }}?')"` no
 * proprio HTML. Isso tem dois problemas: o nome (que vem do container ou do jogo)
 * entrava DENTRO de codigo JavaScript — um apostrofo no nome do arquivo quebrava a
 * pagina — e nada disso sobrevive a uma politica de CSP sem `unsafe-inline`.
 *
 * Aqui a mensagem viaja em data-confirmar, que o navegador ja entrega decodificada
 * e que nunca e interpretada como codigo.
 */
export const confirmar = {
  seletor: '[data-confirmar]',
  montar(el) {
    // No formulario a confirmacao vale para o envio inteiro; no botao, so para
    // aquele botao — um formulario de alertas tem "Salvar", "Testar" e "Remover",
    // e so o ultimo pergunta. O clique e cancelavel e acontece antes do submit.
    const evento = el.tagName === 'FORM' ? 'submit' : 'click';

    el.addEventListener(evento, (ev) => {
      if (!window.confirm(el.dataset.confirmar)) {
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
      // Sair confirmado e uma saida deliberada: o editor de arquivos nao deve
      // perguntar "voce tem alteracoes nao salvas" por cima desta confirmacao.
      document.dispatchEvent(new CustomEvent('gp:saida-deliberada'));
    });
  },
};
