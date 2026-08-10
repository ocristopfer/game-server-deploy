/* Medidores de recursos (CPU, memoria, disco, rede).
 *
 * Mesma marcacao que o Jinja gera no primeiro carregamento, para a atualizacao
 * automatica nao mudar o visual da tela. Usado pela tela de detalhe (medidores
 * completos) e pelo painel de servidores (tres barras finas por card).
 */
(function (global) {
  'use strict';

  function tamanho(bytes) {
    var v = Number(bytes) || 0;
    var unidades = ['B', 'KB', 'MB', 'GB'];
    for (var i = 0; i < unidades.length; i++) {
      if (v < 1024 || i === unidades.length - 1) {
        return i === 0 ? Math.round(v) + ' B' : v.toFixed(1) + ' ' + unidades[i];
      }
      v /= 1024;
    }
    return v.toFixed(1) + ' GB';
  }

  function duracao(seg) {
    var t = Math.floor(Number(seg) || 0);
    var d = Math.floor(t / 86400), h = Math.floor((t % 86400) / 3600), m = Math.floor((t % 3600) / 60);
    if (d) return d + 'd ' + h + 'h';
    if (h) return h + 'h ' + m + 'min';
    if (m) return m + 'min';
    return t + 's';   // jogador que acabou de entrar
  }

  function pctTexto(v) { return (v === null || v === undefined) ? '-' : Number(v).toFixed(1); }

  // Perto do teto o medidor muda de cor: e o que se olha de relance.
  function nivel(pct) {
    if (pct === null || pct === undefined) return '';
    if (pct >= 92) return ' hot';
    if (pct >= 80) return ' warn';
    return '';
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }

  function medidor(chave, titulo, pct, rodape) {
    return '<div class="meter" data-key="' + esc(chave) + '">' +
      '<div class="meter-head"><span>' + esc(titulo) + '</span>' +
      '<span class="val">' + pctTexto(pct) + '%</span></div>' +
      '<div class="bar' + nivel(pct) + '"><i style="width: ' + (pct || 0) + '%"></i></div>' +
      '<div class="meter-foot">' + esc(rodape) + '</div></div>';
  }

  function completos(data) {
    var html = medidor('cpu', 'CPU', data.cpu_pct,
      (data.cores || 1) + ' nucleo(s) - load ' + (data.load || '-'));
    html += medidor('mem', 'Memoria', data.mem && data.mem.pct,
      tamanho(data.mem && data.mem.used) + ' de ' + tamanho(data.mem && data.mem.total));
    if (data.swap && data.swap.total) {
      html += medidor('swap', 'Swap', data.swap.pct,
        tamanho(data.swap.used) + ' de ' + tamanho(data.swap.total));
    }
    (data.disks || []).forEach(function (d) {
      html += medidor('disk:' + d.mount, 'Disco ' + d.mount, d.pct,
        tamanho(d.used) + ' de ' + tamanho(d.total));
    });
    return html;
  }

  // Versao enxuta do card do painel: so o essencial, sem numeros absolutos.
  function resumo(data) {
    if (data.error) return '<span class="muted small">medidores indisponiveis</span>';
    var disco = (data.disks || [])[0];
    var linhas = [
      ['CPU', data.cpu_pct],
      ['RAM', data.mem && data.mem.pct],
      ['Disco', disco && disco.pct]
    ];
    return linhas.map(function (l) {
      var pct = (l[1] === undefined) ? null : l[1];
      return '<div class="mini"><span class="mini-label">' + l[0] + '</span>' +
        '<span class="bar' + nivel(pct) + '"><i style="width: ' + (pct || 0) + '%"></i></span>' +
        '<span class="mini-val">' + pctTexto(pct) + '%</span></div>';
    }).join('');
  }

  global.PanelMetrics = {
    tamanho: tamanho,
    duracao: duracao,
    completos: completos,
    resumo: resumo,
  };
})(window);
