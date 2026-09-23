# CLAUDE.md — como mexer neste repositorio

Deploy de servidores dedicados de jogos (Proxmox LXC ou Docker) mais um **painel web**
em `src/gamepanel/`. Este arquivo e sobre **como escrever codigo aqui**. O que o projeto
faz, e como usar, esta no [README.md](README.md) — nao duplique conteudo entre os dois.

## Regra numero um: TODO identificador e TODO nome de arquivo em INGLES

Vale para o repositorio inteiro e para toda linguagem daqui — Python, bash, PowerShell,
JavaScript, CSS, Jinja, YAML. Funcao, variavel (inclusive local e de laco), classe,
constante, parametro, campo, nome de arquivo e de pasta: **ingles**. Nao existe "e so um
script de apoio" nem "e so uma variavel temporaria"; um arquivo novo em portugues nasce
como divida que alguem vai ter de renomear depois, com o teste e o deploy no meio.

O que **nao** e identificador continua em **portugues sem acento**:

- comentario e docstring — e o padrao daqui explicar POR QUE a linha e assim, de
  preferencia com a consequencia de fazer diferente (ver a secao "Escrita", no fim);
- texto de tela, que vive no catalogo de `i18n/` (portugues e ingles, mesmas chaves);
- nome de TESTE (`def test_a_versao_aparece_no_rodape...`) e a saida dos sandboxes: sao
  frases descritivas, lidas como relatorio, nao nomes chamados de outro lugar;
- chave que ja esta gravada em banco, em disco ou numa API (`"chave"`, `"jogos"`,
  `GAMES_DIR`): mudar ali e mudar DADO, e exige migration — ver os grupos de contrato.

> **Reorganizacao de arquitetura em andamento** (ver `docs/architecture-analysis.md` e
> `docs/architecture-proposal.md`): o codigo saiu de `admin/`/`broker/` para
> `src/gamepanel/`/`src/gamebroker/` (Fase 3), os identificadores estao **em ingles** nos
> dois pacotes, e os dois grupos de mudanca de contrato ja foram: a API do broker (rotas,
> corpo, resposta, cabecalho) e as colunas do banco, cada um com a sua migration. A
> divisao de `app.py` em `services/`/`runtime/`/`tasks/`/`blueprints/` tambem ja foi: as
> 78 rotas moram em `blueprints/`, um arquivo por grupo de tela, e o `app.py` ficou com a
> montagem (banco, sessao, decoradores, tabelas).

O painel roda com poder de **root nos containers de jogo**. Isso muda o peso de tudo:
um botao errado para um servidor de verdade, um cache errado mostra um servidor caido
como se estivesse de pe.

---

## Verificar antes de dizer que terminou

O ambiente de desenvolvimento e um `docker compose` completo: painel + dois containers
de jogo falsos (com sshd, `systemctl` de mentira, query A2S, API REST e log).

```bash
docker compose up --build -d          # painel em http://localhost:8080 (admin/admin12345)
docker compose restart panel          # depois de mexer em app.py/navigation.py
```

As suites do painel (em `tests/gamepanel/`: `test_gamefields.py`, `test_config_format.py`,
`test_charts.py`, `test_schedules.py`, `test_users.py`, `test_players.py`,
`test_alerts.py`, `test_broker.py`, `test_broker_client.py`, `test_i18n.py`,
`test_template_contract.py`, `test_frontend_contract.py`, `test_javascript.py`,
`test_schema.py`, `test_docs_contract.py` e mais uma duzia) sao **pytest** — 964
testes ao todo (mais 901 do pacote `gamebroker`, em `tests/gamebroker/`), com
fixtures compartilhadas em `tests/gamepanel/conftest.py`
(`database`: tabelas limpas a cada teste; `webhooks`: captura o que sairia por HTTP;
`admin`/`operator`: um admin e um operador ja logados; `login`/`post`: entrar e POST com
CSRF). **Rode a suite inteira** depois de mexer em `app.py` — elas cobrem exatamente as
partes onde e facil quebrar algo sem perceber (quando o painel decide avisar, quem ve o
que, o que conta como jogador). Os arquivos ja NAO rodam como script solto
(`python3 test_alerts.py` nao faz nada) — passam sempre por `pytest`.

**Rapido, na maquina** (segundos, e o ciclo normal enquanto se edita):

```powershell
uv sync                          # cria .venv e instala gamepanel/gamebroker editaveis + dev (pytest/ruff/mypy)
uv run pytest                    # a suite inteira, da raiz do repo
uv run pytest tests\gamepanel\test_alerts.py -k test_loop_de_restart
```

`uv` (https://docs.astral.sh/uv/) gerencia SO o `.venv` de desenvolvimento —
`pyproject.toml`, na raiz, declara `flask` (versao que acompanha o apt do Debian 13) mais
o grupo `dev` (pytest/ruff/mypy), e `uv.lock` fixa as versoes exatas. Isso e ferramenta
de desenvolvimento, nunca dependencia do painel em producao (ver abaixo). `pytest.ini`,
na raiz, e quem diz onde procurar os testes (`tests/`) e desliga o cache em disco (ver o
comentario nele — o motivo e o mount read-only do container, nao o venv). O `.venv` tambem
e o que faz o editor resolver `import flask`/`import gamepanel`/`import gamebroker`, via
`pyrightconfig.json`.

**No container, que e a verdade** (mais lento; rode antes de publicar):

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -w /workspace panel python3 -m pytest -q
```

O servico `panel` do compose tem DOIS bind mounts: `src/gamepanel` -> `/opt/gamepanel/gamepanel`
(o codigo que o gunicorn de fato serve, mimetizando o layout de producao) e o repositorio
inteiro -> `/workspace` (so para achar `pytest.ini`, `tests/` e `src/` juntos e rodar a
suite completa). Sem pip nem uv ali dentro (so `python3-pytest` do apt — ver
`docker/panel/Dockerfile`), o `conftest.py` da raiz insere `src/` no `sys.path` na mao
para que `import gamepanel`/`import gamebroker` resolvam sem instalacao. **Rode com
`-p no:cacheprovider`** se quiser o mesmo silencio do venv; sem a flag os testes passam
igual, só com um aviso de cache que nao escreve (sistema de arquivos read-only).
**Rebuild a imagem** (`docker compose build panel`) se `pytest` não for encontrado ali
dentro. Um teste sensivel a `GAMEPANEL_DEV=1` (que o servico `panel` sempre sobe com) —
`test_broker.py::test_config_ruim_desliga_o_recurso_sem_derrubar_o_painel[http-fora-do-loopback]`
— so falha rodando desse jeito, contra o container AO VIVO; no `.venv` (sem essa
variavel) ele passa. Conhecido, nao e regressao de teste nenhum.

Uma diferenca conhecida entre os dois: **2 testes de `test_players.py` sao pulados no
Windows** (`@posix_apenas`, no proprio arquivo) — os que conferem que a pasta do socket
SSH so e visivel pelo dono (`0700`). E permissao POSIX pura: nao existe no Windows, e o
resultado so vale no container. Os outros 962 passam iguais nos dois lugares.

**`test_javascript.py` precisa do `node` no PATH** e e PULADO sem ele. Producao nao
tem node e o painel nao depende dele para nada: o teste so confere que cada modulo
parseia e importa, que e o degrau que faltava — ate aqui um `const` renomeado pela
metade so aparecia no console de quem abrisse a tela.

Templates e estaticos entram por bind mount: recarregar a pagina basta. `app.py` e
`navigation.py` sao recarregados pelo `--reload` do gunicorn, mas **rota nova ou mudanca
de decorador exige `docker compose restart panel`**.

Depois de mexer em template ou rota, passe por todas as telas:

```bash
J=/tmp/p.jar; rm -f $J
TOK=$(curl -s -c $J localhost:8080/login | grep -o 'value="[^"]*"' | head -1 | cut -d'"' -f2)
curl -s -b $J -c $J -o /dev/null -d "csrf=$TOK&username=admin&password=admin12345" localhost:8080/login
for p in / /servers/1 /servers/1/config /servers/1/files /servers/1/charts \
         /servers/1/backups /servers/1/schedules /servers/1/terminal \
         /servers/1/console /servers/1/edit /servers/1/players/discover \
         /history /alerts /users /account /ssh-key /servers/new \
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
VERSION                  a versao do repositorio (semver, a mao); tools/build-release.py a carimba no pacote
pyproject.toml          workspace uv: dependencias de dev (pytest/ruff/mypy), so gamepanel/gamebroker editaveis
pytest.ini               onde o pytest procura os testes (tests/) e config de cache
conftest.py              insere src/ no sys.path antes de qualquer teste (funciona sem `uv sync`)
games/                   catalogo curado de jogos (um *.env por jogo), lido pelo gamebroker E pelos
                        scripts de provisionamento em bash - por isso fica na raiz, fora de src/
lib/                     fases de instalacao de jogo (bash) + install-release.sh (publica um release no CT)
src/
  gamepanel/             o painel (era admin/)
    app.py               a montagem: banco, sessao, decoradores, tabelas, SSH, alertas, agendador
    config.py            TODA variavel GAMEPANEL_*, lida e conferida num lugar so
    version.py           a versao que esta rodando (le o _build.py do release, ou cai no VERSION+dev)
    blueprints/          a camada HTTP, um arquivo por grupo de tela (ver a secao propria)
    persistence/
      schema.py          esquema, MIGRATIONS e RENAMES
      repositories/      uma funcao por consulta; TODO o SQL do painel mora aqui
                         (servers, jobs, schedules, alerts, samples, settings, users)
    wsgi.py              entry point do gunicorn (`gamepanel.wsgi:app`)
    cli.py               bootstrap: --create-user, --reset-2fa, --register-server (o rodape de app.py chama o main() daqui)
    navigation.py        mapa da interface: navegacao e acoes   (puro, sem Flask; era ui.py)
    games/
      config_format.py   leitor/gravador de .ini/.json/.cfg do jogo (era gameconf.py)
      gamefields.py       catalogo: o que cada chave de config significa
      catalog/
        search.py          busca por nome/App ID sobre suggestions.py (era busca_de_jogos.py)
        templates.py        modelos do formulario "Adicionar jogo" (Unreal Linux); puro, so dado
                           (era modelos_de_jogo.py; `tests/gamebroker/test_templates.py` confere
                           que passam no validador do broker)
        suggestions.py      GERADO por tools/import-linuxgsm.py, nao edite (era sugestoes_de_jogos.py)
    i18n/
      __init__.py         cascata idioma->pt->chave, campos na frase, `Mensagem`; ver a secao propria
      pt.py               catalogo em portugues (o padrao)
      en.py               catalogo em ingles, MESMAS chaves (test_i18n.py cobra a paridade)
    security/
      totp.py             2FA, so stdlib
      qr.py               gerador de QR, so stdlib
      passwords.py        scrypt (hash, conferencia e a regra de senha boa)
      csrf.py             o token da sessao e a conferencia do POST
    integrations/
      broker_client.py    cliente do broker (so stdlib, TLS fixado por impressao); ver "Broker"
    templates/
      components/         macros: ui.html (generico) e servidor.html (dominio)
      *.html              uma tela cada
      sw.js.jinja         service worker    (template, nao estatico: tem versao dentro)
      manifest.webmanifest.jinja
    static/
      css/                tokens -> base -> layout -> components -> pages
      js/core/            format, http, poll, dom, dirty   (sem DOM de tela, reutilizavel)
      js/features/        um modulo por comportamento
      js/app.js           liga features aos elementos da pagina
      icons/
  gamebroker/             servico que cria instancias de jogo (Proxmox) e abre portas (OPNsense);
                         pacote Python, ver a secao "Broker" abaixo (era broker/)
tests/
  gamepanel/              as suites do painel (era admin/test_*.py + admin/conftest.py)
  gamebroker/             as suites do broker, mais os dobres de teste fake_http.py (era broker/test_*.py)
tools/
  build-release.py       empacota um release: dist/<pacote>-<versao>.tar.gz + .sha256 (so stdlib, determinista)
  import-linuxgsm.py   gera src/gamepanel/games/catalog/suggestions.py a partir do LinuxGSM (precisa de internet)
  verify-qr.py        verificacao manual do QR contra um leitor de verdade (venv descartavel)
```

`src/gamepanel/games/gamefields.py` ainda e um arquivo so (nao dividido em adapter por
jogo) — o que falta da Fase 4 (ver `docs/architecture-proposal.md`).

### As rotas moram em `blueprints/`, e chamam o `app.py` pelo MODULO

Cada arquivo de `src/gamepanel/blueprints/` e um grupo de tela (`servers.py`, `files.py`,
`alerts.py`, ...) e so faz trabalho de HTTP: ler o pedido, chamar quem decide, escolher o
template. O `app.py` registra todos no rodape, por `register_all(app)` — no FIM do
arquivo, quando tudo o que eles chamam ja existe.

- **Todo acesso ao `app.py` e `panel.X`**, nunca `from gamepanel.app import X`. Os testes
  trocam funcao por falsa com `monkeypatch.setattr(panel, "server_status", ...)`, que
  substitui o nome NO MODULO: um import direto copiaria a referencia na hora do import e
  a troca deixaria de valer **em silencio** — os testes passariam sem testar nada.
- **O que e da stdlib o blueprint importa sozinho** (`import time`, `import sqlite3`).
  `panel.time` funciona, mas so alonga e esconde de quem le de onde o nome vem.
- **Estado de modulo com `global` fica no `app.py`.** Um `global _reaper_started` dentro
  de um blueprint escreveria na copia do modulo DELE, e o painel ligaria uma thread nova
  a cada aba aberta. Por isso `_ensure_reaper()` mora no `app.py` e o blueprint so chama.
- **O endpoint e `grupo.view`**, entao repetir o grupo no nome da funcao so alonga:
  `servers.detail`, nao `servers.server_detail`. Em `url_for`, em `endpoint=` e nas
  tabelas de `navigation.py` o nome e sempre o completo, com ponto.
- **Blueprint novo** = um arquivo aqui e um nome nas duas listas de `register_all`. Se a
  rota precisa pular o segundo fator, tambem uma linha em `app.ENDPOINTS_WITHOUT_2FA`.

### Texto fixo devolvido por funcao nao traduz

Uma funcao que devolve `"A senha precisa ter ao menos 8 caracteres."` passa pelo
`translate` e sai IGUAL: a cascata nao acha a chave, entao devolve a propria string. A
tela em ingles mostrava portugues, e nenhum teste reclamava — nem o `test_i18n.py`, que
confere as CHAMADAS de `_()`, nao o valor de retorno de uma funcao qualquer.

Foram tres, achadas ao extrair codigo do `app.py`: as duas de senha
(`validate_password`) e o rotulo `broker-jogo` do historico, que era `"Jogo adicionado
ao catalogo"` escrito a mao dentro do dicionario de rotulos.

- **Erro que vai para a tela sai como `i18n.Message`**, e nao como texto. `Message` E
  uma `str`, entao `str(exc)`, f-string e `in` continuam funcionando.
- **`test_job_service.py` cobra que todo rotulo do historico seja chave de catalogo**,
  e que os dois idiomas a tenham. Foi ele que teria pego o `broker-jogo`.

### Opcao do painel: uma leitura so, no `config.py`

Toda `GAMEPANEL_*` e lida por `config.load()`, no import, e o `app.py` guarda o resultado
em `settings`. Antes eram ~45 `os.environ.get` espalhados, cada um com a sua conversao
inline — e duas consequencias, as duas em producao:

- **valor invalido derrubava o painel sem dizer qual era.** `int(os.environ.get(...))`
  com lixo levanta `ValueError: invalid literal for int() with base 10: 'abc'`, e a
  mensagem nao cita a variavel: quem lia o journal adivinhava entre 45;
- **nao havia faixa.** `GAMEPANEL_MONITOR_EVERY=0` fazia o monitor girar sem parar.

O desenho e o do broker: lista TODOS os problemas de uma vez, so pelo NOME da variavel —
nunca o valor, porque isso vai para o journal e ha segredo entre elas.

- **Opcao nova** = um campo em `Settings`, uma linha em `load()` e (se for do deploy) o
  nome em `$adminKeys` do `deploy-admin.ps1` mais o `render_panel_config`.
- **O `app.py` mantem os nomes de modulo** (`JOB_TIMEOUT = settings.job_timeout`). Nao e
  redundancia: os testes trocam `panel.X` por falso, e ler o `settings` direto faria a
  troca deixar de valer em silencio. `BROKER_REQUESTED` e `DEV` existem pelo mesmo
  motivo — sao lidos DENTRO de `_configure_broker`, que os testes reexecutam.
- **`test_settings.py` cobra que ninguem leia o ambiente por fora**, varrendo o pacote
  atras de `GAMEPANEL_` junto de `environ`. Uma leitura solta escapa da conferencia de
  faixa e some do lugar onde alguem procuraria a lista de opcoes.
- **Basename de teste e unico entre as duas suites.** Nao ha `__init__.py` em `tests/`,
  entao dois `test_config.py` quebram a COLETA inteira com "import file mismatch" — e o
  arquivo do painel virou `test_settings.py` por isso.

### SQL de uma tabela mora no repositorio dela

`persistence/repositories/` tem uma funcao por consulta, e toda funcao recebe a conexao
como PRIMEIRO parametro — nunca chama `db()`. A conexao e por requisicao e mora no `g`
do Flask: um repositorio que a buscasse sozinho nao serviria ao monitor nem ao agendador,
que rodam em thread propria sem `g`. Passar a conexao tambem e o que permite testar uma
consulta sem subir aplicacao nenhuma.

O motivo de existir: o mesmo `SELECT * FROM servers WHERE id = ?` estava escrito em oito
arquivos e a lista de colunas do `UPDATE` em mais quatro. Nada disso quebra ao renomear
uma coluna — quebra na PRIMEIRA VISITA a tela que usa a copia que ficou para tras, em
runtime, sem lint nem teste acusando.

- **`tests/gamepanel/test_sql_placement.py` guarda a regra**, por TABELA e nao em bloco:
  a tabela que ainda nao tem repositorio segue com SQL onde esta, e entra na lista
  `OWNED` quando for extraida. Uma lista que ja nasce completa e mentira.
- **Instrucao montada a partir da lista de colunas**, nunca escrita a mao quatro vezes.
  O `# noqa: S608` que isso exige tem o motivo na linha acima: nada vem de fora, e todo
  VALOR continua parametrizado.
- **O repositorio nao decide.** Sem `flash`, sem `abort`, sem traducao, sem regra de quem
  ve o que: isso e de quem chama. Ele so sabe ler e escrever linha.
- **Quem liga uma fonte de contagem grava os campos dela E o `player_source` na MESMA
  instrucao** (`use_query_port`, `use_http`, `use_log`). Separar deixaria um servidor
  apontando para uma fonte sem os campos dela preenchidos.
- **As sete tabelas estao extraidas**, e `.execute(` so aparece em `persistence/`. O
  guard cobre todas; tabela nova entra na lista `OWNED` ao ser criada.
- **O tipo honesto do repositorio encontra o que o SQL cru escondia.** `fetchone()`
  devolve `Any`, entao `row["x"]` com `row` nulo nao era erro para ninguem; uma funcao
  que declara `-> Row | None` faz o mypy apontar. Foram tres, todas com o mesmo desenho:
  sessao de um usuario APAGADO enquanto ela estava aberta.

### A regra que sustenta o resto: uma lista, um lugar

Antes, a lista de telas de um servidor estava escrita a mao em **seis templates**. Cada
um tinha um subconjunto diferente, e era por isso que "Graficos" existia numa tela e nao
na outra. Hoje ela esta em `ui.py`.

- **Tela nova de servidor** = uma linha em `ui.SERVER_SECTIONS`. Nao edite template
  de navegacao; nao existe mais.
- **Acao nova** (start/stop/...) = uma entrada em `ui.ACTIONS` (como aparece) + uma em
  `app.COMMANDS` (o que roda). Um `assert` no import quebra se as duas divergirem.
- **Fonte de contagem de jogadores nova** = uma funcao + uma linha em
  `app.COUNT_SOURCES`.
- **Alerta de recurso novo** = uma linha em `app.RESOURCE_ALERTS`.

Se voce se pegar escrevendo a mesma lista pela segunda vez, pare: ela pertence a uma
dessas tabelas.

---

## Python (`app.py`, `navigation.py`)

- **Dependencias do PAINEL EM PRODUCAO: so a stdlib mais o `python3-flask` do apt.** O
  container nao baixa pacote de lugar nenhum. Nada de `pip install`, nada de CDN. Isso
  nao muda com o `uv` — `uv` so gerencia o `.venv` de desenvolvimento (`pyroject.toml`
  na raiz), nunca entra em Dockerfile de producao nem em `provision-*-lxc.sh`. Se
  `import gamepanel`/`import flask` nao resolve no editor, rode `uv sync` (cria o
  `.venv` e instala os dois pacotes do repo como editaveis, mais o Flask que a
  producao usa e as ferramentas de dev — ver a secao de testes, no topo).
- **QR code e codigo proprio, so stdlib** (`security/qr.py`: modo byte, correcao M, versoes
  1-10 da ISO 18004). Existe pela mesma razao do TOTP: sem pip em producao, nao ha
  biblioteca de QR ali. A suite (`test_qr.py`) prova a matematica sem precisar de um
  leitor de verdade — Reed-Solomon com resto zero nas raizes do gerador, e a distancia
  minima 7 do BCH(15,5) dos bits de formato — porque `opencv-python-headless` (o
  decodificador de verdade) passa de 60 MB e nao entra no `.venv` de dev nem no painel.
  **Depois de mexer em `qr.py`, rode `tools/verify-qr.py`** numa venv DESCARTAVEL
  com `opencv-python-headless` e `segno` (nunca no `pyproject.toml` do repo): ele
  desenha o QR e confere que a camera (via OpenCV) le de volta o texto certo.
- **Segundo fator (2FA) e TOTP proprio, so stdlib** (`totp.py`, testado contra os vetores do RFC
  6238). Regras que os testes de `test_2fa.py` guardam: senha certa com 2FA NAO abre sessao (so grava
  `pre2fa`, sem `uid`, por 5 min); codigo usado nao vale de novo (`totp_last_step`, e o `UPDATE ... WHERE
  totp_last_step < ?` e o portao contra dois pedidos simultaneos); a trava do codigo e por USUARIO
  (5 em 15 min), nao por IP; desativar ou pedir codigos novos exige senha E codigo; recuperacao =
  8 codigos de uso unico, so o hash no banco. `GAMEPANEL_REQUIRE_2FA=1` (`ADMIN_REQUIRE_2FA` no `.env`)
  tranca quem nao ativou na tela de ativacao: so ligue DEPOIS de todo admin ter ativado. Saida de
  emergencia: `cd /opt/gamepanel && python3 -m gamepanel.cli --reset-2fa USUARIO` no CT do painel
  (o caminho por arquivo, `python3 /opt/gamepanel/gamepanel/app.py --reset-2fa`, faz o mesmo), ou "Desligar 2FA"
  em Usuarios. A tela de ativacao mostra um QR code (`qr.py`, ver acima) para escanear, a chave em
  texto para digitar a mao e um link `otpauth://` que abre o aplicativo no proprio celular.
- **`broker_required` (app.py) tambem exige o 2FA DA PESSOA, sempre** — independente de
  `GAMEPANEL_REQUIRE_2FA` (que e sobre o painel inteiro). O broker cria/apaga CT e abre porta no
  OPNsense; e a unica barreira que sobra se uma sessao de admin for roubada. GET normal sem 2FA
  redireciona para `/account/2fa`; POST idem (nada e executado); `/api/...` responde 403 em JSON.
  A ordem importa: `GAMEPANEL_ALLOW_BROKER=0` ainda vence e mostra a mensagem dele, mesmo para
  quem nao tem 2FA (`test_allow_broker_desligado_vence_mesmo_para_quem_nao_tem_2fa`). Por isso,
  **em `test_broker.py` (so nele) a fixture `admin` ja vem com 2FA ativo** (override local que
  usa `admin_2fa` do `conftest.py`) — sem isso quase todo teste do arquivo cairia na tela de
  ativacao em vez de exercitar o que quer testar; `admin_without_2fa` e o admin sem 2FA, para provar a
  exigencia em si.
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
  quase sempre e o mesmo: separar *decidir* de *fazer*. `monitor_servers` virou
  `_monitor_rhythm` (o que vence agora) + `_server_alerts` (o que fazer com cada
  um) e caiu de 48 para menos de 10.
- **Literal repetido tres vezes vira constante.** `SHORT_DATE_FORMAT`, `PLAYER_MARK`,
  `_online_text()` nasceram assim — e o ultimo corrigiu um bug de brinde: uma das
  quatro copias dizia "0 jogadores online".
- **Mais de 13 parametros: passe um objeto.** `ensure_server` tinha 15; virou
  `DeployServer(NamedTuple)`. Quinze posicoes e onde um `join_re` vai parar no lugar
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
- **Dicionario de funcoes** (`RESOURCE_ALERTS`, `COUNT_SOURCES`) captura o objeto
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
sao o `monkeypatch` e a fixture `database` (tabelas limpas a cada teste, em
`tests/gamepanel/conftest.py`) que garantem o isolamento.

Essa troca **so alcanca quem chama pelo modulo**. E por isso que os blueprints fazem
`panel.server_status(...)` e nunca `from gamepanel.app import server_status`: o import
direto copia a referencia na hora do import, a troca do teste deixa de valer em silencio
e os testes passam sem testar nada. Vale para qualquer arquivo novo fora do `app.py`.

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

## Idioma da tela (`src/gamepanel/i18n/`)

O painel fala portugues e ingles. Dicionario Python, sem Babel e sem `.mo`: **este repo
nao tem passo de build** — producao so recebe arquivos e sobe (mesma razao do TOTP e do
QR serem codigo proprio). `pt.py` e `en.py` tem as MESMAS chaves, e `test_i18n.py`
cobra a paridade; a busca cai em cascata `idioma pedido -> pt -> a propria chave`, entao
chave que ninguem cadastrou aparece na tela como `nav.servers` em vez de sumir calada.

- **Texto novo de tela = uma linha em `pt.py` e uma em `en.py`.** A chave e
  `area.assunto`, **em ingles** (e identificador de codigo, nao texto de tela), e nunca
  o portugues transformado em slug: amarrar o nome da chave ao texto de UMA lingua faz
  corrigir uma virgula virar renomear em tres arquivos.
- **Frase com numero ou nome no meio nao se parte**: `_('flash.too_many_tries', n=30)`.
  Partir parece obvio e quebra na hora em que a outra lingua muda a ordem das palavras.
- **Frase com marcacao (`<strong>`, `<code>`) usa `_h()`**, nao `_()`. Um paragrafo de
  ajuda quebrado em uma chave por `<strong>` aparece metade em portugues na tela em
  ingles — o comeco da frase, que nao esta entre tags, nao entra em chave nenhuma. A
  frase vem do catalogo (codigo daqui, confiavel); os CAMPOS e que sao escapados.
- **Plural leva duas chaves** (`alert.players_online_one` / `_many`). Colar um `s` no
  fim funciona em portugues e ja falhava aqui.
- **Rotulo em tabela (`ALERT_EVENTS`, `JOB_LABELS`, `ROLE_LABELS`) guarda CHAVE**, nunca
  o texto: a chave do dicionario (`caiu`, `edit-config`) vai para o banco e para o
  `<option value=>`, e nao pode mudar porque alguem mexeu na redacao. Quem traduz e o
  `labels_of()` na hora de renderizar.
- **Texto que nasce em `services/`/`runtime/` usa `i18n.Message`**, que e uma `str` de
  proposito: carrega a chave e os campos, mas `str(exc)`, `f"{erro}"`, `"pedaco" in
  erro` e o `logging` continuam funcionando sem mudanca. Quem quer o idioma da pessoa
  chama `translate`; esquecer cai no idioma do deploy, que era o comportamento antigo.
- **Fora de pedido vale `GAMEPANEL_LANG`, nao a pessoa.** Monitor e agendador rodam em
  thread propria, sem `g` nem `request` — `current_language()` tem um portao para isso, e
  sem ele traduzir um alerta derruba a volta inteira do monitor com "Working outside of
  application context". Pelo mesmo motivo o alerta que vai para o canal e o texto
  GRAVADO num job usam o idioma do deploy (`label_for_db`): o historico e lido
  depois, por outra pessoa, e a mesma acao escrita de tres jeitos quebraria o filtro.
- Conferir uma tela nos dois idiomas: `POST /account/idioma` com `lang=pt|en`. Sem
  sessao (tela de login) vale o `Accept-Language` do navegador.

---

## Renomear identificador aqui: o que nao esta em nenhum linter

Traduzir os dois pacotes para ingles derrubou codigo seis vezes, sempre pelo mesmo
motivo: **o nome existe tambem como TEXTO em algum lugar**, e nenhuma ferramenta liga
os dois. Renomeie por `tokenize` (so token NAME) e nunca por `re` — `portas` aparece
dentro de frase em prosa e como chave de dicionario. Depois, procure cada um destes:

- **Chave de dado que parece identificador.** `d.update(porta_extra=8888)` e kwarg na
  sintaxe e campo do JSON na pratica; `ConfigBroker(**cfg_parcial)` e `CliDeps(**base)`
  recebem o nome do campo por texto. Formato de API, de disco e de banco nao muda junto
  com o codigo.
- **`@pytest.mark.parametrize("nome", ...)`.** O argname e uma string; o pytest so
  reclama na COLETA, depois que o rename ja passou por tudo.
- **`monkeypatch.setattr(panel, "nome")`.** Pior que o anterior: se o nome nao existir
  mais, o teste pode PASSAR sem testar nada.
- **Captura de rota do Flask.** `<int:instancia_id>` casa com o parametro do handler pelo
  nome — renomear so o parametro da 500 em toda chamada. O nome da captura nao aparece
  na URL, entao ele pode acompanhar; o da ROTA nao, que o `url_for` dos templates usa.
- **Colisao com nome que ja existe.** `LogStream` ja tinha `stop()` e o Event `parar`
  caiu em cima; `acao_de_jogador` virou `player_action` e passou a chamar a rota de mesmo
  nome, recursivamente. Foi o mesmo motivo do apelido `term_runtime`, no topo do `app.py`.
- **Marcador de frase do i18n.** O catalogo diz `{name}` e o chamador passa `name=`: sao
  a mesma coisa. Renomear um so quebra a substituicao, e `translate` engole o `KeyError`
  de proposito — o defeito sai CALADO. `test_i18n.py` cobra isso lendo o AST de cada
  `_()`/`_h()`/`Message()`.

E o que nenhum teste pegava antes: **kwarg de `render_template`**. Trocar
`instancias=` por `instances=` deixa a tela VAZIA — 200, sem erro, sem log, porque o
Jinja trata variavel ausente como indefinida. Agora `tests/gamepanel/test_template_contract.py`
confere cada kwarg contra o que os templates de fato leem. Ainda assim, **passe pelas
telas a mao** (a varredura de `curl` abaixo): foi so ali que apareceram o eixo de
grafico sem numero e a macro `energia` chamada pelo nome velho.

---

## O contrato do front: template, CSS e JavaScript

O mesmo defeito do contrato de template, em mais tres pares. Em todos, o nome existe
como TEXTO dos dois lados e nenhuma ferramenta liga os dois; em todos, a pagina continua
respondendo 200.

- classe so no `class=` = estilo que nunca chega, e a tela abre torta;
- classe so no `.css` = regra morta, que a proxima pessoa le como se estivesse em uso;
- `data-*` so no template = comportamento que nao monta, sem nada no console;
- `data-*` so no JavaScript = feature que nunca encontra elemento nenhum.

`tests/gamepanel/test_frontend_contract.py` cobra os quatro, mais o contrato de LEITURA
do medidor (`metrics.X` no `server_detail.html` contra o que o `parse_metrics` entrega —
a lista sai do proprio codigo, nao de uma copia escrita a mao). Achados reais dele, na
primeira execucao: tres classes sem regra e sete regras mortas.

- **Regra de CSS que ninguem usa SAI.** Grandfathering uma lista de excecoes deixaria o
  teste fraco desde o primeiro dia — e a lista e que envelheceria em silencio.
- **Classe montada em runtime** (`{% set classes = classes + ['btn--' ~ variant] %}`)
  entra pelo PREFIXO: o teste junta `btn--` e aceita qualquer `btn--*`. Sem isso toda
  variacao pareceria morta.
- **`cores` e a palavra que colide**: nucleo de CPU em ingles, cor em portugues. Uma
  renomeacao automatica ja trocou uma pela outra nos dois lados e o numero de nucleos
  sumiu da tela. Ha um teste so para ela.

### A doc tambem tem rede

`tests/gamepanel/test_docs_contract.py` cobra que todo `modulo.nome` citado entre crases
NESTE arquivo ainda exista no codigo. Doc que envelhece nao e doc faltando: e doc que
MENTE, e manda a proxima pessoa procurar um nome que nao existe. Achou quatro de uma vez
na primeira execucao: a doc mandava procurar taken_ports no opnsense (o nome e
`busy_ports`), _limpar no instalador por SSH (e `_cleanup`) e somente_banco no broker
(e `db_only`), alem dos tres do `navigation.py` que ja estavam em ingles ha commits.

O escopo e estreito porque tres coisas tem o MESMO formato e nao sao referencia a codigo:
chave de i18n (`charts.players`), nome de arquivo (`compare.sh`) e modulo de fora
(`flask.g`). As duas primeiras saem por reconhecimento — a chave existe no catalogo, o
arquivo tem extensao —, e nao por lista. As quatro colisoes que sobram estao em
`NOT_CODE`, cada uma com o motivo ao lado.

### O JavaScript tem rede agora

`tests/gamepanel/test_javascript.py` (precisa do `node`; PULADO sem ele) faz tres
perguntas: cada modulo parseia, cada modulo IMPORTA, e cada feature MONTA contra um DOM
de mentira. Producao nao tem node e o painel nao depende dele para nada.

O terceiro e o que importa. Tres defeitos reais nasceram de renomeacao e nenhum apareceu
no servidor — 200 na pagina, HTML inteiro, e o erro no console de quem abriu a tela (o
`app.js` ainda o engole de proposito, para uma feature quebrada nao levar as outras):

- o `Poller` passou a expor `start()` e as features continuaram chamando `.iniciar()`;
- `readJSON(url, opcoes)` ficou lendo `options.headers`;
- `shortList` usava `rotulo` numa linha e `label` na seguinte.

**`app.js` exporta `FEATURES` so para este teste.** Sem a lista exportada nao ha como
montar cada feature sem um navegador.

### Renomear JavaScript: `${...}` e codigo, e metodo mora depois do ponto

- **Template literal nao e string inteira.** O trecho entre crases tem CODIGO dentro das
  chaves. Um renomeador que pula a crase deixa de fora exatamente o identificador que so
  aparece ali — foi assim que `rotulo` sobreviveu a tres passadas.
- **Membro de objeto precisa da posicao APOS o ponto**, que e justamente a que se exclui
  ao renomear variavel local. Meia-troca ali nao da erro de sintaxe nem de import.
- **Regex de seletor nao pode atravessar aspas.** Um padrao para `'.classe'` que aceita
  qualquer coisa ate a proxima aspa casou com `...opcoes.headers` no meio do codigo e o
  reescreveu.

### Renomear bash e PowerShell: comentario e mensagem ficam em portugues

So IDENTIFICADOR muda. A primeira tentativa trocou a palavra solta no arquivo e entrou
na prosa: `# e o caso de um release que quebra` virou `# e o run_case de...`, e o
`die "sha256 nao confere"` virou `"nao check"` — texto que o sandbox procura, e que
deixou de casar.

- **Uma posicao, uma troca.** `local origem="$1"` casa como declaracao E como
  atribuicao; aplicar as duas produziu `source_dir_dir` e `local extra_limits""` (sem o
  `=`). Os dois passaram no `bash -n` e so quebraram rodando.
- **`$(funcao)` dentro de aspas duplas e CODIGO.** Pular toda a aspa deixou `$(qual)`
  chamando uma funcao que ja tinha virado `host_path`.
- **`$(( ))` usa o nome SEM cifrao**: `falhas=$((falhas + 1))` precisa dos dois lados.
- **Prove com os quatro sandboxes**: `compare.sh` (instalador de jogo, byte a byte),
  `broker.sh`, `release.sh` e a suite. Foi o `compare.sh` que pegou a unit systemd que
  deixou de ser escrita.

### Renomear no front: cada nome no SEU escopo

- **Classe** troca no seletor do `.css` (com o ponto), dentro de `class="..."` e do
  argumento `css_class=` dos macros, e no `classList`/seletor/`class="..."` do JS.
  Trocar a palavra solta no arquivo mudaria dado: `key` tambem e variavel de template e
  chave de dicionario.
- **Seletor composto nao tem fronteira a esquerda.** Em `body.has-tabbar` o caractere
  antes do ponto e uma letra, entao um `(?<![\w-])` recusa o casamento e a regra fica
  para tras enquanto o template ja usa o nome novo. O ponto JA e a fronteira.
- **O hifen conta como fronteira para o `\b`**, entao `icon` casaria dentro de
  `btn--icon` e as duas trocas se atropelam. Use `(?<![\w-])x(?![\w-])`.
- **`data-x` tem duas formas**: o atributo no template e `dataset.xCamel` no JavaScript.
- **Parametro de macro Jinja vive em dois lugares**: a assinatura e o CORPO. Trocar so a
  assinatura da `'campos' is undefined` na primeira tela que usa o macro.
- **Macro chama macro sem prefixo** dentro do proprio arquivo (`{{ state(status) }}`, e
  nao `srv.state`): uma troca que so procura `ui.`/`srv.` deixa essas para tras.

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
- Todo POST usa os macros `ui.action` / `ui.menu_action`, que montam o CSRF sozinhos.

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
  mostra TODOS os destinos (`ui.NAV_DESKTOP_BAR`, sem icone e com rotulo `curto` onde ha, para
  caberem seis) e o menu do NOME da pessoa leva conta, chave SSH e sair (`NAV_DESKTOP_ACCOUNT`).
  No celular nada mudou: abas embaixo e o "⋯". Item aceso: `active_desktop_nav_for` (cada destino
  acende o proprio) x `active_nav_for` (as quatro abas do celular).
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
  com status 499 e o pedido nem chega ao servidor. A rota daqui e `/api/v1/resources`. Ao
  depurar "a requisicao some", compare **curl x navegador** antes de procurar bug no
  codigo.

---

## Broker (`src/gamebroker/`)

O painel nao guarda credencial de Proxmox nem de OPNsense: quem guarda e o broker, que
expoe verbos fixos (criar/desativar/remover instancia, catalogo). Pronto: nucleo,
backends REAIS de Proxmox (`proxmox.py`) e OPNsense (`opnsense.py`) e o cliente HTTP
(`conexao.py`), todos testados contra servidores falsos (`fake_http.py`), o instalador por
SSH (`ssh_install.py` + `lib/ct-install.sh`), a tela no painel e o DEPLOY do broker
(`config.py`, `prod.py`, `provision-broker-lxc.sh`, `deploy-broker.ps1`). Falta so uma criacao
REAL de ponta a ponta (nada disto rodou contra o seu Proxmox/OPNsense ainda). Segredos de
teste e de deploy ficam em `broker.secrets.env` (fora do git);
`check-broker-access.ps1` confere so leitura e `spike-broker-write.ps1` cria e
apaga um CT/regra de teste.

**Lado do painel** (`src/gamepanel/`): telas `/catalog` e `/instances`, flag
`GAMEPANEL_ALLOW_BROKER` (desligada por padrao; config ruim DESLIGA o recurso em vez de
derrubar o painel), `servers.broker_id` e `jobs.broker_op`. No compose de dev sobe um
broker de brinquedo (`gamebroker/dev.py`, backends falsos): `docker compose up --build`.

- **Um instalador de jogo, dois transportes.** As fases que rodam DENTRO do CT (SteamCMD,
  Wine/Proton, systemd) moram em `lib/ct-phases.sh`, lido por `provision-game-lxc.sh` (host:
  `pct exec`) e por `lib/ct-install.sh` (dentro do CT, o que o broker roda por SSH). O
  bundle do `deploy-game.ps1` e uma pasta SEM subpastas: a lib viaja como `ct-phases.sh` ao
  lado do script. **Mexeu numa fase? Rode `bash docker/ct-sandbox/compare.sh`** (precisa do
  Docker): roda o instalador ANTES e DEPOIS para 8 jogos com `pct`, `systemctl`, `apt-get` e
  SteamCMD falsos e faz diff de arquivos, conteudo e linhas de comando; tambem compara host x
  broker e confere o `install.env` que o Python gera. Sem isso a refatoracao e no escuro: nao
  existe teste de shell no repositorio.
- **`install.env` e sempre `shlex.quote`.** Hook (`PRE/POST_INSTALL_CMD`) so existe no catalogo
  curado; jogo da API escolhe **receitas** (`apply_recipes`, lista fechada), nunca escreve shell.
  Receita desconhecida derruba a instalacao. A chave do broker sai do CT ao fim
  (`_cleanup`, roda SEMPRE) e se ela nao sair a criacao FALHA.
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
- **`gamebroker/config.py` valida TUDO e lista TODOS os problemas de uma vez**, so pelo NOME da
  variavel (nunca o valor). Config ruim derruba o START (`SystemExit(2)`), nunca um pedido.
  https exige impressao SHA-256; http so em loopback.
- **Valor no `EnvironmentFile` do systemd:** `NOME="valor"` com `\` e `"` escapados (`$` nao
  expande ali). Teste com parser caractere a caractere: um regex guloso engole uma aspa sem
  escape e esconde o defeito.
- **Impressao dos certificados do Proxmox/OPNsense e lida do servidor no deploy (TOFU) e
  IMPRESSA para voce conferir.** Se ja souber a impressao, ponha em `*_CERT_SHA256`.
- **`gamebroker` e `gamepanel` sao os dois pacotes do workspace uv** (`src/gamebroker/`,
  `src/gamepanel/`), instalados editaveis no `.venv` por `uv sync` — e por isso que
  `import gamebroker.X` funciona em qualquer lugar do repo sem manipular `sys.path`.
  As suites de cada um vivem em `tests/gamebroker/`/`tests/gamepanel/`, testando o
  pacote instalado, nao um caminho relativo. Rode so o broker da raiz:
  `uv run pytest tests/gamebroker`.
- **`servico.py` so conhece as interfaces de `backends.py`.** Proxmox, OPNsense, SSH e rede
  reais entram depois sem mexer nele; os testes usam `fakes.py`.
- **Catalogo em dois niveis**: `games/*.env` (curado, pode ter `PRE/POST_INSTALL_CMD`) e
  jogos cadastrados pela API (**so dado**). O `.env` e lido por `catalog.read_env`, nunca por
  `source`, e campo que o broker nao conhece e RECUSADO — e assim que `pre_install_cmd`
  deixa de entrar de contrabando. Campo novo em jogo dinamico = regex propria em
  `services/catalog.py` e um caso em `CASOS_INVALIDOS` do teste.
- **Porta interna == externa, sempre.** Jogo `deslocavel` (`PORTS_SHIFTABLE=1`) recebe um bloco
  de portas seguidas da FAIXA do broker (`BROKER_PORT_INICIO/FIM`, padrao 31000-31999, abaixo das
  efemeras 32768+ e longe das portas padrao dos jogos), nunca as portas padrao; os demais ficam
  nas portas padrao e sao recusados se estiverem ocupadas. Isso e ir para a faixa mesmo com a
  porta padrao livre: mistura de "servidor antigo na porta padrao" com "servidor do broker na
  faixa" e o que impede um dia colidir. O jogo so e `deslocavel` se o broker consegue AVISA-LO de
  todas as portas: `START_ARGS` com `{PORT}` (e `{QUERY_PORT}` se ha query, `{EXTRA_PORT}` se ha
  porta extra) e nenhuma porta alem dessas tres (`catalog.shiftable_problem`, validado no
  carregamento). A porta extra (`EXTRA_PORT=`/`porta_extra`) existe por causa do Satisfactory: alem
  da principal (UDP+TCP) ele abre a 8888/TCP de mensagens confiaveis, que sem `-ReliablePort=` fica
  fixa e impede uma segunda instancia. O `ct-phases.sh` troca `{EXTRA_PORT}` como os outros dois; o
  marcador sem porta extra e recusado (viraria `0`). Hoje: Dragonwilds, Satisfactory, Palworld e
  Icarus. Enshrouded (portas no JSON) e DayZ (2303/2304 derivadas) nao. Ver `services/allocator.py`.
  No `compare.sh` o Satisfactory "antes x depois" roda sem o marcador (`satisfactory-legado.env`):
  o instalador de referencia nao o conhece e deixaria `{EXTRA_PORT}` literal no ExecStart.
- **Enderecos: o IP diz o CTID.** Painel `.100` (CT 300), broker `.101` (CT 301), jogos do
  broker `.102-.199` (CT 302-399): `CTID = BROKER_CTID_BASE (200) + ultimo numero do IP`, ou
  seja "3" + os dois ultimos digitos do IP (`allocator.pick_ip_and_ctid`; um IP so serve se o
  CTID dele tambem esta livre). Tudo em 300-399 e deste sistema; os CTs 2xx sao os antigos, feitos
  a mao ou pelo `deploy-game.ps1`, e ficam onde estao. As VMs 100-111 do Proxmox nao colidem. Com
  `BROKER_CTID_BASE=0` o CTID volta a ser escolhido a parte, na faixa `BROKER_CTID_INICIO/FIM`.
  **O DHCP do OPNsense nao pode cobrir `.100-.199`**: a checagem por ping nao pega um aparelho
  que ainda vai chegar.
- **Sugestoes de jogo (formulario "Adicionar jogo")** vem do LinuxGSM (MIT), convertidas por
  `python tools/import-linuxgsm.py` e commitadas em
  `src/gamepanel/games/catalog/suggestions.py` (110 jogos): o painel em producao NAO vai
  a internet (a API oficial da loja Steam nem serve: servidor dedicado e app do tipo
  "Tool" e volta `success:false`). Regras do conversor, cada uma com teste em
  `tests/gamebroker/test_import_linuxgsm.py` e `tests/gamebroker/test_suggestions.py`: so sai o que o
  `validate_dynamic` aceita; porta de RCON/telnet/HTTP vai so no argumento e NUNCA no NAT; variavel
  de senha/nome/IP/token nunca e resolvida (o argumento sai, com aviso); tudo depois de `; | & \`
  `$(` e cortado; variavel vazia derruba a opcao junto (senao ela engole a proxima). Protocolo e
  presumido UDP (so `reliableport`/`httpport` sao TCP): o aviso da sugestao diz isso. ~30 jogos
  guardam a porta no config do proprio jogo e saem como sugestao PARCIAL (App ID sem porta).
  Enshrouded, Icarus e Dragonwilds nao estao no LinuxGSM: continuam manuais. E a busca e SEMPRE
  sugestao: quem valida e o broker no envio.
- **Desfazer nao pode mentir**: se a limpeza falha, a reserva vira `falhou` e continua
  bloqueando IP/CTID/portas ate alguem remover (`instance_service._undo`).
- **TLS e por IMPRESSAO, nunca `verify=False`.** Proxmox e OPNsense sao autoassinados;
  `http_client.Client` aceita so o certificado cuja SHA-256 e a configurada (o
  `check-broker-access.ps1` a imprime), e recusa `http://` fora de loopback. Impressao
  digitada errada e ERRO, nao "sem pin" (ja foi um bug: lixo virava string vazia).
- **Regras que o Proxmox real impoe** (o `PveFalso` as repete, entao regredir quebra teste):
  tag na criacao e `keyctl` sao 403 para o token; tarefa `WARNINGS: n` e sucesso; a tag e
  gravada DEPOIS. A identidade de um CT do broker e o **pool**, nao a tag.
- **O OPNsense guarda porta em ALIAS.** `opnsense.busy_ports` le o alias do resumo em
  HTML do `search_rule` e **falha fechada**: regra do WAN que nao entende => `ErroDeLeitura`
  e nada novo e aberto. Regra desativada continua ocupando a porta. `fechar` casa a
  descricao `gamepanel:<ctid>` por IGUALDADE (por prefixo, o 30 apagaria o 300).
- **`remover` nao libera CTID/IP de CT que talvez exista.** O token so enxerga o pool, e
  "apagado a mao" e "movido de pool" dao o mesmo 403; so `db_only` limpa o registro.
- **Job do broker nao e `start_job`.** Criar instancia demora minutos e nao tem servidor SSH
  ainda: `start_broker_job` grava um job SEM servidor e `follow_operation` faz polling no
  broker gravando o log a cada volta (o `start_job` comum so grava no fim). No fim
  cadastra o servidor pelo `ensure_server`; se isso falhar o job diz que **a instancia
  existe** no Proxmox. `resume_broker_jobs` religa o acompanhamento depois de um restart.
- **Tudo do broker e so de admin**, inclusive a saida dos jobs (`JOB_ACTIONS_ADMIN`): ela cita
  IP, CTID e portas. A rota empilha `@admin_required` e depois `@broker_required`.
- **`broker_client` e chamado sempre pelo modulo** (`broker_client.create(...)`): e assim que os
  testes o trocam por um falso. Nao faca `from broker_client import create`.
- **Tabela no celular: uma coluna.** Com estado e acoes em colunas proprias, as ACOES saiam
  da tela (rolagem lateral). Ver `instancias.html` e `catalogo.html`. E o servidor local so
  recarrega template com `GAMEPANEL_DEV=1`: sem ele voce testa o template ANTIGO.
- **Handler `Exception` do Flask engole 404/405** se nao houver um de `HTTPException` antes
  (ja aconteceu aqui: rota errada virava "erro interno").
- **O formato de FIO da API mora em `domain/wire.py`, e nao no `SELECT`.** Antes,
  `/v1/instancias` devolvia `SELECT * FROM instancias`: o nome de cada coluna era, sem
  ninguem ter decidido, o nome de cada campo do JSON — renomear coluna quebrava o painel,
  e renomear campo pedia migration. Hoje ha uma funcao por recurso, com a lista de campos
  FIXA. O valor nao e traduzir nome (eles ate coincidem agora): e um `SELECT *` nao levar
  a proxima coluna para o contrato no dia em que ela nascer.
- **Coluna que muda de NOME tem mecanismo proprio.** No painel e `schema.RENAMES`
  (a pergunta do `MIGRATIONS` e "a coluna existe?"; aqui e "ela ainda tem o nome
  velho?"); no broker e `_migrate_names`, que renomeia tabela tambem. As duas usam
  `ALTER TABLE ... RENAME`, que preserva os dados — tabela nova mais copia e onde se
  perde linha. Renomear TABELA pede duas coisas a mais: a migration corre ANTES do
  `CREATE TABLE IF NOT EXISTS` (senao ele cria as novas vazias ao lado) e os indices e
  triggers velhos sao derrubados, porque carregam o nome antigo no corpo — um trigger
  de append-only apontando para tabela que nao existe mais e o mesmo que nao existir.
  Migration so roda no banco de quem JA tinha o sistema, e os outros testes vivem num
  banco novo: quem a exercita sao `tests/gamepanel/test_schema.py` e
  `tests/gamebroker/test_migration.py`, que montam o esquema antigo a mao.

---

## Versao e deploy — um artefato, publicado por symlink

A versao do repositorio esta no `VERSION` da raiz (semver, editado a mao). Quem a
transforma em identidade de um artefato e `tools/build-release.py`:

```bash
python tools/build-release.py gamepanel    # dist/gamepanel-0.1.0+abc1234.tar.gz + .sha256
python tools/build-release.py gamebroker
```

- **`_build.py` (versao, commit, data) e gravado DENTRO do tarball, nunca na arvore.**
  `git status` continua limpo depois de empacotar, e o `.gitignore` guarda `src/*/_build.py`
  caso um dia escape. Sem esse arquivo (rodando do repositorio) a versao vira `X.Y.Z+dev`,
  e a marca `+dev` e o que impede confundir "o painel do CT esta na 0.1.0" com "estou
  olhando a minha maquina".
- **O tarball e determinista**: nomes ordenados, dono/grupo zerados, mtime do commit e
  `mtime=0` no cabecalho do gzip. Dois empacotamentos do mesmo commit dao o MESMO sha256 —
  e e isso que faz o hash responder "o CT esta com este codigo?" em vez de so "o arquivo
  chegou inteiro?". **Sem git a data cai fora** (`built_at` vazio, mtime 0) de proposito:
  cair no relogio ali custaria o determinismo.
- **Arvore suja sai marcada `.dirty`** no nome do arquivo e na tela. Um release que nao
  corresponde a commit nenhum nao pode se parecer com um que corresponde.
- **Modulo que nao vai para producao sai por `SKIPPED_NAMES`/`SKIPPED_PREFIXES`**
  (`dev.py`, `conftest.py`, `fakes.py`, `fake_http.py`, `test_*`). O caso que importa e o
  `gamebroker/dev.py`: ele cria instancia contra backends falsos, e no CT de verdade seria
  um jeito de o broker mentir sobre o que existe.
- **A versao aparece em tres lugares**: o rodape de toda tela (`app.version`), o `/health`
  (`{"status","version","commit","built_at"}`) e a marca do service worker. Num release a
  marca do worker E a versao; rodando do repositorio ela volta a ser o mtime dos estaticos,
  porque so o mtime muda quando se salva um CSS sem empacotar nada.

O que o deploy manda e esse tarball mais `lib/install-release.sh`, e o instalador e **o
mesmo** nos dois caminhos:

| caminho | quando |
|---|---|
| `deploy-admin.ps1` | envio direto por SSH (empacota, manda 2 arquivos e reinicia) |
| `provision-admin-lxc.sh` | provisionamento completo pelo Proxmox (`pct push` do tarball) |
| `deploy-broker.ps1` + `provision-broker-lxc.sh` | o broker (CT proprio); ver a secao "Broker" |

```
/opt/gamepanel/releases/0.1.0+abc1234/gamepanel/...
/opt/gamepanel/current -> releases/0.1.0+abc1234     # WorkingDirectory da unit
```

- **Release e PASTA NOVA, nunca copia por cima.** Antes cada caminho tinha a sua lista
  escrita a mao de quais subpastas apagar antes de copiar (`templates/ games/ security/
  integrations/`), e as duas ficaram para tras a cada pasta nova do pacote — `blueprints/`,
  `i18n/`, `persistence/`, `runtime/`, `services/` e `tasks/` nunca entraram. Resultado:
  modulo renomeado continuava vivo no container, importavel, sem ninguem ver. Com pasta por
  versao nao existe o que sobrar. **Nao devolva a lista.**
- **Voltar uma versao = mover o symlink.** `install-release.sh` guarda 5 releases, e faz o
  rollback sozinho quando o servico nao sobe ou a sonda de saude nao responde.
- **A troca do symlink e `ln -sfn` ao lado + `mv -T`**, nunca `ln -sfn` direto: num symlink
  que ja existe o `ln` cria o link DENTRO da pasta apontada. O `mv -T` e atomico.
- **O deploy confirma pelo `/health`**, nao por `systemctl is-active`: "o servico esta de
  pe" e compativel com "o systemd reiniciou a versao velha", e os dois dao verde.
- **Tarball vai por `Copy-Item`/`pct push`, nunca por `Copy-AsLf`/`tee`.** O normalizador de
  fim de linha decodifica como UTF-8 e corrompe binario (foi como os icones do PWA
  chegaram quebrados). `Copy-AsLf` hoje so ve `.sh`.
- **Mexeu no `install-release.sh` ou no empacotador? Rode `bash docker/ct-sandbox/release.sh`**
  (21 verificacoes: sha errado, pasta da versao, virada do symlink, remocao do layout
  antigo, rollback) e `bash docker/ct-sandbox/broker.sh`. Nao existe teste de shell no
  repositorio; a prova e o sandbox.

**`ADMIN_HOST` do `.env` vence `ADMIN_IP_CIDR`** no atalho de envio direto do `deploy-admin.ps1`
(sem `-Full`): ao mudar o painel de CT/IP, troque os DOIS, senao o deploy cai no CT antigo e o
publica la (foi assim que o painel publico velho recebeu codigo novo sem ninguem pedir). `-Full`
segue o `ADMIN_CTID`. O deploy do broker tambem deduz o IP permitido a partir do `ADMIN_HOST`.

`lib/` e `games/` do broker continuam viajando soltos: nao sao o pacote Python, e sim
scripts de instalacao e o catalogo curado, lidos em caminho absoluto. O provisionamento
troca os dois por inteiro.

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
