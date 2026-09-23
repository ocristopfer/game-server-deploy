/* Medidores de recursos (CPU, memoria, disco, rede).
 *
 * O modulo tem duas metades bem separadas de proposito:
 *
 *   - os RENDERIZADORES, que so sabem virar dado em marcacao (a mesma que o Jinja
 *     gera no primeiro carregamento, para a atualizacao nao mudar o visual);
 *   - os MONTADORES, que so sabem ligar um Poller a um pedaco da tela.
 *
 * Quem desenha nao sabe de rede; quem busca nao sabe de HTML.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $, $$ } from '../core/dom.js';
import { fileSize, duration, percentText, level, escapeHtml } from '../core/format.js';

/* ------------------------------------------------------------ renderizadores */

function medidor(key, titulo, pct, rodape) {
  return `<div class="meter" data-key="${escapeHtml(chave)}">` +
    `<div class="meter-head"><span>${escapeHtml(titulo)}</span>` +
    `<span class="val">${percentText(pct)}%</span></div>` +
    `<div class="bar${level(pct)}"><i style="width: ${Number(pct) || 0}%"></i></div>` +
    `<div class="meter-foot">${escapeHtml(rodape)}</div></div>`;
}

export function fullList(data) {
  let html = medidor('cpu', 'CPU', data.cpu_pct,
    `${data.cores || 1} nucleo(s) - load ${data.load || '-'}`);
  html += medidor('mem', 'Memoria', data.mem && data.mem.pct,
    `${fileSize(data.mem && data.mem.used)} de ${fileSize(data.mem && data.mem.total)}`);
  if (data.swap && data.swap.total) {
    html += medidor('swap', 'Swap', data.swap.pct,
      `${fileSize(data.swap.used)} de ${fileSize(data.swap.total)}`);
  }
  (data.disks || []).forEach((d) => {
    html += medidor(`disk:${d.mount}`, `Disco ${d.mount}`, d.pct,
      `${fileSize(d.used)} de ${fileSize(d.total)}`);
  });
  return html;
}

/* Versao enxuta do cartao do painel: so o essencial, sem numeros absolutos. */
export function shortList(data) {
  if (data.error) return '<span class="muted small">medidores indisponiveis</span>';
  const disco = (data.disks || [])[0];
  return [
    ['CPU', data.cpu_pct],
    ['RAM', data.mem && data.mem.pct],
    ['Disco', disco && disco.pct],
  ].map(([label, bruto]) => {
    const pct = (bruto === undefined) ? null : bruto;
    return `<div class="mini"><span class="mini-label">${rotulo}</span>` +
      `<span class="bar${level(pct)}"><i style="width: ${Number(pct) || 0}%"></i></span>` +
      `<span class="mini-val">${percentText(pct)}%</span></div>`;
  }).join('');
}

function textoProcesso(proc) {
  if (!proc || !proc.pid) return 'parado';
  let text = `PID ${proc.pid} · ${fileSize(proc.rss)} RAM`;
  if (proc.cpu_pct !== null && proc.cpu_pct !== undefined) {
    text += ` · ${proc.cpu_pct.toFixed(1)}% CPU`;
  }
  return text;
}

/* ------------------------------------------------------------ montadores */

/* Painel de servidores: UMA leitura alimenta os medidores de todos os cartoes.
 * Uma chamada por cartao multiplicaria o custo de SSH pelo numero de servidores. */
export const panelMeters = {
  selector: '[data-meters-panel]',
  mount(raiz) {
    const url = raiz.dataset.metersPanel;
    const caixas = $$('.mini-meters', raiz);
    if (!url || !caixas.length) return;

    new Poller(async () => {
      const tudo = await readJSON(url);
      caixas.forEach((box) => {
        const data = tudo[box.dataset.server];
        if (data) box.innerHTML = shortList(data);
      });
    }, { interval: Number(raiz.dataset.interval) || 10000 }).iniciar();
  },
};

/* Tela de um servidor: medidores fullList mais rede, uptime e processo. */
export const serverMeters = {
  selector: '[data-meters-server]',
  mount(cartao) {
    const url = cartao.dataset.metersServer;
    const grade = $('#meters', cartao);
    const info = $('#recursos-info', cartao);
    const extra = $('#recursos-extra', cartao);
    if (!url || !grade) return;

    const poller = new Poller(async () => {
      const data = await readJSON(url);
      grade.innerHTML = fullList(data);
      if (extra) {
        $('[data-key="net"]', extra).textContent =
          `${fileSize(data.net_rx)}/s rx · ${fileSize(data.net_tx)}/s tx`;
        $('[data-key="uptime"]', extra).textContent = duration(data.uptime);
        $('[data-key="proc"]', extra).textContent = textoProcesso(data.proc);
      }
      if (info) info.textContent = 'atualiza a cada 5s';
    }, {
      interval: Number(cartao.dataset.interval) || 5000,
      aoErro: () => { if (info) info.textContent = 'sem leitura no momento'; },
    });

    // Sem `imediato`: a tela ja chegou do servidor com a primeira leitura pronta.
    poller.iniciar({ imediato: false });
  },
};

/* As barras desenhadas pelo Jinja recebem a largura aqui: percentual escrito direto
 * no atributo style faria toda ferramenta de CSS tropecar na sintaxe do template. */
export const initialBars = {
  selector: '.bar > i[data-pct]',
  mount(barra) {
    barra.style.width = `${barra.dataset.pct}%`;
  },
};
