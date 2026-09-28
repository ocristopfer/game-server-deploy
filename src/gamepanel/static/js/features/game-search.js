/* Busca de jogo (nome ou App ID) no formulario "Adicionar jogo".
 *
 * Tres respostas, nesta ordem:
 * 1. o jogo JA esta no catalogo (curado ou adicionado antes): nao ha o que preencher, e o
 *    atalho e criar a instancia. A lista vem na propria pagina (data-catalog), sem pedido.
 *    Era o buraco do V Rising: ele e curado, e a busca dizia "nada encontrado".
 * 2. sugestoes das duas listas do repositorio (LinuxGSM e a curadoria do painel), pela API.
 *    O painel nao vai a internet; clicar preenche os campos, e o broker valida no envio.
 * 3. nada: links para o NAVEGADOR procurar o App ID (SteamDB) e as portas. Quem abre e a
 *    pessoa, nunca o painel - continua sem SSRF e sem dependencia de terceiro.
 *
 * Texto de tela vem do template (data-msg-*), que ja passou pelo i18n: escrito aqui ele sairia
 * em portugues na tela em ingles.
 *
 * Nasce escondido: sem JavaScript nao ha o que fazer, e o formulario continua completo.
 */
import { readJSON } from '../core/http.js';
import { createEl, reset, fillForm } from '../core/dom.js';

const DEBOUNCE_MS = 250;
const STEAMDB_SEARCH = 'https://steamdb.info/search/?a=app&q=';
const WEB_SEARCH = 'https://duckduckgo.com/?q=';

/* O mesmo `_normalize` da busca do servidor: sem acento, minusculo, so letras e numeros. */
const normalize = (text) => String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '')
  .toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

const readCatalog = (raw) => {
  try { return JSON.parse(raw || '[]'); } catch { return []; }
};

export const gameSearch = {
  selector: '[data-game-search]',
  mount(block) {
    const field = block.querySelector('[data-search-field]');
    const list = block.querySelector('[data-search-results]');
    const form = block.closest('form');
    if (!field || !list || !form) return;
    block.hidden = false;

    const msg = block.dataset;
    const catalog = readCatalog(msg.catalog).map((game) => ({
      ...game, text: normalize(`${game.name} ${game.key}`),
    }));
    let waitId = null;
    let request = 0;

    const show = (children) => reset(list, children);
    const small = (text) => createEl('p', { className: 'muted small', text });
    const link = (text, href) => createEl('a', {
      className: 'btn btn--ghost btn--sm', text,
      attrs: { href, target: '_blank', rel: 'noopener noreferrer' },
    });

    const choose = (found) => {
      fillForm(form, found.values);
      const notice = createEl('p', { className: 'flash ok', text: `${found.name}: ${msg.msgFilled}` });
      // `warnings`, que e o que a API manda. Com o nome antigo (`avisos`) o `.map` estourava
      // DEPOIS de preencher os campos: a tela ficava sem o aviso de conferir e sem os
      // avisos da sugestao (porta presumida, argumento cortado), e sem erro nenhum a vista.
      show([notice, ...(found.warnings || []).map(small)]);
    };

    const inCatalog = (text) => {
      const terms = normalize(text).split(' ').filter(Boolean);
      if (!terms.length) return [];
      if (/^\d+$/.test(text)) return catalog.filter((g) => String(g.app_id) === text);
      return catalog.filter((g) => terms.every((t) => g.text.includes(t)));
    };

    const catalogRow = (game) => {
      const row = createEl('div', { className: 'cluster' });
      row.append(createEl('span', { text: `${game.name} · ${msg.msgInCatalog}` }));
      if (game.creatable) {
        row.append(createEl('a', {
          className: 'btn btn--primary btn--sm', text: msg.msgCreateInstance,
          attrs: { href: `${msg.instancesUrl}?game=${encodeURIComponent(game.key)}` },
        }));
      }
      return row;
    };

    const suggestionButton = (found) => {
      const button = createEl('button', {
        className: 'btn btn--ghost btn--sm',
        text: `${found.name} · app ${found.appid} · ${found.source}`,
        attrs: { type: 'button' },
      });
      button.addEventListener('click', () => choose(found));
      return button;
    };

    const nothingFound = (text) => {
      const links = createEl('div', { className: 'cluster' });
      links.append(
        link(msg.msgSteamdb, `${STEAMDB_SEARCH}${encodeURIComponent(`${text} dedicated server`)}`),
        link(msg.msgWebPorts, `${WEB_SEARCH}${encodeURIComponent(`${text} dedicated server ports`)}`),
      );
      return [small(msg.msgNone), links];
    };

    const search = async () => {
      const text = field.value.trim();
      if (!text) { show([]); return; }
      const self = ++request;
      const known = inCatalog(text).map(catalogRow);
      try {
        const data = await readJSON(`${block.dataset.url}?q=${encodeURIComponent(text)}`);
        if (self !== request) return; // chegou depois de uma consulta mais nova: descarta
        // O que ja esta no catalogo nao aparece de novo como sugestao: adicionar outra vez
        // criaria um segundo jogo com o mesmo App ID, ou sobreporia o curado.
        const appids = new Set(catalog.map((g) => String(g.app_id)));
        const fresh = data.resultados.filter((found) => !appids.has(String(found.appid)));
        if (!known.length && !fresh.length) { show(nothingFound(text)); return; }
        show([...known, ...fresh.map(suggestionButton)]);
      } catch (failure) {
        if (self === request) show([...known, small(`${msg.msgFailed} ${failure.message}`)]);
      }
    };

    field.addEventListener('input', () => {
      clearTimeout(waitId);
      waitId = setTimeout(search, DEBOUNCE_MS);
    });
    // Enter dentro do campo enviaria o formulario inteiro (e criaria um jogo pela metade).
    field.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      clearTimeout(waitId);
      search();
    });
  },
};
