/* Push notifications on this device: turn on, turn off.
 *
 * The browser's PushManager creates the subscription (an endpoint at Google, Mozilla, Apple or
 * Microsoft plus two keys); the panel stores it and encrypts each alert to it. Push only exists
 * in a secure context with a service worker, and on an iPhone only in the app added to the home
 * screen - so the controls are born hidden and this module reveals them where they work.
 *
 * The subscription is bound to the panel's public key (data-push). A subscription made with
 * another key (a panel whose database was recreated) can never be delivered to, so it counts as
 * "off" and turning on replaces it.
 */
import { postJSON } from '../core/http.js';
import { $, $$ } from '../core/dom.js';

function supported() {
  return Boolean(window.isSecureContext && 'serviceWorker' in navigator &&
    'PushManager' in window && 'Notification' in window);
}

function toBytes(text) {
  const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.codePointAt(0));
}

function sameKey(buffer, bytes) {
  if (!buffer) return false;
  const have = new Uint8Array(buffer);
  return have.length === bytes.length && have.every((b, i) => b === bytes[i]);
}

function csrfToken() {
  return document.querySelector('input[name="csrf"]')?.value || '';
}

/* A name the person recognizes in the device list. It is only a suggestion: the list lets
 * them rename it, and nothing in the panel depends on it. */
function deviceLabel() {
  const ua = navigator.userAgent;
  const systems = [['iPhone', /iPhone/], ['iPad', /iPad/], ['Android', /Android/],
    ['Windows', /Windows/], ['Mac', /Macintosh/], ['Linux', /Linux/]];
  const browsers = [['Edge', /Edg\//], ['Firefox', /Firefox\//], ['Chrome', /Chrome\//], ['Safari', /Safari\//]];
  const system = systems.find(([, re]) => re.test(ua))?.[0] || '';
  const browser = browsers.find(([, re]) => re.test(ua))?.[0] || '';
  return [system, browser].filter(Boolean).join(' · ');
}

export const pushToggle = {
  selector: '[data-push]',
  mount(box) {
    if (!supported()) return;
    box.hidden = false;
    const fallback = $('[data-push-unsupported]');
    if (fallback) fallback.hidden = true;

    const on = box.querySelector('[data-push-on]');
    const off = box.querySelector('[data-push-off]');
    const status = box.querySelector('[data-push-status]');
    const key = toBytes(box.dataset.push);
    const known = new Set($$('[data-push-endpoint]').map((el) => el.dataset.pushEndpoint));

    const fail = (err) => {
      status.textContent = err?.message || String(err);
      on.disabled = false;
      off.disabled = false;
    };

    navigator.serviceWorker.ready.then(async (reg) => {
      const current = await reg.pushManager.getSubscription();
      // Subscribed here AND known to the panel with this key: that is the only "on".
      const live = current && known.has(current.endpoint) &&
        sameKey(current.options?.applicationServerKey, key);
      on.hidden = Boolean(live);
      off.hidden = !live;

      on.addEventListener('click', async () => {
        on.disabled = true;
        status.textContent = '';
        try {
          if (await Notification.requestPermission() !== 'granted') {
            fail(new Error(box.dataset.pushDenied));
            return;
          }
          const old = await reg.pushManager.getSubscription();
          if (old && !sameKey(old.options?.applicationServerKey, key)) await old.unsubscribe();
          const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
          const answer = await postJSON(box.dataset.pushSubscribe,
            { ...sub.toJSON(), label: deviceLabel() }, { csrf: csrfToken() });
          window.location.assign(answer.redirect);
        } catch (err) {
          fail(err);
        }
      });

      off.addEventListener('click', async () => {
        off.disabled = true;
        status.textContent = '';
        try {
          const sub = await reg.pushManager.getSubscription();
          const endpoint = sub?.endpoint || '';
          if (sub) await sub.unsubscribe();
          const answer = await postJSON(box.dataset.pushUnsubscribe, { endpoint }, { csrf: csrfToken() });
          window.location.assign(answer.redirect);
        } catch (err) {
          fail(err);
        }
      });
    }).catch(fail);
  },
};
