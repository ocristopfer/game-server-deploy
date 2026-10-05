/* Core - cadence.
 *
 * Six panel screens did the same thing by hand: setInterval, an `if
 * (document.hidden) return`, a silent try/catch and a visibilitychange listener
 * to fetch on return. Each copy had one detail fewer than the previous one - one
 * kept spending SSH with the tab hidden, another did not back off when the panel went down.
 *
 * Here that is a single piece, with one responsibility: deciding WHEN the task runs.
 * The caller passes the task and knows nothing about timers - which is why this
 * implementation can be swapped (for SSE, for example) without touching any feature.
 */

const MAX_BACKOFF = 4;   // 4 skipped rounds is the ceiling of the failure penalty

export class Poller {
  /**
   * @param {() => Promise<void>} task  what to run each round; let the error bubble up
   *                                    so the backoff kicks in
   * @param {object}   options
   * @param {number}   options.interval   milliseconds between rounds
   * @param {boolean}  options.onReturn   fetch right away when the tab reappears
   * @param {Function} options.onError    called with the error of each round that failed
   */
  constructor(task, { interval = 10000, onReturn = true, onError = null } = {}) {
    this.task = task;
    this.interval = interval;
    this.onReturn = onReturn;
    this.onError = onError;
    this.timer = null;
    this.running = false;   // reentrancy lock: a slow round does not pile onto the next one
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

  /* Runs the task now, if it is its time.
   *
   * A hidden tab does not waste an SSH connection for nothing. After a failure, the
   * following rounds are skipped in growing numbers: with the panel down, ten open
   * tabs stop hitting it every three seconds each. */
  async now() {
    if (this.running || document.hidden) return;
    if (this.failures && this.skipped < Math.min(this.failures, MAX_BACKOFF)) {
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
