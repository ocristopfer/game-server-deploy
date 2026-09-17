/* Terminal do painel: emulador VT100/xterm minimo + transporte por HTTP.
 *
 * Por que escrever um emulador em vez de usar xterm.js: o container do painel nao
 * baixa pacote de CDN (e nao tem npm), entao tudo aqui e servido pelo proprio painel.
 * O suficiente esta implementado para rodar bash, vim, htop, top e menus curses:
 * buffer de tela, regiao de rolagem, tela alternativa, cores (16/256/RGB) e o teclado.
 *
 * Transporte: nada de WebSocket (o painel roda em gunicorn sync). A saida vem de um
 * long-poll com offset em bytes; as teclas sobem num POST por vez, em ordem.
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------ cores
  function buildPalette() {
    var p = [
      '#0c0c0c', '#cd3131', '#0dbc79', '#e5e510', '#2472c8', '#bc3fbc', '#11a8cd', '#cccccc',
      '#666666', '#f14c4c', '#23d18b', '#f5f543', '#3b8eea', '#d670d6', '#29b8db', '#f5f5f5'
    ];
    var lv = [0, 95, 135, 175, 215, 255], r, g, b, i;
    for (r = 0; r < 6; r++)
      for (g = 0; g < 6; g++)
        for (b = 0; b < 6; b++) p.push('rgb(' + lv[r] + ',' + lv[g] + ',' + lv[b] + ')');
    for (i = 0; i < 24; i++) { var v = 8 + i * 10; p.push('rgb(' + v + ',' + v + ',' + v + ')'); }
    return p;
  }
  var PALETTE = buildPalette();

  var BOLD = 1, DIM = 2, ITALIC = 4, UNDER = 8, INVERSE = 16;

  // Larguras duplas mais comuns (CJK, emoji). Sem isso as bordas de menus curses
  // em japones/emoji saem deslocadas.
  function isWide(cp) {
    return (cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0xa4cf) ||
      (cp >= 0xac00 && cp <= 0xd7a3) || (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xfe30 && cp <= 0xfe6f) || (cp >= 0xff00 && cp <= 0xff60) ||
      (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x1f300 && cp <= 0x1f64f) ||
      (cp >= 0x1f900 && cp <= 0x1f9ff) || (cp >= 0x20000 && cp <= 0x3fffd);
  }

  function cell(ch, fg, bg, fl) { return { c: ch, f: fg, b: bg, l: fl }; }
  function blank() { return cell(' ', null, null, 0); }

  // --------------------------------------------------------------- terminal
  function Term(screenEl, scrollEl) {
    this.screenEl = screenEl;
    this.scrollEl = scrollEl;
    this.cols = 80;
    this.rows = 24;
    this.x = 0; this.y = 0;
    this.fg = null; this.bg = null; this.flags = 0;
    this.top = 0; this.bottom = 23;
    this.wrapNext = false;
    this.autowrap = true;
    this.cursorVisible = true;
    this.appCursor = false;      // DECCKM: setas mandam ESC O A em vez de ESC [ A
    this.bracketedPaste = false;
    this.alt = null;             // buffer normal guardado enquanto a tela alternativa roda
    this.saved = null;
    this.state = 'ground';
    this.params = '';
    this.prefix = '';
    this.oscBuf = '';
    this.pending = '';           // sobra de sequencia cortada entre dois poll
    this.reply = function () {};
    this.lines = [];
    this.reset(true);
  }

  Term.prototype.reset = function (hard) {
    this.lines = [];
    for (var i = 0; i < this.rows; i++) this.lines.push(this.blankLine());
    this.x = this.y = 0;
    this.top = 0; this.bottom = this.rows - 1;
    this.fg = this.bg = null; this.flags = 0;
    this.wrapNext = false; this.autowrap = true; this.cursorVisible = true;
    this.alt = null; this.appCursor = false;
    if (hard && this.scrollEl) this.scrollEl.innerHTML = '';
  };

  Term.prototype.blankLine = function () {
    var line = new Array(this.cols);
    for (var i = 0; i < this.cols; i++) line[i] = blank();
    return line;
  };

  Term.prototype.resize = function (cols, rows) {
    if (cols === this.cols && rows === this.rows) return;
    var i, j;
    for (i = 0; i < this.lines.length; i++) {
      var line = this.lines[i];
      if (cols < line.length) line.length = cols;
      else for (j = line.length; j < cols; j++) line.push(blank());
    }
    while (this.lines.length > rows) {
      // Some linha de cima primeiro, como faz um terminal de verdade.
      if (this.y > 0 && this.lines.length - 1 >= this.y) { this.lines.pop(); }
      else { this.pushScrollback(this.lines.shift()); if (this.y > 0) this.y--; }
    }
    this.cols = cols; this.rows = rows;
    while (this.lines.length < rows) this.lines.push(this.blankLine());
    this.top = 0; this.bottom = rows - 1;
    if (this.y >= rows) this.y = rows - 1;
    if (this.x >= cols) this.x = cols - 1;
    this.render();
  };

  // ------------------------------------------------------------- rolagem
  Term.prototype.pushScrollback = function (line) {
    if (!this.scrollEl || this.alt) return;  // tela alternativa nao vai pro historico
    var div = document.createElement('div');
    div.className = 'tl';
    div.innerHTML = renderLine(line, -1);
    this.scrollEl.appendChild(div);
    while (this.scrollEl.childElementCount > 2000) {
      this.scrollEl.removeChild(this.scrollEl.firstChild);
    }
  };

  Term.prototype.scrollUp = function (n) {
    for (var i = 0; i < n; i++) {
      var gone = this.lines.splice(this.top, 1)[0];
      if (this.top === 0) this.pushScrollback(gone);
      this.lines.splice(this.bottom, 0, this.blankLine());
    }
  };

  Term.prototype.scrollDown = function (n) {
    for (var i = 0; i < n; i++) {
      this.lines.splice(this.bottom, 1);
      this.lines.splice(this.top, 0, this.blankLine());
    }
  };

  Term.prototype.newLine = function () {
    if (this.y === this.bottom) this.scrollUp(1);
    else if (this.y < this.rows - 1) this.y++;
  };

  Term.prototype.reverseIndex = function () {
    if (this.y === this.top) this.scrollDown(1);
    else if (this.y > 0) this.y--;
  };

  // ------------------------------------------------------------ escrita
  Term.prototype.putChar = function (ch, wide) {
    if (this.wrapNext) { this.x = 0; this.newLine(); this.wrapNext = false; }
    if (this.x >= this.cols) { this.x = this.cols - 1; }
    this.lines[this.y][this.x] = cell(ch, this.fg, this.bg, this.flags);
    if (wide && this.x + 1 < this.cols) {
      this.x++;
      this.lines[this.y][this.x] = cell('', this.fg, this.bg, this.flags);
    }
    if (this.x + 1 >= this.cols) {
      if (this.autowrap) this.wrapNext = true;
    } else this.x++;
  };

  Term.prototype.write = function (text) {
    var s = this.pending + text;
    this.pending = '';
    var chars = Array.from(s);
    for (var i = 0; i < chars.length; i++) {
      var ch = chars[i];
      var code = ch.codePointAt(0);

      if (this.state === 'osc') {
        // Titulo da janela e afins: consome ate BEL ou ST (ESC \).
        if (code === 7) { this.state = 'ground'; this.oscBuf = ''; }
        else if (ch === '\x1b' && chars[i + 1] === '\\') { i++; this.state = 'ground'; this.oscBuf = ''; }
        else this.oscBuf += ch;
        continue;
      }
      if (this.state === 'esc') { i = this.handleEsc(ch, chars, i); continue; }
      if (this.state === 'csi') {
        if ((code >= 0x30 && code <= 0x3f) || code === 0x20) {
          if (code >= 0x3c && code <= 0x3f) this.prefix = ch; else this.params += ch;
        } else if (code >= 0x40 && code <= 0x7e) {
          this.handleCsi(ch);
          this.state = 'ground';
        } else if (code === 0x1b) { this.state = 'esc'; }
        continue;
      }
      if (this.state === 'charset') { this.state = 'ground'; continue; }

      switch (code) {
        case 0x1b: this.state = 'esc'; break;
        case 0x07: break;                                  // bell
        case 0x08: this.x = Math.max(0, this.x - 1); this.wrapNext = false; break;
        case 0x09: this.x = Math.min(this.cols - 1, (Math.floor(this.x / 8) + 1) * 8); break;
        case 0x0a: case 0x0b: case 0x0c: this.newLine(); this.wrapNext = false; break;
        case 0x0d: this.x = 0; this.wrapNext = false; break;
        case 0x00: case 0x0e: case 0x0f: break;
        default:
          if (code < 0x20) break;
          this.putChar(ch, isWide(code));
      }
    }
    // Sequencia cortada no fim do bloco: guarda para o proximo pedaco.
    if (this.state === 'esc' || this.state === 'csi') {
      this.pending = '\x1b' + (this.state === 'csi' ? '[' + this.prefix + this.params : '');
      this.state = 'ground'; this.params = ''; this.prefix = '';
    }
    this.render();
  };

  Term.prototype.handleEsc = function (ch, chars, i) {
    this.state = 'ground';
    switch (ch) {
      case '[': this.state = 'csi'; this.params = ''; this.prefix = ''; break;
      case ']': this.state = 'osc'; this.oscBuf = ''; break;
      case '(': case ')': case '*': case '+': this.state = 'charset'; break;
      case 'M': this.reverseIndex(); break;
      case 'D': this.newLine(); break;
      case 'E': this.x = 0; this.newLine(); break;
      case '7': this.saved = { x: this.x, y: this.y, fg: this.fg, bg: this.bg, fl: this.flags }; break;
      case '8':
        if (this.saved) {
          this.x = this.saved.x; this.y = this.saved.y;
          this.fg = this.saved.fg; this.bg = this.saved.bg; this.flags = this.saved.fl;
        }
        break;
      case 'c': this.reset(true); break;
      default: break;  // '=', '>', charsets e afins nao mudam nada aqui
    }
    return i;
  };

  Term.prototype.nums = function (def) {
    var out = this.params.split(';').map(function (p) {
      var n = parseInt(p, 10);
      return isNaN(n) ? def : n;
    });
    return out.length ? out : [def];
  };

  Term.prototype.eraseInLine = function (from, to) {
    var line = this.lines[this.y];
    for (var i = from; i <= to && i < this.cols; i++) line[i] = cell(' ', null, this.bg, 0);
  };

  Term.prototype.handleCsi = function (final) {
    var p = this.nums(0), n = p[0] || 0, i;
    var one = Math.max(1, p[0] || 1);

    switch (final) {
      case 'A': this.y = Math.max(this.top, this.y - one); break;
      case 'B': this.y = Math.min(this.bottom, this.y + one); break;
      case 'C': this.x = Math.min(this.cols - 1, this.x + one); this.wrapNext = false; break;
      case 'D': this.x = Math.max(0, this.x - one); this.wrapNext = false; break;
      case 'E': this.y = Math.min(this.bottom, this.y + one); this.x = 0; break;
      case 'F': this.y = Math.max(this.top, this.y - one); this.x = 0; break;
      case 'G': case '`': this.x = Math.min(this.cols - 1, one - 1); break;
      case 'd': this.y = Math.min(this.rows - 1, one - 1); break;
      case 'H': case 'f':
        this.y = Math.min(this.rows - 1, Math.max(1, p[0] || 1) - 1);
        this.x = Math.min(this.cols - 1, Math.max(1, p[1] || 1) - 1);
        this.wrapNext = false;
        break;
      case 'J':
        if (n === 0) {
          this.eraseInLine(this.x, this.cols - 1);
          for (i = this.y + 1; i < this.rows; i++) this.lines[i] = this.blankLine();
        } else if (n === 1) {
          this.eraseInLine(0, this.x);
          for (i = 0; i < this.y; i++) this.lines[i] = this.blankLine();
        } else {
          for (i = 0; i < this.rows; i++) this.lines[i] = this.blankLine();
          if (n === 3 && this.scrollEl) this.scrollEl.innerHTML = '';
        }
        break;
      case 'K':
        if (n === 0) this.eraseInLine(this.x, this.cols - 1);
        else if (n === 1) this.eraseInLine(0, this.x);
        else this.eraseInLine(0, this.cols - 1);
        break;
      case 'L':  // insere linhas na regiao de rolagem
        for (i = 0; i < one && this.y <= this.bottom; i++) {
          this.lines.splice(this.bottom, 1);
          this.lines.splice(this.y, 0, this.blankLine());
        }
        break;
      case 'M':  // remove linhas
        for (i = 0; i < one && this.y <= this.bottom; i++) {
          this.lines.splice(this.y, 1);
          this.lines.splice(this.bottom, 0, this.blankLine());
        }
        break;
      case 'P':  // apaga caracteres puxando o resto da linha
        for (i = 0; i < one; i++) { this.lines[this.y].splice(this.x, 1); this.lines[this.y].push(blank()); }
        break;
      case '@':  // abre espaco na linha
        for (i = 0; i < one; i++) { this.lines[this.y].splice(this.x, 0, blank()); this.lines[this.y].pop(); }
        break;
      case 'X': this.eraseInLine(this.x, this.x + one - 1); break;
      case 'S': this.scrollUp(one); break;
      case 'T': this.scrollDown(one); break;
      case 'r':
        this.top = Math.max(0, (p[0] || 1) - 1);
        this.bottom = Math.min(this.rows - 1, (p[1] || this.rows) - 1);
        if (this.top >= this.bottom) { this.top = 0; this.bottom = this.rows - 1; }
        this.x = 0; this.y = this.top;
        break;
      case 'm': this.sgr(); break;
      case 'h': case 'l': this.mode(final === 'h'); break;
      case 's': this.saved = { x: this.x, y: this.y, fg: this.fg, bg: this.bg, fl: this.flags }; break;
      case 'u':
        if (this.saved) { this.x = this.saved.x; this.y = this.saved.y; }
        break;
      case 'n':
        if (n === 6) this.reply('\x1b[' + (this.y + 1) + ';' + (this.x + 1) + 'R');
        else if (n === 5) this.reply('\x1b[0n');
        break;
      case 'c': this.reply('\x1b[?6c'); break;  // "sou um VT102"
      default: break;
    }
    this.params = ''; this.prefix = '';
  };

  Term.prototype.mode = function (on) {
    var p = this.nums(0);
    for (var i = 0; i < p.length; i++) {
      var m = p[i];
      if (this.prefix !== '?') continue;
      if (m === 1) this.appCursor = on;
      else if (m === 7) this.autowrap = on;
      else if (m === 25) this.cursorVisible = on;
      else if (m === 2004) this.bracketedPaste = on;
      else if (m === 1049 || m === 47 || m === 1047) this.useAlt(on);
    }
  };

  Term.prototype.useAlt = function (on) {
    if (on && !this.alt) {
      this.alt = { lines: this.lines, x: this.x, y: this.y, top: this.top, bottom: this.bottom };
      this.lines = [];
      for (var i = 0; i < this.rows; i++) this.lines.push(this.blankLine());
      this.x = this.y = 0; this.top = 0; this.bottom = this.rows - 1;
    } else if (!on && this.alt) {
      this.lines = this.alt.lines;
      this.x = this.alt.x; this.y = this.alt.y;
      this.top = this.alt.top; this.bottom = this.alt.bottom;
      this.alt = null;
      // A tela guardada pode ter outro tamanho se a janela mudou durante o htop.
      this.resizeLinesTo(this.rows, this.cols);
    }
  };

  Term.prototype.resizeLinesTo = function (rows, cols) {
    while (this.lines.length > rows) this.lines.pop();
    while (this.lines.length < rows) this.lines.push(this.blankLine());
    for (var i = 0; i < rows; i++) {
      var line = this.lines[i];
      if (line.length > cols) line.length = cols;
      else while (line.length < cols) line.push(blank());
    }
    if (this.y >= rows) this.y = rows - 1;
    if (this.x >= cols) this.x = cols - 1;
  };

  Term.prototype.sgr = function () {
    var p = this.params === '' ? [0] : this.nums(0);
    for (var i = 0; i < p.length; i++) {
      var v = p[i];
      if (v === 0) { this.fg = this.bg = null; this.flags = 0; }
      else if (v === 1) this.flags |= BOLD;
      else if (v === 2) this.flags |= DIM;
      else if (v === 3) this.flags |= ITALIC;
      else if (v === 4) this.flags |= UNDER;
      else if (v === 7) this.flags |= INVERSE;
      else if (v === 22) this.flags &= ~(BOLD | DIM);
      else if (v === 23) this.flags &= ~ITALIC;
      else if (v === 24) this.flags &= ~UNDER;
      else if (v === 27) this.flags &= ~INVERSE;
      else if (v >= 30 && v <= 37) this.fg = PALETTE[v - 30];
      else if (v >= 40 && v <= 47) this.bg = PALETTE[v - 40];
      else if (v >= 90 && v <= 97) this.fg = PALETTE[v - 90 + 8];
      else if (v >= 100 && v <= 107) this.bg = PALETTE[v - 100 + 8];
      else if (v === 39) this.fg = null;
      else if (v === 49) this.bg = null;
      else if (v === 38 || v === 48) {
        var color = null;
        if (p[i + 1] === 5) { color = PALETTE[p[i + 2]] || null; i += 2; }
        else if (p[i + 1] === 2) {
          color = 'rgb(' + (p[i + 2] | 0) + ',' + (p[i + 3] | 0) + ',' + (p[i + 4] | 0) + ')';
          i += 4;
        }
        if (v === 38) this.fg = color; else this.bg = color;
      }
    }
  };

  // ---------------------------------------------------------- renderizacao
  function esc(s) {
    return s.replace(/[&<>]/g, function (c) {
      return c === '&' ? '&amp;' : (c === '<' ? '&lt;' : '&gt;');
    });
  }

  function styleOf(c) {
    var fg = c.f, bg = c.b, st = '';
    if (c.l & INVERSE) { var t = fg; fg = bg || '#c9d3de'; bg = t || '#0a0d11'; }
    if (fg) st += 'color:' + fg + ';';
    if (bg) st += 'background:' + bg + ';';
    if (c.l & BOLD) st += 'font-weight:700;';
    if (c.l & DIM) st += 'opacity:.65;';
    if (c.l & ITALIC) st += 'font-style:italic;';
    if (c.l & UNDER) st += 'text-decoration:underline;';
    return st;
  }

  function sigOf(c) { return (c.f || '') + '|' + (c.b || '') + '|' + c.l; }

  // Agrupa celulas consecutivas de mesmo estilo num unico span: uma linha de 200
  // colunas costuma virar 3 ou 4 elementos.
  function renderLine(line, cursorX) {
    var html = '', run = '', sig = null, style = '', i;
    function flush() {
      if (!run) return;
      html += style ? '<span style="' + style + '">' + esc(run) + '</span>' : esc(run);
      run = '';
    }
    for (i = 0; i < line.length; i++) {
      var c = line[i];
      if (i === cursorX) {
        flush();
        html += '<span class="cur" style="' + styleOf(c) + '">' + esc(c.c || ' ') + '</span>';
        sig = null;
        continue;
      }
      var s = sigOf(c);
      if (s !== sig) { flush(); sig = s; style = styleOf(c); }
      run += c.c;
    }
    flush();
    return html || '&nbsp;';
  }

  Term.prototype.render = function () {
    var out = [], showCursor = this.cursorVisible && this.focused;
    // Na tela alternativa (htop, vi) o historico some, como num terminal de verdade:
    // deixa-lo visivel empurraria a tela cheia para fora da area util.
    if (this.scrollEl && this.scrollEl.style) {
      this.scrollEl.style.display = this.alt ? 'none' : '';
    }
    for (var i = 0; i < this.rows; i++) {
      var cx = (showCursor && i === this.y) ? Math.min(this.x, this.cols - 1) : -1;
      out.push('<div class="tl">' + renderLine(this.lines[i], cx) + '</div>');
    }
    this.screenEl.innerHTML = out.join('');
  };

  // O emulador acima nao depende de DOM nem de rede: exportado assim, da para
  // exercita-lo com a saida real de um htop/vim sem abrir navegador (test/terminal-emulator.js).
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { Term: Term, renderLine: renderLine, PALETTE: PALETTE };
  }

  // ------------------------------------------------------------- transporte
  if (typeof document === 'undefined') return;
  var el = document.getElementById('term');
  if (!el) return;

  var CSRF = el.dataset.csrf;
  var URLS = {
    open: el.dataset.openUrl,
    api: el.dataset.apiBase, // /api/term/<id>/...
  };

  var screenEl = document.getElementById('term-screen');
  var scrollEl = document.getElementById('term-scrollback');
  var viewEl = document.getElementById('term-view');
  var inputEl = document.getElementById('term-input');
  var statusEl = document.getElementById('term-status');
  var sizeEl = document.getElementById('term-size');

  var term = new Term(screenEl, scrollEl);
  var decoder = new TextDecoder('utf-8');
  var sessionId = null, offset = 0, running = false, outQueue = '', sending = false;

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = 'badge ' + (cls || 'cold');
  }

  function jsonHeaders() {
    return { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF };
  }

  function b64bytes(b64) {
    var bin = atob(b64), out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function send(data) {
    if (!sessionId || !data) return;
    outQueue += data;
    flushKeys();
  }
  term.reply = send;

  function flushKeys() {
    if (sending || !outQueue || !sessionId) return;
    sending = true;
    var data = outQueue;
    outQueue = '';
    fetch(URLS.api + sessionId + '/keys', {
      method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ data: data })
    }).then(function (r) {
      if (!r.ok) throw new Error('http ' + r.status);
    }).catch(function () {
      outQueue = data + outQueue;   // devolve a ordem original na proxima tentativa
    }).finally(function () {
      sending = false;
      if (outQueue) setTimeout(flushKeys, 120);
    });
  }

  function measure() {
    var probe = document.createElement('div');
    probe.className = 'tl';
    probe.style.position = 'absolute';
    probe.style.visibility = 'hidden';
    probe.textContent = 'W'.repeat(50);
    screenEl.appendChild(probe);
    var rect = probe.getBoundingClientRect();
    var cw = rect.width / 50, ch = rect.height;
    screenEl.removeChild(probe);
    if (!cw || !ch) return { cols: 80, rows: 24 };
    var box = viewEl.getBoundingClientRect();
    return {
      cols: Math.max(20, Math.min(400, Math.floor((box.width - 16) / cw))),
      rows: Math.max(5, Math.min(150, Math.floor((box.height - 12) / ch)))
    };
  }

  function atBottom() {
    return viewEl.scrollHeight - viewEl.scrollTop - viewEl.clientHeight < 40;
  }

  function scrollToBottom() { viewEl.scrollTop = viewEl.scrollHeight; }

  async function pump() {
    var backoff = 0;
    while (running && sessionId) {
      try {
        var res = await fetch(URLS.api + sessionId + '/read?offset=' + offset,
          { headers: { 'Accept': 'application/json' } });
        if (res.status === 404) { finish('sessao expirada'); return; }
        if (!res.ok) throw new Error('http ' + res.status);
        var data = await res.json();
        offset = data.offset;
        if (data.data) {
          var stick = atBottom();
          if (data.lost) term.write('\r\n[painel: saida antiga descartada]\r\n');
          term.write(decoder.decode(b64bytes(data.data), { stream: true }));
          if (stick) scrollToBottom();
        }
        if (!data.alive) {
          finish('encerrado' + (data.exit_code === null ? '' : ' (exit ' + data.exit_code + ')'));
          return;
        }
        backoff = 0;
      } catch (err) {
        if (!running) return;
        backoff = Math.min(5000, backoff + 750);
        setStatus('reconectando...', 'cold');
        await new Promise(function (r) { setTimeout(r, backoff); });
      }
    }
  }

  function finish(msg) {
    running = false;
    setStatus(msg, 'off');
    term.focused = false;
    term.render();
    document.getElementById('term-reconnect').hidden = false;
  }

  async function open() {
    var size = measure();
    term.resize(size.cols, size.rows);
    sizeEl.textContent = size.cols + 'x' + size.rows;
    setStatus('conectando...', 'cold');
    try {
      var res = await fetch(URLS.open, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ cols: size.cols, rows: size.rows })
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok) { setStatus(data.error || ('erro http ' + res.status), 'off'); document.getElementById('term-reconnect').hidden = false; return; }
      sessionId = data.id;
      offset = data.offset || 0;
      running = true;
      document.getElementById('term-reconnect').hidden = true;
      setStatus('conectado', 'on');
      inputEl.focus();
      pump();
    } catch (err) {
      setStatus('falha ao abrir: ' + err.message, 'off');
      document.getElementById('term-reconnect').hidden = false;
    }
  }

  function closeSession(keepalive) {
    if (!sessionId) return;
    var id = sessionId;
    sessionId = null; running = false;
    fetch(URLS.api + id + '/close', {
      method: 'POST', headers: jsonHeaders(), keepalive: !!keepalive
    }).catch(function () {});
  }

  // ------------------------------------------------------------- teclado
  var CTRL_KEYS = {
    Enter: '\r', Tab: '\t', Backspace: '\x7f', Escape: '\x1b',
    Delete: '\x1b[3~', Insert: '\x1b[2~', PageUp: '\x1b[5~', PageDown: '\x1b[6~'
  };
  var FN = {
    F1: '\x1bOP', F2: '\x1bOQ', F3: '\x1bOR', F4: '\x1bOS', F5: '\x1b[15~',
    F6: '\x1b[17~', F7: '\x1b[18~', F8: '\x1b[19~', F9: '\x1b[20~',
    F10: '\x1b[21~', F11: '\x1b[23~', F12: '\x1b[24~'
  };

  function arrow(key) {
    var letter = { ArrowUp: 'A', ArrowDown: 'B', ArrowRight: 'C', ArrowLeft: 'D', Home: 'H', End: 'F' }[key];
    if (!letter) return null;
    return (term.appCursor ? '\x1bO' : '\x1b[') + letter;
  }

  inputEl.addEventListener('keydown', function (ev) {
    if (!sessionId) return;
    var key = ev.key;

    // Ctrl+C com texto selecionado copia (como no xterm); sem selecao vira SIGINT.
    if ((ev.ctrlKey || ev.metaKey) && (key === 'c' || key === 'C') && !window.getSelection().isCollapsed) return;
    if ((ev.ctrlKey || ev.metaKey) && (key === 'v' || key === 'V')) return;  // deixa o evento paste
    if (ev.altKey && key.length === 1) { ev.preventDefault(); send('\x1b' + key); return; }

    var seq = arrow(key) || CTRL_KEYS[key] || FN[key];
    if (seq) { ev.preventDefault(); send(seq); return; }

    if (ev.ctrlKey && key.length === 1) {
      var code = key.toUpperCase().charCodeAt(0);
      if (code >= 64 && code <= 95) { ev.preventDefault(); send(String.fromCharCode(code - 64)); return; }
      if (key === ' ') { ev.preventDefault(); send('\x00'); return; }
    }
    if (!ev.ctrlKey && !ev.metaKey && key.length === 1) {
      ev.preventDefault();
      send(key);
      scrollToBottom();
    }
  });

  inputEl.addEventListener('paste', function (ev) {
    if (!sessionId) return;
    ev.preventDefault();
    var text = (ev.clipboardData || window.clipboardData).getData('text').replace(/\r?\n/g, '\r');
    send(term.bracketedPaste ? '\x1b[200~' + text + '\x1b[201~' : text);
  });

  inputEl.addEventListener('focus', function () { term.focused = true; term.render(); });
  inputEl.addEventListener('blur', function () { term.focused = false; term.render(); });
  viewEl.addEventListener('mouseup', function () {
    // Clicar para focar sem atrapalhar quem esta selecionando texto para copiar.
    if (window.getSelection().isCollapsed) inputEl.focus();
  });

  // ------------------------------------------------------- barra de acoes
  // Botoes Ctrl+X da barra: data-ctrl="C" vira o byte 0x03, como faria o teclado.
  document.querySelectorAll('[data-ctrl]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      send(String.fromCharCode(btn.dataset.ctrl.toUpperCase().charCodeAt(0) - 64));
      inputEl.focus();
    });
  });
  // Teclas que o teclado virtual do celular simplesmente nao tem. Sem esta fileira,
  // vim, htop e qualquer menu curses sao inoperaveis no telefone: nao ha Esc, nao ha
  // Tab e nao ha setas. Cada botao manda a MESMA sequencia que o teclado fisico
  // mandaria, entao nada aqui e um caminho paralelo ao do keydown.
  var SEQUENCIAS = {
    Escape: '\x1b',
    Tab: '\t',
    ArrowUp: function () { return term.appCursor ? '\x1bOA' : '\x1b[A'; },
    ArrowDown: function () { return term.appCursor ? '\x1bOB' : '\x1b[B'; },
    ArrowRight: function () { return term.appCursor ? '\x1bOC' : '\x1b[C'; },
    ArrowLeft: function () { return term.appCursor ? '\x1bOD' : '\x1b[D'; },
    Home: '\x1b[H',
    End: '\x1b[F',
    PageUp: '\x1b[5~',
    PageDown: '\x1b[6~',
    Pipe: '|',
    Barra: '/',
    Til: '~',
  };
  document.querySelectorAll('[data-tecla]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var seq = SEQUENCIAS[btn.dataset.tecla];
      if (!seq) return;
      send(typeof seq === 'function' ? seq() : seq);
      inputEl.focus();
    });
  });

  // No celular o teclado so aparece se um campo receber foco por um gesto do usuario.
  var tecladoBtn = document.getElementById('term-teclado');
  if (tecladoBtn) {
    tecladoBtn.addEventListener('click', function () { inputEl.focus(); });
  }

  document.getElementById('term-clear').addEventListener('click', function () {
    scrollEl.innerHTML = '';
    send('\x0c');  // Ctrl+L: deixa o shell redesenhar o prompt
    inputEl.focus();
  });
  document.getElementById('term-reconnect').addEventListener('click', function () {
    term.reset(true);
    open();
  });
  var fsBtn = document.getElementById('term-fullscreen');
  fsBtn.addEventListener('click', function () {
    el.classList.toggle('full');
    fsBtn.textContent = el.classList.contains('full') ? 'Sair da tela cheia' : 'Tela cheia';
    setTimeout(applyResize, 60);
    inputEl.focus();
  });

  // ------------------------------------------------------------ dimensoes
  var resizeTimer = null;
  function applyResize() {
    var size = measure();
    if (size.cols === term.cols && size.rows === term.rows) return;
    term.resize(size.cols, size.rows);
    sizeEl.textContent = size.cols + 'x' + size.rows;
    if (!sessionId) return;
    fetch(URLS.api + sessionId + '/resize', {
      method: 'POST', headers: jsonHeaders(),
      body: JSON.stringify({ cols: size.cols, rows: size.rows })
    }).catch(function () {});
  }
  function agendarResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(applyResize, 200);
  }
  window.addEventListener('resize', agendarResize);
  // No celular, abrir o teclado nao dispara 'resize' da janela em todo navegador —
  // quem encolhe e a viewport visual. Sem isto o shell continua achando que tem 24
  // linhas enquanto metade da tela virou teclado.
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', agendarResize);
  }
  window.addEventListener('beforeunload', function () { closeSession(true); });
  document.getElementById('term-close').addEventListener('click', function () {
    closeSession(false);
    finish('sessao fechada');
  });

  open();
})();
