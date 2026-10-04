/* Nucleo — conversa com o painel.
 *
 * Toda leitura de JSON do painel passa por aqui. As features nao chamam `fetch`
 * direto: assim o cabecalho Accept, o tratamento de erro e o "isto nunca vem do
 * cache" ficam num lugar so, e trocar o transporte nao mexe em nenhuma tela.
 */

export class NetworkError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'NetworkError';
    this.status = status;
  }
}

/* Le JSON de uma rota do painel.
 *
 * `cache: 'no-store'` importa de verdade aqui: com o service worker instalado, uma
 * leitura de medidores servida do cache mostraria o servidor como estava ha uma hora
 * — pior do que nao mostrar nada. */
export async function readJSON(url, options = {}) {
  return request(url, {
    headers: { Accept: 'application/json', ...options.headers },
    signal: options.signal,
  });
}

/* Manda um POST e le o JSON da resposta.
 *
 * `FormData` vai como formulario (o token CSRF ja esta num campo dele); objeto vai como
 * JSON, e ai o token tem de ir no cabecalho, que e o outro lugar onde o painel o procura. */
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
    throw new NetworkError(err.message || 'sem conexao');
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
