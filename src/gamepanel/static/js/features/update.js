/* An updater status card that refreshes itself.
 *
 * The check/install buttons used to be plain forms, and the person reloaded the page until the
 * root updater had answered. Here the card posts in the background, then asks its status route
 * every couple of seconds until the answer changes (the stamp), and swaps only the card body.
 *
 * The body comes from the panel already rendered, by the same Jinja partial the page includes
 * (escaped there, like any page): nothing from GitHub or the installer log is assembled here.
 */
import { Poller } from '../core/poll.js';
import { postJSON, readJSON } from '../core/http.js';
import { $, $$ } from '../core/dom.js';
import { confirmAction } from './confirm.js';

const ROUND_MS = 2000;
// A check answers in seconds. An install restarts the panel (or the broker) and keeps going if
// the new version does not answer, until the rollback: the wait has to cover that too.
const LIMIT_MS = { check: 90 * 1000, install: 10 * 60 * 1000 };

export const updateCard = {
  selector: '[data-update-status]',
  mount(card) {
    const url = card.dataset.updateStatus;
    const body = $('[data-update-body]', card);
    const note = $('[data-update-note]', card);
    if (!url || !body || !note) return;

    let stamp = card.dataset.updateStamp || '';
    let poller = null;

    const say = (text) => {
      note.textContent = text || '';
      note.hidden = !text;
    };
    const lock = (locked) => $$('button', body).forEach((b) => { b.disabled = locked; });
    const finish = (text) => {
      poller?.stop();
      poller = null;
      lock(false);
      say(text);
    };

    // True when the updater has written something new and the body was swapped.
    const refresh = async () => {
      const data = await readJSON(url);
      if (!data || data.stamp === stamp) return false;
      stamp = data.stamp;
      body.innerHTML = data.html;
      // The swapped buttons are new elements: the install confirmation has to be bound again.
      $$('[data-confirm]', body).forEach((el) => confirmAction.mount(el));
      return true;
    };

    // One listener on the card: it survives the body being swapped.
    card.addEventListener('submit', async (ev) => {
      const form = ev.target;
      if (!(form instanceof HTMLFormElement) || !body.contains(form)) return;
      ev.preventDefault();
      if (poller) return;

      const kind = form.action.endsWith('/install') ? 'install' : 'check';
      const deadline = Date.now() + LIMIT_MS[kind];
      lock(true);
      try {
        say((await postJSON(form.action, new FormData(form)))?.message);
      } catch (err) {
        finish(err.message);
        return;
      }

      const giveUp = () => {
        if (Date.now() > deadline) finish(card.dataset.updateNoAnswer);
      };
      // During an install the panel itself goes down for a moment: a failed round is expected,
      // the Poller backs off, and only the deadline ends the wait.
      poller = new Poller(async () => {
        if (await refresh()) finish('');
        else giveUp();
      }, { interval: ROUND_MS, onError: giveUp });
      poller.start({ immediate: false });
    });
  },
};
