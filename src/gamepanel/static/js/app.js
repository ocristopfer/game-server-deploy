/* Ponto de entrada do painel.
 *
 * Aqui nao ha logica de tela nenhuma: este arquivo so conhece o CONTRATO das
 * features — cada uma exporta `{ selector, mount(el) }` — e as liga aos elementos
 * que a pagina de fato trouxe.
 *
 * O que isso compra:
 *
 *   - uma tela "pede" um comportamento colocando o data-* correspondente na
 *     marcacao; nao existe mais <script> solto dentro de template;
 *   - uma feature nova entra sem que nada aqui precise saber o que ela faz;
 *   - uma feature que quebra nao derruba as outras (cada montagem e isolada).
 *
 * O terminal e a unica excecao deliberada: sao 28 KB de emulador VT100 que so a
 * tela do terminal carrega, no seu proprio <script type="module">.
 */
import { $$ } from './core/dom.js';

import { dropdownMenu } from './features/menu.js';
import { confirmAction } from './features/confirm.js';
import { copyToClipboard } from './features/copy.js';
import { panelMeters, serverMeters, initialBars } from './features/metrics.js';
import { panelPlayers, serverPlayers } from './features/players.js';
import { followLog } from './features/logfeed.js';
import { watchJob } from './features/jobwatch.js';
import { fileEditor } from './features/fileeditor.js';
import { configFilter, moreConfigRows, dirtyConfig } from './features/configform.js';
import { commandBox } from './features/console.js';
import { chart } from './features/charts.js';
import { installButton, offlineWorker } from './features/pwa.js';
import { gameTemplate } from './features/game-template.js';
import { gameSearch } from './features/game-search.js';
import { passkeyLogin, passkeyRegister } from './features/passkey.js';

export const FEATURES = [
  // estrutura
  dropdownMenu, confirmAction, copyToClipboard, offlineWorker, installButton,
  // leitura ao vivo
  initialBars, panelMeters, serverMeters,
  panelPlayers, serverPlayers, followLog, watchJob,
  // formularios
  fileEditor, configFilter, moreConfigRows, dirtyConfig, commandBox, gameTemplate, gameSearch,
  passkeyLogin, passkeyRegister,
  // visualizacao
  chart,
];

export function mountAll(root = document) {
  FEATURES.forEach((feature) => {
    $$(feature.selector, root).forEach((el) => {
      try {
        feature.mount(el);
      } catch (err) {
        // Uma feature quebrada nao pode levar as outras junto: o painel controla
        // servidores de verdade, e uma tela meio viva vale mais que uma tela branca.
        console.error(`feature "${feature.selector}" falhou ao mount`, err);
      }
    });
  });
}

mountAll();
