/* Nucleo — formatacao.
 *
 * Uma responsabilidade: transformar numero em texto do jeito que o painel fala.
 * Nao toca no DOM, nao busca nada na rede, nao guarda estado — por isso pode ser
 * usada por qualquer feature e testada sem navegador.
 */

const UNIDADES = ['B', 'KB', 'MB', 'GB', 'TB'];

export function fileSize(bytes) {
  let v = Number(bytes) || 0;
  for (let i = 0; i < UNIDADES.length; i++) {
    if (v < 1024 || i === UNIDADES.length - 1) {
      return i === 0 ? `${Math.round(v)} B` : `${v.toFixed(1)} ${UNIDADES[i]}`;
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
  return `${t}s`;   // jogador que acabou de entrar
}

export function percentText(v) {
  return (v === null || v === undefined) ? '-' : Number(v).toFixed(1);
}

/* Perto do teto o medidor muda de cor: e o que se olha de relance. */
export function level(pct) {
  if (pct === null || pct === undefined) return '';
  if (pct >= 92) return ' hot';
  if (pct >= 80) return ' warn';
  return '';
}

/* Escapa texto que veio do jogo ou do container antes de virar HTML.
 * Onde der, prefira textContent; isto e para quando a marcacao e montada em bloco. */
export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
