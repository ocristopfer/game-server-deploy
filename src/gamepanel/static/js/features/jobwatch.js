/* Acompanha uma acao que ainda esta rodando.
 *
 * A tela da acao e a do console tinham a mesma rotina escrita duas vezes, com
 * textos e intervalos levemente diferentes. Aqui ela e uma so: o que muda entre as
 * duas telas vem por data-* (a mensagem de "em execucao" e a de conclusao).
 */
import { Poller } from '../core/poll.js';
import { lerJSON } from '../core/http.js';
import { $ } from '../core/dom.js';

const CLASSE_DE_ESTADO = { ok: 'on', error: 'off', running: 'cold' };

export const acompanharJob = {
  seletor: '[data-job-url]',
  montar(raiz) {
    const url = raiz.dataset.jobUrl;
    const saida = $('[data-job-saida]', raiz);
    const selo = $('[data-job-selo]', raiz);
    const dica = $('[data-job-dica]', raiz);
    if (!url || !saida) return;

    const rodando = raiz.dataset.jobRodando || '(executando...)';
    const molde = raiz.dataset.jobFim || 'exit code {codigo}';

    const poller = new Poller(async () => {
      const data = await lerJSON(url);
      saida.textContent = data.output || rodando;
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
    }, { intervalo: Number(raiz.dataset.intervalo) || 1500 });

    poller.iniciar({ imediato: false });
  },
};
