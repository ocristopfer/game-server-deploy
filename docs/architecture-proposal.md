# Proposta de reorganização (Fase 2)

> Depende da leitura de [`architecture-analysis.md`](architecture-analysis.md) (Fase 1).
> Nada foi movido ou editado para produzir este documento — é só a proposta,
> para você aprovar antes da Fase 3 mexer em qualquer arquivo.

---

## 0. Gerenciador de dependências: faz sentido usar `uv`?

**Sim, mas só para o lado de desenvolvimento — nunca para produção.** A
restrição de produção do `CLAUDE.md` (`admin/requirements-dev.txt`: "o painel
em produção roda com o que o apt instala... e não baixa pacote de lugar
nenhum") é deliberada e **continua valendo exatamente como está**: `uv` não
entra em nenhum Dockerfile de produção nem em `provision-*-lxc.sh`. O que ele
substitui é só o fluxo `python -m venv .venv` + `pip install -r
requirements-dev.txt pytest` descrito no `CLAUDE.md` hoje.

**Por que vale a pena:**

- **Hoje a suíte de dev não é reprodutível de verdade**: `flask~=3.1.1` é a
  única versão pinada; `pytest`, e agora `ruff`/`mypy` (instalados manualmente
  na Fase 1), não têm versão fixa em lugar nenhum. Um `uv.lock` versionado
  resolve isso sem esforço extra — todo mundo (e o futuro CI) instala
  exatamente a mesma árvore de dependências.
- **A Fase 2 introduz `src/` layout com dois pacotes** (`gamepanel/`,
  `gamebroker/`, seção 2). Para o pytest e o Pylance resolverem `from
  gamepanel.services import x` em vez de import solto por nome de arquivo
  (como hoje), os pacotes precisam de **instalação editável** (`pip install
  -e .`). `uv` trata isso como parte natural de um *workspace* — `uv sync`
  resolve os dois pacotes-membro e os instala editáveis num só comando, sem a
  dança manual de `pip install -e .` por pacote.
- **Muito mais rápido** que pip puro para o ciclo `venv → install → pytest`
  que o `CLAUDE.md` já descreve como "o ciclo normal enquanto se edita" — isso
  importa porque é rodado com frequência.
- Se a Fase 1 confirmar (com você) que o alvo de CI é GitLab CI, `uv` também é
  a peça mais simples de configurar lá: `uv sync --locked` é uma linha,
  determinística, sem cache de pip para gerenciar.

**Desenho proposto (ajustado na execução, ver nota abaixo)**: um único
`pyproject.toml` **na raiz do repo** (não publicável — não vai para PyPI,
ninguém roda `pip install gamepanel`; existe só para dependências de dev,
lint/type-check e imports editáveis), empacotando os dois pacotes via
`hatchling`:

```toml
[project]
name = "games-workspace"
dependencies = ["flask>=3.1,<3.2"]   # mesma faixa que o apt do Debian 13 traz

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gamepanel", "src/gamebroker"]

[dependency-groups]
dev = ["pytest>=9", "ruff>=0.16", "mypy>=1.14"]
```

`uv.lock` fica versionado; `.venv` continua fora do git como hoje.

> **Nota de execução**: a ideia original desta seção era um *workspace* `uv`
> de dois membros, cada um com seu próprio `pyproject.toml` (padrão
> `src/gamepanel/pyproject.toml` + `src/gamepanel/src/gamepanel/...`, `src/`
> duplicado). Na hora de criar o esqueleto (Fase 3, etapa 1), simplifiquei
> para um único `pyproject.toml` empacotando os dois via `packages = [...]`
> do hatchling — o benefício de um workspace de verdade (versionar/publicar
> cada pacote de forma independente) não se aplica aqui, já que nenhum dos
> dois é publicado nem instalado via pip em produção; a única coisa que
> importa é `import gamepanel`/`import gamebroker` resolverem em dev. Isso
> também deixa a árvore mais perto do pedido original ("`src/<pacote>/`"
> literal, sem aninhar `src/` dentro de `src/`). Não muda nada do resto da
> proposta (mapeamento, riscos, ordem de migração).

Comandos do dia a dia passam a ser `uv sync` (no lugar de criar venv + pip
install), `uv run pytest`, `uv run ruff check`, `uv run mypy` — mais curtos
que os comandos `.venv\Scripts\...` atuais, e funcionam iguais em qualquer
SO. `pyrightconfig.json` continua existindo (Pylance não fala `uv` ainda),
só troca `venvPath`/`venv` para apontar pro `.venv` que o `uv` cria (mesmo
lugar de hoje, então nem muda).

**O que eu NÃO estou propondo**: usar `uv` para empacotar/publicar nada, nem
para resolver dependências de produção (produção continua zero-pip, só apt),
nem para os scripts `.sh`/`.ps1` de deploy (esses não mudam por causa disso).

Se você preferir manter `pip`+`requirements-dev.txt` como está hoje só
estendido com mais um arquivo (`requirements-lint.txt`), o resto desta
proposta funciona igual — a única diferença prática é o comando usado e o
lockfile. Recomendo `uv`, mas é uma decisão de baixo risco de reverter se não
gostar.

---

## 1. Onde os princípios pedidos batem com o que existe — e onde ajustei

O pedido original lista seis princípios (seção "Fase 2 — Proposta"). Cinco
batem direto com o que a Fase 1 encontrou. Um precisa de ajuste, com
justificativa, porque a premissa não corresponde ao que o código faz hoje:

> **"runtime/ (Docker, processo local, SteamCMD): define COMO rodar"**

O painel **nunca** fala com Docker nem controla processo local — ele só sabe
falar **SSH** com um host remoto (seja esse host um CT LXC do Proxmox, seja
um container Docker do `deploy-docker.ps1`). Os dois expõem a mesma interface
de shell (`systemctl`/`journalctl`, reais ou via os wrappers de
`docker/gameserver/`) porque isso foi desenhado assim de propósito — o painel
não sabe nem precisa saber qual dos dois está do outro lado. "Docker vs.
processo local" é uma decisão de **deploy/provisionamento** (Proxmox LXC vs.
`deploy-docker.ps1`), não uma decisão de **runtime do painel**.

Por isso, proponho `runtime/` como **abstração de controle remoto por SSH**
(uma interface, uma implementação real por SSH, uma falsa para teste — o
mesmo padrão que `broker/backends.py` já usa e que funciona bem), não como
"Docker vs. processo local". SteamCMD nem entra aqui — SteamCMD só roda
dentro do CT/container de jogo, nunca é chamado pelo painel nem pelo broker
diretamente (é uma fase do instalador, `lib/ct-fases.sh`).

Os outros cinco princípios (src layout, camada HTTP fina, `services/`, adapter
por jogo, `tasks/`, infra fora do código Python, `tests/` espelhado com
`unit/`+`integration/`) batem com a realidade encontrada e entram como
proposto — com uma ressalva também justificada na seção 2.3 sobre "adapter
por jogo" (o projeto já tem **dois** catálogos de jogo com propósitos
diferentes, e forçar os dois num adapter só criaria acoplamento entre
`admin/` e `broker/` que hoje não existe).

Sobre **"broker isolado: pacote separado ou serviço à parte?"** — a resposta
curta é: **já é um serviço à parte hoje** (CT próprio em produção, fala só
HTTP com o painel, zero import cruzado — confirmado na Fase 1). A decisão real
que sobra é só *onde no repositório* ele mora daqui pra frente. Recomendo
**continuar no mesmo repositório**, como um segundo membro do workspace `uv`
(`src/gamebroker/`), não um repositório separado — ver justificativa na seção
2.2.

---

## 2. Árvore de pastas proposta

```
pyproject.toml                    # workspace uv, dev deps, config ruff/mypy
uv.lock
.python-version

src/
  gamepanel/
      __init__.py
      app.py                      # create_app() — application factory
      wsgi.py                     # entry point do gunicorn: gamepanel.wsgi:app
      cli.py                      # bootstrap: --create-user, --reset-2fa, ensure_server (era o rodapé de app.py)
      config.py                   # leitura das GAMEPANEL_* (Config dataclass, hoje espalhado em ~60 os.environ.get)
      extensions.py               # csrf, before_request, error handlers, security headers

      blueprints/                 # camada HTTP fina — só valida input e chama services/
        __init__.py
        auth.py                   # /login, /login/2fa, /logout
        dashboard.py               # /, /api/status, /api/recursos, /api/players
        servers.py                 # /servers/new, /edit, /delete, /<id>, /<id>/action
        players.py                  # descobrir/usar/ação de jogador
        console.py                  # /servers/<id>/console
        terminal.py                  # /servers/<id>/terminal, /api/term/*
        files.py                     # /servers/<id>/files*
        backups.py                   # /servers/<id>/backups*
        config_quick.py               # /servers/<id>/config*
        schedules.py                  # /servers/<id>/agendamentos, /agendamentos/*
        alerts.py                      # /alertas*
        history.py                      # /historico
        charts.py                        # /servers/<id>/graficos
        broker.py                         # /catalogo*, /instancias*
        account.py                         # /account*, /ssh-key
        users.py                            # /usuarios*
        jobs.py                              # /jobs/<id>
        pwa.py                                # /manifest.webmanifest, /sw.js, /offline
        health.py                             # /health

      services/                   # regra de negócio — sem Flask, sem SQL cru
        __init__.py
        auth_service.py           # hash/verify de senha, gate de 2FA
        server_service.py          # CRUD, validação de formulário (era _form_server)
        player_service.py           # resolve fonte de contagem, cache, ações
        metrics_service.py           # cache/leitura de métricas de recurso
        status_service.py             # cache/leitura de status do serviço
        job_service.py                 # log_job, start_job, COMANDOS
        alert_service.py                # regras de disparo (_alerta_de_*), webhooks
        schedule_service.py              # venceu, dispara_agendamento
        backup_service.py                 # orquestra criar/restaurar/remover
        file_service.py                    # valida path, delega IO ao runtime/
        chart_service.py                    # monta_grafico, coleta_amostras
        broker_service.py                    # cadastra servidor pós-criação, acompanha operação
        user_service.py                       # papéis, gestão de usuário

      games/                      # "O QUE rodar" — adapter por jogo (ver 2.3)
        __init__.py
        base.py                   # Protocol/ABC GameFieldAdapter
        registry.py                # chave de jogo -> adapter (default: GenericAdapter)
        config_format.py            # motor de parsing ini/json (era gameconf.py, genérico)
        adapters/
          enshrouded.py
          palworld.py
          icarus.py
          dayz.py
          dragonwilds.py
        catalog/                    # eixo diferente: sugestões p/ formulário "Adicionar jogo"
          suggestions.py            # gerado por tools/importar-linuxgsm.py (era sugestoes_de_jogos.py)
          search.py                  # era busca_de_jogos.py
          templates.py                 # era modelos_de_jogo.py

      runtime/                    # "COMO rodar" — abstração de controle remoto por SSH
        __init__.py
        base.py                   # Protocol RemoteControl (run/read/write/stream)
        ssh.py                     # implementação real (era ssh_argv/ssh_run/ssh_output)
        fakes.py                    # implementação falsa p/ teste (mesmo padrão de broker/fakes.py)
        a2s.py                       # protocolo A2S
        http_probe.py                  # contagem via API HTTP própria do jogo
        log_replay.py                   # contagem por log (máquina de estados)
        port_probe.py                    # descoberta de porta/API
        terminal.py                       # TermSession (PTY)
        files.py                           # list/read/write/delete remoto
        metrics_probe.py                    # coleta de CPU/mem/disco

      tasks/                       # trabalho longo, fora do ciclo da requisição
        __init__.py
        monitor.py                 # monitora_servidores / _ritmo_do_monitor
        scheduler.py                 # _scheduler_loop
        log_streams.py                 # _LogStream / supervisiona_streams
        broker_jobs.py                   # acompanha_operacao (polling)

      persistence/
        __init__.py
        db.py                       # conexão, init_db
        schema.py                    # SCHEMA + MIGRATIONS (tabelas)
        repositories/                # troca SQL cru inline por uma função por tabela
          servers.py
          jobs.py
          schedules.py
          samples.py
          webhooks.py
          alert_log.py
          users.py
          settings.py

      security/
        __init__.py
        totp.py                     # (já puro hoje, só muda de pasta)
        qr.py                        # (idem)
        csrf.py
        passwords.py

      integrations/
        __init__.py
        broker_client.py            # (já puro/stdlib hoje, só muda de pasta)

      navigation.py                 # era ui.py — mapa de telas/ações (puro)

    templates/                      # movido de admin/templates/
    static/                          # movido de admin/static/

  gamebroker/
    pyproject.toml                  # sem dependência externa (stdlib + flask só p/ api.py)
    src/gamebroker/
      __init__.py
      app.py                        # create_app(servico) — hoje é broker/api.py::criar_app
      wsgi.py                        # era broker/prod.py
      cli.py                          # era broker/dev.py

      services/
        instance_service.py          # era servico.py
        allocator.py                   # era alocador.py
        catalog.py                       # era catalogo.py

      domain/
        exceptions.py                 # era erros.py
        models.py                       # EspecificacaoDeCt e afins (de backends.py)

      runtime/                        # "COMO" criar infraestrutura — já é Protocol hoje
        base.py                       # era backends.py (as 4 interfaces)
        proxmox.py
        opnsense.py
        ssh_installer.py               # era ssh_install.py
        network.py                      # era rede.py
        fakes.py

      persistence/
        db.py                           # era banco.py

      integrations/
        http_client.py                   # era conexao.py

      config.py                           # (já é quase só isso hoje)

tests/
  gamepanel/
    unit/
      services/
      games/
      runtime/                          # usa runtime/fakes.py
      security/
    integration/
      blueprints/                        # Flask test client, banco real, runtime/fakes.py
  gamebroker/
    unit/
      services/
      runtime/                           # usa runtime/fakes.py e http_falso (nome mantido — ver seção 4)
    integration/
  conftest.py                             # fixtures raiz compartilhadas (banco, webhooks, chefe/peao, entrar/postar)

games/                                     # NÃO MOVE — catálogo curado, lido também por lib/ct-fases.sh (bash)
lib/                                        # NÃO MOVE — fases de instalação, bash puro
tools/                                       # NÃO MOVE — scripts manuais de dev

deploy/                                       # NOVO — agrupa infra fora do código Python
  admin/
    deploy-admin.ps1
    provision-admin-lxc.sh
  broker/
    deploy-broker.ps1
    provision-broker-lxc.sh
    verificar-broker-acesso.ps1            # ferramenta manual, mas do broker
    spike-broker-escrita.ps1                # idem
  game/
    deploy-game.ps1
    deploy-docker.ps1
    provision-game-lxc.sh
    provision-teamspeak-lxc.sh

docker/                                        # NÃO MOVE (estrutura interna já faz sentido)
docker-compose.yml                              # fica na raiz (convenção docker compose)
.env.example                                     # fica na raiz
pytest.ini                                        # vira [tool.pytest.ini_options] dentro do pyproject.toml raiz
pyrightconfig.json                                # fica, só ajusta extraPaths/include para src/
```

### 2.1 Por que `games/` (dado), `lib/` e `tools/` não entram no `src/`

Os três são lidos por **bash puro rodando fora de qualquer processo
Python** (`provision-game-lxc.sh` no host Proxmox, `lib/ct-fases.sh` dentro do
CT) ou são scripts de manutenção chamados manualmente, nunca importados por
`gamepanel`/`gamebroker`. Colocá-los dentro de `src/` sugeriria que fazem
parte do pacote Python, o que quebraria a expectativa de quem olha
`provision-game-lxc.sh` e espera `games/*.env` no mesmo lugar de sempre.
`gamebroker.services.catalog` continua **lendo** `games/*.env` do caminho
configurado em `BROKER_GAMES_DIR` — isso não muda.

### 2.2 Por que `gamebroker` fica no mesmo repositório

- Já está isolado onde importa (processo próprio, HTTP-only, zero import
  cruzado — Fase 1, seção 2.3).
- Os dois serviços **compartilham** `games/*.env`, `lib/ct-fases.sh` e os
  scripts de deploy — versionar em repositórios separados criaria o problema
  clássico de "qual commit do broker combina com qual commit do painel",
  sem nenhum ganho de isolamento (o isolamento real já é o processo/CT, não
  o repositório).
- `uv` workspace é feito exatamente para "dois pacotes independentes, um
  repo, dev tooling compartilhado" — o caso de uso bate.
- Se um dia o time quiser cadência de release diferente para o broker (ex.:
  um terceiro operando só o broker, sem acesso ao código do painel), separar
  o repositório depois é fácil justamente porque o acoplamento já é zero —
  não é uma decisão que fecha portas.

### 2.3 Por que "adapter por jogo" vira **dois** catálogos, não um

O projeto já tem dois catálogos de jogo, resolvendo problemas diferentes:

| | `gamebroker` (catálogo curado) | `gamepanel` (adapter de campo) |
|---|---|---|
| Pergunta que responde | "como instalar/alocar porta pra esse jogo?" | "que campos mostrar na tela de edição rápida desse jogo?" |
| Hoje | `games/*.env` (declarativo) + `catalogo.py` | `gamefields.py` (5 dicts: Enshrouded/Palworld/Icarus/DayZ/Dragonwilds) |
| Cobertura | Todo jogo instalável pelo broker (curado + dinâmico da API) | Só os 5 jogos com tela de edição rápida — os demais caem no editor de arquivo genérico |
| Roda em | Processo do broker (outro CT) | Processo do painel |

Forçar os dois em um `GameAdapter` só faria sentido se `gamepanel` e
`gamebroker` compartilhassem código Python — e eles deliberadamente não
compartilham (comunicam só por HTTP, cada um no seu processo/CT). Uma
`games/` "universal" compartilhada exigiria ou (a) uma terceira dependência
Python instalada nos dois lados (mais um pacote pra versionar e mais uma
coisa que pode divergir entre painel e broker em produção), ou (b)
duplicação do zero — nenhuma das duas é melhor que manter os dois catálogos
que já existem, só formalizados como adapter em cada lado (seção 2, acima).

O ganho real de "adicionar um jogo = só um adapter" já existe hoje do lado do
broker (editar `games/*.env` não toca nenhum código Python) e passa a existir
do lado do painel depois da Fase 4 (criar `adapters/novo_jogo.py` e registrar
em `registry.py`, sem tocar nas rotas nem nos outros adapters) — mas
continuam sendo dois pontos de extensão, não um.

---

## 3. Tabela de mapeamento

### 3.1 `admin/` → `src/gamepanel/`

| Caminho atual | Caminho novo | Observação |
|---|---|---|
| `admin/app.py` (seções 1–3, 42: config/factory/security headers) | `gamepanel/app.py`, `gamepanel/config.py`, `gamepanel/extensions.py` | quebra do bootstrap Flask |
| `admin/app.py` (seção 4: SCHEMA/MIGRATIONS) | `gamepanel/persistence/schema.py` | |
| `admin/app.py` (seção 4: hash de senha) | `gamepanel/security/passwords.py` | |
| `admin/app.py` (seção 5: auth/csrf/2fa gate) | `gamepanel/services/auth_service.py` + `gamepanel/security/csrf.py` + `gamepanel/blueprints/auth.py` | |
| `admin/app.py` (seção 5: contexto de navegação) + `admin/ui.py` | `gamepanel/navigation.py` | `ui.py` já é puro, só muda de lugar |
| `admin/app.py` (seção 6: SSH) | `gamepanel/runtime/ssh.py` | |
| `admin/app.py` (seção 7: A2S) | `gamepanel/runtime/a2s.py` | |
| `admin/app.py` (seções 8–9: HTTP API contagem+ações) | `gamepanel/runtime/http_probe.py` + `gamepanel/services/player_service.py` + `gamepanel/blueprints/players.py` | |
| `admin/app.py` (seções 10–11: log/porta) | `gamepanel/runtime/log_replay.py`, `gamepanel/runtime/port_probe.py` | |
| `admin/app.py` (seção 12: fonte de contagem) | `gamepanel/services/player_service.py` | `FONTES_DE_CONTAGEM` vira registry no service |
| `admin/app.py` (seção 13: métricas) | `gamepanel/runtime/metrics_probe.py` + `gamepanel/services/metrics_service.py` | |
| `admin/app.py` (seção 14: status) | `gamepanel/services/status_service.py` | |
| `admin/app.py` (seção 15: jobs/comandos) | `gamepanel/services/job_service.py` | `COMANDOS`/`ACTIONS` + o `assert` de sincronia com `ui.py` viram parte do registry |
| `admin/app.py` (seções 16–17: alertas) | `gamepanel/services/alert_service.py` + `gamepanel/integrations/webhook_client.py` | `ALERTAS_DE_RECURSO` vira registry no service |
| `admin/app.py` (seção 18: log stream) | `gamepanel/tasks/log_streams.py` | |
| `admin/app.py` (seção 19: monitor) | `gamepanel/tasks/monitor.py` | `_ritmo_do_monitor`/`_alertas_do_servidor` já eram a exceção "boa" — vira o modelo pros outros services |
| `admin/app.py` (seção 20: amostras) | `gamepanel/services/chart_service.py` | |
| `admin/app.py` (seção 21: agendador) | `gamepanel/tasks/scheduler.py` + `gamepanel/services/schedule_service.py` | |
| `admin/app.py` (seções 22–41, 43: rotas) | um `gamepanel/blueprints/*.py` por tela (tabela da seção 2) | camada fina — só valida e chama service |
| `admin/app.py` (seção 26: validação de formulário) | `gamepanel/services/server_service.py` | `_form_server` e os ~10 helpers `_porta`/`_servico`/etc. |
| `admin/app.py` (seção 29: terminal) | `gamepanel/runtime/terminal.py` (classe `TermSession`) + `gamepanel/blueprints/terminal.py` | |
| `admin/app.py` (seções 30–32: arquivos/backup) | `gamepanel/runtime/files.py` + `gamepanel/services/file_service.py`/`backup_service.py` + blueprints correspondentes | os 9 scripts bash (`LIST_SCRIPT` etc.) migram para `runtime/files.py`/`runtime/backup.py` como constantes locais, não mais soltos no meio de rotas |
| `admin/app.py` (seção 33: config rápida) | `gamepanel/blueprints/config_quick.py` + `gamepanel/games/` | liga `gameconf.py`+`gamefields.py` (agora `games/config_format.py`+`games/adapters/`) ao formulário |
| `admin/app.py` (seção 35: broker) | `gamepanel/services/broker_service.py` + `gamepanel/tasks/broker_jobs.py` + `gamepanel/blueprints/broker.py` | |
| `admin/app.py` (seção 37: gráficos) | `gamepanel/services/chart_service.py` + `gamepanel/blueprints/charts.py` | |
| `admin/app.py` (seção 44: bootstrap CLI) | `gamepanel/cli.py` | `ensure_admin_user`, `ServidorDoDeploy`, `ensure_server`, `argparse` |
| `admin/gameconf.py` | `gamepanel/games/config_format.py` | puro hoje, só muda de nome/lugar |
| `admin/gamefields.py` | `gamepanel/games/base.py` + `gamepanel/games/adapters/*.py` | 5 dicts → 5 arquivos + 1 `Protocol` |
| `admin/broker_client.py` | `gamepanel/integrations/broker_client.py` | puro/stdlib hoje, só muda de lugar |
| `admin/totp.py`, `admin/qr.py` | `gamepanel/security/totp.py`, `gamepanel/security/qr.py` | puros hoje, só mudam de lugar |
| `admin/busca_de_jogos.py`, `admin/modelos_de_jogo.py`, `admin/sugestoes_de_jogos.py` | `gamepanel/games/catalog/search.py`, `templates.py`, `suggestions.py` | `sugestoes_de_jogos.py` continua **gerado**, só muda o caminho de saída de `tools/importar-linuxgsm.py` |
| `admin/templates/`, `admin/static/` | `gamepanel/templates/`, `gamepanel/static/` (dentro de `src/gamepanel/`) | Flask resolve por padrão relativo ao pacote |
| `admin/test_*.py` (14 arquivos) | `tests/gamepanel/{unit,integration}/...` | reorganização **em etapas** — ver seção 6, não é 1:1 imediato |
| `admin/conftest.py` | `tests/conftest.py` (+ specializations em `tests/gamepanel/conftest.py` se necessário) | |

### 3.2 `broker/` → `src/gamebroker/`

Mapeamento quase 1:1 — `broker/` já está bem dividido, é principalmente
mudança de caminho + tradução de nome:

| Caminho atual | Caminho novo |
|---|---|
| `broker/api.py` | `gamebroker/app.py` |
| `broker/prod.py` | `gamebroker/wsgi.py` |
| `broker/dev.py` | `gamebroker/cli.py` |
| `broker/servico.py` | `gamebroker/services/instance_service.py` |
| `broker/alocador.py` | `gamebroker/services/allocator.py` |
| `broker/catalogo.py` | `gamebroker/services/catalog.py` |
| `broker/erros.py` | `gamebroker/domain/exceptions.py` |
| `broker/backends.py` | `gamebroker/runtime/base.py` |
| `broker/proxmox.py` | `gamebroker/runtime/proxmox.py` |
| `broker/opnsense.py` | `gamebroker/runtime/opnsense.py` |
| `broker/ssh_install.py` | `gamebroker/runtime/ssh_installer.py` |
| `broker/rede.py` | `gamebroker/runtime/network.py` |
| `broker/fakes.py` | `gamebroker/runtime/fakes.py` |
| `broker/http_falso.py` | `gamebroker/runtime/http_fake_server.py` (só para teste) |
| `broker/banco.py` | `gamebroker/persistence/db.py` |
| `broker/conexao.py` | `gamebroker/integrations/http_client.py` |
| `broker/config.py` | `gamebroker/config.py` |
| `broker/test_*.py` (12 arquivos) | `tests/gamebroker/{unit,integration}/...` |

---

## 4. Plano de refactor por módulo

Ordem de execução recomendada para a Fase 4 (depois que a Fase 3 estabilizar
a estrutura nova sem mudar comportamento):

1. **`gamepanel/games/`** (era `gameconf.py`+`gamefields.py`) — já puro, sem
   Flask/banco/SSH; menor risco, bom primeiro módulo pra validar o padrão de
   "teste de comportamento antes de refatorar" com um módulo pequeno.
2. **`gamepanel/security/`** (`totp.py`, `qr.py`) — idem, puro, baixo risco.
3. **`gamepanel/runtime/`** — extrair a camada SSH/A2S/HTTP/log de dentro de
   `app.py` para trás de uma interface (`RemoteControl` Protocol), com
   `runtime/fakes.py` para os testes passarem a usar fake em vez de
   `monkeypatch` de função solta. **Este é o módulo que desbloqueia o resto**
   — sem ele, `services/` não tem como ficar livre de SSH direto.
4. **`gamebroker/`** — só reorganizar/renomear (mapeamento 1:1 da seção 3.2);
   quase não tem SRP pra corrigir, já está bem dividido. É o módulo de
   "menor esforço, valida o padrão de migração" para o time.
5. **`gamepanel/services/`**, um por vez, na ordem: `player_service` →
   `metrics_service`/`status_service` → `alert_service` → `schedule_service`
   → `server_service` → `broker_service` → `backup_service`/`file_service`
   (nessa ordem porque `alert_service` já depende de `player`/`metrics`, e
   `server_service` é o maior, com mais ramificação de validação).
6. **`gamepanel/blueprints/`** por último, telas por telas — nesse ponto cada
   rota já deve ser um repasse fino pro service correspondente.
7. **`gamepanel/persistence/repositories/`** — trocar o SQL cru inline por
   uma função por tabela, em paralelo com o item 5 (cada service ganha seu
   repositório na hora de ser extraído, não numa passada separada).

**Problemas de Sonar/CLAUDE.md resolvidos por essa ordem**:
- Complexidade cognitiva >15: a divisão em service+blueprint já resolve a
  maioria — `app.py` inteiro colapsa de 8.175 linhas / 44 seções para ~25
  arquivos de 100–300 linhas cada.
- "13+ parâmetros → objeto": `broker/config.py`/`prod.py` já usam esse
  padrão (`**dict` para `ConfigProxmox`/`ConfigBroker`) mas perdem tipo nessa
  borda (achado do mypy, Fase 1 §6.2) — na Fase 4, ao tipar `gamebroker`,
  trocar por `TypedDict` ou validação campo a campo resolve os dois de uma
  vez (o smell de parâmetros E o erro de tipo).
- `except Exception` sem `# noqa` correto: a config real de `ruff` (item
  abaixo) precisa habilitar o rule set (`BLE001` etc.) que os comentários
  `# noqa: BLE001` do código já assumem — sem isso, 9 supressões viram lixo
  silencioso (achado da Fase 1 §6.1).
- Padrão "rodar script remoto, converter erro" repetido 7× em `app.py` vira
  um único método em `runtime/ssh.py`/`runtime/files.py`.
- As três implementações quase idênticas de fan-out por thread (`all_status`/
  `all_metrics`/`all_players`) viram uma função genérica em `runtime/base.py`
  ou um utilitário compartilhado, usada pelos três services.
- `subprocess`/`Popen` sem `check=`/com `preexec_fn` (achado do ruff, Fase 1
  §6.1, `PLW1510`/`PLW1509`) — corrigidos ao mover para `runtime/ssh.py`,
  onde ficam concentrados e revisáveis num lugar só.

**Configuração de `ruff`/`mypy` a criar** (no `pyproject.toml` raiz, Fase 3):
```toml
[tool.ruff]
line-length = 100
extend-exclude = ["src/gamepanel/games/catalog/suggestions.py"]  # gerado

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "BLE", "S", "SIM", "RUF", "PL"]

[tool.mypy]
platform = "linux"          # produção é sempre Linux — evita falso positivo
                             # de ioctl/setsid/openpty no Windows (Fase 1 §6.2)
disallow_untyped_defs = true
```
(valores exatos de `select`/regras a ajustar com você antes de ligar `--fix`
em qualquer coisa — isso também é decisão sua, não vou pré-aprovar regras
novas de lint sem confirmar.)

---

## 5. Breaking changes — decisão individual

Retomando a lista completa da Fase 1 (§7.3), organizada em **grupos de
decisão** (mudar um item do grupo normalmente significa mudar o grupo
inteiro, então faz mais sentido aprovar por grupo do que item a item):

> **Estado (atualizado na execucao):** **A**, **B** e **D** foram feitos — a API do
> broker fala ingles com uma camada de fio propria (`gamebroker/domain/wire.py`), e os
> dois bancos tem migration de rename com teste que monta o esquema antigo a mao
> (`tests/gamebroker/test_migracao.py`, `tests/gamepanel/test_schema.py`). Faltam **C**
> (rotas do painel, que ainda depende da preferencia sobre redirect), **E** e **F**.

| # | Grupo | O que muda | Quem consome | Risco | Minha recomendação |
|---|---|---|---|---|---|
| **A** | Rotas + payload JSON do broker (`/v1/saude`, `/v1/catalogo`, `/v1/instancias`, `/v1/operacoes`, chaves `jogo`/`instancia_id`/`porta_jogo`/etc., códigos de erro `nao-encontrado`/`sem-recurso`/etc.) | Traduzir tudo pra inglês | **Só** `gamepanel/integrations/broker_client.py`, no mesmo repo, no mesmo deploy | Baixo — API 100% interna, sem consumidor externo, os dois lados mudam juntos no mesmo commit | **Traduzir agora** (Fase 4), é o breaking change mais barato da lista |
| **B** | Colunas do banco do broker (schema inteiro: `ctid`, `estado`, `criado_em`...) | Traduzir + migração (banco recriado a cada deploy de CT novo, mas dado existente em CT já rodando precisa migrar) | Só `gamebroker` (processo único, dono do próprio banco) | Médio — precisa de migração real (o banco do broker tem estado: instâncias/portas/operações/auditoria ativas) | **Traduzir com migração**, mas só depois de confirmar com você se algum broker já em produção tem dado que não pode perder |
| **C** | Rotas HTTP do painel (`/historico`, `/alertas`, `/usuarios`, `/agendamentos`, `/catalogo`, `/instancias`, `/graficos`) | Traduzir pra inglês | Navegadores de quem usa o painel (pode ter link salvo/favorito) | Baixo-médio — painel interno, não API pública, mas usuário humano pode ter bookmark | Traduzir, com um redirect 301 das rotas antigas por um tempo (barato de manter, evita quebrar bookmark) — **pergunto sua preferência abaixo** |
| **D** | Colunas de banco do painel (`webhooks`, `alert_log`) | Traduzir + entrada em `MIGRATIONS` | Só o próprio `app.py`/`gamepanel` | Baixo — mecanismo de migração incremental já existe e é exatamente pra isso | **Traduzir**, é o padrão que o próprio projeto já usa pra evoluir esse schema |
| **E** | `BROKER_MAX_CRIACOES_HORA` (única env var com palavra em português) | Renomear pra `BROKER_MAX_CREATIONS_PER_HOUR` | `provision-broker-lxc.sh`/`deploy-broker.ps1` (regeneram o `.env` a cada deploy — não é um valor que "persiste" como token/chave) | Baixo | **Renomear**, atualizando os scripts de deploy no mesmo commit |
| **F** | Filtros Jinja (`"nivel"`, `"duracao"`, `"tamanho"`, `"ident"`) e nomes de endpoint Flask usados em `url_for()` | Traduzir | Só templates internos, atualizados no mesmo commit | Baixo | Traduzir junto com o blueprint correspondente na Fase 4 (não precisa de aprovação em separado — é puramente interno ao repo) |

Grupos **E** e **F** não preciso de aprovação separada de verdade (risco
baixo, tudo no mesmo commit, sem consumidor externo) — só listei pra
completude. Os que realmente dependem da sua decisão são **A–D**, e
principalmente a preferência de transição em **C** (rota do painel — corte
seco vs. redirect temporário). Vou perguntar isso já a seguir nesta mensagem.

---

## 6. Riscos e o que pode quebrar

- **Produção não usa `pip install` — o `src/` layout muda como o Python
  resolve `import gamepanel`.** Hoje `gunicorn ... app:app` funciona porque
  o processo roda com `cwd=/opt/gamepanel` e os arquivos estão soltos ali
  (sem pacote). **Validado na Fase 3, etapa 2**, contra a imagem real
  (`debian:13-slim` + `apt-get install python3-flask gunicorn`, sem pip,
  sem editable install — exatamente a restrição de produção): `gunicorn
  --chdir /opt/gamepanel/src gamepanel.wsgi:app` resolve `import gamepanel`
  sem precisar de `PYTHONPATH` nenhum (gunicorn insere o `cwd` resolvido pelo
  `--chdir` em `sys.path`, o mesmo mecanismo que já faz `app:app` funcionar
  hoje). Decisão: o deploy passa a copiar a árvore como
  `/opt/gamepanel/src/gamepanel/...` e a unit systemd/`Dockerfile` ganham
  `--chdir /opt/gamepanel/src` na linha do gunicorn — um parâmetro a mais,
  nada de variável de ambiente nova. Isso entra na etapa 5 (mover `app.py`
  de verdade), junto da atualização de `provision-admin-lxc.sh::render_service`,
  `docker/panel/entrypoint.sh` e `docker/panel/Dockerfile*`.
- **`provision-admin-lxc.sh`/`deploy-admin.ps1` e os equivalentes do broker
  fazem `push_tree`/scp por caminho fixo** (`admin/*.py`, `templates/`,
  `static/`) — todos os caminhos mudam e os dois scripts (mais
  `docker/panel/Dockerfile*`, `docker/broker/Dockerfile`) precisam de
  atualização na mesma etapa que move os arquivos (`git mv` + atualização de
  script no mesmo commit, por etapa — não em separado).
- **`docker-compose.yml` monta `admin/` como bind mount `:ro`** — vira bind
  mount de `src/gamepanel/` (ou do repo inteiro com `--reload` apontando pro
  caminho novo). Testar que o hot-reload continua funcionando é parte do
  "passar por todas as telas" que o `CLAUDE.md` já pede depois de mexer em
  rota.
- **`pytest.ini` (`testpaths = admin broker`) e `pyrightconfig.json`
  (`extraPaths`, `include`)** precisam apontar para os caminhos novos — sem
  isso, os 851 testes documentados no `CLAUDE.md` simplesmente não são
  coletados (silêncio, não erro — risco de "os testes passam" virar
  mentira por coletar zero teste).
- **O padrão de teste `monkeypatch.setattr(panel, "funcao", ...)`** (Fase 1
  §2.1) só funciona enquanto a função trocada é chamada pelo módulo, nunca
  importada por nome. Ao quebrar `app.py` em `services/`, cada extração
  precisa trocar `monkeypatch.setattr(panel, "x", fake)` por
  `monkeypatch.setattr(player_service, "x", fake)` (ou official DI via
  `runtime/fakes.py`) **no mesmo commit** que move a função — nunca depois.
  Isso é o maior risco de "teste verde mentiroso" da Fase 3/4.
- **`entrypoint.sh` do painel roda um heredoc Python** que chama
  `app.ensure_server(...)` diretamente (achado do `CLAUDE.md`: "grep só nos
  `.py` não acha") — vira `gamepanel.cli.ensure_server`, e o heredoc precisa
  do import corrigido no mesmo commit que move `cli.py`.
- **`lib/ct-fases.sh` e `provision-game-lxc.sh` leem `games/*.env` por
  caminho relativo fixo** — como `games/` não move (seção 2.1), isso não
  quebra, mas vale confirmar que nenhum script novo tenta "arrumar" esse
  caminho por engano durante a Fase 3.
- **`admin/requirements-dev.txt` referenciado no `CLAUDE.md`** — se `uv` for
  aprovado (seção 0), o `CLAUDE.md` precisa ser atualizado no mesmo commit
  que remove esse arquivo (ele mesmo pede pra manter `CLAUDE.md` como fonte
  de verdade dos comandos).
- **`docker/ct-sandbox/comparar.sh`** compara o instalador antes/depois
  lendo `provision-game-lxc.sh`/`lib/ct-fases.sh` por caminho fixo — como
  esses não movem, sem risco, mas é o primeiro lugar a rodar depois de
  qualquer mudança em `lib/` (o próprio `CLAUDE.md` já pede isso).

---

## 7. Plano de migração em etapas pequenas (Fase 3)

Cada etapa = branch → `git mv` → atualizar imports/Dockerfile/compose →
rodar testes → commit. Não mistura mudança de comportamento (isso é Fase 4).

1. **Criar o esqueleto**: `pyproject.toml` raiz + dois sub-`pyproject.toml`,
   `uv.lock`, pastas vazias `src/gamepanel/`, `src/gamebroker/`,
   `tests/gamepanel/`, `tests/gamebroker/`. Validar `uv sync` funciona e
   `pyrightconfig.json` resolve os pacotes.
2. ✅ **Feito.** Validar a hipótese de risco do `src/` layout em produção
   (seção 6, primeiro item), isoladamente, contra a imagem real do painel
   (`debian:13-slim` + apt, sem pip), com um `gamepanel` "oco" (`app.py` +
   `wsgi.py`, só rota `/health`) — antes de mover 8.175 linhas de verdade.
   Confirmado: `gunicorn --chdir /opt/gamepanel/src gamepanel.wsgi:app`
   resolve o import sem `PYTHONPATH` extra. `src/gamepanel/app.py` e
   `wsgi.py` ficam como estão (viram a semente da etapa 5, não são
   descartáveis).
3. **Mover `gamebroker`** — mas em duas passadas, não uma, pra manter cada
   commit de baixo risco: **(3a, Fase 3, esta etapa)** relocar `broker/` →
   `src/gamebroker/` **de forma plana**, mesmos nomes de arquivo, mesmos
   identificadores (`servico.py` continua `servico.py`, `Servico` continua
   `Servico`) — só o caminho do pacote muda (`broker.X` → `gamebroker.X`
   nos imports absolutos dos testes e nos scripts de deploy). Zero mudança
   de comportamento, zero tradução ainda. **(3b, Fase 4)** a reorganização
   em subpastas (`services/`, `runtime/`, `persistence/`, `domain/`,
   `integrations/` — mapeamento da seção 3.2) acontece **junto** da tradução
   pra inglês (grupos A/B aprovados), módulo por módulo — já que mover um
   arquivo pra dentro de uma subpasta obriga a tocar em todo import mesmo,
   faz mais sentido fazer as duas mudanças (caminho + nome) na mesma
   passada por módulo, em vez de duas passadas mecânicas separadas tocando
   os mesmos arquivos duas vezes.
   Atualizar `docker/broker/Dockerfile`, `provision-broker-lxc.sh`,
   `deploy-broker.ps1`, `docker-compose.yml`. Rodar as ~415 suítes do broker.
4. **Mover os módulos puros de `admin/`** (`totp.py`→`security/totp.py`,
   `qr.py`→`security/qr.py`, `gameconf.py`+`gamefields.py`→`games/`,
   `ui.py`→`navigation.py`, `broker_client.py`→`integrations/`) — zero lógica
   nova, só `git mv` + ajuste de import. Rodar as suítes correspondentes.
5. **Mover `app.py` inteiro para `gamepanel/app.py`** SEM quebrar em módulos
   ainda (só muda de endereço) — separa "onde as coisas moram" de "como as
   coisas são organizadas", reduzindo o tamanho de cada commit de risco.
   Atualizar `docker/panel/Dockerfile*`, `provision-admin-lxc.sh`,
   `deploy-admin.ps1`, `docker-compose.yml`, `entrypoint.sh` (o heredoc).
   Mover `templates/`/`static/`. Rodar as ~436 suítes do painel.
6. **Mover `admin/test_*.py` para `tests/gamepanel/`** como estão (sem
   dividir ainda) — a divisão em `unit/`+`integration/` e o espelhamento por
   service só faz sentido módulo a módulo, à medida que a Fase 4 extrai cada
   `services/*.py` (ver seção 4). Nesta etapa, só preservar 100% de
   cobertura movendo os arquivos inteiros.
7. **Atualizar `CLAUDE.md`/`README.md`** com os caminhos novos e os comandos
   `uv run ...` — última etapa da Fase 3, antes de declarar a estrutura
   estável e passar pra Fase 4.

A partir daqui, a Fase 4 segue a ordem da seção 4 (games → security → runtime
→ [gamebroker interno, se sobrar algo] → services, um por vez → blueprints →
repositories), cada módulo com commit próprio, teste escrito antes se a
cobertura hoje for insuficiente (backups/arquivos/terminal, achados da Fase 1
§4.1, são os primeiros candidatos a precisar disso).

---

## Decisões aprovadas (2026-09-22)

- **Estrutura geral (seção 2)**: aprovada como está.
- **Grupo A/B (broker)**: traduzir rotas `/v1/*`, chaves de JSON e colunas do
  banco do broker para inglês. Confirmado que não há broker em produção com
  instâncias/portas/operações reais ainda — migração de schema pode ser feita
  sem plano de backup especial (não há dado real a perder).
- **Grupo C (painel)**: traduzir rotas do painel para inglês, com redirect
  301 temporário das rotas antigas em português (`/alertas`, `/usuarios`,
  `/historico`, `/agendamentos`, `/catalogo`, `/instancias`, `/graficos`) —
  os redirects entram na Fase 4, junto do blueprint correspondente, e podem
  ser removidos depois de um período sem uso observado (a decidir quando
  chegar lá).
- **Grupos D/E/F**: seguem a recomendação da seção 5 (traduzir, sem risco
  adicional).

Fase 3 iniciada a seguir.
