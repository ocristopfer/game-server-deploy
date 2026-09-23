/* Acompanha uma acao que ainda esta rodando.
 *
 * A tela da acao e a do console tinham a mesma rotina escrita duas vezes, com
 * textos e intervalos levemente diferentes. Aqui ela e uma so: o que muda entre as
 * duas telas vem por data-* (a mensagem de "em execucao" e a de conclusao).
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
