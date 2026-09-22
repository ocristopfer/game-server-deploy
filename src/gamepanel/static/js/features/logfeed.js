/* "Seguir o log" da tela do servidor.
 *
 * Cada volta pede ao painel so o que entrou depois do cursor do journald; quando o
 * container nao sabe emitir cursor, o bloco inteiro e trocado. A escolha de seguir
 * ou nao fica no navegador (localStorage), por servidor.
 */
import { Poller } from '../core/poll.js';
import { lerJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const VAZIO = '(sem linhas de log)';

export const seguirLog = {
  seletor: '[data-log-feed]',
  montar(raiz) {
    const caixa = $('#log-box', raiz);
    const botao = $('#follow-toggle', raiz);
    const estado = $('#follow-state', raiz);
    if (!caixa || !botao) return;

    const chave = `gamepanel:follow:${botao.dataset.server}`;
    let cursor = botao.dataset.cursor || '';

    const noFim = () => caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 30;
    const paraOFim = () => { caixa.scrollTop = caixa.scrollHeight; };

    function marca(texto, classe) {
      if (!estado) return;
      estado.textContent = texto;
      estado.className = `badge ${classe}`;
    }

    const poller = new Poller(async () => {
      const params = new URLSearchParams({ lines: botao.dataset.lines });
      if (cursor) params.set('cursor', cursor);
      const data = await lerJSON(`${botao.dataset.logFeedUrl || botao.dataset.url}?${params}`);

      const colado = noFim();
      if (data.append) {
        // So chegou o que e novo: anexa sem repintar o que ja estava na tela.
        if (data.text) {
          caixa.textContent += (caixa.textContent.endsWith('\n') ? '' : '\n') + data.text;
        }
      } else if (data.text || !cursor) {
        caixa.textContent = data.text || VAZIO;
      }
      cursor = data.cursor || cursor;
      if (colado) paraOFim();
      marca('ao vivo', 'on');
    }, {
      intervalo: 3000,
      aoErro: () => marca('sem conexao', 'off'),
    });

    function seguir(ligar) {
      botao.textContent = ligar ? 'Parar de seguir' : 'Seguir log';
      botao.classList.toggle('btn--primary', ligar);
      if (estado) estado.hidden = !ligar;
      try { localStorage.setItem(chave, ligar ? '1' : '0'); } catch { /* aba anonima */ }
      if (!ligar) { poller.parar(); return; }
      marca('ao vivo', 'on');
      paraOFim();
      poller.iniciar();
    }

    botao.addEventListener('click', () => seguir(!poller.ativo));

    let guardado = '0';
    try { guardado = localStorage.getItem(chave) || '0'; } catch { /* aba anonima */ }
    if (guardado === '1') seguir(true);
  },
};
