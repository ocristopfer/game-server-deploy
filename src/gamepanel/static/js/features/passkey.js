/* Entrar com a biometria do aparelho (passkey) e cadastrar o aparelho.
 *
 * Quem fala com o leitor de digital ou com o rosto e o `navigator.credentials` do
 * navegador; o painel so manda o desafio e confere a assinatura. O WebAuthn so existe em
 * contexto seguro (https), entao sem ele os dois controles continuam escondidos - e a
 * senha segue funcionando como sempre.
 *
 * O WebAuthn fala ArrayBuffer e o painel fala JSON: os campos binarios viajam em
 * base64url, nos dois sentidos.
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

/* Erro do proprio aparelho (a pessoa cancelou, o tempo acabou) nao e falha do painel:
 * a frase vem do template, no idioma da tela. */
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
        // A senha (e o codigo) vao no formulario; o painel so devolve o desafio se conferirem.
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
