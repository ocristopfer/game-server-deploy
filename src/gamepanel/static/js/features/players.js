/* Contagem de jogadores.
 *
 * Fica separada dos medidores por um motivo de custo: a contagem sai de uma consulta
 * direta ao jogo (rapida), os medidores saem de um SSH por container (lento). Junta-
 * las faria o selo de jogadores esperar o SSH mais devagar da lista.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $, createEl, reset } from '../core/dom.js';
import { duration } from '../core/format.js';

function pinta(selo, data) {
  const teto = data.max_players ? '/' + data.max_players : '';
  selo.textContent = data.players + teto;
  selo.className = `badge ${data.players ? 'on' : 'cold'}`;
}

/* Painel de servidores: um selo por cartao, todos de uma leitura so. */
export const panelPlayers = {
  selector: '[data-players-panel]',
  mount(root) {
    const url = root.dataset.playersPanel;
    const selos = Array.from(root.querySelectorAll('[data-players]'));
    if (!url || !selos.length) return;

    new Poller(async () => {
      const all = await readJSON(url);
      selos.forEach((selo) => {
        const data = all[selo.dataset.players];
        if (!data?.configured || data.error || data.players === null) return;
        pinta(selo, data);
        selo.textContent += ' jogadores';
        selo.hidden = false;
      });
    }, { interval: Number(root.dataset.interval) || 10000 }).start();
  },
};

/* Tela de um servidor: selo mais a tabela de quem esta online. */
export const serverPlayers = {
  selector: '[data-players-server]',
  mount(card) {
    const url = card.dataset.playersServer;
    const tabela = $('#jogadores-tabela', card);
    const selo = $('#jogadores-badge', card);
    if (!url || !tabela) return;

    const body = tabela.querySelector('tbody');
    const colunas = tabela.querySelectorAll('thead th').length;

    function semNinguem(quantos) {
      const tr = createEl('tr');
      tr.append(createEl('td', {
        className: 'muted',
        text: quantos
          ? 'Este jogo nao publica a lista de nomes - so a contagem.'
          : 'Ninguem conectado agora.',
        attrs: { colspan: String(colunas) },
      }));
      return [tr];
    }

    function line(p) {
      const tr = createEl('tr');
      // Nome vem do jogo: entra por textContent, nunca como marcacao.
      tr.append(
        createEl('td', { text: p.name }),
        createEl('td', { className: 'muted', text: duration(p.seconds) }),
        createEl('td', { className: 'muted', text: String(Number(p.score) || 0) }),
      );
      // A coluna de acoes (expulsar/banir) e desenhada pelo servidor com CSRF; ao
      // repintar, ela fica vazia ate a proxima carga da pagina.
      if (colunas > 3) tr.append(createEl('td'));
      return tr;
    }

    new Poller(async () => {
      const data = await readJSON(url);
      if (data.error) return;
      if (selo) {
        pinta(selo, data);
        selo.textContent += ' online';
      }
      reset(body, (data.list?.length)
        ? data.list.map(line)
        : semNinguem(data.players));
    }, { interval: Number(card.dataset.interval) || 10000 }).start({ immediate: false });
  },
};
