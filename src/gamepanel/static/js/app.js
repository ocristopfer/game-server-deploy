/* Panel entry point.
 *
 * There is no screen logic here at all: this file only knows the features'
 * CONTRACT - each one exports `{ selector, mount(el) }` - and binds them to the
 * elements the page actually brought.
 *
 * What this buys:
 *
 *   - a screen "asks" for a behavior by putting the matching data-* in the
 *     markup; there is no more loose <script> inside a template;
 *   - a new feature comes in without anything here needing to know what it does;
 *   - a feature that breaks does not take down the others (each mount is isolated).
 *
 * The terminal is the only deliberate exception: it is 28 KB of VT100 emulator that only
 * the terminal screen loads, in its own <script type="module">.
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
import { themeToggle } from './features/theme.js';

export const FEATURES = [
  // structure
  dropdownMenu, confirmAction, copyToClipboard, offlineWorker, installButton, themeToggle,
  // live reading
  initialBars, panelMeters, serverMeters,
  panelPlayers, serverPlayers, followLog, watchJob,
  // forms
  fileEditor, configFilter, moreConfigRows, dirtyConfig, commandBox, gameTemplate, gameSearch,
  passkeyLogin, passkeyRegister,
  // visualization
  chart,
];

export function mountAll(root = document) {
  FEATURES.forEach((feature) => {
    $$(feature.selector, root).forEach((el) => {
      try {
        feature.mount(el);
      } catch (err) {
        // A broken feature must not take the others along: the panel controls
        // real servers, and a half-alive screen is worth more than a blank one.
        console.error(`feature "${feature.selector}" falhou ao mount`, err);
      }
    });
  });
}

mountAll();
