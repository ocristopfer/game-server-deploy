/* "Follow the log" on the server screen.
 *
 * Each round asks the panel only for what came in after the journald cursor; when the
 * container cannot emit a cursor, the whole block is replaced. The choice to follow
 * or not stays in the browser (localStorage), per server.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $ } from '../core/dom.js';


export const followLog = {
  selector: '[data-log-feed]',
  mount(root) {
    const box = $('#log-box', root);
    const button = $('#follow-toggle', root);
    const state = $('#follow-state', root);
    if (!box || !button) return;
    // Screen text comes translated from the template; the fallback is the Portuguese text.
    const d = root.dataset;
    const text = {
      empty: d.labelEmpty || '(sem linhas de log)',
      live: d.labelLive || 'ao vivo',
      noConnection: d.labelNoConnection || 'sem conexao',
      follow: d.labelFollow || 'Seguir log',
      stopFollowing: d.labelStopFollowing || 'Parar de seguir',
    };

    const key = `gamepanel:follow:${button.dataset.server}`;
    let cursor = button.dataset.cursor || '';

    const atEnd = () => box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    const toEnd = () => { box.scrollTop = box.scrollHeight; };

    function mark(label, className) {
      if (!state) return;
      state.textContent = label;
      state.className = `badge ${className}`;
    }

    const poller = new Poller(async () => {
      const params = new URLSearchParams({ lines: button.dataset.lines });
      if (cursor) params.set('cursor', cursor);
      const data = await readJSON(`${button.dataset.logFeedUrl || button.dataset.url}?${params}`);

      const pasted = atEnd();
      if (data.append) {
        // Only new content arrived: append without repainting what was already on the screen.
        if (data.text) {
          box.textContent += (box.textContent.endsWith('\n') ? '' : '\n') + data.text;
        }
      } else if (data.text || !cursor) {
        box.textContent = data.text || text.empty;
      }
      cursor = data.cursor || cursor;
      if (pasted) toEnd();
      mark(text.live, 'on');
    }, {
      interval: 3000,
      onError: () => mark(text.noConnection, 'off'),
    });

    function follow(turnOn) {
      button.textContent = turnOn ? text.stopFollowing : text.follow;
      button.classList.toggle('btn--primary', turnOn);
      if (state) state.hidden = !turnOn;
      try { localStorage.setItem(key, turnOn ? '1' : '0'); } catch { /* private tab */ }
      if (!turnOn) { poller.stop(); return; }
      mark(text.live, 'on');
      toEnd();
      poller.start();
    }

    button.addEventListener('click', () => follow(!poller.active));

    let stored = '0';
    try { stored = localStorage.getItem(key) || '0'; } catch { /* private tab */ }
    if (stored === '1') follow(true);
  },
};
