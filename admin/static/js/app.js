/* Ponto de entrada do painel.
 *
 * Aqui nao ha logica de tela nenhuma: este arquivo so conhece o CONTRATO das
 * features — cada uma exporta `{ seletor, montar(el) }` — e as liga aos elementos
 * que a pagina de fato trouxe.
 *
 * O que isso compra:
 *
 *   - uma tela "pede" um comportamento colocando o data-* correspondente na
 *     marcacao; nao existe mais <script> solto dentro de template;
 *   - uma feature nova entra sem que nada aqui precise saber o que ela faz;
 *   - uma feature que quebra nao derruba as outras (cada montagem e isolada).
 *
 * O terminal e a unica excecao deliberada: sao 28 KB de emulador VT100 que so a
 * tela do terminal carrega, no seu proprio <script type="module">.
 */
import { $$ } from './core/dom.js';

import { menuSuspenso } from './features/menu.js';
import { confirmar } from './features/confirm.js';
import { copiar } from './features/copy.js';
import { medidoresDoPainel, medidoresDoServidor, barrasIniciais } from './features/metrics.js';
import { jogadoresDoPainel, jogadoresDoServidor } from './features/players.js';
import { seguirLog } from './features/logfeed.js';
import { acompanharJob } from './features/jobwatch.js';
import { editorDeArquivo } from './features/fileeditor.js';
import { filtroDeConfig, maisLinhasDeConfig, configSuja } from './features/configform.js';
import { caixaDeComando } from './features/console.js';
import { grafico } from './features/charts.js';
import { botaoInstalar, servicoOffline } from './features/pwa.js';

const FEATURES = [
  // estrutura
  menuSuspenso, confirmar, copiar, servicoOffline, botaoInstalar,
  // leitura ao vivo
  barrasIniciais, medidoresDoPainel, medidoresDoServidor,
  jogadoresDoPainel, jogadoresDoServidor, seguirLog, acompanharJob,
  // formularios
  editorDeArquivo, filtroDeConfig, maisLinhasDeConfig, configSuja, caixaDeComando,
  // visualizacao
  grafico,
];

export function montarTudo(raiz = document) {
  FEATURES.forEach((feature) => {
    $$(feature.seletor, raiz).forEach((el) => {
      try {
        feature.montar(el);
      } catch (err) {
        // Uma feature quebrada nao pode levar as outras junto: o painel controla
        // servidores de verdade, e uma tela meio viva vale mais que uma tela branca.
        console.error(`feature "${feature.seletor}" falhou ao montar`, err);
      }
    });
  });
}

montarTudo();
