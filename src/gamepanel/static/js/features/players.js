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

function paint(badge, data) {
  const ceiling = data.max_players ? '/' + data.max_players : '';
  badge.textContent = data.players + ceiling;
  badge.className = `badge ${data.players ? 'on' : 'cold'}`;
}

/* Painel de servidores: um selo por cartao, todos de uma leitura so. */
export const panelPlayers = {
  selector: '[data-players-panel]',
  mount(root) {
    const url = root.dataset.playersPanel;
    const badges = Array.from(root.querySelectorAll('[data-players]'));
    if (!url || !badges.length) return;

    new Poller(async () => {
      const all = await readJSON(url);
      badges.forEach((badge) => {
        const data = all[badge.dataset.players];
        if (!data?.configured || data.error || data.players === null) return;
        paint(badge, data);
        badge.textContent += ' jogadores';
        badge.hidden = false;
      });
    }, { interval: Number(root.dataset.interval) || 10000 }).start();
  },
};

/* Tela de um servidor: selo mais a tabela de quem esta online. */
export const serverPlayers = {
  selector: '[data-players-server]',
  mount(card) {
    const url = card.dataset.playersServer;
    const table = $('#players-table', card);
    const badge = $('#players-badge', card);
    if (!url || !table) return;

    const body = table.querySelector('tbody');
    const columnCount = table.querySelectorAll('thead th').length;

    function nobodyText(quantos) {
      const tr = createEl('tr');
      tr.append(createEl('td', {
        className: 'muted',
        text: quantos
          ? 'Este jogo nao publica a lista de nomes - so a contagem.'
          : 'Ninguem conectado agora.',
        attrs: { colspan: String(columnCount) },
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
      if (columnCount > 3) tr.append(createEl('td'));
      return tr;
    }

    new Poller(async () => {
      const data = await readJSON(url);
      if (data.error) return;
      if (badge) {
        paint(badge, data);
        badge.textContent += ' online';
      }
      reset(body, (data.list?.length)
        ? data.list.map(line)
        : nobodyText(data.players));
    }, { interval: Number(card.dataset.interval) || 10000 }).start({ immediate: false });
  },
};
