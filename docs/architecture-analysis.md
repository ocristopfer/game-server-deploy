# Análise de arquitetura — estado atual

> Levantamento read-only (Fase 1). Nenhum arquivo do projeto foi alterado para
> produzir este documento. Gerado em 2026-09-22, contra o `main` em `ee44d90`.
> Este documento é o insumo para a proposta de reorganização (Fase 2) — não é,
> em si, um plano de mudança.

## Sumário executivo

- **~17.100 linhas** de Python em `admin/` (das quais **8.175 só em `app.py`**,
  um monólito com rotas + regra de negócio + SSH/subprocess + SQL cru no mesmo
  arquivo) e **~5.750 linhas** em `broker/` (pacote menor, já com boa separação
  por interfaces).
- **Todos os testes passam** hoje: suíte inteira (`admin/` + `broker/`) verde,
  2 pulados no Windows (esperado, ver `CLAUDE.md`). Não há nenhum teste
  quebrado para "consertar antes de reorganizar".
- **Não existe CI/CD** no repositório (nenhum `.gitlab-ci.yml`, `Jenkinsfile`
  ou `.github/workflows` — só `docker-compose.yml` como `.yml`). Isso é
  trabalho novo, não integração com algo existente.
- **Não existem `ruff`, `mypy` nem Sonar configurados** hoje. Rodei os dois
  primeiros manualmente contra o código (ver seção 6): o resultado é
  **surpreendentemente limpo** para um código sem essas ferramentas — a
  esmagadora maioria dos achados de `ruff` vem de um único arquivo **gerado**
  (`sugestoes_de_jogos.py`), e `mypy` sem tipos ainda encontra poucas dezenas
  de problemas reais em ~23 mil linhas.
- **`broker/` já segue boa parte dos princípios que a Fase 2 vai pedir**
  (inversão de dependência via `typing.Protocol`, camada HTTP fina, acoplamento
  com `admin/` só por HTTP). **`admin/app.py` é o oposto**: um único arquivo
  com 44 seções funcionais diferentes, sem camada de serviço, sem DAO, com
  scripts bash como constantes de módulo ao lado de rotas Flask.
- **Existem DOIS runtimes de produção reais e documentados** — Proxmox LXC
  (`provision-game-lxc.sh`) e Docker puro (`deploy-docker.ps1` +
  `docker/gameserver/`) — o que já valida, na prática, a ideia de uma camada
  `runtime/` abstrata pedida na Fase 2 (não é solução para um problema
  hipotético; o projeto já tem dois runtimes concretos hoje).
- **Nomenclatura em português está em toda parte** — não é um desvio isolado,
  é a convenção predominante do projeto (identificadores Python, ~metade das
  rotas HTTP, duas tabelas do banco do painel, todos os módulos do broker,
  parâmetros de scripts `.ps1`). Isso torna a tradução para inglês um projeto
  do tamanho de uma reescrita parcial, não um rename mecânico — ver seção 7.

---

## 1. O que cada pasta/módulo faz hoje

| Caminho | O que é |
|---|---|
| `admin/` | Painel Flask. Um processo Python só, servido por gunicorn. Interface web completa: autenticação+2FA, CRUD de servidores, SSH remoto, terminal PTY, editor de arquivos, backups, monitor/alertas, agendador, gráficos, integração com o broker. |
| `broker/` | Serviço HTTP separado (pacote Python próprio, `__init__.py`). Cria/desativa/remove instâncias de jogo via API do Proxmox e abre/fecha portas via API do OPNsense. Guarda as credenciais que o painel nunca vê. |
| `games/` | Catálogo **curado** de jogos: um `.env` declarativo por jogo (`dayz.env`, `palworld.env`, ...), lido por `broker/catalogo.py` com parser próprio (nunca `source`/shell). |
| `docker/` | Seis subpastas, com papéis bem diferentes entre si (ver seção 3): ambiente de **dev** (`panel/`, `broker/`, `game/`), runtime de **produção alternativa** (`gameserver/`, usada por `deploy-docker.ps1`), e ambiente de **teste** (`ct-sandbox/`, compara o instalador antes/depois de mudanças). |
| `lib/` | Duas fases de instalação de jogo (`ct-phases.sh`, `ct-install.sh`) compartilhadas entre o caminho Proxmox (host, via `pct exec`) e o caminho broker (dentro do CT, via SSH). |
| `tools/` | Scripts manuais de desenvolvimento: `import-linuxgsm.py` (gera `admin/sugestoes_de_jogos.py`) e `verify-qr.py` (valida `admin/qr.py` contra um leitor real de QR). Nenhum dos dois roda em produção nem no pytest. |
| `*.ps1` na raiz (`deploy-*.ps1`, `check-broker-access.ps1`, `spike-broker-write.ps1`) | Scripts de deploy (Proxmox e Docker) e duas ferramentas manuais de diagnóstico/prova de acesso — nenhuma delas chamada pelo deploy automatizado. |
| `*.sh` na raiz (`provision-*.sh`) | Scripts que rodam **no host Proxmox** (enviados por `pct push`/scp pelos `.ps1`) para provisionar CTs: painel, broker, jogo (via Steam) e TeamSpeak (caminho próprio, não vem da Steam). |
| `pytest.ini`, `pyrightconfig.json` | Config de teste (raiz, cobre `admin/` e `broker/`) e config do editor (Pylance/Pyright) — não afetam o runtime. |
| `.env` / `.env.example` (raiz) | Config de **deploy-time** (Proxmox/Docker) — não é o que o processo Python lê em produção (ver seção 3 e 7). |

`services/` aparece como diretório vazio no disco, mas **não está rastreado
pelo git** (não há nenhum arquivo dentro) — não é um módulo em uso, é resíduo
local; não precisa entrar no mapeamento da Fase 2.

### 1.1 `admin/` — arquivo por arquivo

| Arquivo | Linhas | Responsabilidade |
|---|---|---|
| `app.py` | 8.175 | Rotas Flask, schema/migrações SQLite, auth+CSRF+2FA, SSH/subprocess, A2S, HTTP de API de jogo, parsing de log, monitor/alertas, agendador, terminal PTY, editor de arquivos, backups, integração com broker, gráficos SVG, bootstrap CLI. **Tudo em um módulo.** |
| `ui.py` | 292 | Mapa de navegação (`NAV_PRINCIPAL`, `SECOES_DO_SERVIDOR`) e ações de energia (`ACOES`). Puro — zero Flask, zero banco. |
| `gameconf.py` | 715 | Parser/gravador de texto de config de jogo (ini/json/serverDZ.cfg), preservando formatação. Puro. |
| `gamefields.py` | 419 | Catálogo estático (`ENSHROUDED`, `PALWORLD`, `ICARUS`, `DAYZ`, `DRAGONWILDS`) que dá semântica às chaves que `gameconf.py` lê. |
| `broker_client.py` | 191 | Cliente HTTP stdlib-only do broker, TLS fixado por SHA-256. Único ponto de contato do painel com o processo broker. |
| `totp.py` | 122 | TOTP RFC 6238 + códigos de recuperação, stdlib puro. |
| `qr.py` | 301 | Gerador de QR code (ISO 18004) implementado do zero, sem libs externas. |
| `busca_de_jogos.py` | 62 | Busca por nome/App ID sobre o catálogo gerado. |
| `modelos_de_jogo.py` | 68 | Modelo estático "Unreal Linux" para pré-preencher o formulário de catálogo. |
| `sugestoes_de_jogos.py` | 1.811 | **Gerado** por `tools/import-linuxgsm.py` — dado estático, não editar à mão. |

### 1.2 `broker/` — arquivo por arquivo

| Arquivo | Linhas | Responsabilidade |
|---|---|---|
| `__init__.py` | 5 | Docstring do pacote. |
| `api.py` | 113 | Camada HTTP pura (Flask): registra as 7 rotas `/v1/*`, autentica, traduz exceções de domínio em JSON. **Nenhuma regra de negócio aqui** (comentário explícito no código). |
| `servico.py` | 252 | Orquestração/regra de negócio: criar/desativar/remover instância, cotas, reserva atômica de CTID/IP/porta, execução assíncrona em thread, desfazer em falha. Único módulo que conhece banco+catálogo+backends ao mesmo tempo. |
| `backends.py` | 71 | Quatro `Protocol` (`Proxmox`, `Opnsense`, `Instalador`, `Rede`) — as interfaces que `servico.py` conhece. |
| `proxmox.py` | 192 | Backend real do Proxmox (API REST). |
| `opnsense.py` | 218 | Backend real do OPNsense (portas via alias/HTML, falha fechada). |
| `ssh_install.py` | 253 | Implementação real de `Instalador`: `ssh`/`scp`, `install.env` sempre `shlex.quote`, remove a própria chave ao final. |
| `rede.py` | 25 | Implementação real de `Rede` (ping). |
| `fakes.py` | 101 | Os quatro backends falsos (testes e `dev.py`). |
| `fake_http.py` | 259 | Servidores HTTP falsos que reproduzem regras reais do Proxmox/OPNsense descobertas em spike. |
| `catalogo.py` | 546 | O maior arquivo do pacote. Parser de `.env` sem shell, catálogo curado + dinâmico, persistência JSON atômica. |
| `alocador.py` | 120 | Funções puras: escolher CTID/IP, alocar portas. |
| `conexao.py` | 144 | Cliente HTTP stdlib com TLS pinado por SHA-256 — usado por `proxmox.py` e `opnsense.py`. |
| `banco.py` | 223 | Schema SQLite e toda a persistência — acessado **só** por `servico.py`. |
| `config.py` | 207 | Lê/valida todas as env vars `BROKER_*`/`PROXMOX_*`/`OPNSENSE_*`, acumulando todos os erros antes de recusar subir. |
| `erros.py` | 42 | Hierarquia de exceções HTTP-aware (`Recusa` → `ErroDeValidacao`, `NaoEncontrado`, `Conflito` → `SemRecurso`, `CotaExcedida`). |
| `dev.py` | 57 | Entry point de dev (`python3 -m broker.dev`) — backends 100% falsos, Flask dev server. |
| `prod.py` | 60 | Entry point de produção — factory WSGI para gunicorn, backends reais. |

---

## 2. Como os módulos se comunicam

### 2.1 `admin/` — grafo em estrela, sem ciclo

```
app.py  →  broker_client.py, busca_de_jogos.py, gameconf.py, gamefields.py,
           qr.py, totp.py, ui.py, modelos_de_jogo.py
busca_de_jogos.py → sugestoes_de_jogos.py (dado gerado)
```

`ui.py`, `gameconf.py`, `gamefields.py`, `totp.py`, `qr.py`, `modelos_de_jogo.py`
são folhas puras — zero import entre si, zero import de `app.py`. Não há
import circular. Isso é bom, mas é também **a única coisa boa a nível de
import** — a ausência de ciclos não impede que 44 responsabilidades diferentes
morem no mesmo arquivo (`app.py`).

Este grafo em estrela é também o que sustenta o padrão de teste do projeto
(`monkeypatch.setattr(panel, "funcao", ...)`, documentado no `CLAUDE.md`):
qualquer refactor que mova uma função de `app.py` para um submódulo importado
por referência de função (em vez de por nome do módulo) quebra esse padrão
em silêncio. Isso é uma restrição real para a Fase 3/4, não só um detalhe.

### 2.2 `broker/` — inversão de dependência de fato

```
erros.py, catalogo.py     — módulos de fundo, importados por quase tudo
alocador.py                → catalogo.py, erros.py
backends.py                → alocador.py, catalogo.py      (as 4 interfaces)
banco.py                   → alocador.py, erros.py
fakes.py                   → alocador.py, backends.py, catalogo.py
proxmox.py, opnsense.py    → conexao.py (+ alocador.py no opnsense)
ssh_install.py              → alocador.py, catalogo.py
config.py                  → alocador.py, conexao.py, proxmox.py, ssh_install.py
servico.py                  → alocador.py, backends.py, banco.py, catalogo.py, erros.py
api.py                      → erros.py, servico.py
dev.py                       → alocador.py, api.py, banco.py, catalogo.py, fakes.py, servico.py
prod.py                      → api.py, backends.py, banco.py, catalogo.py, config.py,
                                conexao.py, opnsense.py, proxmox.py, rede.py,
                                servico.py, ssh_install.py
```

Ponto central: **`servico.py` (a regra de negócio) nunca importa `proxmox.py`,
`opnsense.py`, `ssh_install.py`, `rede.py`, `config.py` nem `conexao.py`** — só
as interfaces em `backends.py`. Quem liga a implementação concreta ao serviço
são os entry points (`dev.py` com falsos, `prod.py` com reais). Isso já é o
desenho de inversão de dependência que a Fase 2 vai pedir para `admin/` —
`broker/` serve de referência de "como já fizemos isso aqui dentro".

### 2.3 Acoplamento entre `admin/` e `broker/`

**Confirmado por dois agentes independentes, por grep em todo o repo**: não
existe nenhum `import broker` / `from broker import` em `admin/`. A única
menção a "broker" em `app.py` é `import broker_client`, que é o módulo do
**próprio painel** (`admin/broker_client.py`), não o pacote `broker/`. A
comunicação é **só HTTP**, com TLS pinado por SHA-256 nos dois sentidos
(`admin/broker_client.py` e `broker/conexao.py` implementam,
independentemente, o mesmo padrão de pinagem — duplicação **intencional**:
cada lado da fronteira de confiança tem seu próprio pino, não compartilham
código de validação).

Isso significa que, arquitetonicamente, **`broker/` já poderia ser hoje um
serviço/processo totalmente separado do painel** (na prática, já é — mora em
outro CT Proxmox em produção) — a questão da Fase 2 não é "separar", é "em
que repositório/pacote ele deveria morar daqui pra frente" (ver a pergunta
explícita da Fase 2 sobre isso, e a recomendação na próxima seção).

### 2.4 Acoplamento problemático dentro de `admin/app.py`

Esta é a parte que mais importa para o plano de refactor:

- **Rotas chamando SSH/subprocess direto, sem camada intermediária.**
  Praticamente toda rota de arquivo/backup/config chama `ssh_run`/`ssh_output`
  inline (`console()`, `files()`, `config_quick()` → `load_config_doc()` →
  `read_file()`, `backup_create()`). Não há repositório/DAO nem service layer
  — a view Flask **é** a camada de infraestrutura.
- **Scripts bash como constantes de módulo, ao lado de rotas Flask no mesmo
  namespace**: `HTTP_FETCH_SCRIPT`, `LOG_FOLLOW_SCRIPT`, `LISTEN_PORTS_SCRIPT`,
  `METRICS_SCRIPT`, `LIST_SCRIPT`/`READ_SCRIPT`/`WRITE_SCRIPT`/`DELETE_SCRIPT`,
  `BACKUP_SCRIPT`/`RESTORE_SCRIPT`/`BACKUP_DELETE_SCRIPT`, `UPLOAD_SCRIPT`,
  `HTTP_PROBE_SCRIPT` — nove blocos de shell multi-linha (30–100 linhas cada)
  misturados com funções Python. Não há separação "infra remota" vs "lógica
  do painel".
- **Funções de "negócio" que decidem HTTP diretamente**: `_liga_contagem_a2s`,
  `_liga_contagem_http`, `_liga_contagem_log` fazem validação + `UPDATE` no
  banco + retornam `redirect(...)` (erro) ou `None` (sucesso) — a rota só
  repassa o retorno. Mistura camada HTTP com regra de negócio na mesma função.
- **Sete mecanismos de cache/lock ad-hoc**, sem abstração comum:
  `_players_cache`/`_metrics_cache`/`_status_cache`/`_estado_monitor`/
  `_streams`/`_terms`/`_login_fails`, cada um com seu próprio lock.
- **SQL cru espalhado por toda rota**, sem DAO — dezenas de
  `conn.execute("UPDATE ...")`/`SELECT` inline dentro das próprias funções de
  rota.
- **Exceção que já mostra o caminho certo**: `_ritmo_do_monitor` /
  `_alertas_do_servidor` (comentado no próprio `CLAUDE.md` como o exemplo de
  "separar decidir de fazer", cognitive complexity 48→<10) é a prova de que o
  padrão certo já foi aplicado uma vez neste arquivo — só que numa ilha; o
  resto de `app.py` não segue.

Isso confirma, com evidência concreta, a premissa da Fase 2 do pedido
original: `admin/app.py` precisa de uma camada HTTP fina + `services/` com a
regra de negócio + isolamento do runtime (SSH/subprocess) atrás de uma
interface — exatamente os quatro princípios listados no pedido.

---

## 3. Pontos de entrada

### 3.1 Painel (`admin/`)

| Ambiente | Como sobe |
|---|---|
| **Dev** (`docker compose up`) | `docker/panel/Dockerfile` (Debian 13 + `python3-flask`, `gunicorn`, `python3-pytest`) → `entrypoint.sh` gera chave SSH, cria usuário admin, semeia dados demo, sobe `gunicorn --workers 1 --threads 16 --timeout 120 --reload app:app`. Código entra por bind mount (`admin/` é `:ro` no compose). |
| **Produção via Proxmox LXC** | `deploy-admin.ps1 -Full` envia `provision-admin-lxc.sh` para o host Proxmox (scp+ssh). O script: cria/inicia o CT unprivileged, instala pacotes via apt (sem `python3-pytest`), cria usuário de sistema `gamepanel`, copia a árvore inteira (`pct push`, recursivo — não usa `tar` por ser menos determinístico), gera `/etc/gamepanel/panel.env` (**preservando** as linhas `GAMEPANEL_BROKER_*`/`GAMEPANEL_ALLOW_BROKER` de um deploy anterior do broker), gera a unit systemd (`gunicorn --workers 1 --threads 16 --timeout 120`, com `NoNewPrivileges`/`ProtectSystem=full`/`ProtectHome`) e inicia o serviço. |
| **Produção via envio direto** (`deploy-admin.ps1`, sem `-Full`) | Se o CT já responde por SSH: copia só `*.py`+`templates/`+`static/` (recursivo), limpa o destino, `chown`, apaga `__pycache__`, `systemctl restart gamepanel.service`. Decide o CT/IP de destino por `-PanelHost` > `ADMIN_HOST` do `.env` > `ADMIN_IP_CIDR` — **`ADMIN_HOST` vence `ADMIN_IP_CIDR`**, os dois precisam mudar juntos ao trocar o painel de CT. |

O processo Python em si **nunca lê `ADMIN_*`** — só `GAMEPANEL_*` (ver seção
1.2 do relatório do agente de `admin/`, confirmado por grep completo em
`app.py`). A conversão `ADMIN_*` → `GAMEPANEL_*` acontece só dentro de
`provision-admin-lxc.sh::render_panel_config`. Isso é importante para a Fase
2: renomear uma `GAMEPANEL_*` é breaking change de runtime; renomear uma
`ADMIN_*` é breaking change só de deploy-time.

### 3.2 Broker (`broker/`)

| Ambiente | Como sobe |
|---|---|
| **Dev** | `python3 -m broker.dev` — Flask dev server (`app.run`, `threaded=True`), backends 100% falsos, estado efêmero em `/tmp`. O próprio código marca isso com `# NOSONAR - so no compose de dev`. |
| **Produção** | `deploy-broker.ps1` → `provision-broker-lxc.sh`, CT **dedicado**, fora do pool `games`, **sem `openssh-server`** (nada entra por SSH; só `pct push`). Gera certificado autoassinado (TOFU, impressão SHA-256), token persistente entre deploys, `/etc/gamebroker/broker.env`. Unit systemd mais endurecida que a do painel (`ProtectSystem=strict`+`ReadWritePaths`, `ProtectKernelTunables`, `ProtectControlGroups`, `RestrictSUIDSGID`). Entry point WSGI: `broker.prod:criar_app_de_ambiente()`, gunicorn com TLS embutido (`--certfile`/`--keyfile`, 1 worker — a trava de IP mora em memória). |

### 3.3 Jogo — dois runtimes de produção paralelos

Isto é o achado mais relevante para o desenho da Fase 2:

1. **Proxmox LXC** (`deploy-game.ps1` → `provision-game-lxc.sh`, no host, via
   `pct exec`) — caminho "principal", cria um CT de verdade por jogo.
2. **Docker puro** (`deploy-docker.ps1` → `docker/gameserver/Dockerfile`) —
   caminho **documentado e ativo** no README ("Deploy em Docker, sem
   Proxmox"), para rodar em qualquer máquina com Docker (até PC pessoal, ou
   `DOCKER_HOST` remoto). Implementa `systemctl`/`journalctl` próprios
   (`docker/gameserver/systemctl.sh`, `supervisor.sh`) com a **mesma
   interface** que o caminho Proxmox usa de verdade — ou seja, já existe hoje
   uma camada de abstração de "como controlar o processo do jogo" com duas
   implementações.

As duas compartilham as fases de instalação via `lib/ct-phases.sh` /
`lib/ct-install.sh` (rodadas por `provision-game-lxc.sh` no host e por
`ssh_install.py` do broker dentro do CT). TeamSpeak é o único jogo com
provisionamento **totalmente à parte** (`provision-teamspeak-lxc.sh`, porque
não vem da Steam) — deliberadamente não reaproveita `provision-game-lxc.sh`
(comentário explícito no próprio arquivo), com ~150 linhas de boilerplate
duplicado entre os dois (`msg`/`warn`/`die`, `ensure_container`,
`push_file_to_ct`, etc.) — candidato natural a uma lib compartilhada de
"boilerplate de CT" se a duplicação virar problema de manutenção, mas hoje é
isolamento de risco deliberado, não descuido.

**Não confunda `docker/game/` com `docker/gameserver/`** — são coisas
diferentes apesar do nome parecido:
- `docker/game/` = servidor de jogo **falso** (sshd + `systemctl`/`journalctl`
  falsos + A2S falso + API REST falsa), usado só pelo `docker-compose.yml` de
  dev.
- `docker/gameserver/` = servidor de jogo **real** rodando em Docker puro
  (SteamCMD de verdade, supervisor próprio), usado por `deploy-docker.ps1` em
  produção.

Nenhum dos dois é código morto.

### 3.4 CI/CD

Confirmado por três buscas independentes (minha e dois agentes): **não existe
nenhum arquivo de CI no repositório** — nem `.gitlab-ci.yml`, nem
`.github/workflows`, nem `Jenkinsfile`. O único `.yml` é `docker-compose.yml`.
Isso significa que "adicionar ruff/mypy/Sonar ao pipeline do GitLab" (pedido
na Fase 1) é **criar do zero**, não integrar com algo existente — vale
confirmar com você se o alvo é GitLab CI mesmo (não há remoto GitLab
configurado que eu tenha visto; só uso local de git) ou se é outro CI.

---

## 4. Estado dos testes

Rodei a suíte inteira (`\.venv\Scripts\python.exe -m pytest`, da raiz,
conforme o `CLAUDE.md`): **todos os testes passam**, 2 pulados no Windows
(marcados `@posix_apenas` em `test_players.py`, checam permissão POSIX
`0700` do socket SSH — comportamento esperado e documentado, só vale no
container Linux). Não rodei a suíte também dentro do container Docker nesta
passada (evitar o tempo de build só para reconfirmar o que o `CLAUDE.md` já
garante); vale rodar lá antes de qualquer merge real da Fase 3/4, como o
próprio `CLAUDE.md` pede.

| Suíte | Testes | Cobre |
|---|---|---|
| `admin/test_alerts.py` | 81 | Quando o painel decide avisar (queda/volta, loop de restart, jogo mudo, recurso, diário) |
| `admin/test_players.py` | 49 | Contagem via API HTTP e descoberta de porta |
| `admin/test_broker.py` | 57 | Integração do painel com o broker (jobs assíncronos, cadastro) |
| `admin/test_users.py` | 31 | Papéis admin/operador |
| `admin/test_2fa.py` | 36 | Fluxo de login com TOTP |
| `admin/test_broker_client.py` | 21 | O que trafega/nunca vaza no cliente HTTP do broker |
| `admin/test_qr.py` | 21 | Propriedades matemáticas do QR (Reed-Solomon) |
| `admin/test_charts.py` | 20 | Amostras/retenção/matemática do SVG |
| `admin/test_schedules.py` | 18 | Agendamento e histórico |
| `admin/test_config_format.py` | 15 | Parser/gravador de config |
| `admin/test_totp.py` | 15 | TOTP isolado |
| `admin/test_search.py` | 12 | Busca de jogo |
| `admin/test_gamefields.py` | 11 | Catálogo de campos |
| `admin/test_ui.py` | 8 | Mapa de navegação |
| `broker/test_*.py` (12 arquivos) | ~415 | Alocação, config, catálogo, conexão, integração, Proxmox/OPNsense reais contra HTTP falso, importação do LinuxGSM, instalador SSH, modelos, porta extra, serviço, sugestões |

### 4.1 Lacunas de cobertura identificadas

Inferido pelos nomes/escopo dos testes (não confirmado linha a linha) — **não
há suíte dedicada a**:
- Editor de arquivos (`files`, `files/save|delete|upload|download`)
- Backups (`backups/criar|restaurar|remover|baixar`)
- Console de comando único (`console`)
- Terminal PTY interativo (`terminal`, `api_term_*`)

Essas são justamente as rotas mais privilegiadas (escrita/remoção arbitrária
de arquivo no container, shell interativo como root) e são exatamente onde a
Fase 4 pede para escrever teste de comportamento **antes** de refatorar — este
é o primeiro lugar onde essa regra vai se aplicar na prática.

Também não há teste isolado da máquina de estados de contagem **por log**
(`_events_by_name`/`_by_count`/`_meio_nome`, `_LogStream`) nem suíte dedicada
ao CRUD de servidor (`server_new`/`server_edit`/`server_delete`,
`_form_server`) — possivelmente cobertos de forma indireta por
`test_alerts.py`, mas sem teste direto.

---

## 5. Código morto, duplicado ou abandonado

**Nada que eu classificaria como "abandonado"** — o achado mais parecido com
isso (`docker/gameserver/` vs `docker/game/`) na verdade **não é** duplicação
morta; são dois runtimes ativos e documentados (ver seção 3.3). Da mesma
forma, `check-broker-access.ps1` e `spike-broker-write.ps1` parecem à
primeira vista "scripts soltos", mas são **ferramentas manuais de diagnóstico
intencionais**, referenciadas no texto de erro do `provision-broker-lxc.sh` e
não chamadas pelo deploy automatizado — não são código morto, são scripts de
operação.

Achados reais de duplicação/pontos de atenção:

- **`admin/app.py`, padrão "rodar script remoto e converter erro" repetido 7
  vezes** quase idêntico, nunca extraído em helper comum: `list_dir`,
  `stat_file`, `read_file`, `find_config_files`, `write_file`, `delete_file`,
  `list_backups`.
- **`admin/app.py`, três funções de fan-out por thread quase idênticas**:
  `all_status`, `all_metrics`, `all_players` implementam o mesmo padrão
  (spawn por servidor + `join(timeout=...)` + `setdefault` de erro), sem
  reaproveitar `em_paralelo` nem uma à outra.
- **Rota vestigial documentada como tal**: `files_search` existe só para não
  quebrar link/histórico antigo e redireciona para `config_quick` — o próprio
  código já explica isso no docstring; candidata a remoção se confirmarmos
  que não há mais link externo apontando para ela.
- **Duplicação intencional de pinagem TLS** entre `admin/broker_client.py` e
  `broker/conexao.py` — não é redundância acidental (cada lado da fronteira de
  confiança tem seu próprio pino), mas vale registrar como candidato a NÃO
  unificar na Fase 2, justamente por ser isolamento de segurança deliberado.
- **~150 linhas de boilerplate de CT duplicadas** entre
  `provision-game-lxc.sh` e `provision-teamspeak-lxc.sh` (também presente com
  variações em `lib/ct-phases.sh`) — deliberado (isolamento de risco), mas é o
  maior bloco de duplicação real do repositório.
- **Nenhum `TODO`/`FIXME`/`XXX`/`HACK`** encontrado em `admin/*.py` nem em
  `broker/*.py` (grep vazio nos dois). Nenhum bloco de código comentado
  identificado na leitura completa de `admin/`.

---

## 6. Levantamento de qualidade

Não havia `ruff`, `mypy` nem Sonar instalados/configurados neste repositório.
Instalei os dois primeiros **só no `.venv` de desenvolvimento** (ferramenta
local, não dependência do painel — mesmo espírito do `requirements-dev.txt`
existente) e rodei contra `admin/` e `broker/`, sem criar nenhum arquivo de
config (rule set default de cada ferramenta). Nenhum arquivo do projeto foi
alterado.

### 6.1 `ruff check admin broker` (regras default, sem config)

**329 ocorrências, mas 267 delas (81%) são um único falso positivo em um
único arquivo GERADO**: `admin/sugestoes_de_jogos.py` — `ISC004`
("implicit string concatenation"), disparado pelas listas de avisos em
múltiplas linhas do catálogo importado do LinuxGSM. Esse arquivo é gerado por
`tools/import-linuxgsm.py` e o próprio `CLAUDE.md` já diz "não edite" —
qualquer config de lint real precisa excluí-lo (ou excluir o gerador de rodar
lint nele).

**Excluindo esse arquivo, sobram ~62 ocorrências em todo o resto do
repositório** (~23 mil linhas), concentradas em poucos arquivos:

| Arquivo | Ocorrências |
|---|---|
| `admin/app.py` | 12 |
| `admin/gamefields.py` | 6 |
| `admin/conftest.py` | 5 |
| `admin/test_2fa.py` | 4 |
| `admin/qr.py` | 4 |
| `broker/test_proxmox.py`, `broker/test_opnsense.py` | 2 cada |
| `broker/ssh_install.py` | 2 |
| demais | 1 cada |

Regras mais relevantes (fora o ruído do arquivo gerado): `I001`
(imports não ordenados, 27×, mecânico), `FURB167` (alias de flag de regex,
10× — pode tocar o caso `\w`/`re.ASCII` que o próprio `CLAUDE.md` já discute),
`RUF100` (**9 `# noqa: BLE001` sem efeito** — o projeto usa esse padrão de
supressão em vários `except Exception` "que não deve derrubar o job", mas o
rule set default do `ruff` não tem `BLE001` habilitado; **uma config real de
ruff precisa habilitar o rule set que o `CLAUDE.md` já assume**, senão esses
comentários viram lixo silencioso), `S110` (1× `try/except/pass`),
`PLW1510`/`PLW1509` (subprocess sem `check=`, `Popen` com `preexec_fn` — vale
olhar de perto, é exatamente a categoria "uso inseguro de subprocess" citada
no pedido original).

### 6.2 `mypy admin broker` (sem tipos ainda, `--ignore-missing-imports`)

Rodei duas vezes: sem flag de plataforma (`53` linhas de saída) e com
`--platform linux` (`31` linhas). A diferença confirma um **falso positivo já
conhecido no próprio `pyrightconfig.json`**: sem indicar Linux, o mypy analisa
`app.py` contra a stdlib do Windows e acusa `fcntl.ioctl`, `os.setsid`,
`pty.openpty`, `signal.SIGHUP`, `os.killpg`/`getpgid` como inexistentes — é
exatamente o bloco que `app.py` já protege com `try/except ImportError` para
funcionar fora do Linux. **Qualquer config real de mypy neste projeto precisa
fixar `platform = "linux"`**, senão o CI vai reportar ~20 erros que não são
erros.

Com `--platform linux`, os **~31 erros restantes** (sem tipos declarados em
lugar nenhum ainda) se agrupam em:

- `attr-defined`/`arg-type`/`union-attr` (a maioria): principalmente onde uma
  função retorna `Any`/`object` implícito e o chamador usa como se fosse
  `str` (`busca_de_jogos.py:43-44`) ou onde um `sqlite3.Row | None` é indexado
  sem checar `None` antes (`app.py:709`).
- **`broker/config.py:184,207` — `**dict` passado para construir
  `ConfigProxmox`/`ConfigBroker`**: o padrão de "montar um objeto a partir de
  um dict genérico" (o mesmo padrão que o `CLAUDE.md` recomenda para evitar
  15 parâmetros posicionais) perde tipo nessa borda. Isso é um sinal concreto
  para a Fase 4: ao tipar esse código, vale considerar `TypedDict` ou
  validação explícita campo a campo em vez de `**dict[str, object]`.
  Mesmo padrão em `broker/prod.py:47`.
- `test_suggestions.py`/`test_templates.py`/`test_import_linuxgsm.py` — erros
  em torno de `importlib.util.module_from_spec(...)` sem checar `None`; é um
  idiom comum de teste (import dinâmico de módulo por path) e provavelmente
  fica melhor com um `# type: ignore` pontual do que reescrito.
- 13 ocorrências de `annotation-unchecked` (nota informativa, não erro — corpo
  de função sem tipo não é checado por padrão; some assim que a Fase 4 tipar
  as assinaturas).

**Conclusão prática**: o código já é "type-safe na prática" mesmo sem
anotação nenhuma — poucas dezenas de problemas reais em 23 mil linhas é uma
base muito mais fácil de tipar do que a média. A maior parte do trabalho da
Fase 4 aqui vai ser *escrever* as anotações, não *corrigir comportamento*.

### 6.3 Sonar

Não há `sonar-project.properties` nem config de Sonar em lugar nenhum do
repositório, e não há CI para rodar um `sonar-scanner` contra. Não tentei
rodar um scanner local sem saber que servidor Sonar (SonarCloud/SonarQube
self-hosted) o projeto deveria usar — isso é uma decisão sua para a Fase 2
(qual servidor, qual `sonar-project.properties`, quais quality gates).

---

## 7. Levantamento de idioma

### 7.1 O tamanho real do problema

Nomenclatura em português **não é exceção, é a convenção predominante** deste
projeto — em código, comentários (intencionalmente, por `CLAUDE.md`), rotas
HTTP, duas tabelas inteiras do banco do painel, praticamente todo `broker/`
(módulos, classes, funções), e a maioria dos parâmetros dos scripts `.ps1`.
Traduzir para inglês, seguindo o padrão pedido, é um trabalho do tamanho de
uma reescrita parcial guiada por testes — não um `rename` mecânico. Abaixo, a
lista separada por "custo de mudar".

### 7.2 Internos (sem contrato externo — renomear é seguro para fora, mas
quebra testes que usam `monkeypatch.setattr(panel, "nome", ...)` por string)

**`admin/app.py`** — a maior parte da lógica de domínio: `em_paralelo`,
`players_from_http`/`_log`, `server_players`, `all_players`/`_metrics`/
`_status`, `candidate_ports`, `probe_ports`/`_http_ports`, `notifica`,
`envia_webhook`, `mascara_url`, `webhooks_lista`, `webhook_config`,
`config_get`/`_set`, `monitora_servidores`, `_ritmo_do_monitor`,
`_alertas_do_servidor`, `_alerta_de_estado`/`_restart`/`_mudez`/`_log`/
`_disco`/`_memoria`/`_cpu`/`_jogadores`, `_avisa_por_nome`/`_contagem`,
`_texto_de_online`, `coleta_amostras`, `roda_agendamentos`,
`dispara_agendamento`, `venceu`, `ocorrencia_anterior`, `rotulo_agendamento`,
`agora_local`, `_cadastra_servidor_do_broker`, `acompanha_operacao`,
`retoma_jobs_do_broker`, `enriquece_settings`, `monta_grafico`,
`_segmentos_da_serie`, `usuario_logado`, `destino_seguro`, `_abre_sessao`,
`_confere_segundo_fator`, `valida_senha`, `conta_admins`,
`_liga_contagem_a2s`/`_http`/`_log`, `_form_server`, `_form_agendamento`,
`_campos_http`, `_caminhos_json`, `_caminho_log`, `_jogo_do_form`, `_ator`,
`job_ou_403`, `filtro_de_papel`, `jobs_do_servidor`. Tabelas de módulo:
`COMANDOS`, `FONTES_DE_CONTAGEM`, `ALERTAS_DE_RECURSO`, `MARCA_BASE`/
`_JOGADOR`/`_MENSAGEM`, `ROLE_LABELS`, `DIAS_SEMANA`. Classes: `_LogStream`,
`_Ritmo`, `ServidorDoDeploy`.

**`admin/ui.py`**: `ACOES`, `POR_CHAVE`, `SECOES_DO_SERVIDOR`,
`NAV_PRINCIPAL`/`_SECUNDARIA`/`_DESKTOP_BARRA`/`_DESKTOP_CONTA`,
`GRUPO_ENERGIA`/`_MANUTENCAO`.

**`admin/gameconf.py`**: `_le_par`, `_parse_tuple`, `_insere_novas`,
`_aplica_edit`, `SEM_SECAO`, `RAIZ`.

**`admin/gamefields.py`**: `describe`, `catalogo_de`, `_fator`, `_duracao`,
`_enum`, `_bool`, `ROTULO_NOME`, `ROTULO_SENHA_ENTRADA`/`_ADMIN`.

**`admin/busca_de_jogos.py`/`modelos_de_jogo.py`/`totp.py`**: `buscar`,
`para_o_formulario`, `_normaliza`, `Modelo`, `MODELOS`, `UNREAL_LINUX`,
`PROJETO`, `novo_segredo`, `codigo`, `passo_de`, `verificar`, `agrupar`,
`novos_codigos`, `hash_do_codigo`, `consumir`.

**`broker/` inteiro** (a esmagadora maioria do pacote): módulos
`alocador.py`, `servico.py`, `catalogo.py`, `conexao.py`, `rede.py`,
`erros.py`, `fakes.py`, `fake_http.py`; classes `Servico`, `Catalogo`,
`Jogo`, `Porta`, `PortaAlocada`, `EspecificacaoDeCt`, `ConfigBroker`,
`ConfigProxmox`, `ConfigSsh`, `Banco`, `Cliente`, `RedeReal`/`Falsa`,
`ProxmoxFalso`, `OpnsenseFalso`, `InstaladorFalso`/`Ssh`/`Lento`,
`ErroDeConexao`/`DoOpnsense`/`DeLeitura`/`DoProxmox`/`DeInstalacao`/
`DeConfig`/`DeValidacao`, `NaoEncontrado`, `Conflito`, `SemRecurso`,
`CotaExcedida`, `Recusa`; funções `escolher_ctid`/`_ip`/`_ip_e_ctid`,
`alocar_portas`, `montar_env`, `montar_servico`, `carregar`,
`carregar_curado`, `jogo_de_env`, `ler_env`, `validar_dinamico`,
`pertence_ao_broker`, `reservar`, `mudar_estado`.

### 7.3 Expostos externamente — mudar exige migration/breaking change

Esta é a lista que precisa da sua decisão explícita, item a item, na Fase 2.

**Rotas HTTP do painel** (path — metade português, metade inglês, já
inconsistente hoje): `/historico`, `/alertas` (+`/destinos`, `/testar`),
`/usuarios` (+`/papel`, `/senha`), `/agendamentos` (+`/alternar`, `/remover`,
`/rodar`), `/catalogo` (+`/novo`), `/instancias` (+`/nova`, `/desativar`,
`/remover`), `/servers/<id>/graficos`, `/servers/<id>/players/descobrir`
(+`/usar`, `/acao`), `/servers/<id>/backups` (+`/criar`, `/restaurar`,
`/remover`, `/baixar`).

**Rotas HTTP do broker** (todo o namespace `/v1/*` é português):
`/v1/saude`, `/v1/catalogo`, `/v1/instancias`, `/v1/instancias/<id>/desativar`,
`/v1/operacoes/<id>`.

**Chaves de JSON do contrato do broker** (payload/resposta, consumidas por
`admin/broker_client.py`): `jogo`, `nome`, `operacao_id`, `instancia_id`,
`confirma`, `somente_banco`, `removida`; em `Jogo.publico()`: `chave`,
`app_id`, `porta_jogo`/`_query`/`_extra`, `memoria_mb`, `cores`, `disco_gb`,
`receitas`, `deslocavel`, `origem`, `criavel`, `motivo`; em `/v1/saude`:
`broker`, `proxmox`, `opnsense`, `catalogo_erros`. **Códigos de erro** (parte
do contrato JSON, `erros.py`): `pedido-invalido`, `validacao`,
`nao-encontrado`, `conflito`, `sem-recurso`, `cota`, `nao-autenticado`,
`origem`, `interno`, `http`. Header `X-Ator`.

**Colunas de banco**:
- Painel — tabela `webhooks` inteira (`nome`, `url`, `eventos`, `ativo`,
  `criado_em`) e `alert_log` inteira (`criado_em`, `evento`, `titulo`,
  `detalhe`, `destino`, `status`, `erro`). As demais tabelas (`servers`,
  `users`, `jobs`, `schedules`, `samples`) já são majoritariamente inglês.
- Broker — schema inteiro é português: `ctid`, `ip`, `jogo`, `nome`,
  `hostname`, `estado`, `criado_por`, `criado_em`, `detalhe`, `base`,
  `numero`, `proto`, `papel`, `tipo`, `log`, `resultado`, `iniciada_em`,
  `terminada_em`, `quando`, `ator`, `verbo`, `alvo`, e os valores de estado
  `reservada`/`ativa`/`desativada`/`falhou`/`executando`/`ok`/`erro`.

**Variáveis de ambiente**: a única com palavra em português confirmada é
`BROKER_MAX_CRIACOES_HORA` (`.env.example`, `broker/config.py:199`) — o resto
do namespace `BROKER_*`/`GAMEPANEL_*`/`ADMIN_*` já é inglês, com prefixos
mistos só nos sufixos (`BROKER_IP_INICIO`/`_FIM`, `BROKER_PREFIXO_REDE`).
Também vale registrar: **`GAMEPANEL_*` (a config real de runtime do painel)
já é 100% inglês** — são ~55 chaves, nenhuma em português — o que restringe
bastante o escopo de breaking change de env var no lado do painel.

**Filtros Jinja registrados** (usados em todo template — quebrar sem
atualizar os templates quebra a tela inteira): `"nivel"`, `"duracao"`,
`"tamanho"`, `"ident"`.

**Endpoints Flask usados em `url_for()`**: mistura inconsistente já hoje —
os *paths* tendem a português mas os *nomes de endpoint* tendem a inglês
(`alerts`, `schedules`, `catalog`, `instances_list`, `instance_new` — nomes em
inglês para rotas de path em português). Renomear função de rota sem
atualizar todo `url_for()` correspondente quebra a navegação.

**Nomes de template que são caminho de arquivo**: `catalogo.html`,
`instancias.html` (português) vs `alerts.html`, `schedules.html`,
`users.html`, `history.html` (inglês) — já inconsistente com o nome da rota
correspondente hoje.

**Nomes de arquivo/módulo**: `admin/busca_de_jogos.py`,
`admin/modelos_de_jogo.py`, `admin/sugestoes_de_jogos.py`,
`tools/import-linuxgsm.py`, `tools/verify-qr.py`,
`check-broker-access.ps1`, `spike-broker-write.ps1`,
`broker.secrets.env`, `docker/ct-sandbox/compare.sh`, e praticamente todo
módulo de `broker/` (seção 7.2). Renomear arquivo referenciado por scripts de
deploy (`provision-*.sh` copiam por nome, `NAO_ENVIAR` filtra por regex de
nome) exige atualizar os dois lados.

**Boa notícia**: as chaves de JSON das rotas `/api/*` do **painel** (não do
broker) já são majoritariamente inglês (`reachable`, `service`, `error`,
`players`, `cpu_pct`, `mem_pct`, `max_players`, `server_name`) — não é
breaking change generalizado, é concentrado nas áreas listadas acima.

---

## 8. O que falta para a Fase 2

Este documento não propõe estrutura nova — isso é a Fase 2, e só deve
acontecer depois que você validar este levantamento. Pontos que a Fase 2 vai
precisar decidir, já adiantados aqui porque a evidência apareceu durante a
análise:

1. **`admin/app.py` é o item de maior risco/maior retorno do projeto.** 44
   seções funcionais em 8.175 linhas, sem service layer, sem DAO, com scripts
   bash misturados a rotas Flask. `broker/` não precisa do mesmo nível de
   cirurgia — já segue boa parte dos princípios pedidos.
2. **A pergunta "broker deveria ser pacote separado ou serviço à parte" já
   tem uma resposta parcial pela evidência**: ele já É operacionalmente um
   serviço à parte (roda em outro CT, fala só HTTP com o painel, nunca é
   importado pelo pacote do painel). A decisão real da Fase 2 é só sobre
   *onde no repositório* ele deve morar daqui pra frente (mesmo repo, pasta
   irmã de `admin/`, vs. repositório próprio) — não sobre a arquitetura em
   si, que já está separada.
3. **A camada `runtime/` (Docker vs processo local) não é hipotética** — já
   existem dois runtimes reais e documentados (Proxmox LXC, Docker puro) com
   scripts (`systemctl.sh`/`journalctl.sh` fake vs real) que já imitam a
   mesma interface. A Fase 2 pode formalizar isso em vez de inventar.
   TeamSpeak (não-Steam) precisa entrar nesse desenho também.
   `games/*.env` já é, na prática, o formato de "definição do que rodar"
   citado no pedido — a Fase 2 decide se ele vira o formato de adapter Python
   ou continua `.env` lido por um adapter genérico.
4. **Toda coluna/rota listada na seção 7.3 precisa da sua aprovação
   individual antes de entrar no plano de breaking changes** — o pedido
   original já exige isso; esta análise só concentra a lista para facilitar
   a decisão.
5. **Config de `ruff`/`mypy` real precisa, no mínimo**: excluir
   `admin/sugestoes_de_jogos.py` do lint (ou do fluxo, já que é gerado),
   habilitar o rule set que os `# noqa: BLE001` do `CLAUDE.md` já assumem,
   fixar `platform = "linux"` no mypy. Sem isso, a primeira rodada de CI vai
   reportar ~280 "problemas" que na verdade são 3 ajustes de configuração.
6. **Nenhum teste está quebrado hoje** — a Fase 3 (mover arquivo) não tem
   nenhuma dívida pré-existente para carregar; qualquer teste que quebrar
   durante o `git mv` é causado pela própria Fase 3, não algo herdado.
