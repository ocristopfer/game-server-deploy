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
import { criar } from '../core/dom.js';

const num = (el, nome) => Number.parseFloat(el.getAttribute(nome)) || 0;

function pontosDe(poly) {
  return (poly.getAttribute('points') || '').trim().split(/\s+/)
    .map((par) => {
      const [x, y] = par.split(',');
      return { x: Number.parseFloat(x), y: Number.parseFloat(y) };
    })
    .filter((p) => !Number.isNaN(p.x) && !Number.isNaN(p.y));
}

function horaDe(svg, x) {
  const esq = num(svg, 'data-esq');
  const dir = num(svg, 'data-dir');
  if (dir <= esq) return '';
  const fatia = (x - esq) / (dir - esq);
  const quando = new Date(num(svg, 'data-inicio') + fatia * num(svg, 'data-span') * 1000);
  return quando.toLocaleString([], {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

function valorDe(svg, y) {
  const topo = num(svg, 'data-topo');
  const base = num(svg, 'data-base');
  if (base <= topo) return 0;
  return num(svg, 'data-teto') * (base - y) / (base - topo);
}

export const grafico = {
  seletor: 'svg.grafico',
  montar(svg) {
    const mira = svg.querySelector('.mira');
    const series = Array.from(svg.querySelectorAll('.serie')).map((poly) => ({
      nome: poly.dataset.serie || '',
      sufixo: poly.dataset.sufixo || '',
      cor: poly.getAttribute('stroke') || 'currentColor',
      pontos: pontosDe(poly),
    }));
    if (!mira || !series.length) return;

    // Um X so por instante, vindo de todas as series: o leitor mira numa hora, nunca
    // numa linha de 2px.
    const xs = [...new Set(series.flatMap((s) => s.pontos.map((p) => p.x)))]
      .sort((a, b) => a - b);
    if (!xs.length) return;

    const balao = criar('div', { classe: 'balao' });
    balao.hidden = true;
    svg.parentNode.appendChild(balao);

    let indice = -1;

    function esconde() {
      mira.classList.remove('ativa');
      balao.hidden = true;
      indice = -1;
    }

    function mostra(i) {
      indice = Math.max(0, Math.min(xs.length - 1, i));
      const x = xs[indice];
      mira.setAttribute('x1', x);
      mira.setAttribute('x2', x);
      mira.classList.add('ativa');

      // Titulo e depois uma linha por serie. Tudo por textContent: o rotulo da serie
      // e dado, nao marcacao.
      const linhas = [criar('div', { classe: 'balao-hora', texto: horaDe(svg, x) })];
      series.forEach((s) => {
        const achado = s.pontos.find((p) => p.x === x);
        if (!achado) return;
        const linha = criar('div', { classe: 'balao-linha' });
        const chave = criar('i');
        chave.style.background = s.cor;
        linha.append(
          chave,
          // O valor lidera; o nome da serie e secundario.
          criar('strong', {
            texto: valorDe(svg, achado.y).toFixed(s.sufixo === '%' ? 1 : 0) + s.sufixo,
          }),
          criar('span', { texto: s.nome }),
        );
        linhas.push(linha);
      });
      balao.replaceChildren(...linhas);

      const caixa = svg.getBoundingClientRect();
      const escala = caixa.width / (svg.viewBox.baseVal.width || 1);
      balao.hidden = false;
      // Vira para o outro lado perto da borda direita, para nao sair do cartao.
      const solto = x * escala;
      balao.style.left = `${solto > caixa.width * 0.6 ? solto - balao.offsetWidth - 12 : solto + 12}px`;
    }

    function daPosicao(evento) {
      const caixa = svg.getBoundingClientRect();
      if (!caixa.width) return;
      const x = (evento.clientX - caixa.left) / caixa.width * svg.viewBox.baseVal.width;
      let melhor = 0;
      for (let i = 1; i < xs.length; i++) {
        if (Math.abs(xs[i] - x) < Math.abs(xs[melhor] - x)) melhor = i;
      }
      mostra(melhor);
    }

    svg.addEventListener('pointermove', daPosicao);
    svg.addEventListener('pointerdown', daPosicao);   // no toque nao existe "passar por cima"
    svg.addEventListener('pointerleave', esconde);
    // Teclado ve o mesmo que o mouse: seta anda de amostra em amostra.
    svg.addEventListener('focus', () => mostra(indice < 0 ? xs.length - 1 : indice));
    svg.addEventListener('blur', esconde);
    svg.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowLeft') { mostra(indice - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { mostra(indice + 1); ev.preventDefault(); }
      else if (ev.key === 'Escape') { esconde(); }
    });
  },
};
