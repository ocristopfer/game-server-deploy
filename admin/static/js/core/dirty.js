/* Nucleo — "voce tem alteracoes nao salvas".
 *
 * O editor de texto e o formulario de configuracao precisavam do mesmo aviso, e cada
 * um tinha a sua copia, com uma bandeira global (window.gpSaving) compartilhada no
 * grito. Aqui a bandeira e local e o unico jeito de baixa-la esta na interface que
 * esta funcao devolve.
 */
export function avisarAoSair(estaSujo) {
  let liberado = false;

  window.addEventListener('beforeunload', (ev) => {
    if (!liberado && estaSujo()) ev.preventDefault();
  });

  // Apagar o arquivo aberto, ou qualquer acao que ja perguntou "tem certeza?", e uma
  // saida deliberada: nao cabe um segundo aviso por cima (ver features/confirm.js).
  document.addEventListener('gp:saida-deliberada', () => { liberado = true; });

  return () => { liberado = true; };
}
