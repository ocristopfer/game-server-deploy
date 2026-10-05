/* Core - talking to the panel.
 *
 * Every JSON read from the panel goes through here. Features do not call `fetch`
 * directly: that way the Accept header, error handling and the "this never comes from
 * the cache" live in one place, and swapping the transport touches no screen.
 */

export class NetworkError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'NetworkError';
    this.status = status;
  }
}

/* Reads JSON from a panel route.
 *
 * `cache: 'no-store'` really matters here: with the service worker installed, a
 * gauge reading served from the cache would show the server as it was an hour ago
 * - worse than showing nothing. */
export async function readJSON(url, options = {}) {
  return request(url, {
    headers: { Accept: 'application/json', ...options.headers },
    signal: options.signal,
  });
}

/* Sends a POST and reads the JSON response.
 *
 * `FormData` goes as a form (the CSRF token is already in one of its fields); an object goes as
 * JSON, and then the token has to go in the header, which is the other place the panel looks for it. */
export async function postJSON(url, body, { csrf = '' } = {}) {
  const form = body instanceof FormData;
  const headers = { Accept: 'application/json' };
  if (!form) headers['Content-Type'] = 'application/json';
  if (csrf) headers['X-CSRF-Token'] = csrf;
  return request(url, { method: 'POST', headers, body: form ? body : JSON.stringify(body) });
}

async function request(url, init) {
  let resp;
  try {
    resp = await fetch(url, { ...init, cache: 'no-store', credentials: 'same-origin' });
  } catch (err) {
    // Read at call time, from the page: the module has no catalog of its own. The page's
    // phrase comes FIRST: the browser's own message ("Failed to fetch") is in the browser's
    // language, not the panel's, and says nothing more than "no connection".
    throw new NetworkError(document.body?.dataset.labelNoConnection || err.message);
  }

  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }

  if (!resp.ok) {
    throw new NetworkError(data?.error || `http ${resp.status}`, resp.status);
  }
  return data;
}
