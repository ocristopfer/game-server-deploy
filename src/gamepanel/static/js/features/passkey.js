/* Sign in with the device's biometrics (passkey) and register the device.
 *
 * What talks to the fingerprint or face reader is the browser's `navigator.credentials`;
 * the panel only sends the challenge and checks the signature. WebAuthn only exists in a
 * secure context (https), so without it both controls stay hidden - and the
 * password keeps working as always.
 *
 * WebAuthn speaks ArrayBuffer and the panel speaks JSON: the binary fields travel as
 * base64url, in both directions.
 */
import { postJSON } from '../core/http.js';

function supported() {
  return Boolean(window.PublicKeyCredential && window.isSecureContext && navigator.credentials);
}

function toBuffer(text) {
  const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.codePointAt(0)).buffer;
}

function toText(buffer) {
  let raw = '';
  new Uint8Array(buffer).forEach((b) => { raw += String.fromCodePoint(b); });
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function csrfToken() {
  return document.querySelector('input[name="csrf"]')?.value || '';
}

/* An error from the device itself (the person canceled, time ran out) is not a panel failure:
 * the sentence comes from the template, in the screen's language. */
function explain(status, err) {
  if (err?.name === 'NotAllowedError' || err?.name === 'AbortError') {
    return status.dataset.passkeyCancelled || err.message;
  }
  return err?.message || String(err);
}

export const passkeyLogin = {
  selector: '[data-passkey-login]',
  mount(box) {
    if (!supported()) return;
    box.hidden = false;
    const button = box.querySelector('button');
    const status = box.querySelector('[data-passkey-status]');

    button.addEventListener('click', async () => {
      button.disabled = true;
      status.textContent = '';
      try {
        const options = (await postJSON(box.dataset.passkeyLogin, {}, { csrf: csrfToken() })).publicKey;
        options.challenge = toBuffer(options.challenge);
        const cred = await navigator.credentials.get({ publicKey: options });
        const answer = await postJSON(box.dataset.passkeyFinish, {
          id: cred.id,
          clientDataJSON: toText(cred.response.clientDataJSON),
          authenticatorData: toText(cred.response.authenticatorData),
          signature: toText(cred.response.signature),
          userHandle: cred.response.userHandle ? toText(cred.response.userHandle) : '',
          next: box.dataset.passkeyNext || '',
        }, { csrf: csrfToken() });
        window.location.assign(answer.redirect);
      } catch (err) {
        status.textContent = explain(status, err);
        button.disabled = false;
      }
    });
  },
};

export const passkeyRegister = {
  selector: '[data-passkey-register]',
  mount(form) {
    if (!supported()) return;
    const holder = form.closest('[data-passkey-available]');
    if (holder) holder.hidden = false;
    const status = form.querySelector('[data-passkey-status]');
    const button = form.querySelector('button');

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      button.disabled = true;
      status.textContent = '';
      try {
        // The password (and the code) go in the form; the panel only returns the challenge if they check out.
        const options = (await postJSON(form.action, new FormData(form))).publicKey;
        options.challenge = toBuffer(options.challenge);
        options.user.id = toBuffer(options.user.id);
        options.excludeCredentials = options.excludeCredentials.map((c) => ({ ...c, id: toBuffer(c.id) }));
        const cred = await navigator.credentials.create({ publicKey: options });
        const answer = await postJSON(form.dataset.passkeyRegister, {
          id: cred.id,
          clientDataJSON: toText(cred.response.clientDataJSON),
          attestationObject: toText(cred.response.attestationObject),
        }, { csrf: csrfToken() });
        window.location.assign(answer.redirect);
      } catch (err) {
        status.textContent = explain(status, err);
        button.disabled = false;
      }
    });
  },
};
