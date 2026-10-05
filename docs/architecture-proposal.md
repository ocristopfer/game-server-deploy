# Reorganization proposal (Phase 2)

> **Historical:** this proposal was approved and executed - Phases 3 and 4 are done
> (`src/gamepanel/`/`src/gamebroker/`, English identifiers, all breaking-change groups,
> `app.py` split into blueprints). The plan is kept as approved; the "What has already been
> executed" section at the end records where the execution diverged.

> Depends on reading [`architecture-analysis.md`](architecture-analysis.md) (Phase 1).
> Nothing was moved or edited to produce this document - it is only the proposal,
> for the owner to approve before Phase 3 touches any file.

---

## 0. Dependency manager: does it make sense to use `uv`?

**Yes, but only for the development side - never for production.** The
production constraint in `CLAUDE.md` (`admin/requirements-dev.txt`: "the panel
in production runs with what apt installs... and does not download packages from
anywhere") is deliberate and **stays exactly as it is**: `uv` does not go into any
production Dockerfile or `provision-*-lxc.sh`. What it replaces is only the
`python -m venv .venv` + `pip install -r requirements-dev.txt pytest` flow
described in `CLAUDE.md` today.

**Why it is worth it:**

- **Today the dev suite is not truly reproducible**: `flask~=3.1.1` is the
  only pinned version; `pytest`, and now `ruff`/`mypy` (installed manually
  in Phase 1), have no fixed version anywhere. A versioned `uv.lock`
  solves this with no extra effort - everyone (and the future CI) installs
  exactly the same dependency tree.
- **Phase 2 introduces a `src/` layout with two packages** (`gamepanel/`,
  `gamebroker/`, section 2). For pytest and Pylance to resolve `from
  gamepanel.services import x` instead of a loose import by file name
  (as today), the packages need an **editable install** (`pip install
  -e .`). `uv` treats this as a natural part of a *workspace* - `uv sync`
  resolves the two member packages and installs them editable in a single
  command, without the manual `pip install -e .` dance per package.
- **Much faster** than plain pip for the `venv -> install -> pytest` cycle
  that `CLAUDE.md` already describes as "the normal cycle while editing" - this
  matters because it runs often.
- If Phase 1 confirms (with the owner) that the CI target is GitLab CI, `uv` is
  also the simplest piece to configure there: `uv sync --locked` is one line,
  deterministic, with no pip cache to manage.

**Proposed design (adjusted during execution, see note below)**: a single
`pyproject.toml` **at the repo root** (not publishable - it does not go to PyPI,
nobody runs `pip install gamepanel`; it exists only for dev dependencies,
lint/type-check and editable imports), packaging both packages via
`hatchling`:

```toml
[project]
name = "games-workspace"
dependencies = ["flask>=3.1,<3.2"]   # same range Debian 13's apt ships

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gamepanel", "src/gamebroker"]

[dependency-groups]
dev = ["pytest>=9", "ruff>=0.16", "mypy>=1.14"]
```

`uv.lock` is versioned; `.venv` stays out of git as today.

> **Execution note**: the original idea of this section was a two-member `uv`
> *workspace*, each with its own `pyproject.toml` (the
> `src/gamepanel/pyproject.toml` + `src/gamepanel/src/gamepanel/...` pattern, `src/`
> duplicated). When creating the skeleton (Phase 3, step 1), I simplified it
> to a single `pyproject.toml` packaging both via hatchling's `packages = [...]`
> - the benefit of a real workspace (versioning/publishing each package
> independently) does not apply here, since neither of them is published or
> installed via pip in production; the only thing that matters is that
> `import gamepanel`/`import gamebroker` resolve in dev. This also brings the
> tree closer to the original request (literal "`src/<package>/`", without
> nesting `src/` inside `src/`). It changes nothing in the rest of the
> proposal (mapping, risks, migration order).

Day-to-day commands become `uv sync` (instead of creating a venv + pip
install), `uv run pytest`, `uv run ruff check`, `uv run mypy` - shorter than
the current `.venv\Scripts\...` commands, and they work the same on any
OS. `pyrightconfig.json` keeps existing (Pylance does not speak `uv` yet),
it just switches `venvPath`/`venv` to point at the `.venv` that `uv` creates
(the same place as today, so it does not even change).

**What I am NOT proposing**: using `uv` to package/publish anything, nor to
resolve production dependencies (production stays zero-pip, apt only), nor
for the `.sh`/`.ps1` deploy scripts (those do not change because of this).

If the owner prefers to keep `pip`+`requirements-dev.txt` as it is today, just
extended with one more file (`requirements-lint.txt`), the rest of this
proposal works the same - the only practical difference is the command used and
the lockfile. I recommend `uv`, but it is a low-risk decision to revert if it
turns out not to be liked.

---

## 1. Where the requested principles match what exists - and where I adjusted

The original request lists six principles (section "Phase 2 - Proposal"). Five
match directly what Phase 1 found. One needs an adjustment, with
justification, because the premise does not match what the code does today:

> **"runtime/ (Docker, local process, SteamCMD): defines HOW to run"**

The panel **never** talks to Docker or controls a local process - it only knows
how to talk **SSH** to a remote host (whether that host is a Proxmox LXC CT or
a Docker container from `deploy-docker.ps1`). Both expose the same shell
interface (`systemctl`/`journalctl`, real or via the wrappers in
`docker/gameserver/`) because it was designed that way on purpose - the panel
does not know, and does not need to know, which of the two is on the other side.
"Docker vs. local process" is a **deploy/provisioning** decision (Proxmox LXC vs.
`deploy-docker.ps1`), not a **panel runtime** decision.

That is why I propose `runtime/` as a **remote-control-over-SSH abstraction**
(one interface, one real SSH implementation, one fake for tests - the
same pattern `broker/backends.py` already uses and that works well), not as
"Docker vs. local process". SteamCMD does not even enter here - SteamCMD only runs
inside the game CT/container, it is never called by the panel or by the broker
directly (it is an installer phase, `lib/ct-phases.sh`).

The other five principles (src layout, thin HTTP layer, `services/`, adapter
per game, `tasks/`, infra outside the Python code, mirrored `tests/` with
`unit/`+`integration/`) match the reality found and go in as proposed - with
one caveat, also justified in section 2.3, about "adapter per game" (the project
already has **two** game catalogs with different purposes, and forcing both into
a single adapter would create coupling between `admin/` and `broker/` that does
not exist today).

On **"isolated broker: separate package or separate service?"** - the short
answer is: **it already is a separate service today** (its own CT in production,
talks only HTTP with the panel, zero cross imports - confirmed in Phase 1). The
real decision left is only *where in the repository* it lives from now on. I
recommend **staying in the same repository**, as a second member of the `uv`
workspace (`src/gamebroker/`), not a separate repository - see the justification
in section 2.2.

---

## 2. Proposed folder tree

```
pyproject.toml                    # uv workspace, dev deps, ruff/mypy config
uv.lock
.python-version

src/
  gamepanel/
      __init__.py
      app.py                      # create_app() - application factory
      wsgi.py                     # gunicorn entry point: gamepanel.wsgi:app
      cli.py                      # bootstrap: --create-user, --reset-2fa, ensure_server (was the footer of app.py)
      config.py                   # reads the GAMEPANEL_* (Config dataclass, today spread over ~60 os.environ.get)
      extensions.py               # csrf, before_request, error handlers, security headers

      blueprints/                 # thin HTTP layer - only validates input and calls services/
        __init__.py
        auth.py                   # /login, /login/2fa, /logout
        dashboard.py               # /, /api/status, /api/recursos, /api/players
        servers.py                 # /servers/new, /edit, /delete, /<id>, /<id>/action
        players.py                  # player discover/use/action
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

      services/                   # business rules - no Flask, no raw SQL
        __init__.py
        auth_service.py           # password hash/verify, 2FA gate
        server_service.py          # CRUD, form validation (was _form_server)
        player_service.py           # resolves the counting source, cache, actions
        metrics_service.py           # resource metrics cache/read
        status_service.py             # service status cache/read
        job_service.py                 # log_job, start_job, COMANDOS
        alert_service.py                # trigger rules (_alerta_de_*), webhooks
        schedule_service.py              # venceu, dispara_agendamento
        backup_service.py                 # orchestrates create/restore/remove
        file_service.py                    # validates path, delegates IO to runtime/
        chart_service.py                    # monta_grafico, coleta_amostras
        broker_service.py                    # registers the server after creation, follows the operation
        user_service.py                       # roles, user management

      games/                      # "WHAT to run" - adapter per game (see 2.3)
        __init__.py
        base.py                   # Protocol/ABC GameFieldAdapter
        registry.py                # game key -> adapter (default: GenericAdapter)
        config_format.py            # ini/json parsing engine (was gameconf.py, generic)
        adapters/
          enshrouded.py
          palworld.py
          icarus.py
          dayz.py
          dragonwilds.py
        catalog/                    # a different axis: suggestions for the "Add game" form
          suggestions.py            # generated by tools/import-linuxgsm.py (was sugestoes_de_jogos.py)
          search.py                  # was busca_de_jogos.py
          templates.py                 # was modelos_de_jogo.py

      runtime/                    # "HOW to run" - remote control abstraction over SSH
        __init__.py
        base.py                   # Protocol RemoteControl (run/read/write/stream)
        ssh.py                     # real implementation (was ssh_argv/ssh_run/ssh_output)
        fakes.py                    # fake implementation for tests (same pattern as broker/fakes.py)
        a2s.py                       # A2S protocol
        http_probe.py                  # counting via the game's own HTTP API
        log_replay.py                   # counting by log (state machine)
        port_probe.py                    # port/API discovery
        terminal.py                       # TermSession (PTY)
        files.py                           # remote list/read/write/delete
        metrics_probe.py                    # CPU/mem/disk collection

      tasks/                       # long-running work, outside the request cycle
        __init__.py
        monitor.py                 # monitora_servidores / _ritmo_do_monitor
        scheduler.py                 # _scheduler_loop
        log_streams.py                 # _LogStream / supervisiona_streams
        broker_jobs.py                   # acompanha_operacao (polling)

      persistence/
        __init__.py
        db.py                       # connection, init_db
        schema.py                    # SCHEMA + MIGRATIONS (tables)
        repositories/                # replaces inline raw SQL with one function per table
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
        totp.py                     # (already pure today, only changes folder)
        qr.py                        # (same)
        csrf.py
        passwords.py

      integrations/
        __init__.py
        broker_client.py            # (already pure/stdlib today, only changes folder)

      navigation.py                 # was ui.py - map of screens/actions (pure)

    templates/                      # moved from admin/templates/
    static/                          # moved from admin/static/

  gamebroker/
    pyproject.toml                  # no external dependency (stdlib + flask only for api.py)
    src/gamebroker/
      __init__.py
      app.py                        # create_app(servico) - today it is broker/api.py::criar_app
      wsgi.py                        # was broker/prod.py
      cli.py                          # was broker/dev.py

      services/
        instance_service.py          # was servico.py
        allocator.py                   # was alocador.py
        catalog.py                       # was catalogo.py

      domain/
        exceptions.py                 # was erros.py
        models.py                       # EspecificacaoDeCt and the like (from backends.py)

      runtime/                        # "HOW" to create infrastructure - already a Protocol today
        base.py                       # was backends.py (the 4 interfaces)
        proxmox.py
        opnsense.py
        ssh_installer.py               # was ssh_install.py
        network.py                      # was rede.py
        fakes.py

      persistence/
        db.py                           # was banco.py

      integrations/
        http_client.py                   # was conexao.py

      config.py                           # (already almost only this today)

tests/
  gamepanel/
    unit/
      services/
      games/
      runtime/                          # uses runtime/fakes.py
      security/
    integration/
      blueprints/                        # Flask test client, real database, runtime/fakes.py
  gamebroker/
    unit/
      services/
      runtime/                           # uses runtime/fakes.py and fake_http (name kept - see section 4)
    integration/
  conftest.py                             # shared root fixtures (banco, webhooks, chefe/peao, entrar/postar)

games/                                     # DOES NOT MOVE - curated catalog, also read by lib/ct-phases.sh (bash)
lib/                                        # DOES NOT MOVE - installation phases, pure bash
tools/                                       # DOES NOT MOVE - manual dev scripts

deploy/                                       # NEW - groups infra outside the Python code
  admin/
    deploy-admin.ps1
    provision-admin-lxc.sh
  broker/
    deploy-broker.ps1
    provision-broker-lxc.sh
    check-broker-access.ps1            # manual tool, but belongs to the broker
    spike-broker-write.ps1                # same
  game/
    deploy-game.ps1
    deploy-docker.ps1
    provision-game-lxc.sh
    provision-teamspeak-lxc.sh

docker/                                        # DOES NOT MOVE (internal structure already makes sense)
docker-compose.yml                              # stays at the root (docker compose convention)
.env.example                                     # stays at the root
pytest.ini                                        # becomes [tool.pytest.ini_options] inside the root pyproject.toml
pyrightconfig.json                                # stays, only adjusts extraPaths/include for src/
```

### 2.1 Why `games/` (data), `lib/` and `tools/` do not go into `src/`

All three are read by **pure bash running outside any Python
process** (`provision-game-lxc.sh` on the Proxmox host, `lib/ct-phases.sh` inside the
CT) or are maintenance scripts called by hand, never imported by
`gamepanel`/`gamebroker`. Putting them inside `src/` would suggest they are part
of the Python package, which would break the expectation of someone looking at
`provision-game-lxc.sh` and expecting `games/*.env` in the same place as always.
`gamebroker.services.catalog` keeps **reading** `games/*.env` from the path
configured in `BROKER_GAMES_DIR` - that does not change.

### 2.2 Why `gamebroker` stays in the same repository

- It is already isolated where it matters (its own process, HTTP-only, zero cross
  imports - Phase 1, section 2.3).
- The two services **share** `games/*.env`, `lib/ct-phases.sh` and the
  deploy scripts - versioning them in separate repositories would create the
  classic "which broker commit goes with which panel commit" problem, with no
  isolation gain (the real isolation is already the process/CT, not the
  repository).
- A `uv` workspace is made exactly for "two independent packages, one
  repo, shared dev tooling" - the use case matches.
- If one day the team wants a different release cadence for the broker (e.g.
  a third party operating only the broker, without access to the panel code),
  splitting the repository later is easy precisely because the coupling is
  already zero - it is not a decision that closes doors.

### 2.3 Why "adapter per game" becomes **two** catalogs, not one

The project already has two game catalogs, solving different problems:

| | `gamebroker` (curated catalog) | `gamepanel` (field adapter) |
|---|---|---|
| Question it answers | "how do I install/allocate ports for this game?" | "which fields do I show on this game's quick-edit screen?" |
| Today | `games/*.env` (declarative) + `catalogo.py` | `gamefields.py` (5 dicts: Enshrouded/Palworld/Icarus/DayZ/Dragonwilds) |
| Coverage | Every game installable by the broker (curated + dynamic from the API) | Only the 5 games with a quick-edit screen - the rest fall back to the generic file editor |
| Runs in | Broker process (another CT) | Panel process |

Forcing both into a single `GameAdapter` would only make sense if `gamepanel` and
`gamebroker` shared Python code - and they deliberately do not (they communicate
only over HTTP, each in its own process/CT). A shared "universal" `games/` would
require either (a) a third Python dependency installed on both sides (one more
package to version and one more thing that can diverge between panel and broker
in production), or (b) duplication from scratch - neither is better than keeping
the two catalogs that already exist, just formalized as adapters on each side
(section 2, above).

The real gain of "adding a game = just one adapter" already exists today on the
broker side (editing `games/*.env` touches no Python code) and starts to exist
on the panel side after Phase 4 (create `adapters/novo_jogo.py` and register it
in `registry.py`, without touching the routes or the other adapters) - but they
remain two extension points, not one.

---

## 3. Mapping table

### 3.1 `admin/` -> `src/gamepanel/`

| Current path | New path | Note |
|---|---|---|
| `admin/app.py` (sections 1-3, 42: config/factory/security headers) | `gamepanel/app.py`, `gamepanel/config.py`, `gamepanel/extensions.py` | splitting the Flask bootstrap |
| `admin/app.py` (section 4: SCHEMA/MIGRATIONS) | `gamepanel/persistence/schema.py` | |
| `admin/app.py` (section 4: password hash) | `gamepanel/security/passwords.py` | |
| `admin/app.py` (section 5: auth/csrf/2fa gate) | `gamepanel/services/auth_service.py` + `gamepanel/security/csrf.py` + `gamepanel/blueprints/auth.py` | |
| `admin/app.py` (section 5: navigation context) + `admin/ui.py` | `gamepanel/navigation.py` | `ui.py` is already pure, only changes place |
| `admin/app.py` (section 6: SSH) | `gamepanel/runtime/ssh.py` | |
| `admin/app.py` (section 7: A2S) | `gamepanel/runtime/a2s.py` | |
| `admin/app.py` (sections 8-9: HTTP API counting+actions) | `gamepanel/runtime/http_probe.py` + `gamepanel/services/player_service.py` + `gamepanel/blueprints/players.py` | |
| `admin/app.py` (sections 10-11: log/port) | `gamepanel/runtime/log_replay.py`, `gamepanel/runtime/port_probe.py` | |
| `admin/app.py` (section 12: counting source) | `gamepanel/services/player_service.py` | `FONTES_DE_CONTAGEM` becomes a registry in the service |
| `admin/app.py` (section 13: metrics) | `gamepanel/runtime/metrics_probe.py` + `gamepanel/services/metrics_service.py` | |
| `admin/app.py` (section 14: status) | `gamepanel/services/status_service.py` | |
| `admin/app.py` (section 15: jobs/commands) | `gamepanel/services/job_service.py` | `COMANDOS`/`ACTIONS` + the sync `assert` with `ui.py` become part of the registry |
| `admin/app.py` (sections 16-17: alerts) | `gamepanel/services/alert_service.py` + `gamepanel/integrations/webhook_client.py` | `ALERTAS_DE_RECURSO` becomes a registry in the service |
| `admin/app.py` (section 18: log stream) | `gamepanel/tasks/log_streams.py` | |
| `admin/app.py` (section 19: monitor) | `gamepanel/tasks/monitor.py` | `_ritmo_do_monitor`/`_alertas_do_servidor` were already the "good" exception - they become the model for the other services |
| `admin/app.py` (section 20: samples) | `gamepanel/services/chart_service.py` | |
| `admin/app.py` (section 21: scheduler) | `gamepanel/tasks/scheduler.py` + `gamepanel/services/schedule_service.py` | |
| `admin/app.py` (sections 22-41, 43: routes) | one `gamepanel/blueprints/*.py` per screen (table in section 2) | thin layer - only validates and calls the service |
| `admin/app.py` (section 26: form validation) | `gamepanel/services/server_service.py` | `_form_server` and the ~10 helpers `_porta`/`_servico`/etc. |
| `admin/app.py` (section 29: terminal) | `gamepanel/runtime/terminal.py` (class `TermSession`) + `gamepanel/blueprints/terminal.py` | |
| `admin/app.py` (sections 30-32: files/backup) | `gamepanel/runtime/files.py` + `gamepanel/services/file_service.py`/`backup_service.py` + matching blueprints | the 9 bash scripts (`LIST_SCRIPT` etc.) move to `runtime/files.py`/`runtime/backup.py` as local constants, no longer loose in the middle of routes |
| `admin/app.py` (section 33: quick config) | `gamepanel/blueprints/config_quick.py` + `gamepanel/games/` | wires `gameconf.py`+`gamefields.py` (now `games/config_format.py`+`games/adapters/`) to the form |
| `admin/app.py` (section 35: broker) | `gamepanel/services/broker_service.py` + `gamepanel/tasks/broker_jobs.py` + `gamepanel/blueprints/broker.py` | |
| `admin/app.py` (section 37: charts) | `gamepanel/services/chart_service.py` + `gamepanel/blueprints/charts.py` | |
| `admin/app.py` (section 44: CLI bootstrap) | `gamepanel/cli.py` | `ensure_admin_user`, `DeployServer`, `ensure_server`, `argparse` |
| `admin/gameconf.py` | `gamepanel/games/config_format.py` | pure today, only changes name/place |
| `admin/gamefields.py` | `gamepanel/games/base.py` + `gamepanel/games/adapters/*.py` | 5 dicts -> 5 files + 1 `Protocol` |
| `admin/broker_client.py` | `gamepanel/integrations/broker_client.py` | pure/stdlib today, only changes place |
| `admin/totp.py`, `admin/qr.py` | `gamepanel/security/totp.py`, `gamepanel/security/qr.py` | pure today, only change place |
| `admin/busca_de_jogos.py`, `admin/modelos_de_jogo.py`, `admin/sugestoes_de_jogos.py` | `gamepanel/games/catalog/search.py`, `templates.py`, `suggestions.py` | `sugestoes_de_jogos.py` stays **generated**, only the output path of `tools/import-linuxgsm.py` changes |
| `admin/templates/`, `admin/static/` | `gamepanel/templates/`, `gamepanel/static/` (inside `src/gamepanel/`) | Flask resolves them by default relative to the package |
| `admin/test_*.py` (14 files) | `tests/gamepanel/{unit,integration}/...` | reorganization **in steps** - see section 6, not 1:1 right away |
| `admin/conftest.py` | `tests/conftest.py` (+ specializations in `tests/gamepanel/conftest.py` if needed) | |

### 3.2 `broker/` -> `src/gamebroker/`

An almost 1:1 mapping - `broker/` is already well divided, it is mainly a
path change + name translation:

| Current path | New path |
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
| `broker/fake_http.py` | `gamebroker/runtime/http_fake_server.py` (test only) |
| `broker/banco.py` | `gamebroker/persistence/db.py` |
| `broker/conexao.py` | `gamebroker/integrations/http_client.py` |
| `broker/config.py` | `gamebroker/config.py` |
| `broker/test_*.py` (12 files) | `tests/gamebroker/{unit,integration}/...` |

---

## 4. Refactor plan per module

Recommended execution order for Phase 4 (after Phase 3 stabilizes the new
structure without changing behavior):

1. **`gamepanel/games/`** (was `gameconf.py`+`gamefields.py`) - already pure, no
   Flask/database/SSH; lowest risk, a good first module to validate the
   "behavior test before refactoring" pattern with a small module.
2. **`gamepanel/security/`** (`totp.py`, `qr.py`) - same, pure, low risk.
3. **`gamepanel/runtime/`** - extract the SSH/A2S/HTTP/log layer from inside
   `app.py` behind an interface (`RemoteControl` Protocol), with
   `runtime/fakes.py` so tests start using a fake instead of
   `monkeypatch` of a loose function. **This is the module that unblocks the rest**
   - without it, `services/` has no way to be free of direct SSH.
4. **`gamebroker/`** - only reorganize/rename (the 1:1 mapping of section 3.2);
   it has almost no SRP to fix, it is already well divided. It is the
   "least effort, validates the migration pattern" module for the team.
5. **`gamepanel/services/`**, one at a time, in this order: `player_service` ->
   `metrics_service`/`status_service` -> `alert_service` -> `schedule_service`
   -> `server_service` -> `broker_service` -> `backup_service`/`file_service`
   (in this order because `alert_service` already depends on `player`/`metrics`, and
   `server_service` is the largest, with the most validation branching).
6. **`gamepanel/blueprints/`** last, screen by screen - by that point each
   route should already be a thin pass-through to the corresponding service.
7. **`gamepanel/persistence/repositories/`** - replace the inline raw SQL with
   one function per table, in parallel with item 5 (each service gets its
   repository at the moment it is extracted, not in a separate pass).

**Sonar/CLAUDE.md problems solved by this order**:
- Cognitive complexity >15: the split into service+blueprint already solves
  most of it - the whole `app.py` collapses from 8,175 lines / 44 sections into ~25
  files of 100-300 lines each.
- "13+ parameters -> object": `broker/config.py`/`prod.py` already use this
  pattern (`**dict` for `ConfigProxmox`/`ConfigBroker`) but lose type at that
  edge (mypy finding, Phase 1 section 6.2) - in Phase 4, when typing `gamebroker`,
  switching to `TypedDict` or field-by-field validation solves both at
  once (the parameter smell AND the type error).
- `except Exception` without a correct `# noqa`: the real `ruff` config (item
  below) needs to enable the rule set (`BLE001` etc.) that the
  `# noqa: BLE001` comments in the code already assume - without it, 9 suppressions
  become silent garbage (Phase 1 section 6.1 finding).
- The "run remote script, convert error" pattern repeated 7x in `app.py` becomes
  a single method in `runtime/ssh.py`/`runtime/files.py`.
- The three nearly identical thread fan-out implementations (`all_status`/
  `all_metrics`/`all_players`) become one generic function in `runtime/base.py`
  or a shared utility, used by the three services.
- `subprocess`/`Popen` without `check=`/with `preexec_fn` (ruff finding, Phase 1
  section 6.1, `PLW1510`/`PLW1509`) - fixed when moving to `runtime/ssh.py`,
  where they are concentrated and reviewable in a single place.

**`ruff`/`mypy` configuration to create** (in the root `pyproject.toml`, Phase 3):
```toml
[tool.ruff]
line-length = 100
extend-exclude = ["src/gamepanel/games/catalog/suggestions.py"]  # generated

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "BLE", "S", "SIM", "RUF", "PL"]

[tool.mypy]
platform = "linux"          # production is always Linux - avoids the false positive
                             # of ioctl/setsid/openpty on Windows (Phase 1 section 6.2)
disallow_untyped_defs = true
```
(exact `select`/rule values to be adjusted with the owner before turning on `--fix`
for anything - that is also the owner's decision, I will not pre-approve new lint
rules without confirming.)

---

## 5. Breaking changes - individual decision

Picking up the full list from Phase 1 (section 7.3), organized into **decision
groups** (changing one item of a group usually means changing the whole
group, so it makes more sense to approve by group than item by item):

> **Status (updated during execution):** **A**, **B** and **D** were done - the broker
> API speaks English with its own wire layer (`gamebroker/domain/wire.py`), and both
> databases have a rename migration with a test that builds the old schema by hand
> (`tests/gamebroker/test_migration.py`, `tests/gamepanel/test_schema.py`). Still missing: **C**
> (panel routes, which still depends on the redirect preference), **E** and **F**.

| # | Group | What changes | Who consumes it | Risk | My recommendation |
|---|---|---|---|---|---|
| **A** | Broker routes + JSON payload (`/v1/saude`, `/v1/catalogo`, `/v1/instancias`, `/v1/operacoes`, keys `jogo`/`instancia_id`/`porta_jogo`/etc., error codes `nao-encontrado`/`sem-recurso`/etc.) | Translate everything to English | **Only** `gamepanel/integrations/broker_client.py`, in the same repo, in the same deploy | Low - 100% internal API, no external consumer, both sides change together in the same commit | **Translate now** (Phase 4), it is the cheapest breaking change on the list |
| **B** | Broker database columns (the whole schema: `ctid`, `estado`, `criado_em`...) | Translate + migration (the database is recreated on every new CT deploy, but existing data in a CT already running needs to migrate) | Only `gamebroker` (single process, owner of its own database) | Medium - needs a real migration (the broker database has state: active instances/ports/operations/audit) | **Translate with migration**, but only after confirming with the owner whether any broker already in production has data that cannot be lost |
| **C** | Panel HTTP routes (`/historico`, `/alertas`, `/usuarios`, `/agendamentos`, `/catalogo`, `/instancias`, `/graficos`) | Translate to English | Browsers of panel users (may have saved links/bookmarks) | Low-medium - internal panel, not a public API, but a human user may have a bookmark | Translate, with a 301 redirect from the old routes for a while (cheap to keep, avoids breaking bookmarks) - **I ask for the owner's preference below** |
| **D** | Panel database columns (`webhooks`, `alert_log`) | Translate + an entry in `MIGRATIONS` | Only `app.py`/`gamepanel` itself | Low - the incremental migration mechanism already exists and is exactly for this | **Translate**, it is the pattern the project itself already uses to evolve this schema |
| **E** | `BROKER_MAX_CRIACOES_HORA` (the only env var with a Portuguese word) | Rename to `BROKER_MAX_CREATIONS_PER_HOUR` | `provision-broker-lxc.sh`/`deploy-broker.ps1` (they regenerate the `.env` on every deploy - it is not a value that "persists" like a token/key) | Low | **Rename**, updating the deploy scripts in the same commit |
| **F** | Jinja filters (`"nivel"`, `"duracao"`, `"tamanho"`, `"ident"`) and Flask endpoint names used in `url_for()` | Translate | Only internal templates, updated in the same commit | Low | Translate together with the corresponding blueprint in Phase 4 (no separate approval needed - it is purely internal to the repo) |

Groups **E** and **F** do not really need separate approval (low risk,
everything in the same commit, no external consumer) - I only listed them for
completeness. The ones that really depend on the owner's decision are **A-D**, and
especially the transition preference in **C** (panel route - clean cut vs.
temporary redirect). I will ask about that right after, in this message.

---

## 6. Risks and what can break

- **Production does not use `pip install` - the `src/` layout changes how Python
  resolves `import gamepanel`.** Today `gunicorn ... app:app` works because
  the process runs with `cwd=/opt/gamepanel` and the files are loose there
  (no package). **Validated in Phase 3, step 2**, against the real image
  (`debian:13-slim` + `apt-get install python3-flask gunicorn`, no pip,
  no editable install - exactly the production constraint): `gunicorn
  --chdir /opt/gamepanel/src gamepanel.wsgi:app` resolves `import gamepanel`
  without needing any `PYTHONPATH` (gunicorn inserts the `cwd` resolved by
  `--chdir` into `sys.path`, the same mechanism that already makes `app:app` work
  today). Decision: the deploy starts copying the tree as
  `/opt/gamepanel/src/gamepanel/...` and the systemd unit/`Dockerfile` gain
  `--chdir /opt/gamepanel/src` on the gunicorn line - one more parameter,
  no new environment variable. This goes into step 5 (actually moving `app.py`),
  together with updating `provision-admin-lxc.sh::render_service`,
  `docker/panel/entrypoint.sh` and `docker/panel/Dockerfile*`.
- **`provision-admin-lxc.sh`/`deploy-admin.ps1` and the broker equivalents
  do `push_tree`/scp by fixed path** (`admin/*.py`, `templates/`,
  `static/`) - every path changes and both scripts (plus
  `docker/panel/Dockerfile*`, `docker/broker/Dockerfile`) need to be
  updated in the same step that moves the files (`git mv` + script update in
  the same commit, per step - not separately).
- **`docker-compose.yml` mounts `admin/` as a `:ro` bind mount** - it becomes a
  bind mount of `src/gamepanel/` (or of the whole repo with `--reload` pointing at
  the new path). Testing that hot reload keeps working is part of the
  "go through every screen" that `CLAUDE.md` already asks for after touching a
  route.
- **`pytest.ini` (`testpaths = admin broker`) and `pyrightconfig.json`
  (`extraPaths`, `include`)** need to point at the new paths - without
  that, the 851 tests documented in `CLAUDE.md` simply are not
  collected (silence, not an error - risk of "the tests pass" becoming a
  lie by collecting zero tests).
- **The `monkeypatch.setattr(panel, "funcao", ...)` test pattern** (Phase 1
  section 2.1) only works while the swapped function is called through the module, never
  imported by name. When splitting `app.py` into `services/`, each extraction
  needs to change `monkeypatch.setattr(panel, "x", fake)` to
  `monkeypatch.setattr(player_service, "x", fake)` (or official DI via
  `runtime/fakes.py`) **in the same commit** that moves the function - never later.
  This is the biggest "lying green test" risk of Phases 3/4.
- **The panel `entrypoint.sh` runs a Python heredoc** that calls
  `app.ensure_server(...)` directly (a `CLAUDE.md` finding: "a grep only on the
  `.py` files does not find it") - it becomes `gamepanel.cli.ensure_server`, and the
  heredoc needs the import fixed in the same commit that moves `cli.py`.
- **`lib/ct-phases.sh` and `provision-game-lxc.sh` read `games/*.env` by a fixed
  relative path** - since `games/` does not move (section 2.1), this does not
  break, but it is worth confirming that no new script tries to "fix" that
  path by mistake during Phase 3.
- **`admin/requirements-dev.txt` referenced in `CLAUDE.md`** - if `uv` is
  approved (section 0), `CLAUDE.md` needs to be updated in the same commit
  that removes that file (it asks itself to keep `CLAUDE.md` as the source
  of truth for the commands).
- **`docker/ct-sandbox/compare.sh`** compares the installer before/after
  by reading `provision-game-lxc.sh`/`lib/ct-phases.sh` by fixed path - since
  those do not move, no risk, but it is the first thing to run after
  any change in `lib/` (`CLAUDE.md` itself already asks for this).

---

## 7. Migration plan in small steps (Phase 3)

Each step = branch -> `git mv` -> update imports/Dockerfile/compose ->
run tests -> commit. No behavior change mixed in (that is Phase 4).

1. **Create the skeleton**: root `pyproject.toml` + two sub-`pyproject.toml`,
   `uv.lock`, empty folders `src/gamepanel/`, `src/gamebroker/`,
   `tests/gamepanel/`, `tests/gamebroker/`. Validate that `uv sync` works and
   `pyrightconfig.json` resolves the packages.
2. **Done.** Validate the risk hypothesis of the `src/` layout in production
   (section 6, first item), in isolation, against the real panel image
   (`debian:13-slim` + apt, no pip), with a "hollow" `gamepanel` (`app.py` +
   `wsgi.py`, only the `/health` route) - before moving 8,175 real lines.
   Confirmed: `gunicorn --chdir /opt/gamepanel/src gamepanel.wsgi:app`
   resolves the import without extra `PYTHONPATH`. `src/gamepanel/app.py` and
   `wsgi.py` stay as they are (they become the seed of step 5, they are not
   throwaway).
3. **Move `gamebroker`** - but in two passes, not one, to keep each
   commit low-risk: **(3a, Phase 3, this step)** relocate `broker/` ->
   `src/gamebroker/` **flat**, same file names, same
   identifiers (`servico.py` stays `servico.py`, `Servico` stays
   `Servico`) - only the package path changes (`broker.X` -> `gamebroker.X`
   in the tests' absolute imports and in the deploy scripts). Zero behavior
   change, zero translation yet. **(3b, Phase 4)** the reorganization
   into subfolders (`services/`, `runtime/`, `persistence/`, `domain/`,
   `integrations/` - the section 3.2 mapping) happens **together** with the
   translation to English (groups A/B approved), module by module - since moving a
   file into a subfolder forces touching every import anyway, it makes more
   sense to do both changes (path + name) in the same pass per module,
   instead of two separate mechanical passes touching the same files twice.
   Update `docker/broker/Dockerfile`, `provision-broker-lxc.sh`,
   `deploy-broker.ps1`, `docker-compose.yml`. Run the ~415 broker tests.
4. **Move the pure modules of `admin/`** (`totp.py`->`security/totp.py`,
   `qr.py`->`security/qr.py`, `gameconf.py`+`gamefields.py`->`games/`,
   `ui.py`->`navigation.py`, `broker_client.py`->`integrations/`) - zero new
   logic, only `git mv` + import adjustment. Run the corresponding suites.
5. **Move the whole `app.py` to `gamepanel/app.py`** WITHOUT splitting it into modules
   yet (only its address changes) - separates "where things live" from "how
   things are organized", reducing the size of each risky commit.
   Update `docker/panel/Dockerfile*`, `provision-admin-lxc.sh`,
   `deploy-admin.ps1`, `docker-compose.yml`, `entrypoint.sh` (the heredoc).
   Move `templates/`/`static/`. Run the ~436 panel tests.
6. **Move `admin/test_*.py` to `tests/gamepanel/`** as they are (without
   splitting yet) - the split into `unit/`+`integration/` and the mirroring per
   service only makes sense module by module, as Phase 4 extracts each
   `services/*.py` (see section 4). In this step, only preserve 100%
   coverage by moving whole files.
7. **Update `CLAUDE.md`/`README.md`** with the new paths and the
   `uv run ...` commands - the last step of Phase 3, before declaring the structure
   stable and moving on to Phase 4.

From here, Phase 4 follows the order in section 4 (games -> security -> runtime
-> [internal gamebroker, if anything is left] -> services, one at a time -> blueprints ->
repositories), each module with its own commit, with the test written first if
coverage today is insufficient (backups/files/terminal, Phase 1 findings
section 4.1, are the first candidates to need this).

---

## Approved decisions (2026-09-22)

- **Overall structure (section 2)**: approved as is.
- **Group A/B (broker)**: translate the `/v1/*` routes, JSON keys and broker database
  columns to English. Confirmed that there is no broker in production with
  real instances/ports/operations yet - the schema migration can be done
  without a special backup plan (there is no real data to lose).
- **Group C (panel)**: translate the panel routes to English, with a temporary 301
  redirect from the old Portuguese routes (`/alertas`, `/usuarios`,
  `/historico`, `/agendamentos`, `/catalogo`, `/instancias`, `/graficos`) -
  the redirects go in during Phase 4, together with the corresponding blueprint, and can
  be removed after a period without observed use (to be decided when we
  get there).
- **Groups D/E/F**: follow the recommendation in section 5 (translate, no additional
  risk).

Phase 3 started right after.

---

## What has already been executed (updated on 2026-09-23)

This section is the record; the plan above stayed as it was approved, including where
the execution diverged from it - that is marked.

### Phase 3 - structure

Done. `admin/` and `broker/` became `src/gamepanel/` and `src/gamebroker/`, with
`tests/gamepanel/` and `tests/gamebroker/`, a `uv` workspace and `pyrightconfig.json`.

### Phase 4 - splitting `app.py`

Done, and more than section 4 anticipated. `app.py` went from 4949 to ~3200 lines:
`services/`, `runtime/`, `tasks/`, `persistence/`, `i18n/`, `security/`,
`integrations/` and - at the end - `blueprints/`, with the 78 routes in 19 files, one per
screen group.

What was **not** done from section 4: `games/gamefields.py` remains a single file (it did
not become an adapter per game), and there is no `repositories/`.

**A rule that came out of this and was not in the plan:** a blueprint always accesses
`app.py` through the MODULE (`panel.server_status(...)`). The tests swap a function for a
fake with `monkeypatch.setattr(panel, ...)`; a direct import would copy the reference at
import time and the swap would **silently** stop having any effect.

### Breaking-change groups

| group | what it was | status |
|---|---|---|
| A | database columns and tables (panel and broker) | done, with a `RENAME` migration in both |
| B | broker API (routes, body, response, header) | done, with `domain/wire.py` separating wire from column |
| C | panel routes | done, **without a 301 redirect** - diverges from the approved decision |
| D | i18n | done: English keys in both catalogs, with a parity test |
| E | broker environment variable | done |
| F | Jinja filters | done |

**Group C divergence.** The approved plan called for a temporary 301 redirect from the
Portuguese routes. The execution was a clean cut, on request: the panel is not public,
there is no external link to preserve, and a temporary redirect with no removal date
becomes permanent.

### Translating the identifiers

Done across the whole repository, beyond what the plan asked: besides the two Python
packages (including local variables), also the template context, the Jinja macros, the CSS
classes, the `data-*` attributes, the JavaScript and the bash and PowerShell function and
variable names. File names too (`catalogo.html` -> `catalog.html`, `busca-de-jogo.js` ->
`game-search.js`, `components/servidor.html` -> `components/server.html`).

What stays in Portuguese, on purpose and recorded in `CLAUDE.md`: comments,
docstrings, screen text (which lives in `i18n/`), test names and the sandbox output.

### Outside the plan, but done

- **Application version and deploy by packaged release.** `VERSION` at the root,
  `tools/build-release.py` (deterministic tarball + sha256), `lib/install-release.sh`
  publishing into `releases/<version>/` with a `current` symlink and automatic rollback.
  This fixed a defect that was live: each deploy path had its own hand-written list of
  which subfolders to delete before copying, and both stopped at
  `templates/ games/ security/ integrations/` - `blueprints/`, `i18n/`, `persistence/`,
  `runtime/`, `services/` and `tasks/` never made it in.
- **Versioned panel API** (`/api/v1/...`), like the broker's.
- **Four new safety nets**, all born from a real defect found during execution:
  `test_template_contract.py` (`render_template` kwarg with no reader),
  `test_frontend_contract.py` (class vs CSS rule, `data-*` vs reader),
  `test_javascript.py` (the JS parses, imports and MOUNTS) and `docker/ct-sandbox/release.sh`.

### What is left

- ~~`games/gamefields.py` split into an adapter per game~~ - **done**: `games/base.py`,
  `games/registry.py` and `games/adapters/` (5 games), with `test_game_registry.py`
  enforcing that no adapter is left out of the registry.
- ~~`repositories/`~~ - **done**: the seven panel tables (`servers`, `jobs`,
  `schedules`, `webhooks`+`alert_log`, `samples`, `settings`, `users`) have a repository,
  and `.execute(` only appears in `persistence/`. `test_sql_placement.py` guards the rule
  per table.
- ~~`services/auth_service.py`~~ - **done**, and smaller than section 5 anticipated: password
  hashing and checking had already moved to `security/passwords.py`, and the 2FA gate is
  a decorator that needs `session`/`request`, so it stays in `app.py`. What was left of
  pure policy was the **attempt lockout**, today the `Lockout` class (injectable clock,
  `login_lockout` and `totp_lockout` in `app.py`, `test_auth_service.py` with 11
  cases that need neither HTTP nor a global clock).
- **`services/backup_service.py` and `services/file_service.py` will not be created.** What
  the plan asked of them already exists, under another name: `runtime/backups.py` (`backup_command`,
  `backup_paths`, `list_backups`, `delete_backup`, `validate_backup_name`) and
  `runtime/files.py` (`clean_path`, `_check_roots`, with injected roots). Creating a
  layer on top just to match the paper design would be one more pass-through to read.
- ~~`tasks/monitor.py`~~ - **done in the part that mattered**: the six background clocks
  (`global _last_monitor` and friends) became instances of `tasks.ticker.Ticker`, with
  separate `due()`/`mark()` and 9 tests that need neither a database nor sleeping. The body
  of `monitor_servers` stays in `app.py`: it only orchestrates, and it has been split into
  `_monitor_rhythm` + `_server_alerts` since before (it was the "good" example the plan cites).
- ~~`deploy/`~~ - **done**: the 10 scripts at the root went to `deploy/{admin,broker,game}/`,
  and the root kept only `CLAUDE.md`, `README.md`, `VERSION`, the configuration files and
  the folders. The item was in section 2 of the approved plan and **was not on this list** -
  together with the two below, they were the three forgotten ones.

  What the change forced, and was not anticipated: **`$ScriptDir` was not "this script's
  folder", it was the repository root.** At the root the two coincided, and the `.ps1` files
  used the same name to find the sibling `provision-*.sh` AND to find `tools/`, `lib/`,
  `games/` and the `.env`. Now they are `$ScriptDir` and `$RepoRoot`, and the difference is
  written down. `compare.sh` got the same treatment it already gave `ct-fases.sh`: it looks
  for the script at today's path and falls back to the old one, so that `BASE_REF` keeps
  pointing at commits from before the change.
- ~~`pytest.ini` inside `pyproject.toml`~~ - **done**: the configuration became
  `[tool.pytest.ini_options]`, next to the ruff and mypy ones, and the root lost one more file.
  The apt pytest in the container (8.3) reads the section; checked by running the suite there.

  As a bonus, `filterwarnings` pointed at **three hand-written modules and one of them no
  longer existed** (`gamepanel.games.gamefields`, split into `games/base.py` + `registry.py`
  + `adapters/` commits earlier). A filter pointing at a nonexistent module warns about nothing
  and nobody finds out. It became the package PREFIX (`gamepanel`), which covers any new
  module - including an adapter - and does not rot. Checked with a probe in both directions:
  a warning attributed to `gamepanel.*` becomes an error, one attributed to `gamebroker.*` does not.
- ~~`tests/{unit,integration}/`~~ - **done**, and section 2 was right: 991 unit tests
  in **28 s** against 910 integration tests in **126 s**. I measured both buckets before
  moving any file, precisely so as not to pay the cost without knowing whether the benefit existed.

  What the execution found, measuring instead of assuming:

  1. **Import by name CROSSES the subfolder** - it was what I thought would break, and it
     does not: with `conftest.py` in `tests/<package>/`, a test in `unit/` keeps doing
     `from fake_http import ...`, because loading the conftest puts that folder on `sys.path`.
  2. **What breaks is an import between BUCKETS**, and only when the split is used for what
     it is for: a file in `integration/` importing from `unit/` passes in the whole suite
     (`unit/` was collected first) and gives `ModuleNotFoundError` when running only
     `integration/`. There were two cases, both pulling `FakeRunner` from inside
     `test_ssh_installer.py`; the double moved out to `fake_ssh.py`, next to `fake_http.py`.
     `test_suite_layout.py` guards the rule, with both sides checked by breaking them on purpose.
  3. **A pre-existing flaky test**, which only showed up because running one bucket alone
     is fast enough to repeat five times: the scheduler test counted
     `threading.active_count()`, and importing `gamepanel.app` already starts its own thread.
     It failed 1 in 3. The `Clock` thread got a name and the test counts only its threads.
- `extensions.py`, `services/user_service.py` and the panel's `runtime/base.py`+`runtime/fakes.py`
  remain open: they are orchestration extractions, with no test gain like the
  previous ones. `extensions.py` even contradicts the description of `app.py` itself in
  CLAUDE.md ("the assembly: database, session, decorators, tables"), which is exactly what
  it would take away.

### Gaps from the analysis (Phase 1) that were closed

- **Console suite.** Section 4.1 of the analysis listed four privileged routes without a
  dedicated suite: files, backups, terminal and console. The first three got a suite over
  the course of the execution; the console - the one that runs a shell line as **root** in
  the container - was the last, and now has 25 cases: who opens it, what becomes a job, how
  the command arrives (`bash -lc` with a single argument, so ssh's local shell does not
  interpret pipes and quotes) and what the history shows, including that `?job=` from
  another server does not open.
- **The three duplicated fan-out functions** (`all_status`/`all_metrics`/`all_players`)
  became `parallel.per_server`, and the "run remote script and convert error" pattern, which
  was there seven times, became `runtime/files.py`.

### The quality survey (Phase 1, section 6) - zeroed

The `ruff` and `mypy` configuration that section 4 asked for had existed since Phase 3, and
**nobody had acted on the findings**: 97 in ruff and 11 in mypy. A list that never reaches zero
is a list nobody reads, so both are at **zero** now, and every finding got an answer instead
of a suppression:

- **Two `assert`s guarded an invariant that `python -O` discards.** Measured: with `-O`, the
  divergence between `ui.ACTIONS` and `app.COMMANDS` - the one CLAUDE.md describes as "500 on
  click" - goes through silently. They became `raise`, and the invariant now brings down the
  start, which is the right behavior.
- **Three `pytest.raises(match=...)` with an unescaped `.`**, matching text that was not
  intended (`BROKER_SSH_KEY.pub` would also match `BROKER_SSH_KEYXpub`). The two deliberate
  `.*` became raw strings, so that the intent is stated.
- **A `zip()` silently truncated** in the `install.env` parser; today discarding the final
  piece is explicit and `strict=True` blows up if the count turns odd for another reason.
- **The gauge color thresholds (92/80) were written twice**, in Python and in
  JavaScript, and nothing tied them together: diverging made the bar change color on reload
  and not on the gauge that moves. They became `GAUGE_HOT`/`GAUGE_WARN` with a test comparing
  both files.
- **Six `# noqa` suppressed nothing** and four section dividers were read as commented-out
  code - the same family as the `# Palavra: coisa.ext` CLAUDE.md already recorded.
- **`PLR2004` was turned off IN THE CONFIG, with the reason**, after looking at all 19 one by
  one: 3 became constants and the remaining 13 are protocol numbers (`200 <= status < 300`,
  `<= 254`, `1024`), where naming makes reading worse. Turning it back on is deleting one line.

And a doc correction that came out of measuring: CLAUDE.md claimed that
`# noqa: BLE001 - motivo` was "invalid suppression syntax". **It is not** - ruff honors the
reason at the end and keeps the suppression specific to the code. The preference for the
reason above stays, but as style, not as a correction.

### Real defects found after the plan

- **Every error page was in Portuguese on the English screen.** `abort(403, "frase")` +
  `str(exc)` in the handler: the literal phrase goes through `translate` and comes back the
  same, and the `str(exc)` of an `HTTPException` collapses the `i18n.Message` into the deploy
  language. There were 22 phrases (barriers, form errors and validation flashes), proven
  against the live container and now guarded by `test_screen_text.py`.
- **The docs pointed to eight files that no longer existed** (`conexao.py`,
  `ssh_install.py`, `servico.py`, `backends.py`, `test_gamefields.py`, `instancias.html`,
  `catalogo.html`, `gameconf.py`), plus `ui.py`, `prod.py` and a mistyped `pyroject.toml`.
  They got through because the doc safety net discarded anything with an extension - the
  filter that avoided the false positive was the hole. `test_docs_contract.py` now checks
  file names too.
- A REAL end-to-end instance creation through the broker against Proxmox/OPNsense.
