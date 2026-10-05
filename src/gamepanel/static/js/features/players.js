/* Player count.
 *
 * It stays apart from the gauges for a cost reason: the count comes from a direct
 * query to the game (fast), the gauges come from one SSH per container (slow). Joining
 * them would make the player badge wait for the slowest SSH in the list.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $, createEl, reset } from '../core/dom.js';
import { duration, fillText } from '../core/format.js';

function paint(badge, data) {
  const ceiling = data.max_players ? '/' + data.max_players : '';
  badge.textContent = data.players + ceiling;
  badge.className = `badge ${data.players ? 'on' : 'cold'}`;
}

/* Server dashboard: one badge per card, all from a single reading. */
export const panelPlayers = {
  selector: '[data-players-panel]',
  mount(root) {
    const url = root.dataset.playersPanel;
    const badges = Array.from(root.querySelectorAll('[data-players]'));
    if (!url || !badges.length) return;
    // The phrase comes translated from the template, with `{count}` still in it.
    // Phrases from the template, already in the viewer's language; without one, the bare number.
    const phrase = root.dataset.labelPlayers || '{count}';

    new Poller(async () => {
      const all = await readJSON(url);
      badges.forEach((badge) => {
        const data = all[badge.dataset.players];
        if (!data?.configured || data.error || data.players === null) return;
        paint(badge, data);
        badge.textContent = fillText(phrase, { count: badge.textContent });
        badge.hidden = false;
      });
    }, { interval: Number(root.dataset.interval) || 10000 }).start();
  },
};

/* A server's screen: badge plus the table of who is online. */
export const serverPlayers = {
  selector: '[data-players-server]',
  mount(card) {
    const url = card.dataset.playersServer;
    const table = $('#players-table', card);
    const badge = $('#players-badge', card);
    if (!url || !table) return;

    const body = table.querySelector('tbody');
    const columnCount = table.querySelectorAll('thead th').length;
    // Phrases from the template, already in the viewer's language: one written here would be
    // Portuguese on the English screen.
    const online = card.dataset.labelOnline || '{count}';
    const unpublished = card.dataset.labelNamesUnpublished || '';
    const nobody = card.dataset.labelNobody || '';

    function nobodyText(quantos) {
      const tr = createEl('tr');
      tr.append(createEl('td', {
        className: 'muted',
        text: quantos ? unpublished : nobody,
        attrs: { colspan: String(columnCount) },
      }));
      return [tr];
    }

    function line(p) {
      const tr = createEl('tr');
      // The name comes from the game: it goes in through textContent, never as markup.
      tr.append(
        createEl('td', { text: p.name }),
        createEl('td', { className: 'muted', text: duration(p.seconds) }),
        createEl('td', { className: 'muted', text: String(Number(p.score) || 0) }),
      );
      // The actions column (kick/ban) is drawn by the server with CSRF; on
      // repaint, it stays empty until the next page load.
      if (columnCount > 3) tr.append(createEl('td'));
      return tr;
    }

    new Poller(async () => {
      const data = await readJSON(url);
      if (data.error) return;
      if (badge) {
        paint(badge, data);
        badge.textContent = fillText(online, { count: badge.textContent });
      }
      reset(body, (data.list?.length)
        ? data.list.map(line)
        : nobodyText(data.players));
    }, { interval: Number(card.dataset.interval) || 10000 }).start({ immediate: false });
  },
};
