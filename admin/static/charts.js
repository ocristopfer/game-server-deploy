/* Mira e balaozinho dos graficos de uso.
 *
 * O SVG ja vem desenhado do servidor; este arquivo so acrescenta a camada de leitura.
 * Nada aqui e a UNICA forma de ver um valor: cada linha tem o rotulo na ponta e a pagina
 * traz a tabela com os mesmos numeros — se o JS nao carregar, nada se perde.
 *
 * Os pontos nao sao mandados duas vezes: eles sao lidos de volta do proprio <polyline>, e
 * o valor sai da coordenada usando o teto e a moldura que o servidor deixou no data-*.
 */
(function () {
  'use strict';

  function num(el, nome) { return parseFloat(el.getAttribute(nome)) || 0; }

  function pontosDe(poly) {
    return (poly.getAttribute('points') || '').trim().split(/\s+/).map(function (par) {
      var xy = par.split(',');
      return { x: parseFloat(xy[0]), y: parseFloat(xy[1]) };
    }).filter(function (p) { return !isNaN(p.x) && !isNaN(p.y); });
  }

  function horaDe(svg, x) {
    var esq = num(svg, 'data-esq'), dir = num(svg, 'data-dir');
    if (dir <= esq) return '';
    var fatia = (x - esq) / (dir - esq);
    var quando = new Date(num(svg, 'data-inicio') + fatia * num(svg, 'data-span') * 1000);
    return quando.toLocaleString([], {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  }

  function valorDe(svg, y) {
    var topo = num(svg, 'data-topo'), base = num(svg, 'data-base');
    if (base <= topo) return 0;
    return num(svg, 'data-teto') * (base - y) / (base - topo);
  }

  function prepara(svg) {
    var mira = svg.querySelector('.mira');
    var series = [].map.call(svg.querySelectorAll('.serie'), function (poly) {
      return {
        nome: poly.getAttribute('data-serie') || '',
        sufixo: poly.getAttribute('data-sufixo') || '',
        cor: poly.getAttribute('stroke') || 'currentColor',
        pontos: pontosDe(poly)
      };
    });
    if (!mira || !series.length) return;

    // Um X so por instante, vindo de todas as series: o leitor mira numa hora, nunca
    // numa linha de 2px.
    var xs = [];
    series.forEach(function (s) {
      s.pontos.forEach(function (p) { if (xs.indexOf(p.x) < 0) xs.push(p.x); });
    });
    xs.sort(function (a, b) { return a - b; });
    if (!xs.length) return;

    var balao = document.createElement('div');
    balao.className = 'balao';
    balao.hidden = true;
    svg.parentNode.appendChild(balao);

    var indice = -1;

    function esconde() {
      mira.classList.remove('ativa');
      balao.hidden = true;
      indice = -1;
    }

    function mostra(i) {
      indice = Math.max(0, Math.min(xs.length - 1, i));
      var x = xs[indice];
      mira.setAttribute('x1', x);
      mira.setAttribute('x2', x);
      mira.classList.add('ativa');

      // Titulo e depois uma linha por serie. textContent em tudo: o rotulo da serie e
      // dado, nao marcacao.
      balao.textContent = '';
      var titulo = document.createElement('div');
      titulo.className = 'balao-hora';
      titulo.textContent = horaDe(svg, x);
      balao.appendChild(titulo);

      series.forEach(function (s) {
        var achado = null;
        s.pontos.forEach(function (p) { if (p.x === x) achado = p; });
        if (!achado) return;
        var linha = document.createElement('div');
        linha.className = 'balao-linha';
        var chave = document.createElement('i');
        chave.style.background = s.cor;
        var valor = document.createElement('strong');
        valor.textContent = valorDe(svg, achado.y).toFixed(s.sufixo === '%' ? 1 : 0) + s.sufixo;
        var nome = document.createElement('span');
        nome.textContent = s.nome;
        linha.appendChild(chave);
        linha.appendChild(valor);   // o valor lidera; o nome da serie e secundario
        linha.appendChild(nome);
        balao.appendChild(linha);
      });

      var caixa = svg.getBoundingClientRect();
      var largura = num(svg, 'data-dir') + parseFloat(svg.viewBox.baseVal.width - num(svg, 'data-dir'));
      var escala = caixa.width / (largura || 1);
      balao.hidden = false;
      // Vira para o outro lado perto da borda direita, para nao sair do cartao.
      var solto = x * escala;
      balao.style.left = (solto > caixa.width * 0.6 ? solto - balao.offsetWidth - 12 : solto + 12) + 'px';
    }

    function daPosicao(evento) {
      var caixa = svg.getBoundingClientRect();
      if (!caixa.width) return;
      var x = (evento.clientX - caixa.left) / caixa.width * svg.viewBox.baseVal.width;
      var melhor = 0;
      for (var i = 1; i < xs.length; i++) {
        if (Math.abs(xs[i] - x) < Math.abs(xs[melhor] - x)) melhor = i;
      }
      mostra(melhor);
    }

    svg.addEventListener('pointermove', daPosicao);
    svg.addEventListener('pointerleave', esconde);
    // Teclado ve o mesmo que o mouse: seta anda de amostra em amostra.
    svg.addEventListener('focus', function () { mostra(indice < 0 ? xs.length - 1 : indice); });
    svg.addEventListener('blur', esconde);
    svg.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowLeft') { mostra(indice - 1); ev.preventDefault(); }
      else if (ev.key === 'ArrowRight') { mostra(indice + 1); ev.preventDefault(); }
      else if (ev.key === 'Escape') { esconde(); }
    });
  }

  [].forEach.call(document.querySelectorAll('svg.grafico'), prepara);
})();
