/* Mira e balaozinho dos graficos de uso.
 *
 * O SVG ja vem desenhado do servidor; este arquivo so acrescenta a camada de leitura.
 * Nada aqui e a UNICA forma de ver um valor: cada linha tem o rotulo na ponta e a
 * pagina traz a tabela com os mesmos numeros — se o JS nao carregar, nada se perde.
 *
 * Os pontos nao sao mandados duas vezes: eles sao lidos de volta do proprio
 * <polyline>, e o valor sai da coordenada usando o teto e a moldura que o servidor
 * deixou no data-*.
 */
import { createEl } from '../core/dom.js';

const num = (el, name) => Number.parseFloat(el.getAttribute(name)) || 0;

function pontosDe(poly) {
  return (poly.getAttribute('points') || '').trim().split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(',');
      return { x: Number.parseFloat(x), y: Number.parseFloat(y) };
    })
    .filter((p) => !Number.isNaN(p.x) && !Number.isNaN(p.y));
}

function timeAt(svg, x) {
  const esq = num(svg, 'data-left');
  const dir = num(svg, 'data-dir');
  if (dir <= esq) return '';
  const fatia = (x - esq) / (dir - esq);
  const quando = new Date(num(svg, 'data-start') + fatia * num(svg, 'data-span') * 1000);
  return quando.toLocaleString([], {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function valorDe(svg, y) {
  const top = num(svg, 'data-top');
  const base = num(svg, 'data-base');
  if (base <= top) return 0;
  return num(svg, 'data-ceiling') * (base - y) / (base - top);
}

export const chart = {
  selector: 'svg.chart',
  mount(svg) {
    const mira = svg.querySelector('.crosshair');
    const series = Array.from(svg.querySelectorAll('.series')).map((poly) => ({
      name: poly.dataset.series || '',
      suffix: poly.dataset.suffix || '',
      color: poly.getAttribute('stroke') || 'currentColor',
      points: pontosDe(poly),
    }));
    if (!mira || !series.length) return;

    // Um X so por instante, vindo de todas as series: o leitor mira numa hora, nunca
    // numa linha de 2px.
    const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))]
      .sort((a, b) => a - b);
    if (!xs.length) return;

    const balao = createEl('div', { className: 'bubble' });
    balao.hidden = true;
    svg.parentNode.appendChild(balao);

    let index = -1;

    function esconde() {
      mira.classList.remove('active');
      balao.hidden = true;
      index = -1;
    }

    function showAt(i) {
      index = Math.max(0, Math.min(xs.length - 1, i));
      const x = xs[index];
      mira.setAttribute('x1', x);
      mira.setAttribute('x2', x);
      mira.classList.add('active');

      // Titulo e depois uma linha por serie. Tudo por textContent: o rotulo da serie
      // e dado, nao marcacao.
      const lines = [createEl('div', { className: 'bubble-time', text: timeAt(svg, x) })];
      series.forEach((s) => {
        const found = s.points.find((p) => p.x === x);
        if (!found) return;
        const line = createEl('div', { className: 'bubble-line' });
        const key = createEl('i');
        key.style.background = s.color;
        line.append(
          key,
          // O valor lidera; o nome da serie e secundario.
          createEl('strong', {
            text: valorDe(svg, found.y).toFixed(s.suffix === '%' ? 1 : 0) + s.suffix,
          }),
          createEl('span', { text: s.name }),
        );
        lines.push(line);
      });
      balao.replaceChildren(...lines);

      const box = svg.getBoundingClientRect();
      const scale = box.width / (svg.viewBox.baseVal.width || 1);
      balao.hidden = false;
      // Vira para o outro lado perto da borda direita, para nao sair do cartao.
      const solto = x * scale;
      balao.style.left = `${solto > box.width * 0.6 ? solto - balao.offsetWidth - 12 : solto + 12}px`;
    }

    function daPosicao(evento) {
      const box = svg.getBoundingClientRect();
      if (!box.width) return;
      const x = (evento.clientX - box.left) / box.width * svg.viewBox.baseVal.width;
      let best = 0;
      for (let i = 1; i < xs.length; i++) {
        if (Math.abs(xs[i] - x) < Math.abs(xs[best] - x)) best = i;
      }
      showAt(best);
    }

    svg.addEventListener('pointermove', daPosicao);
    svg.addEventListener('pointerdown', daPosicao);   // no toque nao existe "passar por cima"
    svg.addEventListener('pointerleave', esconde);
    // Teclado ve o mesmo que o mouse: seta anda de amostra em amostra.
    svg.addEventListener('focus', () => showAt(index < 0 ? xs.length - 1 : index));
    svg.addEventListener('blur', esconde);
    svg.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowLeft') { showAt(index - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { showAt(index + 1); ev.preventDefault(); }
      else if (ev.key === 'Escape') { esconde(); }
    });
  },
};
