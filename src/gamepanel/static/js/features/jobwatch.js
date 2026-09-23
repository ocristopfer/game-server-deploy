/* Acompanha uma acao que ainda esta rodando.
 *
 * A tela da acao e a do console tinham a mesma rotina escrita duas vezes, com
 * textos e intervalos levemente diferentes. Aqui ela e uma so: o que muda entre as
 * duas telas vem por data-* (a mensagem de "em execucao" e a de conclusao).
 */
import { Poller } from '../core/poll.js';
import { readJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const CLASSE_DE_ESTADO = { ok: 'on', error: 'off', running: 'cold' };

export const watchJob = {
  selector: '[data-job-url]',
  mount(root) {
    const url = root.dataset.jobUrl;
    const output = $('[data-job-output]', root);
    const selo = $('[data-job-badge]', root);
    const dica = $('[data-job-hint]', root);
    if (!url || !output) return;

    const running = root.dataset.jobRunning || '(executando...)';
    const molde = root.dataset.jobEnd || 'exit code {codigo}';

    const poller = new Poller(async () => {
      const data = await readJSON(url);
      output.textContent = data.output || running;
      if (selo) {
        selo.textContent = data.status;
        selo.className = `badge ${CLASSE_DE_ESTADO[data.status] || ''}`;
      }
      if (data.status === 'running') return;

      poller.stop();
      if (dica) {
        dica.textContent = molde.replace(
          '{codigo}', data.exit_code === null ? '—' : data.exit_code,
        );
      }
    }, { interval: Number(root.dataset.interval) || 1500 });

    poller.start({ immediate: false });
  },
};
