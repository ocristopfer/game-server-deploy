/* Instalacao e atualizacao do aplicativo.
 *
 * Duas coisas separadas moram aqui porque as duas sao a mesma conversa com o
 * usuario ("este painel e um aplicativo"):
 *
 *   1. registrar o service worker e avisar quando ha uma versao nova;
 *   2. oferecer o "Instalar" quando o navegador disser que da.
 *
 * O painel funciona inteiro sem nada disto: o botao nasce escondido e so aparece se
 * o navegador oferecer a instalacao.
 */
import { $ } from '../core/dom.js';

/* Guarda o evento que o Chrome dispara quando a instalacao esta disponivel. Ele so
 * pode ser usado UMA vez e nao pode ser pedido do nada — por isso e capturado aqui,
 * no topo do modulo, antes de qualquer tela mount. */
let invite = null;
const listeners = new Set();

window.addEventListener('beforeinstallprompt', (ev) => {
  ev.preventDefault();          // sem isto o Chrome mostra a propria barrinha
  invite = ev;
  listeners.forEach((f) => f(true));
});

window.addEventListener('appinstalled', () => {
  invite = null;
  listeners.forEach((f) => f(false));
});

const installed = () => window.matchMedia('(display-mode: standalone)').matches ||
  window.navigator.standalone === true;

export const installButton = {
  selector: '[data-install]',
  mount(button) {
    if (installed()) return;

    const refresh = (available) => { button.hidden = !available; };
    listeners.add(refresh);
    refresh(Boolean(invite));

    button.addEventListener('click', async () => {
      if (!invite) return;
      button.hidden = true;
      invite.prompt();
      await invite.userChoice;
      invite = null;      // o evento e de uso unico
    });
  },
};

/* Registro do service worker.
 *
 * A URL vem do HTML (data-sw) porque so o servidor sabe onde ele mora; o escopo e a
 * raiz, senao o worker so enxergaria /static/. */
export const offlineWorker = {
  selector: '[data-sw]',
  mount(el) {
    if (!('serviceWorker' in navigator)) return;

    // Guardado ANTES do registro: e o que separa "primeira instalacao" de
    // "chegou versao nova". Na primeira, o worker assume o controle desta pagina
    // (clients.claim) e isso dispara um controllerchange que NAO pode virar reload —
    // era o bastante para a tela se recarregar sozinha logo depois de abrir,
    // abortando no meio as leituras de medidores que ja estavam a caminho.
    const hadController = Boolean(navigator.serviceWorker.controller);

    navigator.serviceWorker.register(el.dataset.sw, { scope: '/' })
      .then((reg) => {
        if (reg.waiting && hadController) announceNewVersion(reg);
        reg.addEventListener('updatefound', () => {
          const novo = reg.installing;
          if (!novo) return;
          novo.addEventListener('statechange', () => {
            // "installed" com um controlador ja no ar = versao nova esperando.
            if (novo.state === 'installed' && navigator.serviceWorker.controller) {
              announceNewVersion(reg);
            }
          });
        });
      })
      .catch((err) => console.debug('service worker nao registrou', err));

    let reloading = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!hadController || reloading) return;
      reloading = true;
      window.location.reload();
    });
  },
};

/* Mostra a faixa de "ha uma versao nova". Quem troca e o clique: o worker que esta
 * esperando recebe a ordem de assumir, sai do "waiting", e o controllerchange logo
 * em seguida recarrega a pagina ja com o casco novo. */
function announceNewVersion(reg) {
  const notice = $('[data-new-version]');
  if (!notice?.hidden) return;   // ausente, ou ja avisado: nao empilha ouvinte de clique
  notice.hidden = false;
  notice.querySelector('button')?.addEventListener('click', () => {
    reg.waiting?.postMessage({ tipo: 'assumir' });
  });
}
