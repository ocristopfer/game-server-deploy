# CLAUDE.md — como mexer neste repositorio

Deploy de servidores dedicados de jogos (Proxmox LXC ou Docker) mais um **painel web**
em `admin/`. Este arquivo e sobre **como escrever codigo aqui**. O que o projeto faz,
e como usar, esta no [README.md](README.md) — nao duplique conteudo entre os dois.

O painel roda com poder de **root nos containers de jogo**. Isso muda o peso de tudo:
um botao errado para um servidor de verdade, um cache errado mostra um servidor caido
como se estivesse de pe.

---

## Verificar antes de dizer que terminou

O ambiente de desenvolvimento e um `docker compose` completo: painel + dois containers
de jogo falsos (com sshd, `systemctl` de mentira, query A2S, API REST e log).

```bash
docker compose up --build -d          # painel em http://localhost:8080 (admin/admin12345)
docker compose restart panel          # depois de mexer em app.py/ui.py
```

As nove suites do painel (`test_gamefields.py`, `test_gameconf.py`, `test_charts.py`,
`test_schedules.py`, `test_users.py`, `test_players.py`, `test_alerts.py`,
`test_broker.py`, `test_broker_client.py`) sao **pytest** — 436 testes ao todo (mais 415 do
pacote `broker/`, que roda so pelo `.venv`, da raiz), com fixtures compartilhadas em
`admin/conftest.py`
(`banco`: tabelas limpas a cada teste; `webhooks`: captura o que sairia por HTTP;
`chefe`/`peao`: um admin e um operador ja logados; `entrar`/`postar`: login e POST com
CSRF). **Rode a suite inteira** depois de mexer em `app.py` — elas cobrem exatamente as
partes onde e facil quebrar algo sem perceber (quando o painel decide avisar, quem ve o
que, o que conta como jogador). Os arquivos ja NAO rodam como script solto
(`python3 test_alerts.py` nao faz nada) — passam sempre por `pytest`.

**Rapido, na maquina** (segundos, e o ciclo normal enquanto se edita):

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r admin\requirements-dev.txt pytest
.\.venv\Scripts\python.exe -m pytest          # a suite inteira, da raiz do repo
.\.venv\Scripts\python.exe -m pytest admin\test_alerts.py -k test_loop_de_restart
```

`pytest.ini`, na raiz, e quem diz onde procurar os testes (`admin/`) e desliga o cache
em disco (ver o comentario nele — o motivo e o mount read-only do container, nao o
venv). O `.venv` e ferramenta de desenvolvimento, nao dependencia do painel (ver
`admin/requirements-dev.txt`); ele tambem e o que faz o editor resolver `import flask`,
via `pyrightconfig.json`.

**No container, que e a verdade** (mais lento; rode antes de publicar):

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -w /opt/gamepanel panel python3 -m pytest -q
```

O container so ve `/opt/gamepanel` (bind mount de `admin/` sozinho — o `pytest.ini` da
raiz do repo nao existe ali dentro), entao **rode com `-p no:cacheprovider`** se quiser
o mesmo silencio do venv; sem a flag os testes passam igual, só com um aviso de cache
que nao escreve (sistema de arquivos read-only). O apt (`python3-pytest`) e quem
fornece o pytest do container — ver `docker/panel/Dockerfile`; **rebuild a imagem**
(`docker compose build panel`) se `pytest` não for encontrado ali dentro.

Uma diferenca conhecida entre os dois: **2 testes de `test_players.py` sao pulados no
Windows** (`@posix_apenas`, no proprio arquivo) — os que conferem que a pasta do socket
SSH so e visivel pelo dono (`0700`). E permissao POSIX pura: nao existe no Windows, e o
resultado so vale no container. Os outros 321 passam iguais nos dois lugares.

Templates e estaticos entram por bind mount: recarregar a pagina basta. `app.py` e
`ui.py` sao recarregados pelo `--reload` do gunicorn, mas **rota nova ou mudanca de
decorador exige `docker compose restart panel`**.

Depois de mexer em template ou rota, passe por todas as telas:

```bash
J=/tmp/p.jar; rm -f $J
TOK=$(curl -s -c $J localhost:8080/login | grep -o 'value="[^"]*"' | head -1 | cut -d'"' -f2)
curl -s -b $J -c $J -o /dev/null -d "csrf=$TOK&username=admin&password=admin12345" localhost:8080/login
for p in / /servers/1 /servers/1/config /servers/1/files /servers/1/graficos \
         /servers/1/backups /servers/1/agendamentos /servers/1/terminal \
         /servers/1/console /servers/1/edit /servers/1/players/descobrir \
         /historico /alertas /usuarios /account /ssh-key /servers/new \
         /manifest.webmanifest /sw.js /offline; do
  printf "%s %s\n" "$(curl -s -b $J -o /dev/null -w '%{http_code}' localhost:8080$p)" "$p"
done
```

Um `500` aqui e quase sempre template quebrado — e template quebrado **nao aparece em
teste nenhum**. Confira tambem como **operador** (papel nao-admin): o menu e as telas
mudam, e e ali que mora o 403 que ninguem tinha visto.

---

## Onde cada coisa mora

```
pytest.ini             onde o pytest procura os testes (admin/ e broker/) e config de cache
broker/                servico que cria instancias de jogo (Proxmox) e abre portas (OPNsense);
                       pacote Python, ver a secao "Broker" abaixo
admin/
  app.py               rotas, SSH, banco, alertas, agendador  (arquivo grande; ver abaixo)
  ui.py                mapa da interface: navegacao e acoes   (puro, sem Flask)
  gameconf.py          leitor/gravador de .ini/.json/.cfg do jogo
  gamefields.py        catalogo: o que cada chave de config significa
  modelos_de_jogo.py   modelos do formulario "Adicionar jogo" (Unreal Linux); puro, so dado.
                       `broker/test_modelos.py` confere que passam no validador do broker
  busca_de_jogos.py    busca por nome/App ID sobre `sugestoes_de_jogos.py` (GERADO, nao edite)
tools/
  importar-linuxgsm.py gera `admin/sugestoes_de_jogos.py` a partir do LinuxGSM (precisa de internet)
  conftest.py          fixtures pytest compartilhadas: banco, webhooks, chefe, peao...
  broker_client.py     cliente do broker (so stdlib, TLS fixado por impressao); ver "Broker"
  test_*.py            as 9 suites (436 testes) - ver a secao de testes, no topo
  requirements-dev.txt Flask para o .venv local (so ferramenta, nao dependencia do painel)
  templates/
    components/        macros: ui.html (generico) e servidor.html (dominio)
    *.html             uma tela cada
    sw.js.jinja        service worker    (template, nao estatico: tem versao dentro)
    manifest.webmanifest.jinja
  static/
    css/               tokens -> base -> layout -> components -> pages
    js/core/           format, http, poll, dom, dirty   (sem DOM de tela, reutilizavel)
    js/features/       um modulo por comportamento
    js/app.js          liga features aos elementos da pagina
    icons/
```

### A regra que sustenta o resto: uma lista, um lugar

Antes, a lista de telas de um servidor estava escrita a mao em **seis templates**. Cada
um tinha um subconjunto diferente, e era por isso que "Graficos" existia numa tela e nao
na outra. Hoje ela esta em `ui.py`.

- **Tela nova de servidor** = uma linha em `ui.SECOES_DO_SERVIDOR`. Nao edite template
  de navegacao; nao existe mais.
- **Acao nova** (start/stop/...) = uma entrada em `ui.ACOES` (como aparece) + uma em
  `app.COMANDOS` (o que roda). Um `assert` no import quebra se as duas divergirem.
- **Fonte de contagem de jogadores nova** = uma funcao + uma linha em
  `app.FONTES_DE_CONTAGEM`.
- **Alerta de recurso novo** = uma linha em `app.ALERTAS_DE_RECURSO`.

Se voce se pegar escrevendo a mesma lista pela segunda vez, pare: ela pertence a uma
dessas tabelas.

---

## Python (`app.py`, `ui.py`)

- **Dependencias: so a stdlib mais o `python3-flask` do apt.** O container do painel nao
  baixa pacote de lugar nenhum. Nada de `pip install`, nada de CDN.
  Como consequencia **nao existe Python instalado nesta maquina de desenvolvimento**: o
  `Import "flask" could not be resolved` do Pylance e esperado e nao se conserta no
  codigo. Quem tem Flask e o container — e por isso que os testes rodam la dentro.
- **Segundo fator (2FA) e TOTP proprio, so stdlib** (`totp.py`, testado contra os vetores do RFC
  6238). Regras que os testes de `test_2fa.py` guardam: senha certa com 2FA NAO abre sessao (so grava
  `pre2fa`, sem `uid`, por 5 min); codigo usado nao vale de novo (`totp_last_step`, e o `UPDATE ... WHERE
  totp_last_step < ?` e o portao contra dois pedidos simultaneos); a trava do codigo e por USUARIO
  (5 em 15 min), nao por IP; desativar ou pedir codigos novos exige senha E codigo; recuperacao =
  8 codigos de uso unico, so o hash no banco. `GAMEPANEL_REQUIRE_2FA=1` (`ADMIN_REQUIRE_2FA` no `.env`)
  tranca quem nao ativou na tela de ativacao: so ligue DEPOIS de todo admin ter ativado. Saida de
  emergencia: `python3 /opt/gamepanel/app.py --reset-2fa USUARIO` no CT do painel, ou "Desligar 2FA"
  em Usuarios. Nao ha QR code (nao ha biblioteca e o painel nao baixa nada): a tela mostra a chave
  para digitar e um link `otpauth://` que abre o aplicativo no celular.
- **`provision-admin-lxc.sh` reescreve o `panel.env` INTEIRO**; as linhas `GAMEPANEL_BROKER_*` e
  `GAMEPANEL_ALLOW_BROKER` que o `deploy-broker.ps1 -ConfigurarPainel` grava sao preservadas de
  proposito (antes um `-Full` do painel desligava o broker em silencio). Opcao nova de painel =
  variavel `ADMIN_*` no `.env`, uma linha no `render_panel_config` e o nome em `$adminKeys` do
  `deploy-admin.ps1`.
- **CSRF e do painel, nao do Flask-WTF.** `csrf_token()` gera, `_check_csrf`
  (`before_request`) barra todo metodo que muda estado. Analisador estatico marca isso
  como "CSRF desabilitado" — e falso positivo, e ha um comentario no `Flask(__name__)`
  explicando. **Nao remova `_check_csrf`.**
- **Complexidade cognitiva: teto de 15** (regra do Sonar). Quando estourar, o corte
  quase sempre e o mesmo: separar *decidir* de *fazer*. `monitora_servidores` virou
  `_ritmo_do_monitor` (o que vence agora) + `_alertas_do_servidor` (o que fazer com cada
  um) e caiu de 48 para menos de 10.
- **Literal repetido tres vezes vira constante.** `FORMATO_DATA_CURTA`, `MARCA_JOGADOR`,
  `_texto_de_online()` nasceram assim — e o ultimo corrigiu um bug de brinde: uma das
  quatro copias dizia "0 jogadores online".
- **Mais de 13 parametros: passe um objeto.** `ensure_server` tinha 15; virou
  `ServidorDoDeploy(NamedTuple)`. Quinze posicoes e onde um `join_re` vai parar no lugar
  do `leave_re` sem ninguem notar.
- **Parametro que ninguem usa sai da assinatura**, mesmo que quebre a simetria com as
  funcoes irmas. Simetria falsa engana quem le.
- **`except` sem `Exception` redundante**: `BrokenPipeError` ja e `OSError`.
- **Suprimir aviso de lint**: o motivo vai na linha ACIMA, e o comentario fica limpo.
  ```python
  # Alerta nunca derruba o job.
  except Exception:  # noqa: BLE001
  ```
  `# noqa: BLE001 - motivo` na mesma linha e sintaxe invalida de supressao.
- **Dicionario de funcoes** (`ALERTAS_DE_RECURSO`, `FONTES_DE_CONTAGEM`) captura o objeto
  no import. Se um teste precisar trocar a funcao por uma falsa, ele vai ter de trocar a
  entrada da tabela — nao o nome no modulo. Verifique antes de transformar `if/elif` em
  tabela.
- **`\w` em Python NAO e `[A-Za-z0-9_]`** — sem `re.ASCII` ele casa acento e mais uns 900
  caracteres Unicode. O analisador pede a forma curta; se a expressao valida algo que vai
  parar num arquivo ou num comando remoto, a troca so vale **com a flag**. `KEY_RE` no
  `gameconf.py` e o exemplo, e ha teste guardando isso.
- **Nao comece comentario com "todo".** O detector de `TODO` do Sonar casa a palavra
  portuguesa: `# todo). O que faltava...` e `# TODO metodo que muda estado` viraram dois
  falsos positivos. No meio da frase nao dispara; no comeco da linha, sim.
- **Comentario no formato `# Palavra: coisa.ext` e lido como codigo comentado**
  (`nome: tipo` e anotacao valida em Python). Escreva `# Enshrouded (le
  enshrouded_server.json)`, nao `# Arquivo: enshrouded_server.json`.
- **Falso positivo que nao tem como sumir vai de `# NOSONAR` com o motivo ao lado**, e
  nao de um comentario esperando que alguem leia. Aviso repetido que se aprende a ignorar
  e como um aviso de verdade passa batido. Hoje ha dois, ambos revisados: o `python:S4502`
  do `Flask(__name__)` (CSRF proprio) e o `Web:S6845` do SVG do grafico (tabindex e a
  navegacao por teclado; tirar so silencia o aviso e cega quem depende dele).

### Os testes sao a rede de seguranca — nao os enfraqueca

`test_alerts.py` (81 testes) troca funcoes do modulo por falsas via
`monkeypatch.setattr(panel, "server_status", ...)`, que desfaz sozinho no fim de cada
teste — antes disso era uma atribuicao direta (`panel.server_status = ...`) sem `finally`
nenhum, e a suite so nao vazava estado porque cada arquivo era um processo Python
separado. Hoje as suites dividem um processo (pytest as importa todas juntas), e
sao o `monkeypatch` e a fixture `banco` (tabelas limpas a cada teste, em
`admin/conftest.py`) que garantem o isolamento.

Essa troca **so funciona porque tudo mora em `app.py`**. Se um dia esse arquivo for
dividido em pacote, as funcoes precisam ser chamadas pelo modulo
(`metrics.server_metrics(...)`, nao `from .metrics import server_metrics`), senao a
troca no teste deixa de valer em silencio e os testes passam sem testar nada.

### `GAMEPANEL_DB` no `conftest.py` e atribuicao direta, nunca `setdefault`

`docker/panel/Dockerfile` fixa `ENV GAMEPANEL_DB=/var/lib/gamepanel/panel.db`. Essa
variavel **ja existe** quando o processo de teste comeca dentro do container, entao um
`os.environ.setdefault("GAMEPANEL_DB", tmp)` no `conftest.py` e um no-op ali — os testes
rodariam contra o banco de VERDADE do painel de dev. Ja aconteceu: uma suite inteira
apagou o usuario `admin` e encheu a lista de servidores com nomes de teste ("alvo",
"outro"). O `conftest.py` usa `os.environ["GAMEPANEL_DB"] = ...` (atribuicao, nao
`setdefault`) exatamente por isso — nao troque essa linha achando que esta so deixando
uma configuracao externa vencer. Se um dia isso vazar de novo, o conserto e
`docker compose down -v && docker compose up -d` (o painel de dev e descartavel, os
volumes sao regenerados por `PANEL_SEED_DEMO=1`).

### Mexeu numa assinatura? Procure fora do `app.py`

`ensure_server` tambem e chamado de `docker/panel/entrypoint.sh` (dentro de um
heredoc Python) — um `grep` so nos `.py` nao acha. Procure no repositorio inteiro, e
lembre que **`entrypoint.sh` esta dentro da imagem**: exige
`docker compose up -d --build panel`, nao um `restart`.

---

## Templates Jinja

- **Zero `<script>` com logica e zero `onsubmit="return confirm(...)"`.** Comportamento
  vem de `static/js/features/` por `data-*`. Confirmacao e `data-confirmar="mensagem"` —
  o nome do arquivo vem do container, e dentro de codigo JavaScript um apostrofo no nome
  quebra a pagina inteira.
- **Nunca escreva uma tag literal dentro de um comentario `{# ... #}`.** O Jinja ignora,
  o editor nao: ele abre uma tag que nunca fecha e passa a ler o resto do arquivo como
  JavaScript. Escreva "tag de script" por extenso.
- **Nada de `style="...{{ valor }}..."`.** Valor de template dentro de um atributo
  `style` nao e CSS valido para ferramenta nenhuma, e o arquivo inteiro passa a acusar
  erro. Quando a cor vem do servidor, use **atributo** (`fill=`, `stroke=`) num SVG — e o
  que a legenda dos graficos faz.
- **Template que nao e HTML leva sufixo `.jinja`** (`sw.js.jinja`,
  `manifest.webmanifest.jinja`), senao o editor tenta parsear `{% for %}` como JavaScript.
- **`{% import %}` sempre `with context`.** Sem isso o macro nao enxerga `csrf_token()`
  nem `url_for`, e a tela morre com `'csrf_token' is undefined`.
- **`aria-label` so quando nao ha rotulo visivel.** Dentro de um `<label>Servidor`, um
  `aria-label="filtrar por servidor"` SUBSTITUI o texto visivel para o leitor de tela.
- **Toda tabela dentro de `<div class="table-wrap">`**, senao ela empurra a pagina para
  fora da tela no celular.
- Todo POST usa os macros `ui.acao` / `ui.menu_acao`, que montam o CSRF sozinhos.

---

## CSS

Cinco camadas, e cada uma **so pode depender das anteriores**:

| camada | o que entra |
|---|---|
| `tokens.css` | cor, espaco, raio, fonte, alvo de toque, z-index. Nenhum seletor. |
| `base.css` | reset e elementos crus (`a`, `input`, `table`) |
| `layout.css` | esqueleto do app (`.appbar`, `.tabbar`, `.wrap`) e primitivas (`.stack`, `.cluster`) |
| `components.css` | pecas reutilizaveis (`.btn`, `.card`, `.badge`, `.menu`, `.tabs`) |
| `pages.css` | o que e de uma tela so |

- **Mobile primeiro**: o que esta fora de `@media` e a tela do celular; as media queries
  so **acrescentam** quando ha espaco (`min-width`, nunca `max-width`).
- **Nenhum valor cru fora de `tokens.css`.** Sem `#4f9cf9`, sem `16px` solto.
- **Variacao entra por modificador** (`.btn--danger`), nunca por "esse botao dentro
  daquela tela" — regra de descendente e o que faz um CSS deixar de ser reutilizavel.
- **Apareceu duas vezes? Subiu de camada.** Se esta em `pages.css` e serve a duas telas,
  pertence a `components.css`.
- **Alvo de toque `>= var(--tap)` (44px)** em tudo que se clica.
- **Campo de formulario com `font-size >= 16px`**, senao o Safari do iPhone da zoom
  sozinho ao focar.
- **Esconder por `hover` sempre junto com largura**: `@media (hover: hover) and
  (pointer: fine) and (min-width: 900px)`. Navegador de celular que se declara
  `hover: hover` existe, e ali nao ha como revelar o que se escondeu.
- **`--safe-*` (notch/barra de gestos)** em tudo que encosta na borda da tela.
- **Cabecalho e corpo dividem a mesma coluna.** O fundo da barra vai de ponta a ponta, mas o
  conteudo (`.appbar__miolo`) tem a `--largura-max` e o recuo do `.wrap`: sem isso a marca
  fica no canto da janela e o conteudo no meio, sem alinhar com nada. A partir de 900px a barra
  mostra TODOS os destinos (`ui.NAV_DESKTOP_BARRA`, sem icone e com rotulo `curto` onde ha, para
  caberem seis) e o menu do NOME da pessoa leva conta, chave SSH e sair (`NAV_DESKTOP_CONTA`).
  No celular nada mudou: abas embaixo e o "⋯". Item aceso: `nav_ativa_desktop_de` (cada destino
  acende o proprio) x `nav_ativa_de` (as quatro abas do celular).
- **Cartoes lado a lado usam `.grid-cartoes`** (uma coluna no celular, duas a partir de 900px;
  `.grid-cartoes__largo` ocupa a linha inteira). Bloco comprido (log, tabela) vai no `__largo`,
  senao empurra o vizinho.
- **A classe da caixa de marcar e `.checkbox`**, nao `.check` (que nao existe e deixava a caixa
  em cima do texto). Grupo de campos com titulo: `fieldset.grupo`.

---

## JavaScript

Modulos ES, sem build, sem dependencia externa.

- **`core/` nao conhece tela nenhuma.** `format` (numero -> texto), `http` (ler JSON),
  `poll` (quando rodar), `dom`, `dirty`. Testavel, reutilizavel.
- **`features/` tem UM contrato**: `export const x = { seletor, montar(el) }`. O
  `app.js` so liga cada feature aos elementos que a pagina trouxe — feature nova nao
  muda o `app.js` alem de uma linha no registro.
- **Nao chame `fetch` nem `setInterval` direto numa feature.** Use `lerJSON` e `Poller`:
  e ali que moram o `cache: 'no-store'`, o "aba escondida nao gasta SSH" e o recuo
  quando o painel cai. Isso ja foi seis copias com um detalhe a menos cada.
- **Texto que veio do jogo ou do container entra por `textContent`**, nunca por
  `innerHTML`. Nome de jogador e nome de arquivo sao dados, nao marcacao.
- **A tela tem de funcionar sem JavaScript.** O grafico ja vem desenhado do servidor, a
  tabela de numeros esta na pagina, o menu e um `<details>`. Controle que so existe com
  JS (o "+ outra linha") nasce `hidden` e o proprio modulo o revela.
- Preferencias do linter: `Number.parseFloat` (nao `parseFloat`), `el.dataset.x` (nao
  `getAttribute('data-x')`), `a?.b` (nao `a && a.b`).

---

## PWA e service worker

- **`/sw.js` e servido pelo Flask, da raiz.** O escopo de um service worker e a pasta
  onde ele mora: em `/static/sw.js` ele nao enxergaria a navegacao do painel.
- **A versao e o mtime dos arquivos de `static/`**, carimbada ao servir. CSS novo =
  worker diferente = cache velho descartado.
- **Nunca cacheie HTML de pagina logada nem `/api/`.** O painel tem varios usuarios e da
  root nos containers: tela de servidores em cache poderia reaparecer depois do logout, e
  medidor em cache mente sobre um servidor de verdade.
- **O worker nao assume sozinho** (sem `skipWaiting()` no install): pode haver uma sessao
  de terminal aberta no meio de uma edicao. Quem troca e o botao "Atualizar agora".
- **Conferir layout por captura de tela? Ignore o service worker.** Ele serve o CSS/JS antigo do
  cache ate alguem clicar em "Atualizar agora": a foto sai com o estilo da versao anterior e
  parece que a mudanca "nao pegou" (o banner "Ha uma versao nova" aparecendo na foto e o sinal).
  Na captura via DevTools use `Network.setBypassServiceWorker` + `Network.setCacheDisabled`, e
  reinicie o servidor local depois de mexer no `app.py` (o `app.run` nao recarrega codigo Python).
- **Nao batize rota de aplicacao com nome de telemetria.** `/api/metrics` e regra
  corriqueira de bloqueador (uBlock, AdGuard, DNS filtrado): o navegador devolve um pixel
  com status 499 e o pedido nem chega ao servidor. A rota daqui e `/api/recursos`. Ao
  depurar "a requisicao some", compare **curl x navegador** antes de procurar bug no
  codigo.

---

## Broker (`broker/`)

O painel nao guarda credencial de Proxmox nem de OPNsense: quem guarda e o broker, que
expoe verbos fixos (criar/desativar/remover instancia, catalogo). Pronto: nucleo,
backends REAIS de Proxmox (`proxmox.py`) e OPNsense (`opnsense.py`) e o cliente HTTP
(`conexao.py`), todos testados contra servidores falsos (`http_falso.py`), o instalador por
SSH (`ssh_install.py` + `lib/ct-install.sh`), a tela no painel e o DEPLOY do broker
(`config.py`, `prod.py`, `provision-broker-lxc.sh`, `deploy-broker.ps1`). Falta so uma criacao
REAL de ponta a ponta (nada disto rodou contra o seu Proxmox/OPNsense ainda). Segredos de
teste e de deploy ficam em `broker.secrets.env` (fora do git);
`verificar-broker-acesso.ps1` confere so leitura e `spike-broker-escrita.ps1` cria e
apaga um CT/regra de teste.

**Lado do painel** (`admin/`): telas `/catalogo` e `/instancias`, flag
`GAMEPANEL_ALLOW_BROKER` (desligada por padrao; config ruim DESLIGA o recurso em vez de
derrubar o painel), `servers.broker_id` e `jobs.broker_op`. No compose de dev sobe um
broker de brinquedo (`broker/dev.py`, backends falsos): `docker compose up --build`.

- **Um instalador de jogo, dois transportes.** As fases que rodam DENTRO do CT (SteamCMD,
  Wine/Proton, systemd) moram em `lib/ct-fases.sh`, lido por `provision-game-lxc.sh` (host:
  `pct exec`) e por `lib/ct-install.sh` (dentro do CT, o que o broker roda por SSH). O
  bundle do `deploy-game.ps1` e uma pasta SEM subpastas: a lib viaja como `ct-fases.sh` ao
  lado do script. **Mexeu numa fase? Rode `bash docker/ct-sandbox/comparar.sh`** (precisa do
  Docker): roda o instalador ANTES e DEPOIS para 8 jogos com `pct`, `systemctl`, `apt-get` e
  SteamCMD falsos e faz diff de arquivos, conteudo e linhas de comando; tambem compara host x
  broker e confere o `install.env` que o Python gera. Sem isso a refatoracao e no escuro: nao
  existe teste de shell no repositorio.
- **`install.env` e sempre `shlex.quote`.** Hook (`PRE/POST_INSTALL_CMD`) so existe no catalogo
  curado; jogo da API escolhe **receitas** (`apply_recipes`, lista fechada), nunca escreve shell.
  Receita desconhecida derruba a instalacao. A chave do broker sai do CT ao fim
  (`_limpar`, roda SEMPRE) e se ela nao sair a criacao FALHA.
- **`games/*.env` tem de passar no `source` do bash.** Regex de log (`JOIN_RE`) com parenteses
  precisa de aspas: sem elas 5 dos 8 jogos quebravam o deploy pelo Proxmox (o
  `provision-game-lxc.sh` da `source` no arquivo cru). Conferir:
  `for f in games/*.env; do bash -c "set -a; source $f"; done`.
- **Escrever texto para o bash no Windows:** `print()`/stdout em modo texto troca `\n` por
  `\r\n` e o `source` le cada valor com um `\r` (o erro sai como `WINDOWS_RUNTIME invalido: ''`).
  Grave com `newline="\n"` ou bytes.
- **Deploy do broker** (`deploy-broker.ps1` -> `provision-broker-lxc.sh`, no host Proxmox): CT
  unprivileged proprio, FORA do pool `games`, com gunicorn+TLS (1 worker, a trava de IP mora na
  memoria) e systemd endurecido. **Token, chave SSH e certificado PERSISTEM entre deploys**
  (regenerar quebraria o painel); so mudam com `-RotateToken` / `-RotateCert`. Os segredos
  chegam em `broker.secrets.env` (0600, apagado no fim) e vao para `/etc/gamebroker/broker.env`;
  nada de segredo na unit. O deploy **nao liga o recurso no painel**: `-ConfigurarPainel` grava
  URL/token/impressao com `GAMEPANEL_ALLOW_BROKER=0`, e `-LigarNoPainel` pede confirmacao.
  **Prove com `bash docker/ct-sandbox/broker.sh`** (modo/dono, env relido pelo `carregar` real,
  segredo com aspas/barra/cifrao/crase, idempotencia, rotacao).
- **`set -e` + `pipefail` + `$(...)` = saida CALADA.** Falha dentro de uma substituicao encerra o
  script antes do `[[ -n "$x" ]] || die "..."` que a explicaria (foi o que o primeiro deploy real
  fez quando o host Proxmox nao alcancou o OPNsense: parou sem mensagem). Todo script de
  provisionamento tem `trap ERR` (linha + comando, sem segredo) e usa `|| true` dentro do `$(...)`
  que alimenta um `die`. O sandbox tem casos para os dois.
- **ssh/scp no PowerShell 5.1:** o stderr do remoto (ate um `systemctl enable` que da certo imprime
  "Created symlink") vira excecao com `$ErrorActionPreference = "Stop"` e saida redirecionada.
  `Invoke-Native` (deploy-broker.ps1) relaxa a preferencia so durante o comando; o que decide e o
  `$LASTEXITCODE`.
- **Teste de saude de dentro do CT usa `127.0.0.1`, que entra em `BROKER_ALLOW_IPS`** junto do IP do
  painel (lista vazia = qualquer origem, entao ali o loopback NAO e acrescentado). Sonda de saude tem
  prazo curto (`SONDA_TIMEOUT`): um firewall que descarta pacote nao pode fazer a saude demorar 30 s.
- **A API do Proxmox e a do OPNsense precisam de regra de firewall do CT do broker** (o resumo do
  deploy lista). Sem elas o broker sobe, mas a saude mostra "NAO RESPONDE" e nada e criado.
- **`broker/config.py` valida TUDO e lista TODOS os problemas de uma vez**, so pelo NOME da
  variavel (nunca o valor). Config ruim derruba o START (`SystemExit(2)`), nunca um pedido.
  https exige impressao SHA-256; http so em loopback.
- **Valor no `EnvironmentFile` do systemd:** `NOME="valor"` com `\` e `"` escapados (`$` nao
  expande ali). Teste com parser caractere a caractere: um regex guloso engole uma aspa sem
  escape e esconde o defeito.
- **Impressao dos certificados do Proxmox/OPNsense e lida do servidor no deploy (TOFU) e
  IMPRESSA para voce conferir.** Se ja souber a impressao, ponha em `*_CERT_SHA256`.
- **E um pacote** (`broker/__init__.py`), nao arquivos soltos como `admin/`: os dois teriam
  `app.py` e `conftest.py` e colidiriam no mesmo processo do pytest. Rode da raiz:
  `.\.venv\Scripts\python.exe -m pytest broker`.
- **`servico.py` so conhece as interfaces de `backends.py`.** Proxmox, OPNsense, SSH e rede
  reais entram depois sem mexer nele; os testes usam `fakes.py`.
- **Catalogo em dois niveis**: `games/*.env` (curado, pode ter `PRE/POST_INSTALL_CMD`) e
  jogos cadastrados pela API (**so dado**). O `.env` e lido por `catalogo.ler_env`, nunca por
  `source`, e campo que o broker nao conhece e RECUSADO — e assim que `pre_install_cmd`
  deixa de entrar de contrabando. Campo novo em jogo dinamico = regex propria em
  `catalogo.py` e um caso em `CASOS_INVALIDOS` do teste.
- **Porta interna == externa, sempre.** Jogo `deslocavel` (`PORTS_SHIFTABLE=1`) recebe um bloco
  de portas seguidas da FAIXA do broker (`BROKER_PORT_INICIO/FIM`, padrao 31000-31999, abaixo das
  efemeras 32768+ e longe das portas padrao dos jogos), nunca as portas padrao; os demais ficam
  nas portas padrao e sao recusados se estiverem ocupadas. Isso e ir para a faixa mesmo com a
  porta padrao livre: mistura de "servidor antigo na porta padrao" com "servidor do broker na
  faixa" e o que impede um dia colidir. O jogo so e `deslocavel` se o broker consegue AVISA-LO de
  todas as portas: `START_ARGS` com `{PORT}` (e `{QUERY_PORT}` se ha query, `{EXTRA_PORT}` se ha
  porta extra) e nenhuma porta alem dessas tres (`catalogo.problema_de_deslocavel`, validado no
  carregamento). A porta extra (`EXTRA_PORT=`/`porta_extra`) existe por causa do Satisfactory: alem
  da principal (UDP+TCP) ele abre a 8888/TCP de mensagens confiaveis, que sem `-ReliablePort=` fica
  fixa e impede uma segunda instancia. O `ct-fases.sh` troca `{EXTRA_PORT}` como os outros dois; o
  marcador sem porta extra e recusado (viraria `0`). Hoje: Dragonwilds, Satisfactory, Palworld e
  Icarus. Enshrouded (portas no JSON) e DayZ (2303/2304 derivadas) nao. Ver `alocador.py`.
  No `comparar.sh` o Satisfactory "antes x depois" roda sem o marcador (`satisfactory-legado.env`):
  o instalador de referencia nao o conhece e deixaria `{EXTRA_PORT}` literal no ExecStart.
- **Enderecos: o IP diz o CTID.** Painel `.100` (CT 300), broker `.101` (CT 301), jogos do
  broker `.102-.199` (CT 302-399): `CTID = BROKER_CTID_BASE (200) + ultimo numero do IP`, ou
  seja "3" + os dois ultimos digitos do IP (`alocador.escolher_ip_e_ctid`; um IP so serve se o
  CTID dele tambem esta livre). Tudo em 300-399 e deste sistema; os CTs 2xx sao os antigos, feitos
  a mao ou pelo `deploy-game.ps1`, e ficam onde estao. As VMs 100-111 do Proxmox nao colidem. Com
  `BROKER_CTID_BASE=0` o CTID volta a ser escolhido a parte, na faixa `BROKER_CTID_INICIO/FIM`.
  **O DHCP do OPNsense nao pode cobrir `.100-.199`**: a checagem por ping nao pega um aparelho
  que ainda vai chegar.
- **Sugestoes de jogo (formulario "Adicionar jogo")** vem do LinuxGSM (MIT), convertidas por
  `python tools/importar-linuxgsm.py` e commitadas em `admin/sugestoes_de_jogos.py` (110 jogos): o
  painel em producao NAO vai a internet (a API oficial da loja Steam nem serve: servidor dedicado e
  app do tipo "Tool" e volta `success:false`). Regras do conversor, cada uma com teste em
  `broker/test_importar_linuxgsm.py` e `broker/test_sugestoes.py`: so sai o que o
  `validar_dinamico` aceita; porta de RCON/telnet/HTTP vai so no argumento e NUNCA no NAT; variavel
  de senha/nome/IP/token nunca e resolvida (o argumento sai, com aviso); tudo depois de `; | & \`
  `$(` e cortado; variavel vazia derruba a opcao junto (senao ela engole a proxima). Protocolo e
  presumido UDP (so `reliableport`/`httpport` sao TCP): o aviso da sugestao diz isso. ~30 jogos
  guardam a porta no config do proprio jogo e saem como sugestao PARCIAL (App ID sem porta).
  Enshrouded, Icarus e Dragonwilds nao estao no LinuxGSM: continuam manuais. E a busca e SEMPRE
  sugestao: quem valida e o broker no envio.
- **Desfazer nao pode mentir**: se a limpeza falha, a reserva vira `falhou` e continua
  bloqueando IP/CTID/portas ate alguem remover (`servico._desfazer`).
- **TLS e por IMPRESSAO, nunca `verify=False`.** Proxmox e OPNsense sao autoassinados;
  `conexao.Cliente` aceita so o certificado cuja SHA-256 e a configurada (o
  `verificar-broker-acesso.ps1` a imprime), e recusa `http://` fora de loopback. Impressao
  digitada errada e ERRO, nao "sem pin" (ja foi um bug: lixo virava string vazia).
- **Regras que o Proxmox real impoe** (o `PveFalso` as repete, entao regredir quebra teste):
  tag na criacao e `keyctl` sao 403 para o token; tarefa `WARNINGS: n` e sucesso; a tag e
  gravada DEPOIS. A identidade de um CT do broker e o **pool**, nao a tag.
- **O OPNsense guarda porta em ALIAS.** `opnsense.portas_ocupadas` le o alias do resumo em
  HTML do `search_rule` e **falha fechada**: regra do WAN que nao entende => `ErroDeLeitura`
  e nada novo e aberto. Regra desativada continua ocupando a porta. `fechar` casa a
  descricao `gamepanel:<ctid>` por IGUALDADE (por prefixo, o 30 apagaria o 300).
- **`remover` nao libera CTID/IP de CT que talvez exista.** O token so enxerga o pool, e
  "apagado a mao" e "movido de pool" dao o mesmo 403; so `somente_banco` limpa o registro.
- **Job do broker nao e `start_job`.** Criar instancia demora minutos e nao tem servidor SSH
  ainda: `start_broker_job` grava um job SEM servidor e `acompanha_operacao` faz polling no
  broker gravando o log a cada volta (o `start_job` comum so grava no fim). No fim
  cadastra o servidor pelo `ensure_server`; se isso falhar o job diz que **a instancia
  existe** no Proxmox. `retoma_jobs_do_broker` religa o acompanhamento depois de um restart.
- **Tudo do broker e so de admin**, inclusive a saida dos jobs (`JOB_ACTIONS_ADMIN`): ela cita
  IP, CTID e portas. A rota empilha `@admin_required` e depois `@broker_required`.
- **`broker_client` e chamado sempre pelo modulo** (`broker_client.criar(...)`): e assim que os
  testes o trocam por um falso. Nao faca `from broker_client import criar`.
- **Tabela no celular: uma coluna.** Com estado e acoes em colunas proprias, as ACOES saiam
  da tela (rolagem lateral). Ver `instancias.html` e `catalogo.html`. E o servidor local so
  recarrega template com `GAMEPANEL_DEV=1`: sem ele voce testa o template ANTIGO.
- **Handler `Exception` do Flask engole 404/405** se nao houver um de `HTTPException` antes
  (ja aconteceu aqui: rota errada virava "erro interno").

---

## Deploy — os dois caminhos publicam a arvore inteira

| caminho | quando |
|---|---|
| `deploy-admin.ps1` | envio direto por SSH (troca codigo e reinicia) |
| `provision-admin-lxc.sh` | provisionamento completo pelo Proxmox (`pct push`) |
| `deploy-broker.ps1` + `provision-broker-lxc.sh` | o broker (CT proprio); ver a secao "Broker" |

**`ADMIN_HOST` do `.env` vence `ADMIN_IP_CIDR`** no atalho de envio direto do `deploy-admin.ps1`
(sem `-Full`): ao mudar o painel de CT/IP, troque os DOIS, senao o deploy cai no CT antigo e o
publica la (foi assim que o painel publico velho recebeu codigo novo sem ninguem pedir). `-Full`
segue o `ADMIN_CTID`. O deploy do broker tambem deduz o IP permitido a partir do `ADMIN_HOST`.

Os dois copiam `templates/` e `static/` **recursivamente**. Ao criar uma subpasta nova,
confira os dois — eles ja quebraram por copiar so o primeiro nivel. `static/maps` fica
de fora da limpeza: ela e criada dentro do container e nao existe no repo.

### PowerShell (`.ps1`)

Regras que ja custaram caro aqui (ver tambem a memoria do projeto):

- **ASCII puro.** O PowerShell 5.1 le `.ps1` sem BOM como ANSI; um travessao quebra o
  parse com erro enganoso. Confira: `[IO.File]::ReadAllBytes($p) | ? { $_ -gt 127 }`.
- **Variavel nao tem caixa**: `$x` e `$X` sao a mesma. Local com nome de parametro
  `[switch]` quebra em runtime.
- **stderr de executavel** (docker, ssh) precisa de wrapper com `ErrorActionPreference`
  relaxado, senao o script morre em cima de um sucesso.
- **Here-string que vai por ssh** leva `\r` do CRLF e quebra o bash do outro lado —
  normalize no `Invoke-Ssh`.
- **`Copy-AsLf` (ReadAllText + normaliza fim de linha) so serve para texto.** Aplicado a
  um `.png` ele decodifica o arquivo como UTF-8: todo byte fora do plano ASCII vira o
  caractere de substituicao (U+FFFD), e a assinatura de PNG (`89 50 4E 47 0D 0A 1A 0A`)
  chega no servidor como `EF BF BD 50 4E 47 0A 1A 0A` — arquivo corrompido, e o Chrome
  recusa o icone do PWA (`no-acceptable-icon`) sem avisar em lugar nenhum do deploy. Foi
  o que aconteceu: o loop que monta o bundle em `deploy-admin.ps1` passava todo arquivo
  de `admin/` por `Copy-AsLf`, exceto `__pycache__`. O fix e uma lista de extensoes de
  texto (`Copy-ArquivoDoAdmin`) — qualquer coisa fora dela vai por `Copy-Item` (copia de
  bytes, sem decodificar nada). Extensao binaria nova em `static/` (fonte, imagem)
  **entra binaria por padrao** — so vira texto se voce adicionar a extensao na lista.

---

## Escrita: comentarios, mensagens e texto de tela

O codigo aqui e comentado em **portugues sem acento**, e o padrao nao e descrever o que
a linha faz — e **por que ela e assim**, de preferencia com a consequencia de fazer
diferente:

```python
# Aba escondida nao gasta conexao ssh a toa; ao voltar, puxa na hora.
```

```css
/* 16px de base nao e escolha estetica: abaixo disso o Safari do iPhone da zoom
   sozinho ao focar um campo, e a tela inteira sai do lugar. */
```

Comentario que so repete o nome da funcao e ruido. Comentario que explica a armadilha
que voce acabou de desviar e o que impede a proxima pessoa (ou voce em tres meses) de
"simplificar" de volta para o bug.

Texto de tela: portugues direto, sem jargao de infraestrutura onde der. "O servidor
sera PARADO" e melhor que "o servico sera interrompido".
