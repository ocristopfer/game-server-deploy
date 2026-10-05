/* Crosshair and tooltip for the usage charts.
 *
 * The SVG already comes drawn from the server; this file only adds the reading layer.
 * Nothing here is the ONLY way to see a value: each line has its label at the end and the
 * page carries the table with the same numbers - if the JS does not load, nothing is lost.
 *
 * The points are not sent twice: they are read back from the
 * <polyline> itself, and the value comes from the coordinate using the ceiling and frame the server
 * left in the data-*.
 */
import { createEl } from '../core/dom.js';

const num = (el, name) => Number.parseFloat(el.getAttribute(name)) || 0;

function pointsOf(poly) {
  return (poly.getAttribute('points') || '').trim().split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(',');
      return { x: Number.parseFloat(x), y: Number.parseFloat(y) };
    })
    .filter((p) => !Number.isNaN(p.x) && !Number.isNaN(p.y));
}

function timeAt(svg, x) {
  const left = num(svg, 'data-left');
  const dir = num(svg, 'data-dir');
  if (dir <= left) return '';
  const fraction = (x - left) / (dir - left);
  const when = new Date(num(svg, 'data-start') + fraction * num(svg, 'data-span') * 1000);
  return when.toLocaleString([], {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function valueAt(svg, y) {
  const top = num(svg, 'data-top');
  const base = num(svg, 'data-base');
  if (base <= top) return 0;
  return num(svg, 'data-ceiling') * (base - y) / (base - top);
}

export const chart = {
  selector: 'svg.chart',
  mount(svg) {
    const crosshair = svg.querySelector('.crosshair');
    const series = Array.from(svg.querySelectorAll('.series')).map((poly) => ({
      name: poly.dataset.series || '',
      suffix: poly.dataset.suffix || '',
      color: poly.getAttribute('stroke') || 'currentColor',
      points: pointsOf(poly),
    }));
    if (!crosshair || !series.length) return;

    // A single X per instant, taken from all series: the reader aims at a time, never
    // at a 2px line.
    const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))]
      .sort((a, b) => a - b);
    if (!xs.length) return;

    const bubble = createEl('div', { className: 'bubble' });
    bubble.hidden = true;
    svg.parentNode.appendChild(bubble);

    let index = -1;

    function hide() {
      crosshair.classList.remove('active');
      bubble.hidden = true;
      index = -1;
    }

    function showAt(i) {
      index = Math.max(0, Math.min(xs.length - 1, i));
      const x = xs[index];
      crosshair.setAttribute('x1', x);
      crosshair.setAttribute('x2', x);
      crosshair.classList.add('active');

      // Title and then one line per series. All through textContent: the series label
      // is data, not markup.
      const lines = [createEl('div', { className: 'bubble-time', text: timeAt(svg, x) })];
      series.forEach((s) => {
        const found = s.points.find((p) => p.x === x);
        if (!found) return;
        const line = createEl('div', { className: 'bubble-line' });
        const key = createEl('i');
        key.style.background = s.color;
        line.append(
          key,
          // The value leads; the series name is secondary.
          createEl('strong', {
            text: valueAt(svg, found.y).toFixed(s.suffix === '%' ? 1 : 0) + s.suffix,
          }),
          createEl('span', { text: s.name }),
        );
        lines.push(line);
      });
      bubble.replaceChildren(...lines);

      const box = svg.getBoundingClientRect();
      const scale = box.width / (svg.viewBox.baseVal.width || 1);
      bubble.hidden = false;
      // Flips to the other side near the right edge, so it does not leave the card.
      const loose = x * scale;
      bubble.style.left = `${loose > box.width * 0.6 ? loose - bubble.offsetWidth - 12 : loose + 12}px`;
    }

    function atPosition(event) {
      const box = svg.getBoundingClientRect();
      if (!box.width) return;
      const x = (event.clientX - box.left) / box.width * svg.viewBox.baseVal.width;
      let best = 0;
      for (let i = 1; i < xs.length; i++) {
        if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
      }
      showAt(best);
    }

    svg.addEventListener('pointermove', atPosition);
    svg.addEventListener('pointerdown', atPosition);   // on touch there is no "hovering"
    svg.addEventListener('pointerleave', hide);
    // The keyboard sees the same as the mouse: arrow keys move sample by sample.
    svg.addEventListener('focus', () => showAt(index < 0 ? xs.length - 1 : index));
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowLeft') { showAt(index - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { showAt(index + 1); ev.preventDefault(); }
      else if (ev.key === 'Escape') { hide(); }
    });
  },
};
