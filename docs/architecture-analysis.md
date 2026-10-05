# Architecture analysis - current state

> **Historical:** this Phase 1 analysis drove the Phase 3 reorganization (`admin/`/`broker/` ->
> `src/gamepanel/`/`src/gamebroker/`, English identifiers, `app.py` split into blueprints),
> which is done. Paths and names below describe the code as it was when this was written.

> Read-only survey (Phase 1). No project file was changed to produce this
> document. Generated on 2026-09-22, against `main` at `ee44d90`.
> This document is the input for the reorganization proposal (Phase 2) - it is
> not, in itself, a plan of change.

## Executive summary

- **~17,100 lines** of Python in `admin/` (of which **8,175 in `app.py` alone**,
  a monolith with routes + business rules + SSH/subprocess + raw SQL in the same
  file) and **~5,750 lines** in `broker/` (a smaller package, already well
  separated by interfaces).
- **All tests pass** today: the whole suite (`admin/` + `broker/`) is green,
  2 skipped on Windows (expected, see `CLAUDE.md`). There is no broken test
  to "fix before reorganizing".
- **There is no CI/CD** in the repository (no `.gitlab-ci.yml`, `Jenkinsfile`
  or `.github/workflows` - `docker-compose.yml` is the only `.yml`). This is
  new work, not integration with something existing.
- **There is no `ruff`, `mypy` or Sonar configured** today. I ran the first
  two manually against the code (see section 6): the result is
  **surprisingly clean** for code without those tools - the vast majority of
  `ruff` findings come from a single **generated** file
  (`sugestoes_de_jogos.py`), and `mypy` without types still finds only a few
  dozen real problems in ~23 thousand lines.
- **`broker/` already follows a good part of the principles Phase 2 will ask for**
  (dependency inversion via `typing.Protocol`, thin HTTP layer, coupling
  with `admin/` only over HTTP). **`admin/app.py` is the opposite**: a single file
  with 44 different functional sections, no service layer, no DAO, with
  bash scripts as module constants next to Flask routes.
- **There are TWO real, documented production runtimes** - Proxmox LXC
  (`provision-game-lxc.sh`) and plain Docker (`deploy-docker.ps1` +
  `docker/gameserver/`) - which already validates, in practice, the idea of an
  abstract `runtime/` layer requested for Phase 2 (it is not a solution to a
  hypothetical problem; the project already has two concrete runtimes today).
- **Portuguese naming is everywhere** - it is not an isolated deviation,
  it is the project's predominant convention (Python identifiers, ~half of the
  HTTP routes, two tables of the panel database, every broker module,
  `.ps1` script parameters). That makes translating to English a project
  the size of a partial rewrite, not a mechanical rename - see section 7.

---

## 1. What each folder/module does today

| Path | What it is |
|---|---|
| `admin/` | Flask panel. A single Python process, served by gunicorn. Full web interface: authentication+2FA, server CRUD, remote SSH, PTY terminal, file editor, backups, monitor/alerts, scheduler, charts, broker integration. |
| `broker/` | Separate HTTP service (its own Python package, `__init__.py`). Creates/deactivates/removes game instances through the Proxmox API and opens/closes ports through the OPNsense API. Holds the credentials the panel never sees. |
| `games/` | **Curated** game catalog: one declarative `.env` per game (`dayz.env`, `palworld.env`, ...), read by `broker/catalogo.py` with its own parser (never `source`/shell). |
| `docker/` | Six subfolders, with very different roles (see section 3): the **dev** environment (`panel/`, `broker/`, `game/`), an **alternative production** runtime (`gameserver/`, used by `deploy-docker.ps1`), and a **test** environment (`ct-sandbox/`, compares the installer before/after changes). |
| `lib/` | Two game installation phases (`ct-phases.sh`, `ct-install.sh`) shared between the Proxmox path (host, via `pct exec`) and the broker path (inside the CT, via SSH). |
| `tools/` | Manual development scripts: `import-linuxgsm.py` (generates `admin/sugestoes_de_jogos.py`) and `verify-qr.py` (checks `admin/qr.py` against a real QR reader). Neither runs in production or in pytest. |
| `*.ps1` at the root (`deploy-*.ps1`, `check-broker-access.ps1`, `spike-broker-write.ps1`) | Deploy scripts (Proxmox and Docker) and two manual diagnostic/access-proof tools - none of them called by the automated deploy. |
| `*.sh` at the root (`provision-*.sh`) | Scripts that run **on the Proxmox host** (sent via `pct push`/scp by the `.ps1` files) to provision CTs: panel, broker, game (via Steam) and TeamSpeak (its own path, it does not come from Steam). |
| `pytest.ini`, `pyrightconfig.json` | Test config (root, covers `admin/` and `broker/`) and editor config (Pylance/Pyright) - they do not affect the runtime. |
| `.env` / `.env.example` (root) | **Deploy-time** config (Proxmox/Docker) - not what the Python process reads in production (see sections 3 and 7). |

`services/` shows up as an empty directory on disk, but **it is not tracked
by git** (there is no file inside) - it is not a module in use, it is local
residue; it does not need to enter the Phase 2 mapping.

### 1.1 `admin/` - file by file

| File | Lines | Responsibility |
|---|---|---|
| `app.py` | 8,175 | Flask routes, SQLite schema/migrations, auth+CSRF+2FA, SSH/subprocess, A2S, game API HTTP, log parsing, monitor/alerts, scheduler, PTY terminal, file editor, backups, broker integration, SVG charts, CLI bootstrap. **All in one module.** |
| `ui.py` | 292 | Navigation map (`NAV_PRINCIPAL`, `SECOES_DO_SERVIDOR`) and power actions (`ACOES`). Pure - zero Flask, zero database. |
| `gameconf.py` | 715 | Text parser/writer for game config (ini/json/serverDZ.cfg), preserving formatting. Pure. |
| `gamefields.py` | 419 | Static catalog (`ENSHROUDED`, `PALWORLD`, `ICARUS`, `DAYZ`, `DRAGONWILDS`) that gives meaning to the keys `gameconf.py` reads. |
| `broker_client.py` | 191 | Stdlib-only HTTP client for the broker, TLS pinned by SHA-256. The panel's single point of contact with the broker process. |
| `totp.py` | 122 | TOTP RFC 6238 + recovery codes, pure stdlib. |
| `qr.py` | 301 | QR code generator (ISO 18004) implemented from scratch, no external libs. |
| `busca_de_jogos.py` | 62 | Search by name/App ID over the generated catalog. |
| `modelos_de_jogo.py` | 68 | Static "Unreal Linux" template to pre-fill the catalog form. |
| `sugestoes_de_jogos.py` | 1,811 | **Generated** by `tools/import-linuxgsm.py` - static data, do not edit by hand. |

### 1.2 `broker/` - file by file

| File | Lines | Responsibility |
|---|---|---|
| `__init__.py` | 5 | Package docstring. |
| `api.py` | 113 | Pure HTTP layer (Flask): registers the 7 `/v1/*` routes, authenticates, translates domain exceptions into JSON. **No business rule here** (explicit comment in the code). |
| `servico.py` | 252 | Orchestration/business rules: create/deactivate/remove instance, quotas, atomic reservation of CTID/IP/port, asynchronous execution in a thread, undo on failure. The only module that knows database+catalog+backends at the same time. |
| `backends.py` | 71 | Four `Protocol`s (`Proxmox`, `Opnsense`, `Instalador`, `Rede`) - the interfaces `servico.py` knows. |
| `proxmox.py` | 192 | Real Proxmox backend (REST API). |
| `opnsense.py` | 218 | Real OPNsense backend (ports via alias/HTML, fails closed). |
| `ssh_install.py` | 253 | Real implementation of `Instalador`: `ssh`/`scp`, `install.env` always `shlex.quote`, removes its own key at the end. |
| `rede.py` | 25 | Real implementation of `Rede` (ping). |
| `fakes.py` | 101 | The four fake backends (tests and `dev.py`). |
| `fake_http.py` | 259 | Fake HTTP servers that reproduce real Proxmox/OPNsense rules discovered in a spike. |
| `catalogo.py` | 546 | The largest file in the package. Shell-free `.env` parser, curated + dynamic catalog, atomic JSON persistence. |
| `alocador.py` | 120 | Pure functions: pick CTID/IP, allocate ports. |
| `conexao.py` | 144 | Stdlib HTTP client with TLS pinned by SHA-256 - used by `proxmox.py` and `opnsense.py`. |
| `banco.py` | 223 | SQLite schema and all persistence - accessed **only** by `servico.py`. |
| `config.py` | 207 | Reads/validates every `BROKER_*`/`PROXMOX_*`/`OPNSENSE_*` env var, accumulating every error before refusing to start. |
| `erros.py` | 42 | HTTP-aware exception hierarchy (`Recusa` -> `ErroDeValidacao`, `NaoEncontrado`, `Conflito` -> `SemRecurso`, `CotaExcedida`). |
| `dev.py` | 57 | Dev entry point (`python3 -m broker.dev`) - 100% fake backends, Flask dev server. |
| `prod.py` | 60 | Production entry point - WSGI factory for gunicorn, real backends. |

---

## 2. How the modules communicate

### 2.1 `admin/` - star graph, no cycle

```
app.py  ->  broker_client.py, busca_de_jogos.py, gameconf.py, gamefields.py,
           qr.py, totp.py, ui.py, modelos_de_jogo.py
busca_de_jogos.py -> sugestoes_de_jogos.py (generated data)
```

`ui.py`, `gameconf.py`, `gamefields.py`, `totp.py`, `qr.py`, `modelos_de_jogo.py`
are pure leaves - zero imports among themselves, zero imports of `app.py`. There
is no circular import. That is good, but it is also **the only good thing at the
import level** - the absence of cycles does not prevent 44 different
responsibilities from living in the same file (`app.py`).

This star graph is also what supports the project's test pattern
(`monkeypatch.setattr(panel, "funcao", ...)`, documented in `CLAUDE.md`):
any refactor that moves a function from `app.py` into a submodule imported
by function reference (instead of by module name) silently breaks that
pattern. That is a real constraint for Phases 3/4, not just a detail.

### 2.2 `broker/` - dependency inversion in practice

```
erros.py, catalogo.py     - base modules, imported by almost everything
alocador.py                -> catalogo.py, erros.py
backends.py                -> alocador.py, catalogo.py      (the 4 interfaces)
banco.py                   -> alocador.py, erros.py
fakes.py                   -> alocador.py, backends.py, catalogo.py
proxmox.py, opnsense.py    -> conexao.py (+ alocador.py in opnsense)
ssh_install.py              -> alocador.py, catalogo.py
config.py                  -> alocador.py, conexao.py, proxmox.py, ssh_install.py
servico.py                  -> alocador.py, backends.py, banco.py, catalogo.py, erros.py
api.py                      -> erros.py, servico.py
dev.py                       -> alocador.py, api.py, banco.py, catalogo.py, fakes.py, servico.py
prod.py                      -> api.py, backends.py, banco.py, catalogo.py, config.py,
                                conexao.py, opnsense.py, proxmox.py, rede.py,
                                servico.py, ssh_install.py
```

Key point: **`servico.py` (the business rules) never imports `proxmox.py`,
`opnsense.py`, `ssh_install.py`, `rede.py`, `config.py` or `conexao.py`** - only
the interfaces in `backends.py`. What wires the concrete implementation into the
service are the entry points (`dev.py` with fakes, `prod.py` with real ones). This
is already the dependency inversion design that Phase 2 will ask for `admin/` -
`broker/` serves as the reference for "how we already did this in here".

### 2.3 Coupling between `admin/` and `broker/`

**Confirmed by two independent agents, by grep across the whole repo**: there
is no `import broker` / `from broker import` in `admin/`. The only mention of
"broker" in `app.py` is `import broker_client`, which is the **panel's own**
module (`admin/broker_client.py`), not the `broker/` package. Communication is
**HTTP only**, with TLS pinned by SHA-256 in both directions
(`admin/broker_client.py` and `broker/conexao.py` implement the same pinning
pattern independently - **intentional** duplication: each side of the trust
boundary has its own pin, they do not share validation code).

This means that, architecturally, **`broker/` could already be today a service/
process fully separate from the panel** (in practice it already is - it lives in
another Proxmox CT in production) - the Phase 2 question is not "separate it", it
is "which repository/package should it live in from now on" (see the explicit
Phase 2 question about this, and the recommendation in the next section).

### 2.4 Problematic coupling inside `admin/app.py`

This is the part that matters most for the refactor plan:

- **Routes calling SSH/subprocess directly, with no intermediate layer.**
  Virtually every file/backup/config route calls `ssh_run`/`ssh_output`
  inline (`console()`, `files()`, `config_quick()` -> `load_config_doc()` ->
  `read_file()`, `backup_create()`). There is no repository/DAO or service layer
  - the Flask view **is** the infrastructure layer.
- **Bash scripts as module constants, next to Flask routes in the same
  namespace**: `HTTP_FETCH_SCRIPT`, `LOG_FOLLOW_SCRIPT`, `LISTEN_PORTS_SCRIPT`,
  `METRICS_SCRIPT`, `LIST_SCRIPT`/`READ_SCRIPT`/`WRITE_SCRIPT`/`DELETE_SCRIPT`,
  `BACKUP_SCRIPT`/`RESTORE_SCRIPT`/`BACKUP_DELETE_SCRIPT`, `UPLOAD_SCRIPT`,
  `HTTP_PROBE_SCRIPT` - nine multi-line shell blocks (30-100 lines each)
  mixed with Python functions. There is no separation of "remote infra" vs
  "panel logic".
- **"Business" functions that decide HTTP directly**: `_liga_contagem_a2s`,
  `_liga_contagem_http`, `_liga_contagem_log` do validation + `UPDATE` in the
  database + return `redirect(...)` (error) or `None` (success) - the route just
  passes the return value through. Mixes the HTTP layer with business rules in
  the same function.
- **Seven ad-hoc cache/lock mechanisms**, with no common abstraction:
  `_players_cache`/`_metrics_cache`/`_status_cache`/`_estado_monitor`/
  `_streams`/`_terms`/`_login_fails`, each with its own lock.
- **Raw SQL scattered across every route**, no DAO - dozens of inline
  `conn.execute("UPDATE ...")`/`SELECT` inside the route functions themselves.
- **The exception that already shows the right path**: `_ritmo_do_monitor` /
  `_alertas_do_servidor` (cited in `CLAUDE.md` itself as the example of
  "separate deciding from doing", cognitive complexity 48 -> <10) is proof that
  the right pattern was already applied once in this file - only on an island;
  the rest of `app.py` does not follow it.

This confirms, with concrete evidence, the premise of Phase 2 in the original
request: `admin/app.py` needs a thin HTTP layer + `services/` with the business
rules + isolation of the runtime (SSH/subprocess) behind an interface - exactly
the four principles listed in the request.

---

## 3. Entry points

### 3.1 Panel (`admin/`)

| Environment | How it starts |
|---|---|
| **Dev** (`docker compose up`) | `docker/panel/Dockerfile` (Debian 13 + `python3-flask`, `gunicorn`, `python3-pytest`) -> `entrypoint.sh` generates an SSH key, creates the admin user, seeds demo data, starts `gunicorn --workers 1 --threads 16 --timeout 120 --reload app:app`. Code comes in via bind mount (`admin/` is `:ro` in the compose file). |
| **Production via Proxmox LXC** | `deploy-admin.ps1 -Full` sends `provision-admin-lxc.sh` to the Proxmox host (scp+ssh). The script: creates/starts the unprivileged CT, installs packages via apt (without `python3-pytest`), creates the `gamepanel` system user, copies the whole tree (`pct push`, recursive - does not use `tar` because it is less deterministic), generates `/etc/gamepanel/panel.env` (**preserving** the `GAMEPANEL_BROKER_*`/`GAMEPANEL_ALLOW_BROKER` lines from a previous broker deploy), generates the systemd unit (`gunicorn --workers 1 --threads 16 --timeout 120`, with `NoNewPrivileges`/`ProtectSystem=full`/`ProtectHome`) and starts the service. |
| **Production via direct push** (`deploy-admin.ps1`, without `-Full`) | If the CT already answers over SSH: copies only `*.py`+`templates/`+`static/` (recursive), cleans the destination, `chown`, deletes `__pycache__`, `systemctl restart gamepanel.service`. Picks the target CT/IP by `-PanelHost` > `ADMIN_HOST` from `.env` > `ADMIN_IP_CIDR` - **`ADMIN_HOST` beats `ADMIN_IP_CIDR`**, both need to change together when moving the panel to another CT. |

The Python process itself **never reads `ADMIN_*`** - only `GAMEPANEL_*` (see
section 1.2 of the `admin/` agent's report, confirmed by a full grep of
`app.py`). The `ADMIN_*` -> `GAMEPANEL_*` conversion happens only inside
`provision-admin-lxc.sh::render_panel_config`. This matters for Phase 2:
renaming a `GAMEPANEL_*` is a runtime breaking change; renaming an `ADMIN_*`
is a deploy-time-only breaking change.

### 3.2 Broker (`broker/`)

| Environment | How it starts |
|---|---|
| **Dev** | `python3 -m broker.dev` - Flask dev server (`app.run`, `threaded=True`), 100% fake backends, ephemeral state in `/tmp`. The code itself marks this with `# NOSONAR - so no compose de dev`. |
| **Production** | `deploy-broker.ps1` -> `provision-broker-lxc.sh`, a **dedicated** CT, outside the `games` pool, **without `openssh-server`** (nothing enters over SSH; only `pct push`). Generates a self-signed certificate (TOFU, SHA-256 fingerprint), a token that persists across deploys, `/etc/gamebroker/broker.env`. A systemd unit more hardened than the panel's (`ProtectSystem=strict`+`ReadWritePaths`, `ProtectKernelTunables`, `ProtectControlGroups`, `RestrictSUIDSGID`). WSGI entry point: `broker.prod:criar_app_de_ambiente()`, gunicorn with built-in TLS (`--certfile`/`--keyfile`, 1 worker - the IP lockout lives in memory). |

### 3.3 Game - two parallel production runtimes

This is the most relevant finding for the Phase 2 design:

1. **Proxmox LXC** (`deploy-game.ps1` -> `provision-game-lxc.sh`, on the host, via
   `pct exec`) - the "main" path, creates a real CT per game.
2. **Plain Docker** (`deploy-docker.ps1` -> `docker/gameserver/Dockerfile`) -
   a path **documented and active** in the README ("Deploy on Docker, without
   Proxmox"), to run on any machine with Docker (even a personal PC, or a remote
   `DOCKER_HOST`). It implements its own `systemctl`/`journalctl`
   (`docker/gameserver/systemctl.sh`, `supervisor.sh`) with the **same
   interface** the Proxmox path really uses - that is, there already is today
   an abstraction layer for "how to control the game process" with two
   implementations.

Both share the installation phases via `lib/ct-phases.sh` /
`lib/ct-install.sh` (run by `provision-game-lxc.sh` on the host and by the
broker's `ssh_install.py` inside the CT). TeamSpeak is the only game with
**fully separate** provisioning (`provision-teamspeak-lxc.sh`, because it does
not come from Steam) - it deliberately does not reuse `provision-game-lxc.sh`
(explicit comment in the file itself), with ~150 lines of duplicated
boilerplate between the two (`msg`/`warn`/`die`, `ensure_container`,
`push_file_to_ct`, etc.) - a natural candidate for a shared "CT boilerplate"
lib if the duplication becomes a maintenance problem, but today it is
deliberate risk isolation, not carelessness.

**Do not confuse `docker/game/` with `docker/gameserver/`** - they are different
things despite the similar name:
- `docker/game/` = **fake** game server (sshd + fake `systemctl`/`journalctl`
  + fake A2S + fake REST API), used only by the dev `docker-compose.yml`.
- `docker/gameserver/` = **real** game server running on plain Docker
  (real SteamCMD, its own supervisor), used by `deploy-docker.ps1` in
  production.

Neither is dead code.

### 3.4 CI/CD

Confirmed by three independent searches (mine and two agents): **there is no CI
file in the repository** - no `.gitlab-ci.yml`, no `.github/workflows`, no
`Jenkinsfile`. The only `.yml` is `docker-compose.yml`. This means that "add
ruff/mypy/Sonar to the GitLab pipeline" (requested in Phase 1) is **creating it
from scratch**, not integrating with something existing - worth confirming with
the owner whether the target really is GitLab CI (there is no GitLab remote
configured that I have seen; only local git use) or another CI.

---

## 4. State of the tests

I ran the whole suite (`\.venv\Scripts\python.exe -m pytest`, from the root,
as per `CLAUDE.md`): **all tests pass**, 2 skipped on Windows
(marked `@posix_apenas` in `test_players.py`, they check the POSIX `0700`
permission of the SSH socket - expected and documented behavior, only valid in
the Linux container). I did not also run the suite inside the Docker container
in this pass (to avoid the build time just to reconfirm what `CLAUDE.md` already
guarantees); it is worth running it there before any real merge of Phases 3/4, as
`CLAUDE.md` itself asks.

| Suite | Tests | Covers |
|---|---|---|
| `admin/test_alerts.py` | 81 | When the panel decides to alert (down/up, restart loop, silent game, resource, daily) |
| `admin/test_players.py` | 49 | Counting via HTTP API and port discovery |
| `admin/test_broker.py` | 57 | Panel integration with the broker (async jobs, registration) |
| `admin/test_users.py` | 31 | Admin/operator roles |
| `admin/test_2fa.py` | 36 | Login flow with TOTP |
| `admin/test_broker_client.py` | 21 | What goes over / never leaks in the broker HTTP client |
| `admin/test_qr.py` | 21 | Mathematical properties of the QR (Reed-Solomon) |
| `admin/test_charts.py` | 20 | Samples/retention/SVG math |
| `admin/test_schedules.py` | 18 | Scheduling and history |
| `admin/test_config_format.py` | 15 | Config parser/writer |
| `admin/test_totp.py` | 15 | TOTP in isolation |
| `admin/test_search.py` | 12 | Game search |
| `admin/test_gamefields.py` | 11 | Field catalog |
| `admin/test_ui.py` | 8 | Navigation map |
| `broker/test_*.py` (12 files) | ~415 | Allocation, config, catalog, connection, integration, real Proxmox/OPNsense against fake HTTP, LinuxGSM import, SSH installer, templates, extra port, service, suggestions |

### 4.1 Coverage gaps identified

Inferred from test names/scope (not confirmed line by line) - **there is no
dedicated suite for**:
- File editor (`files`, `files/save|delete|upload|download`)
- Backups (`backups/criar|restaurar|remover|baixar`)
- Single-command console (`console`)
- Interactive PTY terminal (`terminal`, `api_term_*`)

These are precisely the most privileged routes (arbitrary file write/removal in
the container, interactive shell as root) and are exactly where Phase 4 asks to
write behavior tests **before** refactoring - this is the first place where that
rule will apply in practice.

There is also no isolated test of the **log-based** counting state machine
(`_events_by_name`/`_by_count`/`_meio_nome`, `_LogStream`) nor a dedicated suite
for server CRUD (`server_new`/`server_edit`/`server_delete`,
`_form_server`) - possibly covered indirectly by `test_alerts.py`, but with no
direct test.

---

## 5. Dead, duplicated or abandoned code

**Nothing I would classify as "abandoned"** - the finding closest to that
(`docker/gameserver/` vs `docker/game/`) actually **is not** dead duplication;
they are two active, documented runtimes (see section 3.3). Likewise,
`check-broker-access.ps1` and `spike-broker-write.ps1` look at first glance like
"loose scripts", but they are **intentional manual diagnostic tools**, referenced
in the error text of `provision-broker-lxc.sh` and not called by the automated
deploy - they are not dead code, they are operations scripts.

Real duplication findings/points of attention:

- **`admin/app.py`, the "run remote script and convert the error" pattern repeated 7
  times** almost identically, never extracted into a common helper: `list_dir`,
  `stat_file`, `read_file`, `find_config_files`, `write_file`, `delete_file`,
  `list_backups`.
- **`admin/app.py`, three nearly identical thread fan-out functions**:
  `all_status`, `all_metrics`, `all_players` implement the same pattern
  (spawn per server + `join(timeout=...)` + `setdefault` of an error), without
  reusing `em_paralelo` or each other.
- ~~**Vestigial route documented as such**: `files_search`~~ - **removed.** Nothing in
  the panel pointed to it (only `_ACTIVE_EXTRA` in `navigation.py`, which cited it without
  ever lighting up because of it), and the panel is not public - the same reason why
  breaking-change group C was a clean cut. The decisive argument, however, is that it was
  **broken**: it sent `pasta=` to a route that started reading `folder`, so whoever
  had the old link silently lost the chosen folder. A redirect that loses the
  argument is worse than a 404.
- **Intentional duplication of TLS pinning** between `admin/broker_client.py` and
  `broker/conexao.py` - not accidental redundancy (each side of the trust boundary
  has its own pin), but worth recording as a candidate NOT to unify in Phase 2,
  precisely because it is deliberate security isolation.
- **~150 lines of CT boilerplate duplicated** between
  `provision-game-lxc.sh` and `provision-teamspeak-lxc.sh` (also present with
  variations in `lib/ct-phases.sh`) - deliberate (risk isolation), but it is the
  largest real duplication block in the repository.
- **No `TODO`/`FIXME`/`XXX`/`HACK`** found in `admin/*.py` or in
  `broker/*.py` (empty grep in both). No commented-out code block identified in
  the full read of `admin/`.

---

## 6. Quality survey

There was no `ruff`, `mypy` or Sonar installed/configured in this repository.
I installed the first two **only in the development `.venv`** (a local tool, not
a panel dependency - same spirit as the existing `requirements-dev.txt`) and ran
them against `admin/` and `broker/`, without creating any config file (each tool's
default rule set). No project file was changed.

### 6.1 `ruff check admin broker` (default rules, no config)

**329 occurrences, but 267 of them (81%) are a single false positive in a single
GENERATED file**: `admin/sugestoes_de_jogos.py` - `ISC004`
("implicit string concatenation"), triggered by the multi-line warning lists of
the catalog imported from LinuxGSM. That file is generated by
`tools/import-linuxgsm.py` and `CLAUDE.md` itself already says "do not edit" -
any real lint config needs to exclude it (or keep the generator from running
lint on it).

**Excluding that file, ~62 occurrences remain in the whole rest of the
repository** (~23 thousand lines), concentrated in a few files:

| File | Occurrences |
|---|---|
| `admin/app.py` | 12 |
| `admin/gamefields.py` | 6 |
| `admin/conftest.py` | 5 |
| `admin/test_2fa.py` | 4 |
| `admin/qr.py` | 4 |
| `broker/test_proxmox.py`, `broker/test_opnsense.py` | 2 each |
| `broker/ssh_install.py` | 2 |
| others | 1 each |

Most relevant rules (outside the generated-file noise): `I001`
(unsorted imports, 27x, mechanical), `FURB167` (regex flag alias,
10x - may touch the `\w`/`re.ASCII` case `CLAUDE.md` already discusses),
`RUF100` (**9 `# noqa: BLE001` with no effect** - the project uses this
suppression pattern in several `except Exception` blocks "that must not bring down
the job", but the default `ruff` rule set does not enable `BLE001`; **a real ruff
config needs to enable the rule set `CLAUDE.md` already assumes**, otherwise those
comments become silent garbage), `S110` (1x `try/except/pass`),
`PLW1510`/`PLW1509` (subprocess without `check=`, `Popen` with `preexec_fn` - worth
a close look, it is exactly the "insecure subprocess use" category cited in the
original request).

### 6.2 `mypy admin broker` (no types yet, `--ignore-missing-imports`)

I ran it twice: without a platform flag (`53` lines of output) and with
`--platform linux` (`31` lines). The difference confirms a **false positive already
known in `pyrightconfig.json` itself**: without stating Linux, mypy analyzes
`app.py` against the Windows stdlib and reports `fcntl.ioctl`, `os.setsid`,
`pty.openpty`, `signal.SIGHUP`, `os.killpg`/`getpgid` as nonexistent - which is
exactly the block `app.py` already guards with `try/except ImportError` to work
outside Linux. **Any real mypy config in this project needs to pin
`platform = "linux"`**, otherwise CI will report ~20 errors that are not
errors.

With `--platform linux`, the **~31 remaining errors** (no types declared
anywhere yet) group into:

- `attr-defined`/`arg-type`/`union-attr` (the majority): mainly where a
  function returns implicit `Any`/`object` and the caller uses it as if it were
  `str` (`busca_de_jogos.py:43-44`) or where a `sqlite3.Row | None` is indexed
  without checking `None` first (`app.py:709`).
- **`broker/config.py:184,207` - `**dict` passed to build
  `ConfigProxmox`/`ConfigBroker`**: the "build an object from a generic dict"
  pattern (the same pattern `CLAUDE.md` recommends to avoid 15 positional
  parameters) loses type at that edge. This is a concrete signal for Phase 4:
  when typing this code, consider `TypedDict` or explicit field-by-field
  validation instead of `**dict[str, object]`.
  Same pattern in `broker/prod.py:47`.
- `test_suggestions.py`/`test_templates.py`/`test_import_linuxgsm.py` - errors
  around `importlib.util.module_from_spec(...)` without checking `None`; it is a
  common test idiom (dynamic module import by path) and probably better served by
  a targeted `# type: ignore` than rewritten.
- 13 occurrences of `annotation-unchecked` (informational note, not an error -
  the body of an untyped function is not checked by default; it goes away as
  soon as Phase 4 types the signatures).

**Practical conclusion**: the code is already "type-safe in practice" even
without any annotation - a few dozen real problems in 23 thousand lines is a
base much easier to type than average. Most of the Phase 4 work here will be
*writing* the annotations, not *fixing behavior*.

### 6.3 Sonar

There is no `sonar-project.properties` or Sonar config anywhere in the
repository, and no CI to run a `sonar-scanner` against. I did not try to run a
local scanner without knowing which Sonar server (SonarCloud/self-hosted
SonarQube) the project should use - that is the owner's decision for Phase 2
(which server, which `sonar-project.properties`, which quality gates).

---

## 7. Language survey

### 7.1 The real size of the problem

Portuguese naming **is not the exception, it is the predominant convention** of
this project - in code, comments (intentionally, per `CLAUDE.md`), HTTP routes,
two whole tables of the panel database, virtually all of `broker/` (modules,
classes, functions), and most of the `.ps1` script parameters. Translating to
English, following the requested standard, is work the size of a test-guided
partial rewrite - not a mechanical `rename`. Below, the list split by "cost of
changing".

### 7.2 Internal (no external contract - renaming is safe from the outside, but
breaks tests that use `monkeypatch.setattr(panel, "nome", ...)` by string)

**`admin/app.py`** - most of the domain logic: `em_paralelo`,
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
`job_ou_403`, `filtro_de_papel`, `jobs_do_servidor`. Module tables:
`COMANDOS`, `FONTES_DE_CONTAGEM`, `ALERTAS_DE_RECURSO`, `MARCA_BASE`/
`_JOGADOR`/`_MENSAGEM`, `ROLE_LABELS`, `DIAS_SEMANA`. Classes: `_LogStream`,
`_Ritmo`, `DeployServer`.

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

**All of `broker/`** (the vast majority of the package): modules
`alocador.py`, `servico.py`, `catalogo.py`, `conexao.py`, `rede.py`,
`erros.py`, `fakes.py`, `fake_http.py`; classes `Servico`, `Catalogo`,
`Jogo`, `Porta`, `PortaAlocada`, `EspecificacaoDeCt`, `ConfigBroker`,
`ConfigProxmox`, `ConfigSsh`, `Banco`, `Cliente`, `RedeReal`/`Falsa`,
`ProxmoxFalso`, `OpnsenseFalso`, `InstaladorFalso`/`Ssh`/`Lento`,
`ErroDeConexao`/`DoOpnsense`/`DeLeitura`/`DoProxmox`/`DeInstalacao`/
`DeConfig`/`DeValidacao`, `NaoEncontrado`, `Conflito`, `SemRecurso`,
`CotaExcedida`, `Recusa`; functions `escolher_ctid`/`_ip`/`_ip_e_ctid`,
`alocar_portas`, `montar_env`, `montar_servico`, `carregar`,
`carregar_curado`, `jogo_de_env`, `ler_env`, `validar_dinamico`,
`pertence_ao_broker`, `reservar`, `mudar_estado`.

### 7.3 Externally exposed - changing requires a migration/breaking change

This is the list that needs the owner's explicit decision, item by item, in Phase 2.

**Panel HTTP routes** (path - half Portuguese, half English, already
inconsistent today): `/historico`, `/alertas` (+`/destinos`, `/testar`),
`/usuarios` (+`/papel`, `/senha`), `/agendamentos` (+`/alternar`, `/remover`,
`/rodar`), `/catalogo` (+`/novo`), `/instancias` (+`/nova`, `/desativar`,
`/remover`), `/servers/<id>/graficos`, `/servers/<id>/players/descobrir`
(+`/usar`, `/acao`), `/servers/<id>/backups` (+`/criar`, `/restaurar`,
`/remover`, `/baixar`).

**Broker HTTP routes** (the whole `/v1/*` namespace is Portuguese):
`/v1/saude`, `/v1/catalogo`, `/v1/instancias`, `/v1/instancias/<id>/desativar`,
`/v1/operacoes/<id>`.

**JSON keys of the broker contract** (payload/response, consumed by
`admin/broker_client.py`): `jogo`, `nome`, `operacao_id`, `instancia_id`,
`confirma`, `somente_banco`, `removida`; in `Jogo.publico()`: `chave`,
`app_id`, `porta_jogo`/`_query`/`_extra`, `memoria_mb`, `cores`, `disco_gb`,
`receitas`, `deslocavel`, `origem`, `criavel`, `motivo`; in `/v1/saude`:
`broker`, `proxmox`, `opnsense`, `catalogo_erros`. **Error codes** (part of the
JSON contract, `erros.py`): `pedido-invalido`, `validacao`,
`nao-encontrado`, `conflito`, `sem-recurso`, `cota`, `nao-autenticado`,
`origem`, `interno`, `http`. Header `X-Ator`.

**Database columns**:
- Panel - the whole `webhooks` table (`nome`, `url`, `eventos`, `ativo`,
  `criado_em`) and the whole `alert_log` (`criado_em`, `evento`, `titulo`,
  `detalhe`, `destino`, `status`, `erro`). The other tables (`servers`,
  `users`, `jobs`, `schedules`, `samples`) are already mostly English.
- Broker - the whole schema is Portuguese: `ctid`, `ip`, `jogo`, `nome`,
  `hostname`, `estado`, `criado_por`, `criado_em`, `detalhe`, `base`,
  `numero`, `proto`, `papel`, `tipo`, `log`, `resultado`, `iniciada_em`,
  `terminada_em`, `quando`, `ator`, `verbo`, `alvo`, and the state values
  `reservada`/`ativa`/`desativada`/`falhou`/`executando`/`ok`/`erro`.

**Environment variables**: the only one with a confirmed Portuguese word is
`BROKER_MAX_CRIACOES_HORA` (`.env.example`, `broker/config.py:199`) - the rest
of the `BROKER_*`/`GAMEPANEL_*`/`ADMIN_*` namespace is already English, with mixed
naming only in suffixes (`BROKER_IP_INICIO`/`_FIM`, `BROKER_PREFIXO_REDE`).
Also worth recording: **`GAMEPANEL_*` (the panel's real runtime config)
is already 100% English** - about 55 keys, none in Portuguese - which narrows
the scope of env var breaking changes on the panel side considerably.

**Registered Jinja filters** (used in every template - breaking them without
updating the templates breaks the whole screen): `"nivel"`, `"duracao"`,
`"tamanho"`, `"ident"`.

**Flask endpoints used in `url_for()`**: already an inconsistent mix today -
the *paths* lean Portuguese but the *endpoint names* lean English
(`alerts`, `schedules`, `catalog`, `instances_list`, `instance_new` - English
names for Portuguese-path routes). Renaming a route function without updating
every matching `url_for()` breaks navigation.

**Template names that are file paths**: `catalogo.html`,
`instancias.html` (Portuguese) vs `alerts.html`, `schedules.html`,
`users.html`, `history.html` (English) - already inconsistent with the
corresponding route name today.

**File/module names**: `admin/busca_de_jogos.py`,
`admin/modelos_de_jogo.py`, `admin/sugestoes_de_jogos.py`,
`tools/import-linuxgsm.py`, `tools/verify-qr.py`,
`check-broker-access.ps1`, `spike-broker-write.ps1`,
`broker.secrets.env`, `docker/ct-sandbox/compare.sh`, and virtually every
module in `broker/` (section 7.2). Renaming a file referenced by deploy scripts
(`provision-*.sh` copy by name, `NAO_ENVIAR` filters by name regex) requires
updating both sides.

**Good news**: the JSON keys of the **panel's** `/api/*` routes (not the
broker's) are already mostly English (`reachable`, `service`, `error`,
`players`, `cpu_pct`, `mem_pct`, `max_players`, `server_name`) - it is not a
generalized breaking change, it is concentrated in the areas listed above.

---

## 8. What is missing for Phase 2

This document does not propose a new structure - that is Phase 2, and it should
only happen after the owner validates this survey. Points Phase 2 will need to
decide, brought forward here because the evidence showed up during the
analysis:

1. **`admin/app.py` is the highest-risk/highest-return item of the project.** 44
   functional sections in 8,175 lines, no service layer, no DAO, with bash
   scripts mixed with Flask routes. `broker/` does not need the same level of
   surgery - it already follows a good part of the requested principles.
2. **The question "should the broker be a separate package or a separate service"
   already has a partial answer from the evidence**: it already IS operationally a
   separate service (runs in another CT, talks only HTTP to the panel, is never
   imported by the panel package). The real Phase 2 decision is only about
   *where in the repository* it should live from now on (same repo, sibling
   folder of `admin/`, vs. its own repository) - not about the architecture
   itself, which is already separate.
3. **The `runtime/` layer (Docker vs local process) is not hypothetical** - there
   already are two real, documented runtimes (Proxmox LXC, plain Docker) with
   scripts (fake vs real `systemctl.sh`/`journalctl.sh`) that already mimic the
   same interface. Phase 2 can formalize this instead of inventing it.
   TeamSpeak (non-Steam) needs to fit into that design too.
   `games/*.env` already is, in practice, the "definition of what to run" format
   cited in the request - Phase 2 decides whether it becomes the Python adapter
   format or stays a `.env` read by a generic adapter.
4. **Every column/route listed in section 7.3 needs individual approval from the
   owner before entering the breaking-change plan** - the original request already
   requires that; this analysis just concentrates the list to make the decision
   easier.
5. **A real `ruff`/`mypy` config needs, at a minimum**: excluding
   `admin/sugestoes_de_jogos.py` from lint (or from the flow, since it is generated),
   enabling the rule set the `# noqa: BLE001` in `CLAUDE.md` already assume,
   pinning `platform = "linux"` in mypy. Without that, the first CI run will
   report ~280 "problems" that are actually 3 configuration tweaks.
6. **No test is broken today** - Phase 3 (moving files) carries no pre-existing
   debt; any test that breaks during the `git mv` is caused by Phase 3 itself,
   not something inherited.
