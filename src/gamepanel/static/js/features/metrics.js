/* Resource gauges (CPU, memory, disk, network).
 *
 * The module has two halves kept apart on purpose:
 *
 *   - the RENDERERS, which only know how to turn data into markup (the same one Jinja
 *     generates on first load, so updating does not change the look);
 *   - the MOUNTERS, which only know how to bind a Poller to a piece of the screen.
 *
 * Whoever draws knows nothing about the network; whoever fetches knows nothing about HTML.
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $, $$ } from '../core/dom.js';
import { fileSize, duration, percentText, level, escapeHtml, fillText } from '../core/format.js';

/* What is used when the template did not hand over a phrase (the mount reads `data-label-*`,
 * already translated). Only placeholders and punctuation, never words: a phrase written here
 * would come out in Portuguese on the English screen. Keeping the placeholders means a missing
 * attribute still shows the number instead of `undefined`. */
const DEFAULT_LABELS = {
  memory: '',
  cores: '{cores} · {load}',
  usedOf: '{used} / {total}',
  diskMount: '{mount}',
  disk: '',
  metersUnavailable: '',
  stopped: '',
  refresh: '',
  noReading: '',
};

/* The labels a mount point declares, over the defaults. */
function labelsFrom(el) {
  const d = el.dataset;
  const given = {
    memory: d.labelMemory,
    cores: d.labelCores,
    usedOf: d.labelUsedOf,
    diskMount: d.labelDiskMount,
    disk: d.labelDisk,
    metersUnavailable: d.labelMetersUnavailable,
    stopped: d.labelStopped,
    refresh: d.labelRefresh,
    noReading: d.labelNoReading,
  };
  return Object.fromEntries(
    Object.entries(DEFAULT_LABELS).map(([k, v]) => [k, given[k] || v]),
  );
}

/* ------------------------------------------------------------ renderers */

function meter(key, title, pct, footer) {
  return `<div class="meter" data-key="${escapeHtml(key)}">` +
    `<div class="meter-head"><span>${escapeHtml(title)}</span>` +
    `<span class="val">${percentText(pct)}%</span></div>` +
    `<div class="bar${level(pct)}"><i style="width: ${Number(pct) || 0}%"></i></div>` +
    `<div class="meter-foot">${escapeHtml(footer)}</div></div>`;
}

export function fullList(data, labels = DEFAULT_LABELS) {
  const usedOf = (used, total) => fillText(labels.usedOf, { used: fileSize(used), total: fileSize(total) });
  // `cores`, not `colors`: the gauge field is the CPU core count (see the frontend contract test).
  let html = meter('cpu', 'CPU', data.cpu_pct,
    fillText(labels.cores, { cores: data.cores || 1, load: data.load || '-' }));
  html += meter('mem', labels.memory, data.mem && data.mem.pct,
    usedOf(data.mem && data.mem.used, data.mem && data.mem.total));
  if (data.swap && data.swap.total) {
    html += meter('swap', 'Swap', data.swap.pct, usedOf(data.swap.used, data.swap.total));
  }
  (data.disks || []).forEach((d) => {
    html += meter(`disk:${d.mount}`, fillText(labels.diskMount, { mount: d.mount }), d.pct,
      usedOf(d.used, d.total));
  });
  return html;
}

/* Slim version of the dashboard card: only the essentials, no absolute numbers. */
export function shortList(data, labels = DEFAULT_LABELS) {
  if (data.error) return `<span class="muted small">${escapeHtml(labels.metersUnavailable)}</span>`;
  const diskEl = (data.disks || [])[0];
  return [
    ['CPU', data.cpu_pct],
    ['RAM', data.mem && data.mem.pct],
    [labels.disk, diskEl && diskEl.pct],
  ].map(([label, bruto]) => {
    const pct = (bruto === undefined) ? null : bruto;
    return `<div class="mini"><span class="mini-label">${escapeHtml(label)}</span>` +
      `<span class="bar${level(pct)}"><i style="width: ${Number(pct) || 0}%"></i></span>` +
      `<span class="mini-val">${percentText(pct)}%</span></div>`;
  }).join('');
}

function processText(proc, labels = DEFAULT_LABELS) {
  if (!proc || !proc.pid) return labels.stopped;
  let text = `PID ${proc.pid} · ${fileSize(proc.rss)} RAM`;
  if (proc.cpu_pct !== null && proc.cpu_pct !== undefined) {
    text += ` · ${proc.cpu_pct.toFixed(1)}% CPU`;
  }
  return text;
}

/* ------------------------------------------------------------ mounters */

/* Server dashboard: ONE reading feeds the gauges of every card.
 * One call per card would multiply the SSH cost by the number of servers. */
export const panelMeters = {
  selector: '[data-meters-panel]',
  mount(root) {
    const url = root.dataset.metersPanel;
    const boxes = $$('.mini-meters', root);
    if (!url || !boxes.length) return;
    const labels = labelsFrom(root);

    new Poller(async () => {
      const all = await readJSON(url);
      boxes.forEach((box) => {
        const data = all[box.dataset.server];
        if (data) box.innerHTML = shortList(data, labels);
      });
    }, { interval: Number(root.dataset.interval) || 10000 }).start();
  },
};

/* A server's screen: full gauges plus network, uptime and process. */
export const serverMeters = {
  selector: '[data-meters-server]',
  mount(card) {
    const url = card.dataset.metersServer;
    const grid = $('#meters', card);
    const info = $('#recursos-info', card);
    const extra = $('#recursos-extra', card);
    if (!url || !grid) return;
    const labels = labelsFrom(card);

    const poller = new Poller(async () => {
      const data = await readJSON(url);
      grid.innerHTML = fullList(data, labels);
      if (extra) {
        $('[data-key="net"]', extra).textContent =
          `${fileSize(data.net_rx)}/s rx · ${fileSize(data.net_tx)}/s tx`;
        $('[data-key="uptime"]', extra).textContent = duration(data.uptime);
        $('[data-key="proc"]', extra).textContent = processText(data.proc, labels);
      }
      if (info) info.textContent = labels.refresh;
    }, {
      interval: Number(card.dataset.interval) || 5000,
      onError: () => { if (info) info.textContent = labels.noReading; },
    });

    // No `immediate`: the screen already came from the server with the first reading ready.
    poller.start({ immediate: false });
  },
};

/* The bars drawn by Jinja get their width here: a percentage written straight
 * into the style attribute would make every CSS tool trip over the template syntax. */
export const initialBars = {
  selector: '.bar > i[data-pct]',
  mount(bar) {
    bar.style.width = `${bar.dataset.pct}%`;
  },
};
