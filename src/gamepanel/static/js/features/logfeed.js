/* "Seguir o log" da tela do servidor.
 *
 * Cada volta pede ao painel so o que entrou depois do cursor do journald; quando o
 * container nao sabe emitir cursor, o bloco inteiro e trocado. A escolha de seguir
 * ou nao fica no navegador (localStorage), por servidor.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const VAZIO = '(sem linhas de log)';

export const followLog = {
  selector: '[data-log-feed]',
  mount(raiz) {
    const box = $('#log-box', raiz);
    const botao = $('#follow-toggle', raiz);
    const state = $('#follow-state', raiz);
    if (!box || !botao) return;

    const key = `gamepanel:follow:${botao.dataset.server}`;
    let cursor = botao.dataset.cursor || '';

    const noFim = () => box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    const paraOFim = () => { box.scrollTop = box.scrollHeight; };

    function marca(text, classe) {
      if (!state) return;
      state.textContent = text;
      state.className = `badge ${classe}`;
    }

    const poller = new Poller(async () => {
      const params = new URLSearchParams({ lines: botao.dataset.lines });
      if (cursor) params.set('cursor', cursor);
      const data = await readJSON(`${botao.dataset.logFeedUrl || botao.dataset.url}?${params}`);

      const colado = noFim();
      if (data.append) {
        // So chegou o que e novo: anexa sem repintar o que ja estava na tela.
        if (data.text) {
          box.textContent += (box.textContent.endsWith('\n') ? '' : '\n') + data.text;
        }
      } else if (data.text || !cursor) {
        box.textContent = data.text || VAZIO;
      }
      cursor = data.cursor || cursor;
      if (colado) paraOFim();
      marca('ao vivo', 'on');
    }, {
      interval: 3000,
      aoErro: () => marca('sem conexao', 'off'),
    });

    function seguir(ligar) {
      botao.textContent = ligar ? 'Parar de seguir' : 'Seguir log';
      botao.classList.toggle('btn--primary', ligar);
      if (state) state.hidden = !ligar;
      try { localStorage.setItem(key, ligar ? '1' : '0'); } catch { /* aba anonima */ }
      if (!ligar) { poller.parar(); return; }
      marca('ao vivo', 'on');
      paraOFim();
      poller.iniciar();
    }

    botao.addEventListener('click', () => seguir(!poller.ativo));

    let guardado = '0';
    try { guardado = localStorage.getItem(key) || '0'; } catch { /* aba anonima */ }
    if (guardado === '1') seguir(true);
  },
};
