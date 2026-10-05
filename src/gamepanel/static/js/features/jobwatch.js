/* Follows an action that is still running.
 *
 * The action screen and the console screen had the same routine written twice, with
 * slightly different texts and intervals. Here it is a single one: what changes between the
 * two screens comes through data-* (the "running" message and the completion one).
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const STATE_CLASS = { ok: 'on', error: 'off', running: 'cold' };

export const watchJob = {
  selector: '[data-job-url]',
  mount(root) {
    const url = root.dataset.jobUrl;
    const output = $('[data-job-output]', root);
    const badge = $('[data-job-badge]', root);
    const hint = $('[data-job-hint]', root);
    if (!url || !output) return;

    const running = root.dataset.jobRunning || '(executando...)';
    const template = root.dataset.jobEnd || 'exit code {codigo}';

    const poller = new Poller(async () => {
      const data = await readJSON(url);
      output.textContent = data.output || running;
      if (badge) {
        badge.textContent = data.status;
        badge.className = `badge ${STATE_CLASS[data.status] || ''}`;
      }
      if (data.status === 'running') return;

      poller.stop();
      if (hint) {
        hint.textContent = template.replace(
          '{codigo}', data.exit_code === null ? '—' : data.exit_code,
        );
      }
    }, { interval: Number(root.dataset.interval) || 1500 });

    poller.start({ immediate: false });
  },
};
