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
  constructor(tarefa, { intervalo = 10000, aoVoltar = true, aoErro = null } = {}) {
    this.tarefa = tarefa;
    this.intervalo = intervalo;
    this.aoVoltar = aoVoltar;
    this.aoErro = aoErro;
    this.timer = null;
    this.rodando = false;   // trava de reentrada: volta lenta nao empilha sobre a proxima
    this.falhas = 0;
    this.puladas = 0;
    this._aoMudarVisibilidade = () => {
      if (!document.hidden && this.timer && this.aoVoltar) this.agora();
    };
  }

  get ativo() { return this.timer !== null; }

  iniciar({ imediato = true } = {}) {
    if (this.timer) return this;
    this.timer = setInterval(() => this.agora(), this.intervalo);
    document.addEventListener('visibilitychange', this._aoMudarVisibilidade);
    if (imediato) this.agora();
    return this;
  }

  parar() {
    if (!this.timer) return this;
    clearInterval(this.timer);
    this.timer = null;
    document.removeEventListener('visibilitychange', this._aoMudarVisibilidade);
    return this;
  }

  alternar() { return this.ativo ? this.parar() : this.iniciar(); }

  /* Roda a tarefa agora, se for a hora dela.
   *
   * Aba escondida nao gasta conexao SSH a toa. Depois de uma falha, as voltas
   * seguintes sao puladas em numero crescente: com o painel fora do ar, dez abas
   * abertas deixam de bater nele de tres em tres segundos cada uma. */
  async agora() {
    if (this.rodando || document.hidden) return;
    if (this.falhas && this.puladas < Math.min(this.falhas, RECUO_MAX)) {
      this.puladas += 1;
      return;
    }
    this.rodando = true;
    try {
      await this.tarefa();
      this.falhas = 0;
      this.puladas = 0;
    } catch (err) {
      this.falhas += 1;
      this.puladas = 0;
      if (this.aoErro) this.aoErro(err);
      else console.debug('volta falhou, tentando de novo', err);
    } finally {
      this.rodando = false;
    }
  }
}
