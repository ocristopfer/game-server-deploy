/* Core - formatting.
 *
 * One responsibility: turning a number into text the way the panel speaks.
 * It does not touch the DOM, fetch anything from the network or keep state - which is why it
 * can be used by any feature and tested without a browser.
 */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

export function fileSize(bytes) {
  let v = Number(bytes) || 0;
  for (let i = 0; i < UNITS.length; i++) {
    if (v < 1024 || i === UNITS.length - 1) {
      return i === 0 ? `${Math.round(v)} B` : `${v.toFixed(1)} ${UNITS[i]}`;
    }
    v /= 1024;
  }
  return `${v.toFixed(1)} TB`;
}

export function duration(seg) {
  const t = Math.floor(Number(seg) || 0);
  const d = Math.floor(t / 86400);
  const h = Math.floor((t % 86400) / 3600);
  const m = Math.floor((t % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}min`;
  if (m) return `${m}min`;
  return `${t}s`;   // player who just joined
}

export function percentText(v) {
  return (v === null || v === undefined) ? '-' : Number(v).toFixed(1);
}

/* Near the ceiling the gauge changes color: that is what you look at at a glance. */
export function level(pct) {
  if (pct === null || pct === undefined) return '';
  if (pct >= 92) return ' hot';
  if (pct >= 80) return ' warn';
  return '';
}

/* Fills `{name}` placeholders of a screen phrase.
 *
 * JavaScript has no catalog: the template hands the translated phrase over in a data-*
 * attribute, with the placeholders still in it (`_('x', n='{n}')`), and this puts the
 * values in. Same contract as the Python `translate`: a placeholder without a field stays. */
export function fillText(template, fields = {}) {
  return Object.entries(fields).reduce(
    (text, [name, value]) => text.split(`{${name}}`).join(String(value)),
    String(template),
  );
}

/* Escapes text that came from the game or the container before it becomes HTML.
 * Where possible, prefer textContent; this is for when the markup is built in one block. */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
