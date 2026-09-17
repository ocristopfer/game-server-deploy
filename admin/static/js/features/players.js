/* Contagem de jogadores.
 *
 * Fica separada dos medidores por um motivo de custo: a contagem sai de uma consulta
 * direta ao jogo (rapida), os medidores saem de um SSH por container (lento). Junta-
 * las faria o selo de jogadores esperar o SSH mais devagar da lista.
 */
import { Poller } from '../core/poll.js';
import { lerJSON } from '../core/http.js';
import { $, criar, repor } from '../core/dom.js';
import { duracao } from '../core/format.js';

function pinta(selo, data) {
  const teto = data.max_players ? '/' + data.max_players : '';
  selo.textContent = data.players + teto;
  selo.className = `badge ${data.players ? 'on' : 'cold'}`;
}

/* Painel de servidores: um selo por cartao, todos de uma leitura so. */
export const jogadoresDoPainel = {
  seletor: '[data-jogadores-painel]',
  montar(raiz) {
    const url = raiz.dataset.jogadoresPainel;
    const selos = Array.from(raiz.querySelectorAll('[data-players]'));
    if (!url || !selos.length) return;

    new Poller(async () => {
      const tudo = await lerJSON(url);
      selos.forEach((selo) => {
        const data = tudo[selo.dataset.players];
        if (!data?.configured || data.error || data.players === null) return;
        pinta(selo, data);
        selo.textContent += ' jogadores';
        selo.hidden = false;
      });
    }, { intervalo: Number(raiz.dataset.intervalo) || 10000 }).iniciar();
  },
};

/* Tela de um servidor: selo mais a tabela de quem esta online. */
export const jogadoresDoServidor = {
  seletor: '[data-jogadores-servidor]',
  montar(cartao) {
    const url = cartao.dataset.jogadoresServidor;
    const tabela = $('#jogadores-tabela', cartao);
    const selo = $('#jogadores-badge', cartao);
    if (!url || !tabela) return;

    const corpo = tabela.querySelector('tbody');
    const colunas = tabela.querySelectorAll('thead th').length;

    function semNinguem(quantos) {
      const tr = criar('tr');
      tr.append(criar('td', {
        classe: 'muted',
        texto: quantos
          ? 'Este jogo nao publica a lista de nomes - so a contagem.'
          : 'Ninguem conectado agora.',
        attrs: { colspan: String(colunas) },
      }));
      return [tr];
    }

    function linha(p) {
      const tr = criar('tr');
      // Nome vem do jogo: entra por textContent, nunca como marcacao.
      tr.append(
        criar('td', { texto: p.name }),
        criar('td', { classe: 'muted', texto: duracao(p.seconds) }),
        criar('td', { classe: 'muted', texto: String(Number(p.score) || 0) }),
      );
      // A coluna de acoes (expulsar/banir) e desenhada pelo servidor com CSRF; ao
      // repintar, ela fica vazia ate a proxima carga da pagina.
      if (colunas > 3) tr.append(criar('td'));
      return tr;
    }

    new Poller(async () => {
      const data = await lerJSON(url);
      if (data.error) return;
      if (selo) {
        pinta(selo, data);
        selo.textContent += ' online';
      }
      repor(corpo, (data.list?.length)
        ? data.list.map(linha)
        : semNinguem(data.players));
    }, { intervalo: Number(cartao.dataset.intervalo) || 10000 }).iniciar({ imediato: false });
  },
};
