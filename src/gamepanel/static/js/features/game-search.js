/* Game search (name or App ID) in the "Add game" form.
 *
 * Three answers, in this order:
 * 1. the game is ALREADY in the catalog (curated or added before): there is nothing to fill in, and
 *    the shortcut is to create the instance. The list comes in the page itself (data-catalog), no request.
 *    That was the V Rising hole: it is curated, and the search said "nothing found".
 * 2. suggestions from the repository's lists (LinuxGSM, Pterodactyl eggs and the panel's
 *    curation), through the API.
 *    The panel does not go to the internet; clicking fills the fields, and the broker validates on submit.
 * 3. nothing: links for the BROWSER to look up the App ID (SteamDB) and the ports. Whoever opens them is the
 *    person, never the panel - still no SSRF and no third-party dependency.
 *
 * Screen text comes from the template (data-msg-*), which already went through i18n: written here it would
 * come out in Portuguese on the English screen.
 *
 * Born hidden: without JavaScript there is nothing to do, and the form stays complete.
 */
import { readJSON } from '../core/http.js';
import { createEl, reset, fillForm } from '../core/dom.js';

const DEBOUNCE_MS = 250;
const STEAMDB_SEARCH = 'https://steamdb.info/search/?a=app&q=';
const WEB_SEARCH = 'https://duckduckgo.com/?q=';

/* The same `_normalize` as the server-side search: no accents, lowercase, only letters and digits. */
const normalize = (text) => String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

const readCatalog = (raw) => {
  try { return JSON.parse(raw || '[]'); } catch { return []; }
};

export const gameSearch = {
  selector: '[data-game-search]',
  mount(block) {
    const field = block.querySelector('[data-search-field]');
    const list = block.querySelector('[data-search-results]');
    const form = block.closest('form');
    if (!field || !list || !form) return;
    block.hidden = false;

    const msg = block.dataset;
    const catalog = readCatalog(msg.catalog).map((game) => ({
      ...game, text: normalize(`${game.name} ${game.key}`),
    }));
    let waitId = null;
    let request = 0;

    const show = (children) => reset(list, children);
    const small = (text) => createEl('p', { className: 'muted small', text });
    const link = (text, href) => createEl('a', {
      className: 'btn btn--ghost btn--sm', text,
      attrs: { href, target: '_blank', rel: 'noopener noreferrer' },
    });

    const choose = (found) => {
      fillForm(form, found.values);
      const notice = createEl('p', { className: 'flash ok', text: `${found.name}: ${msg.msgFilled}` });
      // `warnings`, which is what the API sends. With the old name (`avisos`) the `.map` blew up
      // AFTER filling the fields: the screen ended up without the "double check" notice and without the
      // suggestion's warnings (assumed port, cut argument), and with no error in sight.
      show([notice, ...(found.warnings || []).map(small)]);
    };

    const inCatalog = (text) => {
      const terms = normalize(text).split(' ').filter(Boolean);
      if (!terms.length) return [];
      if (/^\d+$/.test(text)) return catalog.filter((g) => String(g.app_id) === text);
      return catalog.filter((g) => terms.every((t) => g.text.includes(t)));
    };

    const catalogRow = (game) => {
      const row = createEl('div', { className: 'cluster' });
      row.append(createEl('span', { text: `${game.name} · ${msg.msgInCatalog}` }));
      if (game.creatable) {
        row.append(createEl('a', {
          className: 'btn btn--primary btn--sm', text: msg.msgCreateInstance,
          attrs: { href: `${msg.instancesUrl}?game=${encodeURIComponent(game.key)}` },
        }));
      }
      return row;
    };

    const suggestionButton = (found) => {
      const button = createEl('button', {
        className: 'btn btn--ghost btn--sm',
        text: `${found.name} · app ${found.appid} · ${found.source}`,
        attrs: { type: 'button' },
      });
      button.addEventListener('click', () => choose(found));
      return button;
    };

    const nothingFound = (text) => {
      const links = createEl('div', { className: 'cluster' });
      links.append(
        link(msg.msgSteamdb, `${STEAMDB_SEARCH}${encodeURIComponent(`${text} dedicated server`)}`),
        link(msg.msgWebPorts, `${WEB_SEARCH}${encodeURIComponent(`${text} dedicated server ports`)}`),
      );
      return [small(msg.msgNone), links];
    };

    const search = async () => {
      const text = field.value.trim();
      if (!text) { show([]); return; }
      const self = ++request;
      const known = inCatalog(text).map(catalogRow);
      try {
        const data = await readJSON(`${block.dataset.url}?q=${encodeURIComponent(text)}`);
        if (self !== request) return; // arrived after a newer query: discard
        // What is already in the catalog does not show up again as a suggestion: adding it again
        // would create a second game with the same App ID, or override the curated one.
        const appids = new Set(catalog.map((g) => String(g.app_id)));
        const fresh = data.resultados.filter((found) => !appids.has(String(found.appid)));
        if (!known.length && !fresh.length) { show(nothingFound(text)); return; }
        show([...known, ...fresh.map(suggestionButton)]);
      } catch (failure) {
        if (self === request) show([...known, small(`${msg.msgFailed} ${failure.message}`)]);
      }
    };

    field.addEventListener('input', () => {
      clearTimeout(waitId);
      waitId = setTimeout(search, DEBOUNCE_MS);
    });
    // Enter inside the field would submit the whole form (and create a half-done game).
    field.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      clearTimeout(waitId);
      search();
    });
  },
};
