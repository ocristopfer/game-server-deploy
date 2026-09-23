/* Nucleo — cadencia.
 *
 * Seis telas do painel faziam a mesma coisa a mao: setInterval, um `if
 * (document.hidden) return`, um try/catch mudo e um ouvinte de visibilitychange
 * para puxar na volta. Cada copia tinha um detalhe a menos que a anterior — uma
 * seguia gastando SSH com a aba escondida, outra nao recuava quando o painel caia.
 *
 * Aqui isso e uma peca so, com uma responsabilidade: decidir QUANDO a tarefa roda.
 * Quem usa passa a tarefa e nao sabe nada sobre temporizadores — e por isso da para
 * trocar esta implementacao (por SSE, por exemplo) sem tocar em nenhuma feature.
 */

const RECUO_MAX = 4;   // 4 voltas puladas e o teto do castigo por falha

export class Poller {
  /**
   * @param {() => Promise<void>} tarefa  o que rodar a cada volta; deixe o erro subir
   *                                      para o recuo entrar em acao
   * @param {object}   opcoes
   * @param {number}   opcoes.intervalo   milissegundos entre voltas
   * @param {boolean}  opcoes.aoVoltar    puxar na hora quando a aba reaparece
   * @param {Function} opcoes.aoErro      chamado com o erro de cada volta que falhou
   */
  constructor(task, { interval = 10000, onReturn = true, onError = null } = {}) {
    this.task = task;
    this.interval = interval;
    this.onReturn = onReturn;
    this.onError = onError;
    this.timer = null;
    this.running = false;   // trava de reentrada: volta lenta nao empilha sobre a proxima
    this.failures = 0;
    this.skipped = 0;
    this._onVisibilityChange = () => {
      if (!document.hidden && this.timer && this.onReturn) this.now();
    };
  }

  get active() { return this.timer !== null; }

  start({ immediate = true } = {}) {
    if (this.timer) return this;
    this.timer = setInterval(() => this.now(), this.interval);
    document.addEventListener('visibilitychange', this._onVisibilityChange);
    if (immediate) this.now();
    return this;
  }

  stop() {
    if (!this.timer) return this;
    clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener('visibilitychange', this._onVisibilityChange);
    return this;
  }

  toggle() { return this.active ? this.stop() : this.start(); }

  /* Roda a tarefa agora, se for a hora dela.
   *
   * Aba escondida nao gasta conexao SSH a toa. Depois de uma falha, as voltas
   * seguintes sao puladas em numero crescente: com o painel fora do ar, dez abas
   * abertas deixam de bater nele de tres em tres segundos cada uma. */
  async now() {
    if (this.running || document.hidden) return;
    if (this.failures && this.skipped < Math.min(this.failures, RECUO_MAX)) {
      this.skipped += 1;
      return;
    }
    this.running = true;
    try {
      await this.task();
      this.failures = 0;
      this.skipped = 0;
    } catch (err) {
      this.failures += 1;
      this.skipped = 0;
      if (this.onError) this.onError(err);
      else console.debug('volta falhou, tentando de novo', err);
    } finally {
      this.running = false;
    }
  }
}
