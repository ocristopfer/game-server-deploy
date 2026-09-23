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
let convite = null;
const ouvintes = new Set();

window.addEventListener('beforeinstallprompt', (ev) => {
  ev.preventDefault();          // sem isto o Chrome mostra a propria barrinha
  convite = ev;
  ouvintes.forEach((f) => f(true));
});

window.addEventListener('appinstalled', () => {
  convite = null;
  ouvintes.forEach((f) => f(false));
});

const instalado = () => window.matchMedia('(display-mode: standalone)').matches ||
  window.navigator.standalone === true;

export const installButton = {
  selector: '[data-install]',
  mount(botao) {
    if (instalado()) return;

    const refresh = (disponivel) => { botao.hidden = !disponivel; };
    ouvintes.add(refresh);
    refresh(Boolean(convite));

    botao.addEventListener('click', async () => {
      if (!convite) return;
      botao.hidden = true;
      convite.prompt();
      await convite.userChoice;
      convite = null;      // o evento e de uso unico
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
    const jaTinhaControlador = Boolean(navigator.serviceWorker.controller);

    navigator.serviceWorker.register(el.dataset.sw, { scope: '/' })
      .then((reg) => {
        if (reg.waiting && jaTinhaControlador) avisarVersaoNova(reg);
        reg.addEventListener('updatefound', () => {
          const novo = reg.installing;
          if (!novo) return;
          novo.addEventListener('statechange', () => {
            // "installed" com um controlador ja no ar = versao nova esperando.
            if (novo.state === 'installed' && navigator.serviceWorker.controller) {
              avisarVersaoNova(reg);
            }
          });
        });
      })
      .catch((err) => console.debug('service worker nao registrou', err));

    let recarregando = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!jaTinhaControlador || recarregando) return;
      recarregando = true;
      window.location.reload();
    });
  },
};

/* Mostra a faixa de "ha uma versao nova". Quem troca e o clique: o worker que esta
 * esperando recebe a ordem de assumir, sai do "waiting", e o controllerchange logo
 * em seguida recarrega a pagina ja com o casco novo. */
function avisarVersaoNova(reg) {
  const notice = $('[data-new-version]');
  if (!notice?.hidden) return;   // ausente, ou ja avisado: nao empilha ouvinte de clique
  notice.hidden = false;
  notice.querySelector('button')?.addEventListener('click', () => {
    reg.waiting?.postMessage({ tipo: 'assumir' });
  });
}
