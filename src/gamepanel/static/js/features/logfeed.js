/* "Seguir o log" da tela do servidor.
 *
 * Cada volta pede ao painel so o que entrou depois do cursor do journald; quando o
 * container nao sabe emitir cursor, o bloco inteiro e trocado. A escolha de seguir
 * ou nao fica no navegador (localStorage), por servidor.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const EMPTY_LOG = '(sem linhas de log)';

export const followLog = {
  selector: '[data-log-feed]',
  mount(root) {
    const box = $('#log-box', root);
    const button = $('#follow-toggle', root);
    const state = $('#follow-state', root);
    if (!box || !button) return;

    const key = `gamepanel:follow:${button.dataset.server}`;
    let cursor = button.dataset.cursor || '';

    const atEnd = () => box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    const toEnd = () => { box.scrollTop = box.scrollHeight; };

    function mark(text, className) {
      if (!state) return;
      state.textContent = text;
      state.className = `badge ${classe}`;
    }

    const poller = new Poller(async () => {
      const params = new URLSearchParams({ lines: button.dataset.lines });
      if (cursor) params.set('cursor', cursor);
      const data = await readJSON(`${button.dataset.logFeedUrl || button.dataset.url}?${params}`);

      const pasted = atEnd();
      if (data.append) {
        // So chegou o que e novo: anexa sem repintar o que ja estava na tela.
        if (data.text) {
          box.textContent += (box.textContent.endsWith('\n') ? '' : '\n') + data.text;
        }
      } else if (data.text || !cursor) {
        box.textContent = data.text || EMPTY_LOG;
      }
      cursor = data.cursor || cursor;
      if (pasted) toEnd();
      mark('ao vivo', 'on');
    }, {
      interval: 3000,
      onError: () => mark('sem conexao', 'off'),
    });

    function follow(turnOn) {
      button.textContent = turnOn ? 'Parar de seguir' : 'Seguir log';
      button.classList.toggle('btn--primary', turnOn);
      if (state) state.hidden = !turnOn;
      try { localStorage.setItem(key, turnOn ? '1' : '0'); } catch { /* aba anonima */ }
      if (!turnOn) { poller.stop(); return; }
      mark('ao vivo', 'on');
      toEnd();
      poller.start();
    }

    button.addEventListener('click', () => follow(!poller.active));

    let stored = '0';
    try { stored = localStorage.getItem(key) || '0'; } catch { /* aba anonima */ }
    if (stored === '1') follow(true);
  },
};
