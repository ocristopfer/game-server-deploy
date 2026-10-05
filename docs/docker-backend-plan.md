# Plan: Docker instances in the broker, and the Proxmox leak

> **Status:** partially executed. Phase 1 items 1.1-1.4 (the `handle`/`backend` rename in
> data and contract) are done; 1.5-1.7 and Phases 2-3 (the Docker backend itself) have not
> started, and remain blocked on Phase 0 - a first real end-to-end creation against
> Proxmox/OPNsense, which has not happened yet.

> Written after reading all of `src/gamebroker/` (~2.9k lines) and the
> `src/gamepanel/runtime/` layer. Nothing was moved or edited to produce this document.
> It exists to be approved before anyone touches a file.
>
> Companion to [`architecture-analysis.md`](architecture-analysis.md) and
> [`architecture-proposal.md`](architecture-proposal.md), which describe the folder
> reorganization (Phases 1-4). This one is about **what the broker creates**, not about where
> the code lives.

---

## 0. The decision, before the plan

The question that started this was "do I support every mode (Proxmox, Docker, Kubernetes)
or migrate to just one?". The answer is **neither**:

- **Not "support every mode"**: there has not yet been ONE real end-to-end creation against
  the real Proxmox/OPNsense. An abstraction designed before the first real run
  encodes a guess - and the guess then has to be fixed in three implementations
  instead of one. Three untested backends are worse than one tested, especially in a
  system where the panel has root inside the containers.
- **Not "migrate to K8s"**: K8s sells scheduling across nodes. There is **one** Proxmox host and
  **one** OPNsense. On a single host the operating cost is high and networking gets worse: the
  invariant "internal port == external port, always" (correct - the game announces its own port
  in the Steam list) fights with NodePort, which lives in 30000-32767, right on top of the broker's
  31000-31999 range.

What this plan does: **keeps Proxmox as the only backend in production, takes its
vocabulary out of the places where it is expensive to change later, and adds Docker as the
SECOND backend** - because two backends is the number that proves an abstraction. One is a guess,
three is a tax.

### What "scale" means here

It is worth recording what does NOT limit scale today, so Docker is not sold as the cure for
what it does not cure:

| current limit | where |
|---|---|
| 8 instances, 4 creations/hour | `instance_service.Config` |
| one operation at a time, global | `db.Db.operation_in_progress` |
| 1 gunicorn worker (the IP lockout lives in memory) | `provision-broker-lxc.sh` |
| ~1000 ports in the range, 1 WAN IP | `BROKER_PORT_INICIO/FIM` |
| full disk per instance (the whole SteamCMD) | each game's `disk_gb` |

Switching backend does not touch the first four. It touches the fifth - and that is where the
**only good technical argument** for Docker lives: shared layers, creation in
seconds instead of a full SteamCMD, no OS per instance.

---

## 1. Phase 0 (blocker): the real creation on Proxmox

**Nothing in this plan starts before this.** It is the item already listed as "what is left"
in `architecture-proposal.md`. Reason: the first real creation is what decides whether the
compute backend needs one more verb, whether the installer needs a retry, whether the
health probe needs a different timeout. Finding that out with two backends written costs
double.

If the real creation reveals something that changes the shape of the interfaces, **this document is
updated before Phase 1 continues**.

---

## 2. Which Docker: "small machine" or "idiomatic container"

There are two possible designs, and the difference between them is the difference between a plan
of days and one of months.

### Model A - container as a small machine (RECOMMENDED)

The container runs `sshd` and has a real `systemctl` (or the shim), the game is a unit,
and each instance gets a LAN IP (`macvlan` network or a bridge with a fixed IP).

From the panel's point of view, **it is indistinguishable from a CT**:

- the panel's command table (`systemctl start/restart/stop`) still holds;
- `status_service` (`systemctl show`), `metrics_probe` (the `MainPID`), `log_probe`,
  `backups`, `files` and `terminal` still hold;
- the `servers` table (`host`, `ssh_port`, `ssh_user`, `service`) still holds;
- internal port == external port still holds, and the OPNsense NAT keeps pointing
  at a LAN IP.

This is not theory: `ssh.py` already opens by saying it talks to the game container "(LXC or
Docker)", and the development `docker compose` already starts two game containers with
sshd and a fake `systemctl`. **The panel does not change at all** - zero of the 964 tests at risk.

Where the scale gain is: installation (`ct-phases.sh`) stops being a
post-creation step over SSH and becomes the **build of one image per game**. Palworld is installed
once; the tenth instance is born in seconds and shares the layers on disk.

### Model B - idiomatic container

One image per game with PID 1 = the game, no sshd, no systemd, logs via `docker logs`,
shell via `docker exec`, files via a volume.

More "correct" in spirit, and it is the mandatory step if it is ever K8s. But it charges the
full price: the eight probes in `gamepanel/runtime/` need a second
**transport**, and the command table needs to stop being a list of
`systemctl` lines. That means rewriting the 964-test side of the repository, not the 901 side.

### Decision

**Model A now. Model B stays recorded as a future decision**, conditioned on
"I need more than one host" - and on that day step 1 is the panel transport, not the
broker backend.

Important consequence: **with Model A, IP allocation, port allocation and
OPNsense do not change at all.** The Docker backend only needs to: create, start, stop,
destroy, say whether a container is its own, and say what is already taken.

---

## 3. Phase 1 - taking Proxmox out of the vocabulary (broker only)

> **Status: 1.1 to 1.4 done; 1.5 to 1.7 postponed, on purpose.** The cut was not out of
> fatigue: 1.1-1.4 change **data and contract**, which is what becomes expensive once there is an
> instance in production. 1.5, 1.6 and 1.7 design an interface for a backend that does not yet
> exist - and section 0 of this document says, rightly, that an abstraction before the first
> real creation encodes a guess. `propose_handle`/`taken_handles` with a single implementation would
> hide that the service still knows about `ctid_base`; `BROKER_BACKEND` would be a
> variable with one valid value.
>
> **Two things the plan did not anticipate and the execution found:**
>
> 1. **`ALTER TABLE ... RENAME COLUMN` preserves the AFFINITY.** The column stays declared
>    `INTEGER`, so in a migrated database the old CTID comes back from `SELECT` as an `int`, and a
>    `CAST(... AS TEXT)` does not help - the affinity converts it back on write (checked
>    in this machine's sqlite3). A non-numeric handle, like `palworld-1`, goes in as text
>    normally: the affinity only converts what *looks* like a number. Without handling this the
>    column has a mixed type and `{"307"} | {307}` does not deduplicate - the taken-handle check
>    would pass when it should not. Rebuilding the table would fix the declaration but is expensive
>    (`ports` has `ON DELETE CASCADE` to `instances`), so the way out is to normalize on
>    read, with `str()`, in `db.taken` and `wire.instance`. There is a test for both sides.
> 2. **The `int(ctid)` in `instance_description` was a guard.** It was what rejected
>    `"300; drop"`, and with the opaque handle it would have gone away too - the description test caught it.
>    The description goes into the rule's `descr` field and `close_ports` matches it by EQUALITY:
>    a weird handle would not become shell injection, but it would break the matching and leave an
>    **orphan rule in the firewall**, which is the silent way for a port to stay open for a
>    container that no longer exists. Today there is `HANDLE_RE` (a simple token, `re.ASCII`).
>
> Proven against the toy broker in the compose setup, live: an instance created with the
> old schema (`ctid=302`, INTEGER) survives the migration and comes back over the wire as
> `handle: "302"` **str**, next to a new `"303"`; and the screen shows `proxmox 303` in
> place of the old `CT 300`.

The port layer already exists and is clean: `base.py` defines four Protocols and
`instance_service.py` knows nothing else. The problem is not the interface, it is the
**noun**: `ctid` went through the service, the database and the API contract.

Each item below is expensive later and cheap today (zero instances in production).

### 1.1 `base.py` - the interface names

| today | becomes | why |
|---|---|---|
| `Proxmox` | `Compute` | the Protocol describes "where the instance runs", not a product |
| `Opnsense` | `Ingress` | same: "who opens the port to the internet" |
| `CtSpec` | `InstanceSpec` | CT is LXC; Docker has no CT |
| the `ctid: int` field | the `handle: str` field | opaque: `"307"` on Proxmox, the container name on Docker |
| `Installer` | (see 1.6) | it is the only one that does not generalize |

`Network` stays as it is.

### 1.2 The `handle` goes up through the whole service

`instance_service` today writes `inst["ctid"]` in eight places (create, undo,
deactivate, remove, the ownership check and the destruction). All of them become `handle`.

The open/close ports signature changes along with it - and with it the rule description in
OPNsense, which today is `gamepanel:<ctid>` and becomes `gamepanel:<handle>`.

> **Trap**: `opnsense.close_ports` matches the description by **equality** (on
> purpose - by prefix, deleting 30 would take 300 with it). Changing the description
> format **orphans any rule already created**. With zero instances that is free;
> with ten, it is a manual cleanup in OPNsense. One more reason to do it now.

### 1.3 Database: `handle` and `backend`

In `db.py`:

```sql
ctid INTEGER NOT NULL UNIQUE   -->   handle  TEXT NOT NULL UNIQUE
                                     backend TEXT NOT NULL DEFAULT 'proxmox'
```

It needs a migration in the same spirit as the existing `_migrate_names` (its question
is "does the table still have the old name?"; the new one is "does the `ctid` column still exist?").
SQLite does `ALTER TABLE ... RENAME COLUMN`, which preserves the data - a new table plus
copy is where rows get lost.

`backend` has a default so that the database of whoever was already running stays valid without
guesswork.

Test: `test_migration.py` builds the old schema by hand; it gets a new case. The other
tests live in a fresh database and exercise no migration at all.

### 1.4 `wire.py` - the contract with the panel

The instance wire format starts carrying `handle` and `backend` **instead of** `ctid`.

The panel reads `ctid` in **one** place only: `instances.html`, in the line that shows
`{{ i.game }} · {{ i.ip }} · CT {{ i.ctid }}`. That is why the switch can be clean instead of
having a compatibility period with both fields - and a compatibility field that
nobody removes is how a `SELECT *` comes back through the back door.

> This is exactly what the wire layer was created for: the format changes together with the
> panel, the database schema changes with a migration, and neither drags the other.

### 1.5 `allocator.py` - the "CTID = 300 + octet" rule belongs to Proxmox

`allocator.pick_ip_and_ctid` encodes a great and **Proxmox-specific** convention:
read the IP and know the CTID by heart. On Docker there is no number to derive.

Proposal: the allocator stays pure and gains the generic form; the one that decides the handle is the
backend, through two new verbs in the compute Protocol:

```
propose_handle(ip)  ->  str     # proxmox: str(ctid_base + octet); docker: the hostname
taken_handles()     ->  set     # replaces the "ctids" half of what is today ctids_and_ips
```

`pick_ip_and_ctid` becomes a generic address choice - same logic ("an IP is only usable
if its handle is also free"), without the CTID arithmetic inside. The arithmetic
lives in `proxmox.py`, which is where it belongs.

`BROKER_CTID_BASE` / `BROKER_CTID_INICIO` / `BROKER_CTID_FIM` keep those names:
an environment variable is **data written to disk**, and renaming requires touching
`deploy-broker.ps1`, `provision-broker-lxc.sh` and the `broker.env` of whoever already
deployed. They start being read only by the Proxmox backend.

### 1.6 The installer is the Protocol that does not generalize

The `Installer` receives an IP and speaks SSH, because the model is "bring up an empty CT and install
inside". In Docker Model A **there is no installation step at runtime** - the image
already is the installed game.

Proposal: it stops being a parameter of the service and becomes a detail of whoever
implements compute. Whoever materializes the instance is whoever knows how the game gets there:

- the Proxmox backend receives the SSH installer in its constructor and calls it inside
  `create`;
- the Docker backend receives nothing: the image already brings everything.

The service's `_build` gets one step fewer (create -> start -> open firewall), and the
progress `log` becomes an argument of `create`, so the screen keeps showing which
phase the installation is in.

> Alternative considered and discarded: keep the Protocol and give Docker a no-op.
> Discarded because a no-op is a cheap lie that survives for years - and because the
> phase log would be empty on Docker without anyone understanding why.

### 1.7 `config.py` - choosing the backend

A new variable, `BROKER_BACKEND` (`proxmox` | `docker`, default `proxmox`), read with the
design that already exists: **list ALL problems at once, only by the variable NAME**,
never the value, and bad config brings down the START (`SystemExit(2)`), never a
request.

Each backend requires its own set of variables. Validation has to be
**conditional on the chosen backend** - demanding the Proxmox URL from someone who chose Docker
would turn the error message into noise, which is exactly what that design exists
to avoid.

---

## 4. Phase 2 - the Docker backend

New file: `src/gamebroker/runtime/docker.py`, implementing the compute Protocol.

### 4.1 How it talks to Docker

**Over HTTP, reusing `http_client.Client`** - not through the CLI and not through the PyPI
`docker` library (the broker in production also does not download packages from anywhere; the
"stdlib only + apt's flask" rule applies to both packages).

The Docker API speaks HTTP over a unix socket. The client today is HTTPS with a pinned
fingerprint; it would gain a "unix socket" mode - and then the security lock stops being the
certificate fingerprint and becomes **the socket permission**, which is a different
thing and needs to be written in the code.

> **Security decision to make BEFORE writing the file.** Access to the Docker
> socket is equivalent to root on the host. Today the broker talks to a REMOTE Proxmox with a
> pool-scoped token - the blast radius is limited by what the token can see. With the local
> socket there is no scope at all: a defect in the broker becomes root on the whole host, and the host is
> where the broker itself lives.
>
> Options, in order of preference:
> 1. **Docker on a separate host**, over TCP with TLS and a pinned fingerprint - which is exactly
>    what `http_client` already knows how to do, and keeps the symmetry with Proxmox.
> 2. A socket proxy with a closed list of endpoints.
> 3. Direct socket (only acceptable in development).

### 4.2 What each verb does

| verb | Docker |
|---|---|
| `create` | `POST /containers/create`: game image, macvlan network with a fixed IP, memory/cpu limits, `restart=unless-stopped` |
| `start` / `stop` / `destroy` | `POST /containers/{id}/start`, `/stop`, `DELETE /containers/{id}` |
| `belongs_to_broker` | **label** `gamebroker=1` - the equivalent of the Proxmox pool |
| `taken_handles` / taken addresses | `GET /containers/json?all=1` |
| `propose_handle` | the instance hostname (`<game>-<n>`), already unique by the database index |
| `reachable` | `GET /_ping`, with a short timeout |

> **Inherited trap**: the identity of a broker CT is the **pool**, not the tag (the tag is
> written later; the token cannot even write it at creation). On Docker the label can be
> applied at creation, so the identity is the label - but it is written by whoever creates it, and
> a container made by hand with the same label would be adopted. Docker's
> `belongs_to_broker` must require **label AND a database row**, which is what Proxmox already does in practice.

A short health probe timeout applies here too: a firewall that drops packets cannot
make health take 30 s.

### 4.3 The game image

`ct-phases.sh` gets a **third consumer**. Today there are two: `provision-game-lxc.sh`
(on the host, via `pct exec`) and `ct-install.sh` (inside the CT, what the broker runs over SSH).
The third is a `Dockerfile` that runs the same phases in a `RUN`.

Rules that still apply and need attention:

- `install.env` is always `shlex.quote`; an unknown recipe brings down the installation;
- hooks (`PRE/POST_INSTALL_CMD`) only exist in the curated catalog, never in a game from the API;
- writing text for bash on Windows requires `newline="\n"` (the `\r` shows up later as
  `WINDOWS_RUNTIME invalido: ''`).

**The broker's SSH key does not go into the image.** In the CT it is removed at the end (the cleanup
always runs, and if the key does not come out the creation FAILS); in an image it would stay in a layer,
visible through `docker history` forever. The panel's access uses the PANEL's key,
injected at container creation (`authorized_keys` via volume or variable), never baked
into the image.

### 4.4 Proof

`docker/ct-sandbox/compare.sh` today compares the installer "before vs after" for 8 games
with fake `pct`, `systemctl`, `apt-get` and SteamCMD. It gains a third axis: **host vs
broker vs Docker image** - the three routes have to produce the same `install.env` and the same
systemd unit. Without that Phase 2 is done in the dark: **there are no shell tests in the
repository**, the proof is the sandboxes.

On the Python side: `fakes.py` gains a Docker double (next to `FakeProxmox`,
`FakeOpnsense`, `FakeInstaller` and `FakeNetwork`), and `fake_http.py` gains a fake
server that answers the Docker API - with the same design as the Proxmox fake, **repeating the
rules the real Docker imposes**, so that regressing breaks a test.

---

## 5. Phase 3 - the panel side

Small, and only after Phase 1 is on `main`.

- `instances.html`: `CT {{ i.ctid }}` becomes the backend + handle pair. Remember the
  mobile table rule: **one column** - with state and actions in their own columns, the actions
  go off screen.
- `i18n/pt.py` and `i18n/en.py`: a new key for the backend label, **the same keys in
  both** (`test_i18n.py` enforces parity). A key in English, in the `area.subject` format,
  never the Portuguese text turned into a slug.
- `broker_service.py`: pass the new fields through. Nothing beyond that - the broker is the one
  that decides.
- The `servers` table **does not change**. That is the whole point of Model A.

---

## 6. What needs to pass before saying it is done

1. `uv run pytest` - the whole suite, from the root (964 from the panel + 901 from the broker).
2. `MSYS_NO_PATHCONV=1 docker compose exec -T -w /workspace panel python3 -m pytest -q`
   - in the container, which is the truth.
3. `bash docker/ct-sandbox/compare.sh` - mandatory, because Phase 2 touches an installation
   phase.
4. `bash docker/ct-sandbox/broker.sh` - if `config.py` or the provisioning change.
5. The `curl` sweep through every screen, as admin **and as operator** - a broken
   template does not show up in any test, and the operator's 403 lives there.
6. One real creation per backend, end to end. A backend that never created anything for real
   is not ready, however green the suite is.

---

## 7. Explicitly out of scope

- **Kubernetes.** Back on the table when there is more than one host. The step before it is
  Model B (non-SSH transport in the panel), not this plan.
- **Docker Model B** (PID 1 = game, no sshd). Recorded in section 2, with the reason.
- **The scale limits from section 0** (one operation at a time, 1 worker, port range).
  They are real, but independent of the backend and deserve their own decision.
- **Migrating existing instances between backends.** A CT does not become a container; it is
  creating again and restoring a backup.

---

## 8. Coordination

Another work stream is working on Phase 4 (`src/gamepanel/games/` - the field catalog
becoming `adapters/` + `registry.py`). The areas barely cross: this plan is
`src/gamebroker/**` plus three panel files, and only in Phase 3.

The two meeting points:

- **`src/gamepanel/app.py`** - both fronts touch it, for different reasons. Rebase,
  not a blind merge.
- **`i18n/pt.py` / `en.py`** - both add keys. An append conflict is easy,
  as long as parity between the two catalogs holds.

That is why Phase 1 and Phase 2 are **broker only** and can land on their own; Phase 3 (the
only one that touches the panel) waits until Phase 4 lands.
