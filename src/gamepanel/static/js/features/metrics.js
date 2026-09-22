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
import { lerJSON } from '../core/http.js';
import { $, $$ } from '../core/dom.js';
import { tamanho, duracao, pctTexto, nivel, esc } from '../core/format.js';

/* ------------------------------------------------------------ renderizadores */

function medidor(chave, titulo, pct, rodape) {
  return `<div class="meter" data-key="${esc(chave)}">` +
    `<div class="meter-head"><span>${esc(titulo)}</span>` +
    `<span class="val">${pctTexto(pct)}%</span></div>` +
    `<div class="bar${nivel(pct)}"><i style="width: ${Number(pct) || 0}%"></i></div>` +
    `<div class="meter-foot">${esc(rodape)}</div></div>`;
}

export function completos(data) {
  let html = medidor('cpu', 'CPU', data.cpu_pct,
    `${data.cores || 1} nucleo(s) - load ${data.load || '-'}`);
  html += medidor('mem', 'Memoria', data.mem && data.mem.pct,
    `${tamanho(data.mem && data.mem.used)} de ${tamanho(data.mem && data.mem.total)}`);
  if (data.swap && data.swap.total) {
    html += medidor('swap', 'Swap', data.swap.pct,
      `${tamanho(data.swap.used)} de ${tamanho(data.swap.total)}`);
  }
  (data.disks || []).forEach((d) => {
    html += medidor(`disk:${d.mount}`, `Disco ${d.mount}`, d.pct,
      `${tamanho(d.used)} de ${tamanho(d.total)}`);
  });
  return html;
}

/* Versao enxuta do cartao do painel: so o essencial, sem numeros absolutos. */
export function resumo(data) {
  if (data.error) return '<span class="muted small">medidores indisponiveis</span>';
  const disco = (data.disks || [])[0];
  return [
    ['CPU', data.cpu_pct],
    ['RAM', data.mem && data.mem.pct],
    ['Disco', disco && disco.pct],
  ].map(([rotulo, bruto]) => {
    const pct = (bruto === undefined) ? null : bruto;
    return `<div class="mini"><span class="mini-label">${rotulo}</span>` +
      `<span class="bar${nivel(pct)}"><i style="width: ${Number(pct) || 0}%"></i></span>` +
      `<span class="mini-val">${pctTexto(pct)}%</span></div>`;
  }).join('');
}

function textoProcesso(proc) {
  if (!proc || !proc.pid) return 'parado';
  let texto = `PID ${proc.pid} · ${tamanho(proc.rss)} RAM`;
  if (proc.cpu_pct !== null && proc.cpu_pct !== undefined) {
    texto += ` · ${proc.cpu_pct.toFixed(1)}% CPU`;
  }
  return texto;
}

/* ------------------------------------------------------------ montadores */

/* Painel de servidores: UMA leitura alimenta os medidores de todos os cartoes.
 * Uma chamada por cartao multiplicaria o custo de SSH pelo numero de servidores. */
export const medidoresDoPainel = {
  seletor: '[data-medidores-painel]',
  montar(raiz) {
    const url = raiz.dataset.medidoresPainel;
    const caixas = $$('.mini-meters', raiz);
    if (!url || !caixas.length) return;

    new Poller(async () => {
      const tudo = await lerJSON(url);
      caixas.forEach((caixa) => {
        const data = tudo[caixa.dataset.server];
        if (data) caixa.innerHTML = resumo(data);
      });
    }, { intervalo: Number(raiz.dataset.intervalo) || 10000 }).iniciar();
  },
};

/* Tela de um servidor: medidores completos mais rede, uptime e processo. */
export const medidoresDoServidor = {
  seletor: '[data-medidores-servidor]',
  montar(cartao) {
    const url = cartao.dataset.medidoresServidor;
    const grade = $('#meters', cartao);
    const info = $('#recursos-info', cartao);
    const extra = $('#recursos-extra', cartao);
    if (!url || !grade) return;

    const poller = new Poller(async () => {
      const data = await lerJSON(url);
      grade.innerHTML = completos(data);
      if (extra) {
        $('[data-key="net"]', extra).textContent =
          `${tamanho(data.net_rx)}/s rx · ${tamanho(data.net_tx)}/s tx`;
        $('[data-key="uptime"]', extra).textContent = duracao(data.uptime);
        $('[data-key="proc"]', extra).textContent = textoProcesso(data.proc);
      }
      if (info) info.textContent = 'atualiza a cada 5s';
    }, {
      intervalo: Number(cartao.dataset.intervalo) || 5000,
      aoErro: () => { if (info) info.textContent = 'sem leitura no momento'; },
    });

    // Sem `imediato`: a tela ja chegou do servidor com a primeira leitura pronta.
    poller.iniciar({ imediato: false });
  },
};

/* As barras desenhadas pelo Jinja recebem a largura aqui: percentual escrito direto
 * no atributo style faria toda ferramenta de CSS tropecar na sintaxe do template. */
export const barrasIniciais = {
  seletor: '.bar > i[data-pct]',
  montar(barra) {
    barra.style.width = `${barra.dataset.pct}%`;
  },
};
