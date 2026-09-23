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
  mount(raiz) {
    const url = raiz.dataset.jobUrl;
    const output = $('[data-job-output]', raiz);
    const selo = $('[data-job-badge]', raiz);
    const dica = $('[data-job-hint]', raiz);
    if (!url || !output) return;

    const rodando = raiz.dataset.jobRunning || '(executando...)';
    const molde = raiz.dataset.jobEnd || 'exit code {codigo}';

    const poller = new Poller(async () => {
      const data = await readJSON(url);
      output.textContent = data.output || rodando;
      if (selo) {
        selo.textContent = data.status;
        selo.className = `badge ${CLASSE_DE_ESTADO[data.status] || ''}`;
      }
      if (data.status === 'running') return;

      poller.parar();
      if (dica) {
        dica.textContent = molde.replace(
          '{codigo}', data.exit_code === null ? '—' : data.exit_code,
        );
      }
    }, { interval: Number(raiz.dataset.interval) || 1500 });

    poller.iniciar({ imediato: false });
  },
};
