/* Busca de jogo (nome ou App ID) no formulario "Adicionar jogo".
 *
 * Digitar consulta /api/catalogo/sugestoes (uma lista fixa, gerada do LinuxGSM e guardada no
 * repositorio: o painel nao vai a internet). Clicar num resultado preenche os campos. E so
 * sugestao — o broker valida tudo de novo no envio.
 *
 * Nasce escondido: sem JavaScript nao ha o que fazer, e o formulario continua completo.
 */
import { lerJSON } from '../core/http.js';
import { criar, repor, preencherFormulario } from '../core/dom.js';

const ESPERA_MS = 250;

export const buscaDeJogo = {
  seletor: '[data-busca-de-jogo]',
  montar(bloco) {
    const campo = bloco.querySelector('[data-busca-campo]');
    const lista = bloco.querySelector('[data-busca-resultados]');
    const formulario = bloco.closest('form');
    if (!campo || !lista || !formulario) return;
    bloco.hidden = false;

    let espera = null;
    let pedido = 0;

    const mostrar = (filhos) => repor(lista, filhos);

    const escolher = (achado) => {
      preencherFormulario(formulario, achado.valores);
      const aviso = criar('p', {
        classe: 'flash ok',
        texto: `${achado.nome}: campos preenchidos. Confira antes de enviar.`,
      });
      const observacoes = achado.avisos.map((texto) => criar('p', { classe: 'muted small', texto }));
      mostrar([aviso, ...observacoes]);
    };

    const buscar = async () => {
      const texto = campo.value.trim();
      if (!texto) { mostrar([]); return; }
      const este = ++pedido;
      try {
        const dados = await lerJSON(`${bloco.dataset.url}?q=${encodeURIComponent(texto)}`);
        if (este !== pedido) return; // chegou depois de uma consulta mais nova: descarta
        if (!dados.resultados.length) {
          mostrar([criar('p', {
            classe: 'muted small',
            texto: 'Nada no catalogo do LinuxGSM. Preencha a mao (o App ID esta no SteamDB).',
          })]);
          return;
        }
        mostrar(dados.resultados.map((achado) => {
          const botao = criar('button', {
            classe: 'btn btn--ghost btn--sm',
            texto: `${achado.nome} · app ${achado.appid}`,
            attrs: { type: 'button' },
          });
          botao.addEventListener('click', () => escolher(achado));
          return botao;
        }));
      } catch (erro) {
        if (este === pedido) {
          mostrar([criar('p', { classe: 'muted small', texto: `Nao consegui buscar: ${erro.message}` })]);
        }
      }
    };

    campo.addEventListener('input', () => {
      clearTimeout(espera);
      espera = setTimeout(buscar, ESPERA_MS);
    });
    // Enter dentro do campo enviaria o formulario inteiro (e criaria um jogo pela metade).
    campo.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      clearTimeout(espera);
      buscar();
    });
  },
};
