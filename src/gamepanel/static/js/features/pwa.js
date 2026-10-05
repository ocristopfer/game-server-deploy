/* App installation and update.
 *
 * Two separate things live here because both are the same conversation with the
 * user ("this panel is an app"):
 *
 *   1. registering the service worker and announcing when there is a new version;
 *   2. offering "Install" when the browser says it can.
 *
 * The panel works fully without any of this: the button is born hidden and only shows up if
 * the browser offers the installation.
 */
import { $ } from '../core/dom.js';

/* Keeps the event Chrome fires when installation is available. It can only
 * be used ONCE and cannot be requested out of nowhere - which is why it is captured here,
 * at the top of the module, before any screen mounts. */
let invite = null;
const listeners = new Set();

window.addEventListener('beforeinstallprompt', (ev) => {
  ev.preventDefault();          // without this Chrome shows its own little bar
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
      invite = null;      // the event is single-use
    });
  },
};

/* Service worker registration.
 *
 * The URL comes from the HTML (data-sw) because only the server knows where it lives; the scope is the
 * root, otherwise the worker would only see /static/. */
export const offlineWorker = {
  selector: '[data-sw]',
  mount(el) {
    if (!('serviceWorker' in navigator)) return;

    // Stored BEFORE registration: it is what separates "first install" from
    // "a new version arrived". On the first one, the worker takes control of this page
    // (clients.claim) and that fires a controllerchange that must NOT become a reload -
    // that was enough for the screen to reload itself right after opening,
    // aborting midway the gauge readings that were already on their way.
    const hadController = Boolean(navigator.serviceWorker.controller);

    navigator.serviceWorker.register(el.dataset.sw, { scope: '/' })
      .then((reg) => {
        if (reg.waiting && hadController) announceNewVersion(reg);
        reg.addEventListener('updatefound', () => {
          const novo = reg.installing;
          if (!novo) return;
          novo.addEventListener('statechange', () => {
            // "installed" with a controller already live = new version waiting.
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

/* Shows the "there is a new version" strip. The click is what swaps it: the waiting
 * worker gets the order to take over, leaves "waiting", and the controllerchange right
 * after reloads the page already with the new shell. */
function announceNewVersion(reg) {
  const notice = $('[data-new-version]');
  if (!notice?.hidden) return;   // missing, or already announced: do not pile up click listeners
  notice.hidden = false;
  notice.querySelector('button')?.addEventListener('click', () => {
    reg.waiting?.postMessage({ tipo: 'assumir' });
  });
}
