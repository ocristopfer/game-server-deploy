# CLAUDE.md — how to work in this repository

Deployment of dedicated game servers (Proxmox LXC or Docker) plus a **web panel** in
`src/gamepanel/`. This file is about **how to write code here**. What the project does,
and how to use it, is in the [README.md](README.md) — do not duplicate content between
the two.

## Rule number one: EVERY identifier, EVERY file name and EVERY comment in ENGLISH

It applies to the whole repository and to every language in it — Python, bash,
PowerShell, JavaScript, CSS, Jinja, YAML, `.env`. Function, variable (including locals
and loop variables), class, constant, parameter, field, file and folder name: **English**.
Comments and docstrings: **English** too. There is no "it's just a helper script" or
"it's just a temporary variable"; a new file in Portuguese is born as debt that someone
will have to rename later, with the tests and the deploy in the way.

Comments still follow the house standard: explain WHY the line is the way it is,
preferably with the consequence of doing it differently (see the "Writing" section at
the end).

What **stays in Portuguese**, because it is not an identifier or a comment:

- TEST function names (`def test_a_versao_aparece_no_rodape...`): they are descriptive
  sentences, read as a report, not names called from anywhere else (ASCII, no accents:
  they are still Python identifiers);
- screen text, which lives in the `i18n/` catalog (Portuguese and English, same keys).
  Portuguese screen text is written as proper Brazilian Portuguese, **with accents and
  cedilla** (UTF-8: "Usuários", "não", "é", "configuração"); code, comments and
  identifiers stay English/ASCII. A test that asserts screen text asserts it WITH the
  accents; a stored key or a value compared in code (`inacessivel`, `agendador`) is data,
  not screen text, and stays as it is. **No screen text is hardcoded anywhere** — Python,
  templates or JS: if a person can read it on the panel, it is a catalog key (see "Screen
  language");
- keys already stored in a database, on disk or in an API (`"chave"`, `"jogos"`,
  `GAMES_DIR`): changing them changes DATA, and requires a migration — see the contract
  groups;
- existing script output messages that the sandboxes grep for (`die "sha256 nao
  confere"`): the sandbox looks for that exact text, and translating it makes the check
  stop matching in silence.

> **Architecture reorganization in progress** (see `docs/architecture-analysis.md` and
> `docs/architecture-proposal.md`): the code moved from `admin/`/`broker/` to
> `src/gamepanel/`/`src/gamebroker/` (Phase 3), the identifiers are **in English** in
> both packages, and both contract-change groups are done: the broker API (routes, body,
> response, headers) and the database columns, each with its own migration. Splitting
> `app.py` into `services/`/`runtime/`/`tasks/`/`blueprints/` is done too: the 81 routes
> live in `blueprints/`, one file per screen group, and `app.py` kept the assembly
> (database, session, decorators, tables).

The panel runs with **root power inside the game containers**. That changes the weight of
everything: a wrong button stops a real server, a wrong cache shows a dead server as if
it were up.

---

## Verify before saying you are done

The development environment is a complete `docker compose`: panel + two fake game
containers (with sshd, a fake `systemctl`, A2S query, REST API and log).

```bash
docker compose up --build -d          # panel at http://localhost:8080 (admin/admin12345)
docker compose restart panel          # after touching app.py/navigation.py
```

The panel suites (in `tests/gamepanel/`: `test_game_fields.py`, `test_config_format.py`,
`test_charts.py`, `test_schedules.py`, `test_users.py`, `test_players.py`,
`test_alerts.py`, `test_broker.py`, `test_broker_client.py`, `test_i18n.py`,
`test_template_contract.py`, `test_frontend_contract.py`, `test_javascript.py`,
`test_schema.py`, `test_docs_contract.py` and a dozen more) are **pytest** — 999 tests
in total (plus 901 from the `gamebroker` package, in `tests/gamebroker/`), with fixtures
shared in `tests/gamepanel/conftest.py` (`database`: tables cleaned for each test;
`webhooks`: captures what would go out over HTTP; `admin`/`operator`: an admin and an
operator already logged in; `login`/`post`: log in and POST with CSRF). **Run the whole
suite** after touching `app.py` — it covers exactly the parts where it is easy to break
something without noticing (when the panel decides to alert, who sees what, what counts
as a player). The files do NOT run as loose scripts anymore (`python3 test_alerts.py`
does nothing) — they always go through `pytest`.

### The two buckets: `unit/` and `integration/`

The split is by CRITERION, not taste: **integration = the test crosses a boundary**
(Flask HTTP client, fake HTTP server, sqlite in a file, `subprocess`); **unit = only
function calls**. Measured: 991 unit tests in 28 s against 910 integration tests in
126 s — which is why editing with `uv run pytest tests/gamepanel/unit` pays off, and the
whole suite is left for before publishing.

- **Each bucket must RUN ON ITS OWN, and that is what breaks silently.** A file in
  `integration/` that imports one from `unit/` by NAME passes in the whole suite — pytest
  puts the folder of every file it collects on `sys.path`, and `unit/` was collected
  first — and blows up with `ModuleNotFoundError` the moment someone runs only
  `integration/`, which is exactly what the split exists for. Measured in a separate
  experiment before moving any file. `test_suite_layout.py` guards the rule.
- **A test double shared by more than one file lives next to `conftest.py`**, which is
  the only folder pytest always inserts in `sys.path`. `FakeRunner` lived inside
  `test_ssh_installer.py` and two other files imported it from there; it moved to
  `fake_ssh.py`, next to `fake_http.py`, which already followed that pattern.
- **Import by name DOES cross subfolders**, that works: with `conftest.py` in
  `tests/<package>/`, a test in `unit/` still does `from fake_http import ...`. Also
  measured — it was what I thought would break, and it does not.
- **Counting process threads in a test is a recipe for flakiness.** The scheduler test
  used `threading.active_count()` and failed 1 in 3 when running the bucket alone:
  importing `gamepanel.app` already starts a scheduler thread, and any unrelated thread
  between the two readings makes the count wrong. Today the `Clock` thread has a NAME
  (`Clock.THREAD_NAME`) and the test counts only its own — and the name also helps whoever
  reads a stack dump, which used to show `Thread-1 (_loop)`.

**Fast, on the machine** (seconds, the normal loop while editing):

```powershell
uv sync                          # creates .venv and installs gamepanel/gamebroker editable + dev (pytest/ruff/mypy)
uv run pytest tests\gamepanel\unit    # 28 s - the loop while editing
uv run pytest                    # the whole suite, from the repo root
uv run pytest tests\gamepanel\integration\test_alerts.py -k test_loop_de_restart
uv run ruff check src tests      # ZERO is the current state: any finding is new
uv run mypy src                  # same
```

**`ruff check` and `mypy` are at ZERO, and that is what makes them worth anything.** They
sat at 97 and 11 for a good part of the reorganization, and a list that never reaches
zero is a list nobody reads. Each remaining finding got an answer: `MAX_PORT` and
`GAUGE_HOT`/`GAUGE_WARN` became constants (the repository's own rule), three
`pytest.raises(match=...)` had an unescaped dot that matched the wrong text, a `zip`
truncated silently, two `assert`s guarded an invariant that `python -O` drops, and what
was genuinely left was disabled IN THE CONFIG with the reason written down, never with a
loose `# noqa`. A new finding, therefore, is a real finding.

`uv` (https://docs.astral.sh/uv/) manages ONLY the development `.venv` —
`pyproject.toml`, at the root, declares `flask` (the version that tracks Debian 13's apt)
plus the `dev` group (pytest/ruff/mypy), and `uv.lock` pins the exact versions. This is a
development tool, never a dependency of the panel in production (see below). The pytest
configuration lives in `pyproject.toml` itself, under `[tool.pytest.ini_options]`: where
to look for tests (`tests/`), the failure summary and the on-disk cache turned off (see
the comment there — the reason is the container's read-only mount, not the venv). The
`.venv` is also what lets the editor resolve `import flask`/`import gamepanel`/`import
gamebroker`, via `pyrightconfig.json`.

**In the container, which is the truth** (slower; run before publishing):

```bash
MSYS_NO_PATHCONV=1 docker compose exec -T -w /workspace panel python3 -m pytest -q
```

The compose `panel` service has TWO bind mounts: `src/gamepanel` -> `/opt/gamepanel/gamepanel`
(the code gunicorn actually serves, mimicking the production layout) and the whole
repository -> `/workspace` (only to find `pyproject.toml`, `tests/` and `src/` together
and run the full suite). With no pip or uv in there (only `python3-pytest` from apt — see
`docker/panel/Dockerfile`), the root `conftest.py` inserts `src/` into `sys.path` by hand
so that `import gamepanel`/`import gamebroker` resolve without installation. **Run with
`-p no:cacheprovider`** if you want the same silence as the venv; without the flag the
tests pass the same, just with a warning about a cache that cannot be written (read-only
file system). **Rebuild the image** (`docker compose build panel`) if `pytest` is not
found in there. One test sensitive to `GAMEPANEL_DEV=1` (which the `panel` service always
starts with) —
`test_broker.py::test_config_ruim_desliga_o_recurso_sem_derrubar_o_painel[http-fora-do-loopback]`
— only fails when run this way, against the LIVE container; in the `.venv` (without that
variable) it passes. Known, not a regression of any test.

**What each side skips is different, and that is why both are worth running.** In the
Windows `.venv`: 14 skipped, **2 of them from `test_players.py`** (`@posix_apenas`, in
the file itself) — the ones checking that the SSH socket folder is visible only to its
owner (`0700`). That is pure POSIX permission: it does not exist on Windows, and the
result only counts in the container. In the container: **23 skipped, all from
`test_javascript.py`** (there is no node in the image), and the 2 POSIX ones finally RUN.
Today's numbers: 1900 pass in the `.venv`, 1888 in the container plus the 1 known
`GAMEPANEL_DEV` one above — the total collected is the same (1912) in both.

**`test_javascript.py` needs `node` on the PATH** and is SKIPPED without it. Production
has no node and the panel does not depend on it for anything: the test only checks that
each module parses and imports, which was the missing step — until then a `const`
renamed halfway only showed up in the console of whoever opened the screen.

Templates and static files come in through a bind mount: reloading the page is enough.
`app.py` and `navigation.py` are reloaded by gunicorn's `--reload`, but **a new route or a
decorator change requires `docker compose restart panel`**.

After touching a template or a route, walk through every screen:

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

A `500` here is almost always a broken template — and a broken template **does not show
up in any test**. Also check as an **operator** (the non-admin role): the menu and the
screens change, and that is where the 403 nobody had seen lives. And check both themes
and both languages (see "Theme" and "Screen language").

---

## Where each thing lives

```
VERSION                  the repository version (semver, by hand); tools/build-release.py stamps it into the package
pyproject.toml          uv workspace: dev dependencies (pytest/ruff/mypy) and the pytest,
                        ruff and mypy config; only gamepanel/gamebroker editable
conftest.py              inserts src/ in sys.path before any test (works without `uv sync`)
games/                   curated game catalog (one *.env per game), read by gamebroker AND by the
                        bash provisioning scripts - that is why it sits at the root, outside src/
lib/                     game install phases (bash) + install-release.sh (publishes a release in the CT)
                        + ct-firewall.sh (the nftables firewall INSIDE each CT; see "CT firewall")
deploy/                  infra outside the Python code, one group per target:
  admin/                  deploy-admin.ps1 + provision-admin-lxc.sh
  broker/                 deploy-broker.ps1 + provision-broker-lxc.sh, plus the two
                         manual tools (check-broker-access.ps1, spike-broker-write.ps1)
  game/                   deploy-game.ps1, deploy-docker.ps1 and the two game provision-*-lxc.sh
  firewall/               apply-firewall.ps1 + .sh: puts the firewall on CTs that already existed
src/
  gamepanel/             the panel (was admin/)
    app.py               the assembly: database, session, decorators, tables, SSH, alerts, scheduler
    config.py            EVERY GAMEPANEL_* variable, read and checked in one place
    version.py           the running version (reads the release's _build.py, or falls back to VERSION+dev)
    blueprints/          the HTTP layer, one file per screen group (see its own section)
    persistence/
      schema.py          schema, MIGRATIONS and RENAMES
      repositories/      one function per query; ALL of the panel's SQL lives here
                         (servers, jobs, schedules, alerts, samples, settings, users)
    wsgi.py              gunicorn entry point (`gamepanel.wsgi:app`)
    cli.py               bootstrap: --create-user, --reset-2fa, --register-server (the footer of app.py calls main() from here)
    navigation.py        map of the interface: navigation and actions   (pure, no Flask; was ui.py)
    games/
      config_format.py   reader/writer of the game's .ini/.json/.cfg (knows no game at all)
      base.py             what a field IS: type, limit, unit, label
      registry.py          which adapter applies to which file
      adapters/            one file per game with a quick-edit screen
      mods/                mod manager: one profile per game (profiles.py), the reader of ETS2's
                           server_packages (ets2.py), Workshop IDs (workshop.py) and
                           Thunderstore/BepInEx (thunderstore.py in the panel, thunderstore_remote.py
                           which RUNS IN THE CT), removal by name (removal.py) and the manual setup
                           for games without a profile (custom.py in the panel, custom_remote.py in the CT)
      catalog/
        search.py          search by name/App ID over suggestions.py (was busca_de_jogos.py)
        templates.py        "Add game" form templates, one per engine (Unreal/Unity Linux
                           and Windows via Proton, Source); pure, data only
                           (was modelos_de_jogo.py; `tests/gamebroker/test_templates.py` checks
                           that they pass the broker's validator)
        suggestions.py      GENERATED by tools/import-linuxgsm.py, do not edit (was sugestoes_de_jogos.py)
        manual_suggestions.py  written BY HAND: Windows-only servers LinuxGSM does not cover (same
                           format + platform/recipes); curated ones stay out (search finds them in the catalog)
        pterodactyl_suggestions.py  GENERATED by tools/import-pterodactyl.py, do not edit: new games
                           (SUGGESTIONS) and fields missing in LinuxGSM (COMPLEMENTS, by App ID)
    i18n/
      __init__.py         cascade language->pt->key, fields in the sentence, `Mensagem`; see its own section
      pt.py               Portuguese catalog (the default)
      en.py               English catalog, SAME keys (test_i18n.py enforces parity)
    security/
      totp.py             2FA, stdlib only
      webauthn.py         passkey (device biometrics): CBOR, ES256 and RS256, stdlib only
      qr.py               QR generator, stdlib only
      passwords.py        scrypt (hash, check and the good-password rule)
      csrf.py             the session token and the POST check
    services/            pure decisions (no Flask, no SQL): alert, chart, player,
                         history, attempt lockout (auth_service), ...
    integrations/
      broker_client.py    broker client (stdlib only, TLS pinned by fingerprint); see "Broker"
    templates/
      components/         macros: ui.html (generic) and servidor.html (domain)
      *.html              one screen each
      sw.js.jinja         service worker    (a template, not static: it has the version inside)
      manifest.webmanifest.jinja
    static/
      css/                tokens -> base -> layout -> components -> pages
      js/core/            format, http, poll, dom, dirty   (no screen DOM, reusable)
      js/features/        one module per behavior
      js/app.js           wires features to the page's elements
      icons/
  gamebroker/             service that creates game instances (Proxmox) and opens ports (OPNsense);
                         Python package, see the "Broker" section below (was broker/)
tests/
  gamepanel/              conftest.py (fixtures) and the two buckets
    unit/                  function calls only — 28 s, the loop while editing
    integration/           crosses a boundary (Flask client, sqlite in a file, subprocess) — 126 s
  gamebroker/             conftest.py + the shared doubles (fake_http.py, fake_ssh.py)
    unit/                  3 s
    integration/           fake HTTP server, assembled service, subprocess
tools/
  build-release.py       packages a release: dist/<package>-<version>.tar.gz + .sha256 (stdlib only, deterministic)
  import-linuxgsm.py   generates src/gamepanel/games/catalog/suggestions.py from LinuxGSM (needs internet)
  import-pterodactyl.py  generates pterodactyl_suggestions.py from the eggs (pelican-eggs/games-steamcmd, MIT)
  verify-qr.py        manual check of the QR against a real reader (throwaway venv)
```

### Mod manager: what "mod" means changes per game

The Mods screen (`blueprints/mods.py`) does not treat every mod as "a file in a folder",
because it is not: in ETS2 the server loads NO mod file at all (map, DLCs and mods come
inside the `server_packages`, exported from the game), and sending a `.scs` to the CT
would do nothing. What a game means by mod is said by the profile in
`games/mods/profiles.py`, chosen by the SERVICE NAME (`profiles.profile_for`) - it is the
only game identity every server has.

- **Two kinds**: `KIND_PACKAGES` (ETS2: the screen reads what the packages load, builds
  the Workshop links for the players and compares against the pasted reference list) and
  `KIND_FOLDER` (Palworld: lists, receives and removes the files in the mods folder). New
  profile = one entry in `PROFILES`; a test ensures two profiles do not claim the same
  service.
- **Where a loader's ENVIRONMENT goes depends on the access mode.** Legacy (root): the systemd
  drop-ins and `/etc/game-runtime.env` described below, byte-identical to before. Helper mode
  (phase 6): the installer runs as steam with `--overlay` (`mods.uses_overlay`) and writes the
  SAME variables into steam's overlay - `/etc/gamepanel/game-env/service.env` (reaches the unit
  through the `gamepanel-env.conf` drop-in's `EnvironmentFile=`) and `runtime.env` (win-run
  sources it after `/etc/game-runtime.env`, and appends `GAMEPANEL_EXTRA_ARGS` to the game's
  arguments - that is how ARK's `-mods=` gets in without an ExecStart drop-in). Removing a line
  restores the original, no `daemon-reload` is needed, and the job's restart step applies it.
  - **The folder is root's, the files are steam's, on purpose**: systemd reads the
    EnvironmentFile AS ROOT, so a file steam could swap for a symlink would leak the
    `KEY=value` lines of root-only files into the game's environment. That is why it is not in
    `/home/steam` (the first idea in the plan). steam changes the content, never WHICH file;
    and it cannot create one, so a missing file is "CT never prepared" (`overlay_problem`).
  - **win-run reads runtime.env only when the file belongs to whoever runs it**: root never
    sources a file steam can write.
  - **The overlay block is copied into five standalone installers** (`thunderstore`,
    `shroudtopia`, `ue4ss`, `ue4ss_linux`, `workshop` remotes), between markers; a test
    (`test_mod_overlay.py`) requires the five copies to be identical, like `scanner`.
  - **What a ROOT installer left before migration is converted by `ct-panel-access.sh install`**
    (rerun `migrate-ct.ps1`): loader drop-ins -> service.env, the loader's WINE_DLL_OVERRIDES ->
    runtime.env (the base goes back to BepInEx's `overrides_before`, or loses only `winmm=n,b`/
    `dwmapi=n,b`), ARK's `gamepanel-mods.conf` -> `GAMEPANEL_EXTRA_ARGS` (only if its recorded
    base is the unit's current ExecStart and goes through win-run), an old win-run gets the hook
    inserted (never rewritten, and BEFORE the runtime.env conversions, which are skipped without
    it - a value moved where win-run does not look would turn the loader off at the next restart), and the game folder goes back to steam (`chown -R -P`, what every
    deploy already does). A drop-in that is not exactly ours stays, with a warning. Until that
    rerun, helper mode refuses the loader with `overlay_problem`/`root_dropin` instead of
    "disabling" something steam cannot remove. Proven by `docker/ct-sandbox/panel-access.sh`.
- **Upload only accepts what the profile declares** (`accepts`): exact name or extension,
  and only the last part of the name the browser sent. Removal is by NAME, inside the
  profile's folder - the form never sends a path.
- **The reference list is the `mods_expected` column of the servers table** (Workshop
  IDs, one per line). The reader (`workshop.parse_ids`) accepts the list the way it
  circulates in chat, with time and name in front; a number with fewer than 6 digits is
  not an ID.
- **Thunderstore (V Rising): the CT does the download.** `thunderstore_remote.py` goes to
  the container as TEXT and runs there (`python3 -c`, over SSH): the panel does not go to
  the internet, the CT does. That is why it is stdlib only and imports nothing from
  `gamepanel` - the package does not exist in there. Install and remove become a JOB
  (downloading BepInEx is 33 MB), with the restart as the NEXT STEP of the same job: an
  install that fails does not restart the server. Three things MEASURED on a real V Rising
  under Proton, each with a test: the `mscoree=` of the Windows .env files prevents BepInEx
  (.NET) from loading, and is removed from the list (`fix_overrides`); `winhttp=n,b` is how
  it gets in; and the BepInEx console FROZE the server under the virtual X (stopped, no
  CPU and no log), so it stays off. The first start with it reached 9.4 GB (the profile's
  `min_memory_mb`; the screen warns before installing). A game redeploy rewrites
  `/etc/game-runtime.env` and undoes the Wine adjustment: the status flags it
  (`overrides_ok`) and reinstalling reapplies it.
- **The mod version is chosen on screen, never pinned in code.** BepInEx, Thunderstore
  plugins and Shroudtopia accept an `x.y.z` version (empty = the newest), checked in the
  panel (`thunderstore.parse_version`) and again in the CT, because it becomes part of the
  API URL. A pinned plugin brings its dependencies at the version IT declares: that is the
  set the author tested, and the newest is exactly what breaks the mod one wanted to hold
  (cost: a dependency shared with another mod may go back to an older one). Changing the
  version of a server that already runs is the same install POST, through the installer
  folder; the installer marker (`MARK`) records `pinned`, and an old marker without the
  field counts as "the newest". The Shroudtopia tag on GitHub appears with and without
  `v`, and the installer tries both.
- **Every mod goes through the antivirus before reaching the game**
  (`games/mods/antivirus.py`). `SCAN_SCRIPT` is the rule in one place: the upload runs it
  as a job step (the file first goes to `INCOMING_PREFIX`, outside the game folder, and
  `PLACE_SCRIPT` only moves it afterwards), and the remote installers receive it via
  `--scan` and download EVERYTHING (package and dependencies) before scanning it all at
  once - a rejected dependency does not leave the main mod half installed. The `scanner`
  of the two installers is a copy (they run standalone in the CT), and a test ensures they
  stay equal. **Fails closed**: without ClamAV, without signatures up to 7 days old, or on
  error, nothing gets in; installing without `--scan` is refused in the CT itself. ClamAV
  only reaches the CT on the first mod (`apt`), so a server that already runs gains the
  scan without a redeploy. The script only accepts (and only deletes) paths under
  `STAGING_PREFIX`. ClamAV loads ~1 GB while scanning, next to the game, and only finds
  what is already known: it is a layer, not a barrier.
- **"Scan installed mods" (`AUDIT_SCRIPT`) only READS**: it reports in the log and deletes
  nothing, because deleting on its own on a false positive would take down a mod the
  server depends on. It shares with `SCAN_SCRIPT` the ClamAV install and the `clamscan`
  options (`_ENSURE`), and scans `profile.scan_paths` - the mod folders and the loader,
  never the whole `/opt/game`. With nothing installed it does not even install ClamAV.
- **Uninstalling the loader (`loader-uninstall`) returns the game to the original**, and
  each installer only deletes what IT put there: BepInEx and Windows UE4SS record in the
  marker the root names they CREATED (whatever already existed belonged to the game and
  stays; an old install without the list falls back to the loader's known names);
  Shroudtopia and UE4SS Linux have fixed names. The Wine adjustment goes back to what it
  was (BepInEx keeps the original WINE_DLL_OVERRIDES, because re-enabling mscoree cannot
  be undone without it) and the systemd drop-in goes away. Oxide restores the game DLLs
  FILE BY FILE, only where the folder still has Oxide's: after a Rust update the backup is
  from the old version, and copying it back would break the server. The mods that live
  inside the loader (plugins, Lua) go with it, and the screen asks for confirmation first;
  the `.pak` files in the game folder stay. SML has no such button: it is a mod, and it
  already has remove.
- **`KIND_GUIDE` is a profile without a button, and that is a decision**: a loader nobody
  has proven on a real server gets instructions only - V Rising showed three traps that
  only appeared there. A button that "installs" without proof is worse than clear
  instructions. Every profile has `sources` (where to find mods), and Nexus is LINK only:
  its API only delivers files to Premium accounts, and automating without it violates the
  terms.
- **Enshrouded is `KIND_SHROUDTOPIA`, proven on CT 303** (Proton GE 11): the loader gets
  in through `winmm.dll` next to the `.exe` and only runs with `winmm=n,b` in Wine; with
  that it starts and loads the DLL from `mods/`, and the server keeps answering A2S.
  `shroudtopia_remote.py` runs in the CT like the Thunderstore one. The EXAMPLE mods from
  the official zip are left out (cheats enabled), disabling means removing `winmm=n,b` (no
  loader code runs), and the status shows the tail of `shroudtopia.log`: a mod for another
  game version silently loses function (`not found`).
- **UE4SS is `KIND_UE4SS`, only for Unreal servers that are the Windows `.exe` under
  Proton** (today, Icarus). `ue4ss_remote.py` runs in the CT like the other two. MEASURED
  on a test Icarus: the STABLE v3.0.1 loads and runs Lua, but the server's Steam comes up
  with `AppId: 0` and A2S disappears; `experimental-latest` (loose `dwmapi.dll` proxy, the
  rest in `ue4ss/`) keeps Steam and A2S. That is why the default is experimental, and the
  profile has `loader_dir` (the `.exe` folder), because the mods sit two levels below.
  Installing turns off the console, the window and the factory cheat mods (only
  `BPModLoaderMod`/`BPML_GenericFunctions` stay on), and the official `mods.txt` comes with
  a BOM, which sticks to the name of the first mod. Native Linux servers (Dragonwilds,
  Palworld here) are the "UE4SS for Linux" item below. Careful when measuring freezes on
  Dragonwilds: its output reaches the journal in delayed blocks; the right signal is
  `Saved/Logs/RSDragonwilds.log` (the `HeartbeatSession` every 30 s).
- **`proven=False` is an installer written without a test CT, and the screen WARNS**
  (`mods.not_proven`). It was requested this way for Satisfactory, Valheim and Rust:
  implement everything and prove it later. Whoever proves it on a real CT switches it to
  `True` and writes in the profile what was measured - the same rule as `KIND_GUIDE`, just
  with the button already built. A test ensures the four (with Dragonwilds, below) stay
  marked.
- **Satisfactory is `KIND_SML`, through the ficsit.app API** (`sml_remote.py`), and not
  through ficsit-cli: v0.7.1 has no command to ADD a mod (only the interactive UI). The
  API is public, and gives the `LinuxServer` package of each version with its sha256 and
  dependencies; the sha256 is checked BEFORE the antivirus, and a dependency comes at the
  version the constraint asks for (`^3.12.0` does not accept SML 4.0.0). Each mod in its
  own folder under `FactoryGame/Mods`, replaced as a whole.
- **Valheim is Thunderstore in Linux mode** (`linux_bepinex`): BepInEx gets in through a
  systemd drop-in with the variables of the start script that comes INSIDE the BepInEx
  package (start_server_bepinex, outside the repo) (`DOORSTOP_*`, `LD_PRELOAD` of
  `libdoorstop_x64.so`), with absolute paths, without replacing the game's wrapper.
  Disabling deletes the drop-in; without `daemon-reload` systemd would keep the old
  environment.
- **UE4SS for Linux (15 Linux Unreal servers, 4.26 to 5.7) is `KIND_UE4SS_LINUX`: the
  OFFICIAL UE4SS compiled for Linux**, in our fork (github.com/ocristopfer/RE-UE4SS,
  branch `linux`, release `linux-v2`; the fork's README, docs/linux.md, lists the tested
  games). It is no longer a port: it is the official mechanisms (patternsleuth,
  UE4SS_Signatures, VTableLayout.ini, Lua mods) with what Linux needs - and what Linux
  needs was MEASURED, each item in gdb: the C++ runtime and the unwinder linked inside the
  library (the game exports its own, and every UE4SS `throw` died in them); the vtable and
  member layout of each engine version GENERATED from Epic's code (the fork's
  `tools/linux-layouts`: Itanium orders vtables differently from MSVC, reuses the tail of
  a base class, and `FRWLock` is 56 bytes on Linux, against 8); and the Lua state lock in
  `RegisterHook` callbacks (Palworld calls hooked functions from an animation thread).
  Proven on the two real servers in Docker with a test mod: Lua, `FindFirstOf`,
  `RegisterHook` on Blueprint and native, `ExecuteInGameThread` - Palworld 10 minutes up.
  The old ports (XarminaEu and our own ocristopfer/ue4ss-linux) are gone: they crashed
  Palworld.
  - **`ue4ss_linux_remote.py`** downloads the profile's FIXED tag (`ue4ss_release`),
    checks each file against SHA256SUMS BEFORE the antivirus, and installs in the official
    layout: `ue4ss/` next to the executable (UE4SS finds config, mods and log in its own
    library's folder), `.so` replaced by `rename` (copying over it with the server running
    corrupts the mapping), the owner's config and `mods.txt` preserved, `Mods/shared`
    (UEHelpers) replaced as a whole, `LD_PRELOAD` in a systemd drop-in. The library only
    starts in an executable with `-Linux-` in the name: the start script is left out.
  - **A modified engine needs the `.sym`.** The built-in layout is Epic's engine;
    Dragonwilds is a Jagex 5.6.1 with extra virtuals in AActor (BeginPlay landed in
    RemoveTickPrerequisiteComponent). A server that ships the `.sym` (300 MB, Unreal's
    crash file) gets, generated IN THE CT by `ue_sym_layout.py` (it goes as text, which is
    why it lives in the package and not in `tools/`), the VTableLayout.ini of this build
    and the UE4SS_Signatures of the four functions patternsleuth cannot find in Clang code
    (FName::ToString, the FName constructor, StaticConstructObject, GNatives). Regenerated
    on every install (a game update changes everything); without a `.sym` (Palworld) there
    is nothing to generate. Verified: the generator produces, byte for byte, the files
    tested on Dragonwilds.
  - **Migrates the old fork's install** (everything next to the executable, with the
    marker .gamepanel-ue4ss-linux.json): Lua mods go to `ue4ss/Mods` and only the files
    the fork wrote are removed. Without the marker nothing next to the executable is
    touched.
  - **Every studio modifies the engine, and without symbols the layout comes from a
    REFERENCE game.** MEASURED on the 4.27 servers: Soulmask has 62 extra virtuals in
    AGameModeBase, The Front 0x18 extra bytes in FUObjectArray, Squad itself 44 one virtual
    in AActor. One layout per version crashed more than half of them. What carries over
    from one game to another of the same version is the CODE of each engine function and
    the target's own vtables, which the servers export in `.dynsym` (_ZTV*). The release
    ships one pack per version (LinuxReferencePacks.tar.gz, made by the fork's
    ue_reference_pack.py from a game with `.sym` and `.debug`: DWARF gives the full
    layout), and `ue_linux_layout.py` (text for the CT, like `ue_sym_layout.py`) generates
    from this executable: the signatures by the shortest prefix of the reference code that
    matches here (and never shorter than the unique one IN the reference: too short
    matches uniquely in the wrong place), the VTableLayout.ini aligning vtables by code,
    and the FUObjectArray MemberVariableLayout.ini when the code's access history is
    shifted. A server WITH `.sym` uses `ue_sym_layout.py` as before and the pack only for
    the globals.
  - **GMalloc and the console manager are checked AT RUNTIME, in Lua**: candidates are
    globals read by the most called functions, and the one that points to an object with
    an allocator's vtable (or FConsoleManager's) wins. A byte pattern caught the console
    manager instead of GMalloc on Smalland. UE4SS's `DerefToInt32` returns nil when it
    READS zero (the high half of every non-PIE vtable): without the `or 0`, the Lua error
    kills the whole signature pass.
  - **The UE4SS scanner refuses a pattern that STARTS with a wildcard**, and one refusal
    takes the other signatures with it: the generator puts the instruction bytes in front,
    taken from this executable.
  - **Binary without `-Linux-` in the name** (TheFrontServer, SquadGameServer,
    AstroColonyServer): the drop-in carries `UE4SS_TARGET_EXE`, otherwise UE4SS never
    starts. The drop-in goes on the SERVER's service (the profile serves more than one
    name: the curated one and the LinuxGSM suggestion key).
  - **`proven=False` on all of them** until the first install through this screen on a
    real CT (the proof was in Docker). The game DETECTS the `.so` (Dragonwilds marks the
    session as modified, `CheckForMods`): it is only a warning. No pack: 4.18, 4.22, 4.25,
    5.2 and 5.4 (no server in the catalog ships symbols of those versions to serve as a
    reference); 5.1 does not need one (built-in layout, Palworld and Pavlov).
  - **Hooking a function called outside the game thread is expensive**: the lock
    serializes the animation threads with the game thread. A mod that hooks
    `KismetMathLibrary` works, but weighs.
- **Rust is `KIND_OXIDE`** (`oxide_remote.py`): the package OVERWRITES game DLLs, so the
  installer keeps the original (only what is NOT Oxide's, comparing sha256: reinstalling
  with Oxide on cannot become "original") and disabling restores it. Every Rust update
  through Steam wipes Oxide: the status compares the files and flags it (`wiped`). Plugins
  are `.cs` files through upload.
- **Dragonwilds (Unreal 5) accepts `.pak`, `.utoc` and `.ucas`**, and the upload checks
  ALL names before sending any of them (`_checked_name`): the mod comes in three files,
  and two out of three in the folder is a broken mod.
- **In ETS2, `mod_id` is only a Workshop ID when `workshop_mod: true`.** In a mod
  installed by hand (the BR Map) it is an internal signature, and turning it into a link
  would point to some random item.
- **`KIND_WORKSHOP` is Workshop through the game's CONFIG** (DST, Zomboid, Unturned,
  Reforger): the server itself downloads, on start, and `workshop_remote.py` (in the CT,
  like the others) only reads and writes the list in each game's file
  (`workshop_format`). Each format was MEASURED on a real server in Docker, with the mod
  downloaded and loaded in the log, and each one has a trap:
  - **DST needs BOTH files**: `ServerModSetup` in `dedicated_server_mods_setup.lua`
    DOWNLOADS, each shard's `modoverrides.lua` ENABLES. The cluster comes from the command
    line (`-cluster`, `-conf_dir`, `-persistent_storage_root`): the first start only
    creates `<shard>/server.ini`, and cluster.ini only exists after someone configures the
    cluster - looking for it found nothing. Each mod's options block comes out whole as
    TEXT (`workshop_remote.lua_entries`, which skips strings and comments: `scale = "1}"`
    would cut the block in the middle). A game update rewrites the setup:
    `setup_missing`.
  - **Zomboid has two lists and they are NOT the same**: `WorkshopItems=` (Workshop ID)
    and `Mods=` (the `id=` from `mod.info`). One item can bring several mods, and enabling
    all of them is what breaks; that is why the panel does not infer `Mods=`, it only shows
    what each downloaded item brought. Build 42 loaded `Mods=BB_CommonSense` without the
    backslash some guides add.
  - **Unturned needs `+InternetServer/<nome>`** (the server folder) and `steamclient.so`
    in `~/.steam/sdk64` (the `steamclient-sdk64` recipe): without it you get "GameServer
    API initialization failed" before reaching the Workshop. Dependencies (map + assets)
    come on their own.
  - **Reforger is not Steam**: a 16-hex GUID from Bohemia's workshop, `game.mods` in the
    JSON of `-config` (`workshop.parse_guids` reads the page link, which has the name at
    the end). Without `-config` in the command there is nowhere to write, and the LinuxGSM
    catalog removes it.
  - **The antivirus does not scan BEFORE**: the download is the game's. Each profile's
    `audit_paths` is where the game keeps what it downloaded, and the screen tells you to
    use "Scan installed mods".
  - **A list that yielded no ID at all is refused**; only an EMPTY field clears the list.
    A wrong paste would delete all of the server's mods.
  - **ARK: Survival Ascended only takes `-mods=` on the command line.** `ActiveMods=` in
    GameUserSettings.ini is ignored ("LoadGameMods with 0 mods", measured), and a mod folder
    left on disk does not load either. The list is a systemd drop-in repeating the unit's own
    ExecStart plus `-mods=` in legacy mode; in helper mode it is `GAMEPANEL_EXTRA_ARGS` in steam's
    runtime.env, which win-run appends (`profiles.ENV_WORKSHOP_FORMATS`; ExecStart cannot come
    from an EnvironmentFile, but ARK already starts through win-run). The base command is read from the
    UNIT section of `systemctl cat` (`workshop_remote.ark_base`), never from a drop-in - ours
    would feed itself back - and is recorded in the drop-in, so a redeploy that changes the
    command shows up as `base_changed` instead of being masked by the stale copy.
  - **Conan Exiles is the exception: the server does NOT download mods**, the CT does, so it is
    the one Workshop format that goes through the antivirus (`profiles.SCANNED_WORKSHOP_FORMATS`).
    The job is: holding folder, `fetch` (SteamCMD, anonymous, three tries, only the IDs the
    server does not have yet), the scan steps, `set` (files under their ORIGINAL names - a renamed
    pak fails in silence -, `modlist.txt` as `*Name.pak` in list order, `ServerModList=modlist.txt`).
    `set` only deletes files the panel placed (`workshop_remote.CONAN_MARK`), and keeps the CRLF of
    ServerSettings.ini (`read_text(..., raw=True)`: text mode turned it into LF). Measured: a
    "[Legacy]" (UE4) item is ignored without a word, and a mod "too old for this game version"
    makes the server EXIT at boot; the status reads those refusals from ConanSandbox.log.
- **Every mod that can get in can get out, by NAME, as a job.** The lists (files, folder mods,
  UE4SS Lua mods, Oxide plugins) are one form with a box per row, one restart choice and one
  confirmed button (`srv.mod_removal`): a form per row could not carry the restart, which is the
  job's LAST step. The panel says which rows are files (`name`) and which are folders (`folder`,
  only where the profile has `folder_mods`, today Shroudtopia and the manual setup); a name with a
  slash, `..` or an extension the profile does not take refuses the WHOLE batch
  (`removal.targets`). The script (`removal.REMOVE_SCRIPT`, as steam in helper mode) refuses a
  mods folder whose `realpath` is not itself: in legacy mode it runs as root in a folder the game
  writes, and a planted link would turn `rm -rf` into a delete elsewhere. An Unreal 5 `.pak`
  takes its `.utoc`/`.ucas` (IoStore) along, only where the profile accepts them. A Lua mod goes
  through its installer (`mod-remove`), which also drops ONLY its `mods.txt` line, byte for byte
  (BOM, CRLF and the owner's comments stay; the block is identical in both UE4SS installers and a
  test compares them). Two lists were invisible before: a DLL or `.cs` uploaded before its loader
  was installed (Shroudtopia, Oxide) - the status lists the folder regardless now.
- **`rmtree(..., ignore_errors=True)` lied**: the Thunderstore and SML removals answered "removed"
  when steam could not delete a folder a root install had left, and the plugin kept loading. They
  raise now, and refuse a plugins/mods folder under a link (`under_link`, ancestor by ancestor:
  `realpath` against `abspath` also flags Windows 8.3 names in the tests).
- **`KIND_CUSTOM` is the manual setup** (`games/mods/custom.py`), for a game with NO built-in
  profile: the built-in one wins (two managers on one folder would fight over the same files and
  Wine setting), so the form is only offered, and the POST only accepted, there. It is one JSON
  column (mods_custom, in the servers table): the six fields are always read, checked and written together.
  The row is re-validated through `custom.parse` on every read, and the CT checks it again
  (`custom_remote.load_setup`, same rules; a test keeps the copies equal). No free text becomes
  shell: an https link, folders relative to `profiles.GAME_DIR` (one short character set per
  part, no `.`/`..`), extensions (scripts, `.so` and executables never), and only two
  environment settings - Wine overrides (`name=n,b`) and one `LD_PRELOAD` `.so`.
  - **The environment needs helper mode.** It goes through steam's overlay, applied when the
    loader is installed and taken out on uninstall (with the game's own replaced entries, like
    `mscoree=`, put back). In legacy mode a setup with environment is refused on save AND in the
    CT: writing root's drop-ins for a loader nobody measured is the wrong place to start.
  - **The CT does everything inside the game folder after `realpath`** (`custom_remote.confined`),
    caps the download (256 MB, https redirects only) and the unpacking (1 GB, 20000 entries),
    refuses links, devices and `..` in the archive BEFORE writing, and refuses to overwrite a file
    the install did not create (a game file it could not give back). The marker records what the
    install CREATED (written even when it stops halfway, flagged as incomplete), and uninstall
    removes only that. Uploads land through the custom installer (`mod-place`), not the generic
    `PLACE_SCRIPT`, because the folder is the admin's choice and has to be confined in the CT.
  - Proven in the dev compose with the real BepInEx 5 Linux zip and real ClamAV, in both modes.

### A new game with its own screen = one file, one line and its keys

`games/adapters/<jogo>.py` declares `FILENAME` (which file it recognizes) and `FIELDS`
(what it knows about each key), `registry.ADAPTERS` gets one line, and the field texts go
into `i18n/pt.py` and `i18n/en.py`, in the "game config fields" section at the end. No
route, template or other game is touched.

- **A field holds KEYS, never sentences**: label, help, option labels and unit are
  `game.<adapter>.<field>.label` / `.help` / `.opt.<value>` (field and value lowercased:
  the key convention test), and the Config template translates them with `_()` at render
  time. The labels several games share on purpose are `base.LABEL_NAME` and the two
  password ones (`game.common.*`); units are `base.UNIT_FACTOR` and friends
  (`game.unit.*`). The labels used to be Portuguese sentences inside each adapter, and
  the English screen showed them in Portuguese: `test_i18n.py` reads the `_()` CALLS,
  never a `FieldSpec`, so nothing noticed. `test_game_texts.py` walks every adapter of
  `registry.ADAPTERS` and fails for a text that is not a key of BOTH catalogs, a key
  outside the field's own prefix and a `game.*` key no field uses. Forgetting the keys
  raises nothing at runtime: the screen just shows `game.valheim.slots.label`.
- **One key per game, even for the same Portuguese.** "Vagas" in four games is four keys:
  each English follows that game's own menu ("Max players", "Slots"), and rewording one
  never changes another.

- **A game without an adapter is not left out**: it falls into the generic file editor,
  which knows no game at all. That is why forgetting the registry line does not raise an
  error — the screen keeps working, just generic. `test_game_registry.py` ensures no module
  in the folder is left out, and that two adapters do not claim the same file (the first
  in the list would win and the second would become silent dead code).
- **The list is explicit, not a folder scan**: whoever reads it knows, without running
  anything, which games have their own screen. The test is what guarantees it does not
  fall behind.
- **The choice is by the file NAME**, not by the game registered on the server: it is the
  same criterion the panel already uses to choose the reader, and it works even on a
  server whose game nobody declared.

### Routes live in `blueprints/`, and call `app.py` through the MODULE

Each file in `src/gamepanel/blueprints/` is a screen group (`servers.py`, `files.py`,
`alerts.py`, ...) and only does HTTP work: read the request, call whoever decides, pick
the template. `app.py` registers all of them at the bottom, via `register_all(app)` — at
the END of the file, when everything they call already exists.

- **Every access to `app.py` is `panel.X`**, never `from gamepanel.app import X`. Tests
  swap a function for a fake with `monkeypatch.setattr(panel, "server_status", ...)`,
  which replaces the name IN THE MODULE: a direct import would copy the reference at
  import time and the swap would stop applying **silently** — the tests would pass
  without testing anything.
- **Whatever is stdlib, the blueprint imports itself** (`import time`, `import sqlite3`).
  `panel.time` works, but it only lengthens the code and hides from the reader where the
  name comes from.
- **Module state with `global` stays in `app.py`.** A `global _reaper_started` inside a
  blueprint would write to ITS module's copy, and the panel would start a new thread for
  every open tab. That is why `_ensure_reaper()` lives in `app.py` and the blueprint only
  calls it.
- **The endpoint is `grupo.view`**, so repeating the group in the function name only
  lengthens it: `servers.detail`, not `servers.server_detail`. In `url_for`, in
  `endpoint=` and in the `navigation.py` tables the name is always the full one, with the
  dot.
- **New blueprint** = one file here and one name in the two lists of `register_all`. If
  the route must skip the second factor, also one line in `app.ENDPOINTS_WITHOUT_2FA`.

### Fixed text returned by a function does not translate

A function that returns `"A senha precisa ter ao menos 8 caracteres."` goes through
`translate` and comes out UNCHANGED: the cascade does not find the key, so it returns the
string itself. The English screen showed Portuguese, and no test complained — not even
`test_i18n.py`, which checks the CALLS to `_()`, not the return value of an arbitrary
function.

There were three, found while extracting code from `app.py`: the two password ones
(`validate_password`) and the history label `broker-jogo`, which was `"Jogo adicionado
ao catalogo"` written by hand inside the label dictionary.

Then sixteen more, found against the LIVE container: with the screen in English, the
operator 403 said "restrita" and the missing route said "Pagina nao encontrada". All the
barriers (`abort`), the form errors (`errors.append`) and the validation flashes were
literals. `tests/gamepanel/test_screen_text.py` guards the three doors through which text
reaches the screen — `abort`, `flash` and `errors.append` — and refuses a literal with a
space: a catalog key (`error.admin_only`) never has a space, a sentence always does.

- **An error that goes to the screen leaves as an `i18n.Message`**, not as text.
  `Message` IS a `str`, so `str(exc)`, f-strings and `in` keep working — and `translate`
  recognizes the class and rebuilds the sentence in the viewer's language.
- **The error page reads `exc.description`, not `str(exc)`.** The latter prepends
  "403 Forbidden: " (the template already shows the code above) and, worse, collapses the
  `Message` into a plain `str` — which is the DEPLOY's language. That alone was what made
  the English screen show Portuguese on every 400/403/404/413/503.
- **Text that goes to a JOB's OUTPUT stays literal, on purpose** (`_log_broker_action`,
  `notify`): the history is read later, by someone else, and the same action written three
  ways would break the filter. The guard does not look at those two doors.
- **`test_job_service.py` ensures every history label is a catalog key**, and that both
  languages have it. It is the one that would have caught `broker-jogo`.

### Panel option: one single read, in `config.py`

Every `GAMEPANEL_*` is read by `config.load()`, at import, and `app.py` keeps the result
in `settings`. Before, there were ~45 scattered `os.environ.get` calls, each with its own
inline conversion — and two consequences, both in production:

- **an invalid value took the panel down without saying which one.**
  `int(os.environ.get(...))` with garbage raises `ValueError: invalid literal for int()
  with base 10: 'abc'`, and the message does not mention the variable: whoever read the
  journal had to guess among 45;
- **there were no ranges.** `GAMEPANEL_MONITOR_EVERY=0` made the monitor spin nonstop.

The design is the broker's: list ALL problems at once, only by the variable NAME — never
the value, because that goes to the journal and there are secrets among them.

- **New option** = one field in `Settings`, one line in `load()` and (if it belongs to the
  deploy) the name in `$adminKeys` of `deploy-admin.ps1` plus `render_panel_config`.
- **`app.py` keeps the module names** (`JOB_TIMEOUT = settings.job_timeout`). It is not
  redundancy: tests swap `panel.X` for a fake, and reading `settings` directly would make
  the swap stop applying silently. `BROKER_REQUESTED` and `DEV` exist for the same reason
  — they are read INSIDE `_configure_broker`, which the tests re-run.
- **`test_settings.py` ensures nobody reads the environment on the side**, scanning the
  package for `GAMEPANEL_` next to `environ`. A loose read escapes the range check and
  disappears from the place where someone would look for the list of options.
- **Test basenames are unique across the two suites.** There is no `__init__.py` in
  `tests/`, so two `test_config.py` break the whole COLLECTION with "import file
  mismatch" — and the panel's file became `test_settings.py` because of that.

### A table's SQL lives in its repository

`persistence/repositories/` has one function per query, and every function receives the
connection as its FIRST parameter — it never calls `db()`. The connection is per request
and lives in Flask's `g`: a repository that fetched it on its own would not serve the
monitor or the scheduler, which run in their own thread without `g`. Passing the
connection is also what makes it possible to test a query without starting any
application.

Why it exists: the same `SELECT * FROM servers WHERE id = ?` was written in eight files
and the column list of the `UPDATE` in four more. None of that breaks when renaming a
column — it breaks on the FIRST VISIT to the screen that uses the copy left behind, at
runtime, with no lint or test complaining.

- **`tests/gamepanel/test_sql_placement.py` guards the rule**, per TABLE and not as a
  block: a table that has no repository yet keeps its SQL where it is, and enters the
  `OWNED` list when it is extracted. A list that is born complete is a lie.
- **Statements built from the column list**, never written by hand four times. The
  `# noqa: S608` this requires has its reason on the line above: nothing comes from
  outside, and every VALUE stays parameterized.
- **The repository does not decide.** No `flash`, no `abort`, no translation, no rule
  about who sees what: that belongs to the caller. It only knows how to read and write
  rows.
- **Whoever enables a counting source writes its fields AND `player_source` in the SAME
  statement** (`use_query_port`, `use_http`, `use_log`). Splitting would leave a server
  pointing at a source without its fields filled in.
- **All seven tables are extracted**, and `.execute(` only appears in `persistence/`. The
  guard covers all of them; a new table enters the `OWNED` list when it is created.
- **The repository's honest type finds what raw SQL hid.** `fetchone()` returns `Any`, so
  `row["x"]` with a null `row` was nobody's error; a function that declares
  `-> Row | None` makes mypy point at it. There were three, all with the same shape: the
  session of a user DELETED while it was open.

### A policy that holds state leaves `app.py` with an injectable clock

The attempt lockout (password and code) lives in `services/auth_service.py`, as the
`Lockout` class: limit, window and a dictionary of key -> failure times. `app.py` only
has two instances (`login_lockout`, `totp_lockout`) and the blueprints call
`panel.login_lockout.remaining(key)`.

- **There are TWO instances, not one with two limits.** Getting the password wrong five
  times cannot spend the attempts of someone who already got past it and is typing the
  code. The keys would even be distinct (`ip|usuario` x `2fa|usuario`), but the limits
  differ (5/5min against 5/15min) and a lockout's `remaining()` only knows its own limit.
- **The clock comes in through the constructor, and `clock=time.time` in the signature
  would be a BUG.** A default value is evaluated once, at method definition: it would keep
  the original function, and the `monkeypatch.setattr(time, "time", ...)` in
  `test_2fa.py` would have no effect at all — the lockout tests would stay green without
  exercising the window. That is why the default is `None` and `_now()` resolves the name
  in the module on every call. There is a test just for that.
- **`reset()` exists for `conftest.py`**, which clears both lockouts between tests:
  without it, a test that gets the password wrong five times would lock out the next one.
- The state is IN MEMORY on purpose: the panel runs with a single worker, and writing to
  the database would cost one write per wrong attempt — which is exactly what an attack
  produces in volume.

### Background task rhythm: a `Ticker`, not a `global` per clock

Monitor, service state, resource gauge, log, sample and history cleanup have six
different steps in the same thread. Each was a module variable with `global` on top;
today they are six instances of `tasks.ticker.Ticker` (`monitor_tick`, `state_tick`,
`resource_tick`, `log_tick`, `sample_tick`, `cleanup_tick`).

- **`due()` does NOT record the pass, and that is on purpose.** The resource gauge clock
  only advances when some resource alert is on: if asking consumed the window, a round
  with none of them would spend the interval and the next round — already with one on —
  would wait all over again. Asking and recording are `due()` and `mark()`.
- **The interval goes in the CALL, not in the constructor.** The monitor step shortens
  when there is a player alert on: the same clock answers at 60s and at 15s depending on
  the round.
- **`conftest.py` resets the list of instances, not six names.** With `global`, one
  silently renamed variable left a test inheriting the previous test's clock — no error,
  just an alert that does not fire. And `monkeypatch.setattr(panel, "_last_monitor", ...)`,
  which five tests in `test_alerts.py` did, became `panel.monitor_tick.mark(...)`.
- **The initial zero is intentional**: the first round after the panel starts always
  counts.

### The rule that holds up the rest: one list, one place

Before, the list of a server's screens was written by hand in **six templates**. Each had
a different subset, and that was why "Charts" existed on one screen and not on another.
Today it is in `navigation.py`.

- **New server screen** = one line in `ui.SERVER_SECTIONS`. Do not edit a navigation
  template; it does not exist anymore.
- **New action** (start/stop/...) = one entry in `ui.ACTIONS` (how it looks) + one in
  `app.COMMANDS` (what runs). An `assert` at import breaks if the two diverge.
- **New player counting source** = one function + one line in `app.COUNT_SOURCES`.
- **New resource alert** = one line in `app.RESOURCE_ALERTS`.

If you catch yourself writing the same list a second time, stop: it belongs in one of
those tables.

---

## Python (`app.py`, `navigation.py`)

- **Dependencies of the PANEL IN PRODUCTION: only the stdlib plus `python3-flask` from
  apt.** The container downloads packages from nowhere. No `pip install`, no CDN. That
  does not change with `uv` — `uv` only manages the development `.venv`
  (`pyproject.toml` at the root), and never goes into a production Dockerfile or into
  `provision-*-lxc.sh`. If `import gamepanel`/`import flask` does not resolve in the
  editor, run `uv sync` (creates the `.venv` and installs the repo's two packages as
  editable, plus the Flask production uses and the dev tools — see the testing section,
  at the top).
- **QR code is our own code, stdlib only** (`security/qr.py`: byte mode, M correction,
  versions 1-10 of ISO 18004). It exists for the same reason as TOTP: without pip in
  production, there is no QR library there. The suite (`test_qr.py`) proves the math
  without needing a real reader — Reed-Solomon with zero remainder at the generator's
  roots, and the minimum distance 7 of the BCH(15,5) format bits — because
  `opencv-python-headless` (the real decoder) is over 60 MB and goes neither into the dev
  `.venv` nor into the panel. **After touching `qr.py`, run `tools/verify-qr.py`** in a
  THROWAWAY venv with `opencv-python-headless` and `segno` (never in the repo's
  `pyproject.toml`): it draws the QR and checks that the camera (via OpenCV) reads back
  the right text.
- **Second factor (2FA) is our own TOTP, stdlib only** (`totp.py`, tested against the RFC
  6238 vectors). Rules the `test_2fa.py` tests guard: a correct password with 2FA does NOT
  open a session (it only records `pre2fa`, without `uid`, for 5 min); a used code does
  not work again (`totp_last_step`, and the `UPDATE ... WHERE totp_last_step < ?` is the
  gate against two simultaneous requests); the code lockout is per USER (5 in 15 min), not
  per IP; disabling or requesting new codes requires password AND code; recovery = 8
  single-use codes, only the hash in the database. `GAMEPANEL_REQUIRE_2FA=1`
  (`ADMIN_REQUIRE_2FA` in `.env`) locks whoever has not enabled it into the activation
  screen: only turn it on AFTER every admin has enabled it. Emergency exit:
  `cd /opt/gamepanel/current && python3 -m gamepanel.cli --reset-2fa USUARIO` in the
  panel's CT (the file path, `python3 /opt/gamepanel/current/gamepanel/app.py --reset-2fa`,
  does the same), or "Disable 2FA" in Users. The activation screen shows a QR code
  (`qr.py`, see above) to scan, the key as text to type by hand, and an `otpauth://` link
  that opens the app on the phone itself.
- **Passkey (device biometrics) is our own WebAuthn, stdlib only**
  (`security/webauthn.py`, routes in `blueprints/passkeys.py`). For the same reason as
  TOTP: without `cryptography` in production, the P-256 curve math (ES256:
  Android/iPhone) and RSA (RS256: Windows Hello) live there, with the RFC 6979 vector in
  the test. Rules `test_passkeys.py` guards: the challenge is single-use and lives IN THE
  server's MEMORY (`webauthn.Challenges`, `panel.passkey_challenges`), not in the session
  - the cookie belongs to the client, and an old cookie would bring back an already spent
  challenge; it only counts with UV (the device verified the person), and that is why the
  passkey replaces password AND 2FA, and registering asks for the password (plus the code,
  if 2FA is on); the registration challenge keeps the `uid` of whoever requested it.
  Disabled without `GAMEPANEL_WEBAUTHN_ORIGIN` (`ADMIN_WEBAUTHN_ORIGIN` in `.env`), which
  must be https with a DOMAIN (an IP is refused at start): the browser only allows
  WebAuthn in a secure context, and the device key is bound to the domain. The passkey
  login does not say the user before checking the signature, so the lockout is per IP
  (`passkey|ip`), in the same `login_lockout`. The tests' fake device is
  `fake_passkey.py`, next to `conftest.py` (both buckets use it).
- **`broker_required` (app.py) also requires THE PERSON's 2FA, always** — regardless of
  `GAMEPANEL_REQUIRE_2FA` (which is about the whole panel). The broker creates/deletes CTs
  and opens ports on OPNsense; it is the only barrier left if an admin session is stolen.
  A normal GET without 2FA redirects to `/account/2fa`; POST too (nothing is executed);
  `/api/...` answers 403 in JSON. The order matters: `GAMEPANEL_ALLOW_BROKER=0` still wins
  and shows its message, even for someone without 2FA
  (`test_allow_broker_desligado_vence_mesmo_para_quem_nao_tem_2fa`). That is why, **in
  `test_broker.py` (only there) the `admin` fixture already comes with 2FA on** (a local
  override that uses `admin_2fa` from `conftest.py`) — without it almost every test in the
  file would land on the activation screen instead of exercising what it wants to test;
  `admin_without_2fa` is the admin without 2FA, to prove the requirement itself.
- **`provision-admin-lxc.sh` rewrites the WHOLE `panel.env`**; the `GAMEPANEL_BROKER_*`
  and `GAMEPANEL_ALLOW_BROKER` lines that `deploy-broker.ps1 -ConfigurePanel` writes are
  preserved on purpose (before, a panel `-Full` silently turned the broker off). New panel
  option = an `ADMIN_*` variable in `.env`, one line in `render_panel_config` and the name
  in `$adminKeys` of `deploy-admin.ps1`.
- **CSRF is the panel's own, not Flask-WTF.** `csrf_token()` generates, `_check_csrf`
  (`before_request`) blocks every state-changing method. Static analyzers flag this as
  "CSRF disabled" — it is a false positive, and there is a comment on `Flask(__name__)`
  explaining it. **Do not remove `_check_csrf`.**
- **Cognitive complexity: ceiling of 15** (Sonar rule). When it overflows, the cut is
  almost always the same: separate *deciding* from *doing*. `monitor_servers` became
  `_monitor_rhythm` (what is due now) + `_server_alerts` (what to do with each one) and
  dropped from 48 to under 10.
- **A literal repeated three times becomes a constant.** `SHORT_DATE_FORMAT`,
  `PLAYER_MARK`, `_online_text()` were born that way — and the last one fixed a bonus bug:
  one of the four copies said "0 jogadores online".
- **More than 13 parameters: pass an object.** `ensure_server` had 15; it became
  `DeployServer(NamedTuple)`. Fifteen positions is where a `join_re` ends up in the place
  of `leave_re` without anyone noticing.
- **A parameter nobody uses leaves the signature**, even if it breaks the symmetry with
  sibling functions. False symmetry misleads the reader.
- **`except` without a redundant `Exception`**: `BrokenPipeError` already is an
  `OSError`.
- **Suppressing a lint warning**: the reason goes on the line ABOVE, and the comment stays
  clean.
  ```python
  # An alert never takes the job down.
  except Exception:  # noqa: BLE001
  ```
  This is STYLE, not correctness: for a long time this line said that
  `# noqa: BLE001 - motivo` was "invalid suppression syntax", and **I measured that it is
  not** — ruff honors the trailing reason AND keeps the suppression specific to the code
  (a `# noqa: BLE001 - x` on a line with E741 does not hide the E741; a bare `# noqa`
  hides both). The preference for the reason above is because a one-sentence reason does
  not fit at the end of the line without blowing the 120 columns, and when it fits it is
  because it was shortened until it no longer explains anything.
- **Dictionaries of functions** (`RESOURCE_ALERTS`, `COUNT_SOURCES`) capture the object at
  import. If a test needs to swap the function for a fake, it will have to swap the table
  entry — not the name in the module. Check before turning an `if/elif` into a table.
- **`\w` in Python is NOT `[A-Za-z0-9_]`** — without `re.ASCII` it matches accented
  letters and some 900 more Unicode characters. The analyzer asks for the short form; if
  the expression validates something that will end up in a file or a remote command, the
  swap is only valid **with the flag**. `KEY_RE` in `games/config_format.py` is the
  example, and there is a test guarding it.
- **Do not start a comment with "todo".** Sonar's `TODO` detector matches the word in any
  case, including the Portuguese "todo" (= "every"), which is how these two came about:
  `# todo). O que faltava...` and `# TODO metodo que muda estado` became two false
  positives. In the middle of a sentence it does not fire; at the start of the line, it
  does.
- **A comment in the form `# Word: thing.ext` is read as commented-out code**
  (`name: type` is a valid annotation in Python). Write `# Enshrouded (reads
  enshrouded_server.json)`, not `# File: enshrouded_server.json`.
- **A false positive that cannot go away gets a `# NOSONAR` with the reason next to it**,
  not a comment hoping someone reads it. A repeated warning one learns to ignore is how a
  real warning slips by. Today there are two, both reviewed: `python:S4502` on
  `Flask(__name__)` (our own CSRF) and `Web:S6845` on the chart SVG (tabindex is keyboard
  navigation; removing it only silences the warning and blinds whoever depends on it).

### The tests are the safety net — do not weaken them

`test_alerts.py` (81 tests) swaps module functions for fakes via
`monkeypatch.setattr(panel, "server_status", ...)`, which undoes itself at the end of each
test — before that it was a direct assignment (`panel.server_status = ...`) without any
`finally`, and the suite only did not leak state because each file was a separate Python
process. Today the suites share one process (pytest imports them all together), and it
is `monkeypatch` and the `database` fixture (tables cleaned for each test, in
`tests/gamepanel/conftest.py`) that guarantee isolation.

That swap **only reaches whoever calls through the module**. That is why the blueprints
do `panel.server_status(...)` and never `from gamepanel.app import server_status`: the
direct import copies the reference at import time, the test's swap silently stops
applying and the tests pass without testing anything. It applies to any new file outside
`app.py`.

### `GAMEPANEL_DB` in `conftest.py` is a direct assignment, never `setdefault`

`docker/panel/Dockerfile` sets `ENV GAMEPANEL_DB=/var/lib/gamepanel/panel.db`. That
variable **already exists** when the test process starts inside the container, so an
`os.environ.setdefault("GAMEPANEL_DB", tmp)` in `conftest.py` is a no-op there — the tests
would run against the REAL database of the dev panel. It has happened: a whole suite
deleted the `admin` user and filled the server list with test names ("alvo", "outro").
`conftest.py` uses `os.environ["GAMEPANEL_DB"] = ...` (assignment, not `setdefault`)
exactly for that reason — do not change that line thinking you are just letting an
external configuration win. If this ever leaks again, the fix is
`docker compose down -v && docker compose up -d` (the dev panel is disposable, the
volumes are regenerated by `PANEL_SEED_DEMO=1`).

### Changed a signature? Search outside `app.py`

`ensure_server` is also called from `docker/panel/entrypoint.sh` (inside a Python
heredoc) — a `grep` over `.py` files alone will not find it. Search the whole repository,
and remember that **`entrypoint.sh` is inside the image**: it requires
`docker compose up -d --build panel`, not a `restart`.

---

## Screen language (`src/gamepanel/i18n/`)

The panel speaks Portuguese and English. A Python dictionary, no Babel and no `.mo`:
**this repo has no build step** — production only receives files and starts (the same
reason TOTP and QR are our own code). `pt.py` and `en.py` have the SAME keys, and
`test_i18n.py` enforces parity; lookup cascades `idioma pedido -> pt -> a propria chave`
(requested language -> pt -> the key itself), so a key nobody registered shows on screen
as `nav.servers` instead of silently disappearing.

> **No screen text is hardcoded anywhere — Python, templates or JS.** If a person can read
> it on the panel, it is a catalog key (`pt.py` + `en.py`). That includes exception
> messages that end up on screen (`i18n.Message`), field labels, units and section names.
> The only literals allowed are DATA (stored keys, values compared in code) and job/script
> output (see below). Why it is a rule and not a preference: the English screen showed
> Portuguese in every Config label and in the config readers' errors, because that text
> lived in `games/adapters/` and `games/config_format.py`, where no test looked — every
> test was green and every page answered 200. `test_screen_text.py` now also refuses a
> `raise ...("sentence")` in the modules whose errors reach the screen and a `FieldSpec`
> built with a sentence instead of a key.

- **New screen text = one line in `pt.py` and one in `en.py`.** The key is
  `area.assunto` (area.subject), **in English** (it is a code identifier, not screen
  text), and never the Portuguese turned into a slug: tying the key name to the text of
  ONE language turns fixing a comma into a rename across three files.
- **A sentence with a number or name in the middle is not split**:
  `_('flash.too_many_tries', n=30)`. Splitting looks obvious and breaks the moment the
  other language changes the word order.
- **A sentence with markup (`<strong>`, `<code>`) uses `_h()`**, not `_()`. A help
  paragraph broken into one key per `<strong>` shows up half in Portuguese on the English
  screen — the start of the sentence, which is not between tags, does not go into any key.
  The sentence comes from the catalog (our code, trusted); the FIELDS are what get
  escaped.
- **Plurals take two keys** (`alert.players_online_one` / `_many`). Gluing an `s` at the
  end works in Portuguese and had already failed here.
- **Labels in tables (`ALERT_EVENTS`, `JOB_LABELS`, `ROLE_LABELS`) store the KEY**, never
  the text: the dictionary key (`caiu`, `edit-config`) goes to the database and to the
  `<option value=>`, and cannot change because someone touched the wording. Translation is
  done by `labels_of()` at render time.
- **Text born in `services/`/`runtime/` uses `i18n.Message`**, which is a `str` on
  purpose: it carries the key and the fields, but `str(exc)`, `f"{erro}"`, `"pedaco" in
  erro` and `logging` keep working unchanged. Whoever wants the person's language calls
  `translate`; forgetting falls back to the deploy's language, which was the old behavior.
- **Outside a request, `GAMEPANEL_LANG` applies, not the person.** Monitor and scheduler
  run in their own thread, without `g` or `request` — `current_language()` has a gate for
  that, and without it translating an alert takes down the whole monitor round with
  "Working outside of application context". For the same reason the alert that goes to the
  channel and the text RECORDED in a job use the deploy's language (`label_for_db`): the
  history is read later, by someone else, and the same action written three ways would
  break the filter.
- Checking a screen in both languages: the language button in the top-right corner
  (`POST /preferences/language`), or `POST /account/language` with `lang=pt|en`. Without a
  chosen language, the browser's `Accept-Language` applies.

---

## Renaming an identifier here: what no linter covers

Translating the two packages to English broke code six times, always for the same reason:
**the name also exists as TEXT somewhere**, and no tool links the two. Rename via
`tokenize` (NAME tokens only) and never via `re` — `portas` appears inside prose sentences
and as a dictionary key. Afterwards, look for each of these:

- **A data key that looks like an identifier.** `d.update(porta_extra=8888)` is a kwarg
  in syntax and a JSON field in practice; `ConfigBroker(**cfg_parcial)` and
  `CliDeps(**base)` receive the field name as text. API, disk and database formats do not
  change along with the code.
- **A form field and a query parameter are a pair with the template.** `request.
  form.get("acao")` matches `name="acao"` in an `.html`, and the macros' `fields={...}`
  hides the other end in a Jinja dictionary no HTTP test sees — it only appears in the
  rendered HTML. Renaming the route without the template leaves the field EMPTY: that is
  how kick/ban stopped, with the two tests that existed (only 302, permission) passing
  just the same. `test_players.py` compares both sides now.
- **A VALUE compared as text in Jinja is worse**, because it does not even look like an
  identifier. The route's default (`get("tab", "port")`) and the template's
  `{% if tab == 'porta' %}` are the same decision written twice: changing one left the
  ports tab without content and without highlight for whoever opens the screen WITHOUT a
  query string — 200, full HTML, nothing in the log. There is a test comparing the tabs
  the route knows with the ones the template sends.
- **`@pytest.mark.parametrize("nome", ...)`.** The argname is a string; pytest only
  complains at COLLECTION, after the rename has already gone through everything.
- **`monkeypatch.setattr(panel, "nome")`.** Worse than the previous one: if the name no
  longer exists, the test may PASS without testing anything.
- **Flask route captures.** `<int:instancia_id>` matches the handler's parameter by name —
  renaming only the parameter gives a 500 on every call. The capture name does not appear
  in the URL, so it can follow along; the ROUTE's name cannot, because the templates'
  `url_for` uses it.
- **Collision with a name that already exists.** `LogStream` already had `stop()` and the
  Event `parar` landed on top of it; `acao_de_jogador` became `player_action` and started
  calling the route of the same name, recursively. It was the same reason for the
  `term_runtime` alias at the top of `app.py`.
- **i18n sentence placeholders.** The catalog says `{name}` and the caller passes
  `name=`: they are the same thing. Renaming only one breaks the substitution, and
  `translate` swallows the `KeyError` on purpose — the defect comes out SILENT.
  `test_i18n.py` enforces it by reading the AST of every `_()`/`_h()`/`Message()`.

- **A `url_for` kwarg is a pair with whoever READS that key.** What is not a route
  capture becomes a query string, and someone has to `request.args.get` with the same
  name. Renaming one side only leaves the link answering 200 and the value never arrives:
  `aba="http"` after the route started reading `tab` sent the "use this API" button to the
  ports tab, and a `{"pasta": ...}` in a `**extras` lost the folder chosen in the file
  search. The three cases were `url_for` built in PYTHON, which is where the template
  check does not look. `test_url_contract.py` covers the direct kwarg AND the dict that
  feeds the `**`.
- **Endpoint names in `navigation.py` also rot.** They are text, nothing ties them to
  the route, and a name left over after the route died breaks nothing — the tab just
  never lights up for it. The files.search one stayed like that for ages (without
  backticks on purpose: the docs test requires every backticked name to exist). The same
  test covers it.

And what no test caught before: **`render_template` kwargs**. Changing `instancias=` to
`instances=` leaves the screen EMPTY — 200, no error, no log, because Jinja treats a
missing variable as undefined. Now `tests/gamepanel/test_template_contract.py` checks
each kwarg against what the templates actually read. Even so, **walk through the screens
by hand** (the `curl` sweep above): only there did the chart axis without numbers and the
`energia` macro called by its old name show up.

---

## The front-end contract: template, CSS and JavaScript

The same defect as the template contract, in three more pairs. In all of them, the name
exists as TEXT on both sides and no tool links the two; in all of them, the page keeps
answering 200.

- class only in `class=` = a style that never arrives, and the screen opens crooked;
- class only in the `.css` = a dead rule, which the next person reads as if it were in
  use;
- `data-*` only in the template = behavior that never mounts, with nothing in the
  console;
- `data-*` only in the JavaScript = a feature that never finds any element.

`tests/gamepanel/test_frontend_contract.py` enforces all four, plus the gauge's READ
contract (`metrics.X` in `server_detail.html` against what `parse_metrics` delivers —
the list comes from the code itself, not from a hand-written copy). Its real findings on
the first run: three classes without a rule and seven dead rules.

- **A CSS rule nobody uses GOES.** Grandfathering an exception list would leave the test
  weak from day one — and it is the list that would silently age.
- **A class built at runtime** (`{% set classes = classes + ['btn--' ~ variant] %}`)
  enters by PREFIX: the test collects `btn--` and accepts any `btn--*`. Without that every
  variant would look dead.
- **A FULL name inside a `{% set %}` is checked, and that was the gap.** The macro emitted
  `['btn--bloco']` and the CSS had `.btn--block`: every `block=true` button in the panel
  (log in, save, add — some twenty screens) stopped taking the card's width, and nothing
  complained. The class is not in a `class=`, so `JINJA_EXPR.sub` erased it along with the
  rest of the expression, and the `btn--` prefix absolved it on the other side. Today
  `SET_CLASS` collects it and the test fails.
- **A CSS token (`--nome`) has BOTH sides checked**, like a class: defined and never used,
  and `var(--x)` without a definition. `var()` of a nonexistent name is not an error for
  any browser — the property simply does not apply, and the screen opens without the color
  or without the spacing. It found three dead tokens at once (`--sombra-1`, `--r-lg`,
  `--sp-7`), all removed: keeping an exception list would leave the test weak from day
  one.
- **`cores` is the colliding word**: CPU cores in English, colors in Portuguese. An
  automatic rename once swapped one for the other on both sides and the number of cores
  disappeared from the screen. There is a test just for it.

**Renaming JavaScript with a dictionary? Use `Map`, not an object.** `MAP['constructor']`
on a plain object returns `Object.prototype.constructor` instead of `undefined`, and the
renamer replaces the word `constructor` of every class with the TEXT of a native function
(`function Object() { [native code] }`). `test_javascript.py` caught it on the first run
— without it, the terminal and the chart would have broken only in the browser of
whoever opened the screen.

### The docs have a net too

`tests/gamepanel/test_docs_contract.py` ensures that every `modulo.nome` cited in
backticks in THIS file still exists in the code. Docs that age are not missing docs: they
are docs that LIE, and send the next person looking for a name that does not exist. It
found four at once on the first run: the docs said to look for taken_ports in opnsense
(the name is `busy_ports`), _limpar in the SSH installer (it is `_cleanup`) and
somente_banco in the broker (it is `db_only`), besides the three in `navigation.py` that
had already been in English for several commits.

The scope is narrow because three things have the SAME shape and are not references to
code: an i18n key (`charts.players`), a file name (`compare.sh`) and an external module
(`flask.g`). The first two are filtered out by recognition — the key exists in the
catalog, the file has an extension —, not by a list. The four remaining collisions are in
`NOT_CODE`, each with its reason next to it.

### JavaScript has a net now

`tests/gamepanel/test_javascript.py` (needs `node`; SKIPPED without it) asks three
questions: each module parses, each module IMPORTS, and each feature MOUNTS against a
fake DOM. Production has no node and the panel does not depend on it for anything.

The third is the one that matters. Three real defects were born from renames and none of
them showed up on the server — 200 on the page, full HTML, and the error in the console of
whoever opened the screen (`app.js` still swallows it on purpose, so one broken feature
does not take the others with it):

- `Poller` started exposing `start()` and the features kept calling `.iniciar()`;
- `readJSON(url, opcoes)` kept reading `options.headers`;
- `shortList` used `rotulo` on one line and `label` on the next.

**`app.js` exports `FEATURES` only for this test.** Without the exported list there is no
way to mount each feature without a browser.

### Renaming JavaScript: `${...}` is code, and methods live after the dot

- **A template literal is not a whole string.** The part between backticks has CODE
  inside the braces. A renamer that skips backticks leaves out exactly the identifier that
  only appears there — that is how `rotulo` survived three passes.
- **An object member needs the position AFTER the dot**, which is precisely the one
  excluded when renaming a local variable. A half-rename there gives neither a syntax nor
  an import error.
- **A selector regex must not cross quotes.** A pattern for `'.classe'` that accepted
  anything up to the next quote matched `...opcoes.headers` in the middle of the code and
  rewrote it.

### Renaming bash and PowerShell: prose is not an identifier

A rename pass changes only IDENTIFIERS. The first attempt replaced the loose word across
the file and got into the prose: `# e o caso de um release que quebra` became
`# e o run_case de...`, and `die "sha256 nao confere"` became `"nao check"` — text the
sandbox looks for, and which stopped matching. Translating comments is a separate,
deliberate pass, by hand; output messages the sandboxes grep for are not translated at
all.

- **One position, one replacement.** `local origem="$1"` matches as a declaration AND as
  an assignment; applying both produced `source_dir_dir` and `local extra_limits""`
  (without the `=`). Both passed `bash -n` and only broke when run.
- **`$(funcao)` inside double quotes is CODE.** Skipping the whole quoted string left
  `$(qual)` calling a function that had already become `host_path`.
- **`$(( ))` uses the name WITHOUT the dollar sign**: `falhas=$((falhas + 1))` needs both
  sides.
- **Prove it with the four sandboxes**: `compare.sh` (game installer, byte for byte),
  `broker.sh`, `release.sh` and the suite. It was `compare.sh` that caught the systemd
  unit that stopped being written.

### Renaming in the front end: each name in ITS scope

- **A class** changes in the `.css` selector (with the dot), inside `class="..."` and the
  macros' `css_class=` argument, and in the JS `classList`/selector/`class="..."`.
  Replacing the loose word across the file would change data: `key` is also a template
  variable and a dictionary key.
- **A compound selector has no left boundary.** In `body.has-tabbar` the character before
  the dot is a letter, so a `(?<![\w-])` refuses the match and the rule is left behind
  while the template already uses the new name. The dot ALREADY is the boundary.
- **The hyphen counts as a boundary for `\b`**, so `icon` would match inside `btn--icon`
  and the two replacements trample each other. Use `(?<![\w-])x(?![\w-])`.
- **`data-x` has two forms**: the attribute in the template and `dataset.xCamel` in
  JavaScript.
- **A Jinja macro parameter lives in two places**: the signature and the BODY. Changing
  only the signature gives `'campos' is undefined` on the first screen that uses the
  macro.
- **A macro calls a macro without a prefix** inside its own file (`{{ state(status) }}`,
  not `srv.state`): a replacement that only looks for `ui.`/`srv.` leaves those behind.

## Jinja templates

- **Zero `<script>` with logic and zero `onsubmit="return confirm(...)"`.** Behavior comes
  from `static/js/features/` through `data-*`. Confirmation is
  `data-confirmar="mensagem"` — the file name comes from the container, and inside
  JavaScript code an apostrophe in the name breaks the whole page.
- **Never write a literal tag inside a `{# ... #}` comment.** Jinja ignores it, the editor
  does not: it opens a tag that never closes and starts reading the rest of the file as
  JavaScript. Write "script tag" in words.
- **No `style="...{{ valor }}..."`.** A template value inside a `style` attribute is not
  valid CSS for any tool, and the whole file starts reporting errors. When the color comes
  from the server, use an **attribute** (`fill=`, `stroke=`) in an SVG — that is what the
  chart legend does.
- **A template that is not HTML gets the `.jinja` suffix** (`sw.js.jinja`,
  `manifest.webmanifest.jinja`), otherwise the editor tries to parse `{% for %}` as
  JavaScript.
- **`{% import %}` always `with context`.** Without it the macro does not see
  `csrf_token()` or `url_for`, and the screen dies with `'csrf_token' is undefined`.
- **`aria-label` only when there is no visible label.** Inside a `<label>Servidor`, an
  `aria-label="filtrar por servidor"` REPLACES the visible text for the screen reader.
- **Every table inside `<div class="table-wrap">`**, otherwise it pushes the page off the
  screen on a phone.
- Every POST uses the `ui.action` / `ui.menu_action` macros, which add the CSRF on their
  own.

---

## CSS

Five layers, and each one **may only depend on the previous ones**:

| layer | what goes in |
|---|---|
| `tokens.css` | color, spacing, radius, font, tap target, z-index. No selectors (except the theme blocks, below). |
| `base.css` | reset and raw elements (`a`, `input`, `table`) |
| `layout.css` | app skeleton (`.appbar`, `.tabbar`, `.wrap`) and primitives (`.stack`, `.cluster`) |
| `components.css` | reusable pieces (`.btn`, `.card`, `.badge`, `.menu`, `.tabs`) |
| `pages.css` | what belongs to a single screen |

- **Mobile first**: what is outside `@media` is the phone screen; media queries only
  **add** when there is room (`min-width`, never `max-width`).
- **No raw value outside `tokens.css`.** No `#4f9cf9`, no loose `16px`. There is a test
  (`test_frontend_contract.py`), and the exception is not a list of names:
  `color-mix(..., #fff)` is recognized by its SHAPE (it means "lighten this", not a
  color), and two colors remain with a physical reason written in the CSS itself — the QR
  white (a token would follow dark mode and the camera would not find the code, exactly
  when the person is locked out) and the terminal foreground, which follows the ANSI
  palette of `terminal.js`, which is protocol.
- **State has a PAIR of tokens: `--x-line` and `--x-text`.** `--ok` had only the border,
  and `.flash.ok` resolved it with a loose `#8ce39a` — the success message was the only
  color in the panel outside the palette. State text is a lighter tone of the state itself
  on the dark theme (and a darker one on the light theme): the border color does not have
  enough contrast to read a sentence on either background.
- **Variation comes in through a modifier** (`.btn--danger`), never through "that button
  inside that screen" — descendant rules are what make a CSS stop being reusable.
- **Showed up twice? It moves up a layer.** If it is in `pages.css` and serves two
  screens, it belongs in `components.css`.
- **Tap target `>= var(--tap)` (44px)** on everything clickable.
- **Form fields with `font-size >= 16px`**, otherwise iPhone Safari zooms in on its own
  on focus.
- **Hiding by `hover` always together with width**: `@media (hover: hover) and
  (pointer: fine) and (min-width: 900px)`. Phone browsers that declare `hover: hover`
  exist, and there is no way to reveal what was hidden there.
- **`--safe-*` (notch/gesture bar)** on everything that touches the screen edge.
- **Header and body share the same column.** The bar's background goes edge to edge, but
  the content (`.appbar__miolo`) has the `--largura-max` and the `.wrap` padding: without
  that the brand sits in the window's corner and the content in the middle, aligned with
  nothing. From 900px the bar shows ALL destinations (`ui.NAV_DESKTOP_BAR`, without icons
  and with the `curto` label where there is one, so that seven fit - measured at 900px,
  and it is the limit: an eighth does not fit without touching the CSS) and the menu under
  the person's NAME holds account, SSH key and log out (`NAV_DESKTOP_ACCOUNT`). On the
  phone nothing changed: tabs at the bottom and the "⋯". Highlighted item:
  `active_desktop_nav_for` (each destination lights up its own) x `active_nav_for` (the
  four phone tabs).
- **Side-by-side cards use `.grid-cartoes`** (one column on the phone, two from 900px;
  `.grid-cartoes__largo` takes the whole row). A long block (log, table) goes in
  `__largo`, otherwise it pushes its neighbor.
- **The checkbox class is `.checkbox`**, not `.check` (which does not exist and left the
  box on top of the text). A group of fields with a title: `fieldset.grupo`.

### Theme: light and dark, by tokens only

The panel has a dark theme (the default) and a light one, and both are ONLY token values
in `static/css/tokens.css` — no other layer knows which theme is on. The dark values are
the defaults on `:root`; the light values come in through two doors:
`:root[data-theme="light"]` (the person chose light with the button, which beats the
system) and `@media (prefers-color-scheme: light)` with `:root:not([data-theme="dark"])`
(the device is in light mode and nobody chose anything). CSS has no way to reuse one
block between a selector and a media query, so **the light list appears twice by
necessity**: changing a light color means changing both.

- **A new color goes into BOTH the dark defaults and the light block** (both copies of
  it). A token defined only for dark keeps the dark value on the light theme — a dark
  stripe on a white page, or text without contrast — and no test sees it: the page
  answers 200 and `var()` resolves.
- **`--term-bg` keeps the terminal dark in both themes**, on purpose: its foreground
  follows the ANSI palette of `terminal.js` (protocol, see above), which was designed for
  a dark background. That is why the light block does not redefine it.
- **Theme and language are chosen by the two buttons in the top-right corner**, served by
  `blueprints/preferences.py` (`POST /preferences/theme`, `POST /preferences/language`).
  They are COOKIES, not session or database, because the login screen respects them too,
  and there is no user there yet. For a logged-in user the language is ALSO stored on the
  account (the `lang` column of the users table): that is what follows the person to
  another device, and the cookie only covers the way to the login. The `next` the form
  sends back is validated with the same `app.safe_target` the login uses: accepting
  anything there would turn the button into an open redirect.
- Check every screen you touched in both themes (and both languages): a color that only
  works on one background is the usual defect.

---

## JavaScript

ES modules, no build, no external dependency.

- **`core/` knows no screen at all.** `format` (number -> text), `http` (read JSON),
  `poll` (when to run), `dom`, `dirty`. Testable, reusable.
- **`features/` has ONE contract**: `export const x = { seletor, montar(el) }`. `app.js`
  only wires each feature to the elements the page brought — a new feature changes
  `app.js` by no more than one line in the registry.
- **Do not call `fetch` or `setInterval` directly in a feature.** Use `lerJSON` and
  `Poller`: that is where `cache: 'no-store'`, the "hidden tab does not spend SSH" and the
  backoff when the panel goes down live. This was once six copies, each missing one
  detail.
- **Text that came from the game or the container goes in through `textContent`**, never
  through `innerHTML`. Player names and file names are data, not markup.
- **The screen must work without JavaScript.** The chart already comes drawn from the
  server, the table of numbers is on the page, the menu is a `<details>`. A control that
  only exists with JS (the "+ another line") is born `hidden` and the module itself
  reveals it.
- Linter preferences: `Number.parseFloat` (not `parseFloat`), `el.dataset.x` (not
  `getAttribute('data-x')`), `a?.b` (not `a && a.b`).

---

## PWA and service worker

- **`/sw.js` is served by Flask, from the root.** A service worker's scope is the folder
  where it lives: at `/static/sw.js` it would not see the panel's navigation.
- **The version is the mtime of the files in `static/`**, stamped when serving. New CSS =
  different worker = old cache discarded.
- **Never cache logged-in page HTML or `/api/`.** The panel has several users and gives
  root in the containers: a cached servers screen could reappear after logout, and a
  cached gauge lies about a real server.
- **The worker does not take over on its own** (no `skipWaiting()` on install): there may
  be a terminal session open in the middle of an edit. The "Update now" button does the
  swap.
- **Checking layout through screenshots? Bypass the service worker.** It serves the old
  CSS/JS from cache until someone clicks "Update now": the picture comes out with the
  previous version's style and it looks like the change "did not take" (the "There is a
  new version" banner showing in the picture is the sign). When capturing via DevTools use
  `Network.setBypassServiceWorker` + `Network.setCacheDisabled`, and restart the local
  server after touching `app.py` (`app.run` does not reload Python code).
- **Do not name an application route after telemetry.** `/api/metrics` is a common
  blocker rule (uBlock, AdGuard, filtered DNS): the browser returns a pixel with status
  499 and the request never reaches the server. The route here is `/api/v1/resources`.
  When debugging "the request disappears", compare **curl x browser** before looking for a
  bug in the code.

---

## Access to game containers: `gamepanel`, not root

The contract is [docs/security-hardening-contract.md](docs/security-hardening-contract.md) and
the reasoning is [docs/security-hardening.md](docs/security-hardening.md). In short:

- **Two modes per server, decided by the `ssh_user` column of the servers table**: `root` is legacy mode (commands go out
  exactly as before), anything else is helper mode. There is no schema migration; new servers
  default to `gamepanel`, existing rows keep their user.
- **Every remote command goes through `runtime/remote_cmd.py`**, which states the intent
  (`as_root_action`, `as_steam`, `unprivileged`, `interactive_shell`, `presence`,
  `clamav_ensure`). Never write `sudo` or `systemctl` by hand at a call site: in root mode the
  builder must return byte-identical strings to the old ones, and that is what the existing suite
  proves.
- **Content runs as `steam`, never as root** (files, backups, console, terminal, folder/workshop
  mods, antivirus scan). Root writing inside folders the game can write is a path from a
  compromised game to root: a planted symlink is followed by `cat >`, `cp -a`, `chown` or `tar`.
  The `cd /` before `sudo -u steam` exists because the session starts in the 0700 home of
  `gamepanel`, which `steam` cannot enter.
- **Root helpers take no free argument.** `gp-service` reads the unit from the root-owned
  `/etc/gamepanel/ct.env`; helpers without arguments are written with `""` in sudoers, because a
  command written without arguments accepts ANY arguments.
- **Loader installers work in helper mode (phase 6) without any new sudo rule**: they run as
  steam and write steam's overlay in `/etc/gamepanel/game-env` instead of root's drop-ins and
  `/etc/game-runtime.env` (see the Mod manager section). `ct-panel-access.sh install` prepares
  the overlay, the `EnvironmentFile=` drop-in and the win-run hook once, and converts what a
  root installer had left; rerunning `migrate-ct.ps1` on an already migrated CT is how an old CT
  gets it.
- **`lib/ct-panel-access.sh` is the one place that creates the user, helpers, sudoers and the
  root lock**, used by `ct-phases.sh` (host and broker), both Docker images and the future
  migration. `lock` only runs after `verify` passes, so a broken sudo never locks anyone out.
  Prove it with `bash docker/ct-sandbox/panel-access.sh` (real sudo and sshd of Debian 13).
- **The real Docker image (`docker/gameserver`) is helper mode only**, and its `systemctl`,
  `journalctl` and `game-supervisor` play systemd's part: several `-p` in one `show`,
  `NRestarts`/`SubState`/`Result`, the unit's drop-ins (`Environment=`/`EnvironmentFile=`, PARSED
  by the supervisor, never sourced: the overlay is steam's and the supervisor is root). Touched any
  of them? Run `bash docker/ct-sandbox/gameserver.sh` (real build, real SteamCMD install of app
  1007, ssh as gamepanel with the panel's own command strings; `--game <key>` for a real game).
- **The game unit sandbox is opt-in per CT and lives in ONE file, `lib/ct-sandbox-unit.sh`**
  (`on|off|status|render`; drop-in `<unit>.d/gamepanel-sandbox.conf`). `on` restarts the game and
  rolls back on its own (journal printed, drop-in removed, game restarted) when the game does not
  stay up or does not reopen the ports it had. Never `MemoryDenyWriteExecute` (Wine/Proton/Mono/
  UE4SS JIT), never `ProtectHome` (prefixes in `/home/steam`). Existing CTs go through the HOST
  (`deploy/game/sandbox-ct.ps1`, `pct exec`), new ones through `deploy-game.ps1 -UnitSandbox`; the
  panel has no switch for it on purpose. The panel's own unit is `ProtectSystem=strict` with
  `ReadWritePaths=/var/lib/gamepanel`: a new path the panel WRITES must live in that folder or get
  its own line. Touched either unit? Run `bash docker/ct-sandbox/unit-sandbox.sh` (real systemd
  as PID 1 in privileged Docker: it proves the drop-ins and the rollback, NOT an unprivileged
  LXC's AppArmor).
- **In the dev compose `game-palworld` is helper mode and `game-dragonwilds` is root**, so both
  paths run every day. Rebuilding the game images changes their SSH host keys: the panel refuses
  them (as it should) until you remove the old keys from `/var/lib/gamepanel/known_hosts` in the
  panel container.

## Broker (`src/gamebroker/`)

The panel does not keep Proxmox or OPNsense credentials: the broker does, and exposes
fixed verbs (create/deactivate/remove instance, catalog). Done: the core, REAL Proxmox
(`proxmox.py`) and OPNsense (`opnsense.py`) backends and the HTTP client
(`integrations/http_client.py`), all tested against fake servers (`fake_http.py`), the
SSH installer (`runtime/ssh_installer.py` + `lib/ct-install.sh`), the screen in the panel
and the broker DEPLOY (`config.py`, `wsgi.py`, `provision-broker-lxc.sh`,
`deploy-broker.ps1`). Only a REAL end-to-end creation is missing (none of this has run
against your Proxmox/OPNsense yet). Test and deploy secrets live in `broker.secrets.env`
(outside git); `check-broker-access.ps1` checks read-only access and
`spike-broker-write.ps1` creates and deletes a test CT/rule.

**Panel side** (`src/gamepanel/`): the `/catalog` and `/instances` screens, the
`GAMEPANEL_ALLOW_BROKER` flag (off by default; a bad config TURNS THE FEATURE OFF instead
of taking the panel down), `servers.broker_id` and `jobs.broker_op`. The dev compose
starts a toy broker (`gamebroker/dev.py`, fake backends): `docker compose up --build`.

- **One game installer, two transports.** The phases that run INSIDE the CT (SteamCMD,
  Wine/Proton, systemd) live in `lib/ct-phases.sh`, read by `provision-game-lxc.sh` (host:
  `pct exec`) and by `lib/ct-install.sh` (inside the CT, what the broker runs over SSH).
  The `deploy-game.ps1` bundle is a folder WITHOUT subfolders: the lib travels as
  `ct-phases.sh` next to the script. **Touched a phase? Run
  `bash docker/ct-sandbox/compare.sh`** (needs Docker): it runs the installer BEFORE and
  AFTER for 8 games with fake `pct`, `systemctl`, `apt-get` and SteamCMD and diffs files,
  content and command lines; it also compares host x broker and checks the `install.env`
  the Python side generates. Without it the refactoring is done in the dark: there are no
  shell tests in the repository.
- **The broker's Steam account only goes to a CURATED game that requires it**
  (`Game.needs_account`, from `STEAM_ANONYMOUS=0`; today, DayZ). Without
  `STEAM_USER`/`STEAM_PASS` on the broker that game shows as "manual" in the catalog; with
  only one of them, the broker does not start. `validate_dynamic` never asks for it: an
  API game has no way to carry the password to a CT. It goes into `install.env` (deleted
  by `_cleanup`), the operation log replaces it with `******` (`_masking`) and
  `SteamAccount` strips it from the `repr`. The account must have NO Steam Guard: the
  first login of each new CT happens minutes after the request.
- **Server without a Linux build: Proton first, ALWAYS.** Every `games/*.env`, template
  and manual suggestion of a Windows-only game is born with `proton`; `wine` directly only
  after Proton has been tried and failed with that game, with the reason written in the
  `.env`. The price of Proton is the appid: Steam's game server API needs the REAL one
  (UMU_ID/SteamAppId), otherwise the query never opens - see `icarus.env` and
  `vrising.env`. `test_templates.py` and `test_suggestions.py` enforce the rule.
- **A software Vulkan driver is the `vulkan` recipe** (mesa-vulkan-drivers, installed by
  `apply_recipes`), also only next to `proton`/`wine`. ARK: Survival Ascended creates a
  Direct3D 12 device even headless; Proton turns it into Vulkan, and with only the libvulkan1
  loader the server died at boot in d3d12/dxgi (measured, GE-Proton11-5).
- **`client_app_id` is the client's Steam appid for a .exe with no steam_appid.txt next to it**
  (Conan Exiles: 440900, while the server app is 443030). It goes to `install.env` as
  `CLIENT_APP_ID`, `ct-phases.sh` writes it to `/etc/game-runtime.env`, and win-run falls back to
  it. Without it the server answers A2S with appid 0 and the game's server browser never lists it.
- **Virtual X is the `xvfb` recipe**, which only applies together with `proton`/`wine`.
  A curated game with `WINDOWS_RUNTIME_XVFB=1` gets it in `catalog._curated_recipes`:
  before, only the runtime went to the broker's `install.env`, and an Icarus created by
  the panel started WITHOUT the virtual X its `.env` asks for.
- **An `.exe` in `START_SCRIPT` becomes `win-run` in `ExecStart`**
  (`render_systemd_unit`). A dynamic game has no `POST_INSTALL_CMD` to write a `.sh`
  wrapper, and without this the service died with "Exec format error". A curated game
  keeps its wrapper (`compare.sh` proves nothing changed).
- **The curated `WINE_DLL_OVERRIDES` goes to `install.env`** (`Game.wine_overrides`).
  Before, only the runtime went, and a V Rising created by the panel was born with the
  `ct-phases.sh` default, which disables the mscoree BepInEx needs. An API game does not
  choose Wine DLLs.
- **`install.env` is always `shlex.quote`.** Hooks (`PRE/POST_INSTALL_CMD`) only exist in
  the curated catalog; an API game chooses **recipes** (`apply_recipes`, a closed list),
  never writes shell. An unknown recipe aborts the install. The broker's key leaves the
  CT at the end (`_cleanup`, runs ALWAYS) and if it does not leave, the creation FAILS.
- **`games/*.env` must pass bash `source`.** A log regex (`JOIN_RE`) with parentheses
  needs quotes: without them 5 of the 8 games broke the deploy through Proxmox
  (`provision-game-lxc.sh` does `source` on the raw file). To check:
  `for f in games/*.env; do bash -c "set -a; source $f"; done`.
- **Writing text for bash on Windows:** `print()`/stdout in text mode turns `\n` into
  `\r\n` and `source` reads each value with a `\r` (the error comes out as
  `WINDOWS_RUNTIME invalido: ''`). Write with `newline="\n"` or bytes.
- **Broker deploy** (`deploy-broker.ps1` -> `provision-broker-lxc.sh`, on the Proxmox
  host): its own unprivileged CT, OUTSIDE the `games` pool, with gunicorn+TLS (1 worker,
  the IP lockout lives in memory) and hardened systemd. **Token, SSH key and certificate
  PERSIST across deploys** (regenerating would break the panel); they only change with
  `-RotateToken` / `-RotateCert`. The secrets arrive in `broker.secrets.env` (0600,
  deleted at the end) and go to `/etc/gamebroker/broker.env`; no secrets in the unit. The
  deploy **does not turn the feature on in the panel**: `-ConfigurePanel` writes
  URL/token/fingerprint with `GAMEPANEL_ALLOW_BROKER=0`, and `-EnableOnPanel` asks for
  confirmation. The old names (`-ConfigurarPainel`, `-LigarNoPainel`, and
  `-SoProxmox`/`-SoOpnsense`/`-ComSsh` in the spike) keep working through `[Alias(...)]`:
  the command line is the only thing here someone has saved somewhere else, and
  translating the identifier cannot break what is already written down in a README or a
  shell history. **Prove it with `bash docker/ct-sandbox/broker.sh`** (mode/owner, env
  re-read by the real `config.load`, secrets with quotes/backslash/dollar/backtick,
  idempotency, rotation).
- **`set -e` + `pipefail` + `$(...)` = SILENT exit.** A failure inside a substitution ends
  the script before the `[[ -n "$x" ]] || die "..."` that would explain it (that is what
  the first real deploy did when the Proxmox host could not reach OPNsense: it stopped
  with no message). Every provisioning script has `trap ERR` (line + command, no secret)
  and uses `|| true` inside the `$(...)` that feeds a `die`. The sandbox has cases for
  both.
- **ssh/scp in PowerShell 5.1:** the remote stderr (even a successful `systemctl enable`
  prints "Created symlink") becomes an exception with `$ErrorActionPreference = "Stop"`
  and redirected output. `Invoke-Native` (deploy-broker.ps1) relaxes the preference only
  during the command; what decides is `$LASTEXITCODE`.
- **The health check from inside the CT uses `127.0.0.1`, which goes into
  `BROKER_ALLOW_IPS`** along with the panel's IP (empty list = any origin, so there the
  loopback is NOT added). The health probe has a short deadline (`SONDA_TIMEOUT`): a
  firewall that drops packets cannot make the health check take 30 s.
- **The Proxmox API and the OPNsense API need a firewall rule for the broker's CT** (the
  deploy summary lists them). Without them the broker starts, but health shows
  "NOT RESPONDING" and nothing gets created.
- **`gamebroker/config.py` validates EVERYTHING and lists ALL problems at once**, only by
  the variable NAME (never the value). A bad config kills the START (`SystemExit(2)`),
  never a request. https requires a SHA-256 fingerprint; http only on loopback.
- **Values in a systemd `EnvironmentFile`:** `NOME="valor"` with `\` and `"` escaped (`$`
  does not expand there). Test with a character-by-character parser: a greedy regex
  swallows an unescaped quote and hides the defect.
- **The Proxmox/OPNsense certificate fingerprint is read from the server at deploy time
  (TOFU) and PRINTED for you to check.** If you already know the fingerprint, put it in
  `*_CERT_SHA256`.
- **`gamebroker` and `gamepanel` are the two packages of the uv workspace**
  (`src/gamebroker/`, `src/gamepanel/`), installed editable in the `.venv` by `uv sync` —
  that is why `import gamebroker.X` works anywhere in the repo without touching
  `sys.path`. Each one's suites live in `tests/gamebroker/`/`tests/gamepanel/`, testing
  the installed package, not a relative path. Run only the broker from the root:
  `uv run pytest tests/gamebroker`.
- **`services/instance_service.py` only knows the interfaces in `runtime/base.py`.** Real
  Proxmox, OPNsense, SSH and network come in later without touching it; the tests use
  `runtime/fakes.py`.
- **Two-level catalog**: `games/*.env` (curated, may have `PRE/POST_INSTALL_CMD`) and
  games registered through the API (**data only**). The `.env` is read by
  `catalog.read_env`, never by `source`, and a field the broker does not know is REFUSED
  — that is how `pre_install_cmd` stops getting smuggled in. New field in a dynamic game =
  its own regex in `services/catalog.py` and a case in the test's `INVALID_CASES`.
- **Editing a CURATED game from the panel writes an overlay, never the `.env`.** The edit
  goes to `<chave>.json` in the dynamic games folder, passes through the same
  `validate_dynamic` and only changes DATA: the `PRE/POST_INSTALL_CMD` and the reason for
  not being creatable stay those of the file (`catalog._as_override`). "Delete" on an
  edited curated game UNDOES the edit; on an unedited curated game it is refused (it
  comes from git). A consequence that bites: an old `.json` with the key of a new curated
  game starts applying ON TOP of it — that was the case of Valheim, registered from the
  LinuxGSM suggestion before `games/valheim.env` existed.
- **Internal port == external port, always.** A `deslocavel` (shiftable) game
  (`PORTS_SHIFTABLE=1`) gets a block of consecutive ports from the broker's RANGE
  (`BROKER_PORT_INICIO/FIM`, default 31000-31999, below the ephemeral 32768+ and far from
  the games' default ports), never the default ports; the others stay on the default
  ports and are refused if those are taken. That means going to the range even with the
  default port free: a mix of "old server on the default port" and "broker server in the
  range" is what prevents a collision one day. A game is only `deslocavel` if the broker
  can TELL it about all of its ports: `START_ARGS` with `{PORT}` (and `{QUERY_PORT}` if
  there is a query, `{EXTRA_PORT}` if there is an extra port) and no port beyond those
  three (`catalog.shiftable_problem`, validated at load). The extra port
  (`EXTRA_PORT=`/`porta_extra`) exists because of Satisfactory: besides the main one
  (UDP+TCP) it opens 8888/TCP for reliable messages, which without `-ReliablePort=` is
  fixed and prevents a second instance. `ct-phases.sh` replaces `{EXTRA_PORT}` like the
  other two; the placeholder without an extra port is refused (it would become `0`).
  **No curated game uses the range, by decision** (`PORTS_SHIFTABLE=0` with the reason
  written in each `.env`): the server stays on the port everybody knows, and a second
  instance of the same game is refused. The placeholders stay in `START_ARGS` (they
  receive the default port), so going back is changing one number. A dynamic game can
  still move ports. See `services/allocator.py`. In `compare.sh` the "before x after"
  Satisfactory runs without the placeholder (`satisfactory-legado.env`): the reference
  installer does not know it and would leave `{EXTRA_PORT}` literal in the ExecStart.
- **Addresses: the IP tells the CTID.** Panel `.100` (CT 300), broker `.101` (CT 301),
  broker games `.102-.199` (CT 302-399): `CTID = BROKER_CTID_BASE (200) + ultimo numero do
  IP` (the last number of the IP), that is, "3" + the IP's last two digits
  (`allocator.pick_ip_and_ctid`; an IP only works if its CTID is also free). Everything in
  300-399 belongs to this system; the 2xx CTs are the old ones, made by hand or by
  `deploy-game.ps1`, and stay where they are. The Proxmox VMs 100-111 do not collide. With
  `BROKER_CTID_BASE=0` the CTID goes back to being chosen separately, in the
  `BROKER_CTID_INICIO/FIM` range. **OPNsense's DHCP must not cover `.100-.199`**: the ping
  check cannot catch a device that has yet to arrive.
- **Game suggestions (the "Add game" form)** come from LinuxGSM (MIT), converted by
  `python tools/import-linuxgsm.py` and committed in
  `src/gamepanel/games/catalog/suggestions.py` (110 games): the panel in production does
  NOT go to the internet (the official Steam store API does not even help: a dedicated
  server is a "Tool" type app and returns `success:false`). Converter rules, each with a
  test in `tests/gamebroker/test_import_linuxgsm.py` and
  `tests/gamebroker/test_suggestions.py`: only what `validate_dynamic` accepts comes out;
  an RCON/telnet/HTTP port goes only into the argument and NEVER into NAT; a
  password/name/IP/token variable is never resolved (the argument is dropped, with a
  warning); everything after `; | & \` `$(` is cut; an empty variable drops the option
  with it (otherwise it swallows the next one). **Three sources besides `_default.cfg`**,
  and without them the converter does not error, it just comes out poorer
  (`test_suggestions.py` flags it): LinuxGSM's info_game.sh says in which KEY of the
  game's config the port lives for the ~30 that do not have it in `_default.cfg`, and the
  default file from `Game-Server-Configs` gives the value (`ports_from_game_config`) -
  without that the form showed the field's EXAMPLE (7777) as if it were the port;
  info_messages.sh gives each port's protocol (Terraria is TCP only), except the Steam
  query, which is always UDP even though it lists TCP for Unreal games. A query port the
  game opens on its own (Valheim's `queryport="$((port + 1))"`) goes into the firewall and
  takes the game out of port shifting: the broker has no way to tell it. Enshrouded,
  Icarus and Dragonwilds are not in LinuxGSM: they stay manual. And search is ALWAYS a
  suggestion: the broker validates on submission.
- **Second source: Pterodactyl eggs** (`python tools/import-pterodactyl.py`, or
  `--source` with a clone of pelican-eggs/games-steamcmd). Order of who wins the same App
  ID: the page's catalog, the manual list, LinuxGSM, egg - the generator SKIPS what the
  others already have, and `test_suggestions.py` ensures no App ID crosses sources. The
  egg only COMPLETES a LinuxGSM suggestion field by field, where it is empty (config
  files; ports when LinuxGSM found none, and then as a block and without shifting), and
  the merge passes through `validate_dynamic` AT GENERATION: the panel in production does
  not have the broker package to validate at use time. Three things the egg does not say
  and the converter does NOT guess: the main port number (it is Pterodactyl's allocation;
  it comes from the "Server Ports" table in the folder's README), the protocol (no column,
  UDP with a warning) and the executable when the egg starts through `java`/`dotnet` (left
  blank with a warning). The egg's `install` is shell and is never read. A Windows server
  from an egg comes out with `proton`, even when the egg uses wine.
- **Undo cannot lie**: if the cleanup fails, the reservation becomes `falhou` (failed) and
  keeps blocking IP/CTID/ports until someone removes it (`instance_service._undo`).
- **TLS is by FINGERPRINT, never `verify=False`.** Proxmox and OPNsense are self-signed;
  `http_client.Client` only accepts the certificate whose SHA-256 is the configured one
  (`check-broker-access.ps1` prints it), and refuses `http://` outside loopback. A
  mistyped fingerprint is an ERROR, not "no pin" (it was a bug once: garbage became an
  empty string).
- **Rules the real Proxmox imposes** (`PveFalso` repeats them, so regressing breaks a
  test): a tag at creation and `keyctl` are 403 for the token; a `WARNINGS: n` task is a
  success; the tag is written AFTERWARDS. The identity of a broker CT is the **pool**, not
  the tag.
- **OPNsense keeps ports in an ALIAS.** `opnsense.busy_ports` reads the alias from the
  HTML summary of `search_rule` and **fails closed**: a WAN rule it does not understand
  => `ErroDeLeitura` and nothing new is opened. A disabled rule still occupies the port.
  `fechar` matches the `gamepanel:<ctid>` description by EQUALITY (by prefix, 30 would
  delete 300).
- **`remover` does not release the CTID/IP of a CT that may exist.** The token only sees
  the pool, and "deleted by hand" and "moved out of the pool" give the same 403; only
  `db_only` clears the record.
- **A broker job is not `start_job`.** Creating an instance takes minutes and has no SSH
  server yet: `start_broker_job` records a job WITHOUT a server and `follow_operation`
  polls the broker writing the log on each round (the regular `start_job` only writes at
  the end). At the end it registers the server through `ensure_server`; if that fails the
  job says that **the instance exists** in Proxmox. `resume_broker_jobs` reattaches the
  follow-up after a restart.
- **Everything about the broker is admin-only**, including the jobs' output
  (`JOB_ACTIONS_ADMIN`): it mentions IP, CTID and ports. The route stacks
  `@admin_required` and then `@broker_required`.
- **`broker_client` is always called through the module** (`broker_client.create(...)`):
  that is how the tests swap it for a fake. Do not do `from broker_client import create`.
- **Table on the phone: one column.** With state and actions in their own columns, the
  ACTIONS went off screen (horizontal scrolling). See `instances.html` and
  `catalog.html`. And the local server only reloads templates with `GAMEPANEL_DEV=1`:
  without it you are testing the OLD template.
- **Flask's `Exception` handler swallows 404/405** if there is no `HTTPException` one
  before it (it happened here: a wrong route became "internal error").
- **The API's WIRE format lives in `domain/wire.py`, not in the `SELECT`.** Before,
  `/v1/instancias` returned `SELECT * FROM instancias`: the name of each column was,
  without anyone having decided it, the name of each JSON field — renaming a column broke
  the panel, and renaming a field required a migration. Today there is one function per
  resource, with a FIXED field list. The value is not translating names (they even match
  now): it is a `SELECT *` not carrying the next column into the contract the day it is
  born.
- **A column that changes NAME has its own mechanism.** In the panel it is
  `schema.RENAMES` (the question for `MIGRATIONS` is "does the column exist?"; here it is
  "does it still have the old name?"); in the broker it is `_migrate_names`, which renames
  tables too. Both use `ALTER TABLE ... RENAME`, which preserves the data — new table plus
  copy is where rows get lost. Renaming a TABLE needs two more things: the migration runs
  BEFORE `CREATE TABLE IF NOT EXISTS` (otherwise it creates the new ones empty next to
  them) and the old indexes and triggers are dropped, because they carry the old name in
  their body — an append-only trigger pointing to a table that no longer exists is the
  same as not existing. A migration only runs on the database of someone who ALREADY had
  the system, and the other tests live in a new database: what exercises it is
  `tests/gamepanel/test_schema.py` and `tests/gamebroker/test_migration.py`, which build
  the old schema by hand.

---

## CT firewall (`lib/ct-firewall.sh`)

A single script, with three roles (`panel`, `broker`, `game`), installed in each CT as
`/usr/local/sbin/ct-firewall`; the CT's configuration lives in `/etc/ct-firewall.env`. It
exists because OPNsense does not see traffic INSIDE the subnet. The README has the rule
table.

- **Every deploy path calls the SAME script**: `provision-admin-lxc.sh`,
  `provision-broker-lxc.sh`, `setup_firewall` in `ct-phases.sh` (host and broker) and
  `deploy/firewall/apply-firewall.sh`. A security rule written in two places diverges.
- **Every value is checked before becoming a rule** (IPv4/CIDR/range, port 1-65535): it
  ends up inside nft text. A crooked value stops the `apply` with the old rule intact.
- **`nft -c` before writing the boot file**: a rule the kernel refuses cannot become
  `/etc/nftables.conf`, otherwise the CT boots without a firewall next time.
- **Without knowing who administers it, it does NOT apply** (a game without
  `FW_MGMT_SOURCES`, a panel without an IP): the mistake that locks the panel out of a
  server is worse than the CT staying without a firewall.
- **Applied, test; the test failed, turn it off.** The broker deploy repeats the health
  probe without the rules; the panel's tests the web from the host; `apply-firewall.sh`
  tests each CT. Everything goes through `pct`, so a wrong rule never locks the deploy out
  of the CT.
- **The game applies the firewall LAST** (`setup_firewall` after `start_game_service`):
  the earlier phases download from the internet, and a wrong egress rule would break the
  install without saying why. Through the broker, the key cleanup comes afterwards and
  needs ITS IP in `BROKER_FIREWALL_SOURCES`, which the provision writes from the CT's IP.
- **`established` does NOT hold the session that was already open before the apply.** In
  a Proxmox CT nothing asks for conntrack before the firewall, so the broker's SSH session
  (the one running the install) is not tracked; with `tcp_loose=1` the first outgoing
  packet after the apply becomes a NEW connection and falls into the internal network
  refusal. The V Rising creation froze that way, "running" forever with the end of the log
  stuck in the socket. That is why the `game` role's output accepts the REPLY of SSH and
  ping to `FW_MGMT_SOURCES` before anything else, even before `invalid drop`
  (`output_game_first`). The sandbox (WSL2 kernel) does NOT reproduce the failure - there
  conntrack already tracks the session -, and the case's comment says so; the proof was on
  the real CT.
- **The host loads `nf_tables`** (and leaves it in `/etc/modules-load.d`): an unprivileged
  CT uses nftables, but cannot load kernel modules.
- **Prove it with `bash docker/ct-sandbox/firewall.sh`** (REAL nftables, with
  `CAP_NET_ADMIN`: one container per role plus an intruder on the same LAN, testing every
  connection that must open and every one that must close). `compare.sh` proves that host
  and broker generate the same firewall, and `broker.sh` the broker's rules; both use a
  fake `nft`.

## Version and deploy — one artifact, published by symlink

The repository version is in the root `VERSION` (semver, edited by hand). What turns it
into an artifact's identity is `tools/build-release.py`:

```bash
python tools/build-release.py gamepanel    # dist/gamepanel-0.1.0+abc1234.tar.gz + .sha256
python tools/build-release.py gamebroker
```

- **`_build.py` (version, commit, date) is written INSIDE the tarball, never in the
  tree.** `git status` stays clean after packaging, and `.gitignore` guards
  `src/*/_build.py` in case it ever escapes. Without that file (running from the
  repository) the version becomes `X.Y.Z+dev`, and the `+dev` mark is what prevents
  confusing "the CT's panel is on 0.1.0" with "I am looking at my machine".
- **The tarball is deterministic**: sorted names, zeroed owner/group, the commit's mtime
  and `mtime=0` in the gzip header. Two packagings of the same commit give the SAME
  sha256 — and that is what makes the hash answer "is the CT running this code?" instead
  of just "did the file arrive whole?". **Without git the date is dropped** (empty
  `built_at`, mtime 0) on purpose: falling back to the clock there would cost the
  determinism.
- **A dirty tree comes out marked `.dirty`** in the file name and on screen. A release
  that matches no commit cannot look like one that does.
- **Modules that do not go to production are dropped via
  `SKIPPED_NAMES`/`SKIPPED_PREFIXES`** (`dev.py`, `conftest.py`, `fakes.py`,
  `fake_http.py`, `test_*`). The case that matters is `gamebroker/dev.py`: it creates
  instances against fake backends, and on a real CT it would be a way for the broker to
  lie about what exists.
- **The version shows up in three places**: the footer of every screen (`app.version`),
  `/health` (`{"status","version","commit","built_at"}`) and the service worker mark. In a
  release the worker mark IS the version; running from the repository it goes back to
  being the mtime of the static files, because only the mtime changes when a CSS is saved
  without packaging anything.

What the deploy sends is that tarball plus `lib/install-release.sh`, and the installer is
**the same** in both paths:

| path | when |
|---|---|
| `deploy/admin/deploy-admin.ps1` | direct push over SSH (packages, sends 2 files and restarts) |
| `deploy/admin/provision-admin-lxc.sh` | full provisioning through Proxmox (`pct push` of the tarball) |
| `deploy/broker/deploy-broker.ps1` + `provision-broker-lxc.sh` | the broker (its own CT); see the "Broker" section |

**`$ScriptDir` is no longer the repository root.** At the root the two coincided by
accident, and the `.ps1` files used `$ScriptDir` both to find the sibling
`provision-*.sh` and to find `tools/`, `lib/`, `games/` and the `.env`. Inside
`deploy/<grupo>/` they are two things: `$ScriptDir` is the script's folder, `$RepoRoot`
(two levels up) is the repository. A new path in a deploy `.ps1` picks one of the two on
purpose.

```
/opt/gamepanel/releases/0.1.0+abc1234/gamepanel/...
/opt/gamepanel/current -> releases/0.1.0+abc1234     # the unit's WorkingDirectory
```

- **A release is a NEW FOLDER, never a copy on top.** Before, each path had its own
  hand-written list of which subfolders to delete before copying (`templates/ games/
  security/ integrations/`), and both fell behind with every new folder in the package —
  `blueprints/`, `i18n/`, `persistence/`, `runtime/`, `services/` and `tasks/` never got
  in. Result: a renamed module stayed alive in the container, importable, without anyone
  seeing it. With one folder per version there is nothing to leave behind. **Do not bring
  the list back.**
- **Going back a version = moving the symlink.** `install-release.sh` keeps 5 releases,
  and rolls back on its own when the service does not start or the health probe does not
  answer.
- **The symlink swap is `ln -sfn` alongside + `mv -T`**, never `ln -sfn` directly: on a
  symlink that already exists, `ln` creates the link INSIDE the folder it points to.
  `mv -T` is atomic.
- **The deploy confirms through `/health`**, not through `systemctl is-active`: "the
  service is up" is compatible with "systemd restarted the old version", and both show
  green.
- **The tarball goes through `Copy-Item`/`pct push`, never through `Copy-AsLf`/`tee`.**
  The line-ending normalizer decodes as UTF-8 and corrupts binaries (that is how the PWA
  icons arrived broken). `Copy-AsLf` today only sees `.sh`.
- **Touched `install-release.sh` or the packager? Run
  `bash docker/ct-sandbox/release.sh`** (21 checks: wrong sha, version folder, symlink
  flip, removal of the old layout, rollback) and `bash docker/ct-sandbox/broker.sh`.
  There are no shell tests in the repository; the proof is the sandbox.

**`ADMIN_HOST` from `.env` beats `ADMIN_IP_CIDR`** in the direct-push shortcut of
`deploy-admin.ps1` (without `-Full`): when moving the panel to another CT/IP, change BOTH,
otherwise the deploy lands on the old CT and publishes there (that is how the old public
panel received new code without anyone asking). `-Full` follows `ADMIN_CTID`. The broker
deploy also derives the allowed IP from `ADMIN_HOST`.

The broker's `lib/` and `games/` keep traveling loose: they are not the Python package,
but install scripts and the curated catalog, read from an absolute path. Provisioning
replaces both as a whole.

### PowerShell (`.ps1`)

Rules that have already cost dearly here:

- **Pure ASCII.** PowerShell 5.1 reads a `.ps1` without a BOM as ANSI; an em dash breaks
  the parse with a misleading error. Check: `[IO.File]::ReadAllBytes($p) | ? { $_ -gt 127 }`.
- **Variables have no case**: `$x` and `$X` are the same. A local with the name of a
  `[switch]` parameter breaks at runtime.
- **stderr of an executable** (docker, ssh) needs a wrapper with a relaxed
  `ErrorActionPreference`, otherwise the script dies on top of a success.
- **A here-string that goes over ssh** carries the `\r` from CRLF and breaks bash on the
  other side — normalize in `Invoke-Ssh`.
- **`Copy-AsLf` (ReadAllText + normalizes line endings) is only for text.** Applied to a
  `.png` it decodes the file as UTF-8: every byte outside the ASCII plane becomes the
  replacement character (U+FFFD), and the PNG signature (`89 50 4E 47 0D 0A 1A 0A`)
  reaches the server as `EF BF BD 50 4E 47 0A 1A 0A` — a corrupted file, and Chrome
  refuses the PWA icon (`no-acceptable-icon`) without a warning anywhere in the deploy.
  That is what happened: the loop that builds the bundle in `deploy-admin.ps1` passed
  every file in `admin/` through `Copy-AsLf`, except `__pycache__`. The fix is a list of
  text extensions (`Copy-ArquivoDoAdmin`) — anything outside it goes through `Copy-Item`
  (a byte copy, decoding nothing). A new binary extension in `static/` (font, image)
  **goes in as binary by default** — it only becomes text if you add the extension to the
  list.

---

## Writing: comments, messages and screen text

Code here is commented **in English** — in every language of the repository. The reason
is the same as for identifiers: the repository is public, and a comment is the part of
the code that exists to be read by the next person; in a language they cannot read, it
explains nothing, and the trap it was guarding against gets "simplified" right back in.
Mixing languages also makes code search unreliable: the explanation you are looking for
is under a word you did not think to grep for. The whole repository was translated in one
pass before going public; a Portuguese comment that turns up now is a leftover and is
translated by hand, never by a word-replacing script (see "Renaming bash and PowerShell").
The exceptions are deliberate: script OUTPUT that the sandboxes grep for, and the
`; Gerado pelo painel` mark that the mod installers match to know which files are theirs.

The standard is not to describe what the line does — it is **why it is that way**,
preferably with the consequence of doing it differently:

```python
# A hidden tab does not spend an ssh connection for nothing; when it comes back, it fetches right away.
```

```css
/* A 16px base is not an aesthetic choice: below that, iPhone Safari zooms in on its
   own when a field gets focus, and the whole screen shifts. */
```

A comment that only repeats the function name is noise. A comment that explains the trap
you just avoided is what stops the next person (or you, three months from now) from
"simplifying" it back into the bug.

Screen text lives in the i18n catalog, in Portuguese and English with the same keys:
plain, direct language, without infrastructure jargon where possible, and the Portuguese
side with its accents. "O servidor será PARADO" / "The server will be STOPPED" is better
than "o serviço será interrompido" / "the service will be interrupted".
