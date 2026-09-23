/* Nucleo — conversa com o painel.
 *
 * Toda leitura de JSON do painel passa por aqui. As features nao chamam `fetch`
 * direto: assim o cabecalho Accept, o tratamento de erro e o "isto nunca vem do
 * cache" ficam num lugar so, e trocar o transporte nao mexe em nenhuma tela.
 */

export class ErroDeRede extends Error {
  constructor(mensagem, status = 0) {
    super(mensagem);
    this.name = 'ErroDeRede';
    this.status = status;
  }
}

/* Le JSON de uma rota do painel.
 *
 * `cache: 'no-store'` importa de verdade aqui: com o service worker instalado, uma
 * leitura de medidores servida do cache mostraria o servidor como estava ha uma hora
 * — pior do que nao mostrar nada. */
export async function readJSON(url, opcoes = {}) {
  let resp;
  try {
    resp = await fetch(url, {
      headers: { Accept: 'application/json', ...options.headers },
      cache: 'no-store',
      credentials: 'same-origin',
      signal: opcoes.signal,
    });
  } catch (err) {
    throw new ErroDeRede(err.message || 'sem conexao');
  }

  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }

  if (!resp.ok) {
    throw new ErroDeRede(data?.error || `http ${resp.status}`, resp.status);
  }
  return data;
}
