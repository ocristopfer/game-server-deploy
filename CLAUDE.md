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

As sete suites (`test_gamefields.py`, `test_gameconf.py`, `test_charts.py`,
`test_schedules.py`, `test_users.py`, `test_players.py`, `test_alerts.py`) sao **pytest**
— 323 testes ao todo, com fixtures compartilhadas em `admin/conftest.py`
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
pytest.ini             onde o pytest procura os testes (admin/) e config de cache
admin/
  app.py               rotas, SSH, banco, alertas, agendador  (arquivo grande; ver abaixo)
  ui.py                mapa da interface: navegacao e acoes   (puro, sem Flask)
  gameconf.py          leitor/gravador de .ini/.json/.cfg do jogo
  gamefields.py        catalogo: o que cada chave de config significa
  conftest.py          fixtures pytest compartilhadas: banco, webhooks, chefe, peao...
  test_*.py            as 7 suites (323 testes) - ver a secao de testes, no topo
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
separado. Hoje as sete suites dividem um processo (pytest as importa todas juntas), e
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
- **Nao batize rota de aplicacao com nome de telemetria.** `/api/metrics` e regra
  corriqueira de bloqueador (uBlock, AdGuard, DNS filtrado): o navegador devolve um pixel
  com status 499 e o pedido nem chega ao servidor. A rota daqui e `/api/recursos`. Ao
  depurar "a requisicao some", compare **curl x navegador** antes de procurar bug no
  codigo.

---

## Deploy — os dois caminhos publicam a arvore inteira

| caminho | quando |
|---|---|
| `deploy-admin.ps1` | envio direto por SSH (troca codigo e reinicia) |
| `provision-admin-lxc.sh` | provisionamento completo pelo Proxmox (`pct push`) |

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
