# Security hardening: no more root inside the game containers

Status: **phases 1-8 implemented** (see the table at the end and
[security-hardening-contract.md](security-hardening-contract.md)). Phase 8 ran on a real Proxmox:
four existing game CTs were migrated with `deploy/game/migrate-ct.ps1 -Ctid <CT>` and root SSH
is refused on them. Phase 6 (mod loaders without root) is proven in the sandbox (real Debian 13
sudo) and in the dev compose (UE4SS Linux install/uninstall on the helper-mode fake Palworld),
and still needs one real CT per loader. Phases 9 and 10 still need a real CT to be validated. Root stays only where it is unavoidable: provisioning a container
(`pct exec` on the host, or the broker's one-time install).

## Goal

- The panel logs in to game CTs (and Docker game containers) as a dedicated user,
  `gamepanel`, never as `root`.
- The game and SteamCMD keep running as `steam`, which gets **no** sudo at all.
- `gamepanel` can do exactly two kinds of things: act as `steam` (files, backups, mods,
  console) and run a handful of fixed root helpers with no free-form arguments.
- `ssh root@<ct>` is refused once a container is migrated.

## Why this matters more than "least privilege"

Today the panel works inside the game folders **as root**, and those folders are writable by
`steam`. That is already a path from a compromised game to root:

- the file editor writes with `cat > "$f"`, which follows a symlink the game planted;
- upload/write use `cp -a` and `chown --reference`, which touch whatever the path points to;
- restore runs `tar -xzf -C /` as root through directories the game controls;
- the mod installers (`games/mods/*_remote.py`) download archives from the internet and
  extract them as root, calling `open`/`chown` in those folders.

A game exploited over the network can plant a symlink and wait for an admin to save a config
file or restore a backup.

## Inventory: what needs root today

How the panel connects: `runtime/ssh.py` builds `ssh_user@host`; the per-server user already
exists (`servers.ssh_user`) but defaults to `root` everywhere (schema, `app.py`,
`blueprints/servers.py`, `services/server_service.py`, `cli.py`, the server form). The panel
key is written to root's `authorized_keys` by `lib/ct-phases.sh` (`setup_panel_access`), by the
broker through Proxmox `ssh-public-keys` (`gamebroker/config.py`, `runtime/proxmox.py`) and by
both Docker entrypoints.

| Feature | Where | Needs root? |
|---|---|---|
| start / stop / restart | `app.COMMANDS` (`systemctl`) | yes (fixed helper) |
| update / check update | `/usr/local/bin/update-game`, `check-game-update` | yes, no arguments |
| status | `services/status_service.py` (`systemctl show`) | no |
| logs | `runtime/log_probe.py` (`journalctl -u`) | no: group `systemd-journal` |
| metrics | `runtime/metrics_probe.py` (`/proc`, cgroup) | no: world-readable |
| port discovery | `runtime/port_probe.py` (`/proc/<pid>/fd`) | only to map other users' sockets; as `steam` it still maps the game's |
| player presence | `runtime/presence_probe.py` (`nft -j list set ...`) | yes: one exact sudo line |
| file manager | `runtime/files.py` | no: run as `steam` |
| backups / restore | `runtime/backups.py` | only the service stop/start |
| mod installers | `blueprints/mods.py` + `games/mods/*_remote.py` | only systemd drop-ins and `/etc/game-runtime.env` edits |
| antivirus | `games/mods/antivirus.py` | only the ClamAV install |
| console / terminal | `blueprints/console.py`, `runtime/terminal.py` | root by design today |

The installers (`lib/ct-install.sh`, `lib/ct-phases.sh`, `gamebroker/runtime/ssh_installer.py`,
`deploy/game/provision-game-lxc.sh`, `lib/ct-firewall.sh`) run once at provisioning and stay
root.

Already unprivileged: the game (`User=steam` in the unit; `setpriv` in Docker), SteamCMD, and
the panel and broker services themselves (own system users, systemd sandboxing).

## Design (option A, recommended)

**Users.** `gamepanel`: system user, home `/var/lib/gamepanel-agent` (0700), member of
`systemd-journal`, **not** in group `steam`. `steam`: no sudo, so a compromised game cannot
escalate.

**`/etc/sudoers.d/gamepanel`** (0440, checked with `visudo -cf`):

```
Defaults:gamepanel !requiretty, !use_pty, env_reset, !log_output
Cmnd_Alias GP_ROOT = /usr/local/sbin/gp-service start, /usr/local/sbin/gp-service stop, \
  /usr/local/sbin/gp-service restart, /usr/local/bin/update-game, /usr/local/bin/check-game-update, \
  /usr/sbin/nft -j list set inet ct_firewall players, /usr/local/sbin/gp-clamav-ensure
gamepanel ALL=(root)  NOPASSWD: GP_ROOT
gamepanel ALL=(steam) NOPASSWD: ALL
```

- Exact arguments, no wildcards. `gp-service` takes **no unit name**: it reads `GAME_UNIT` from
  the root-owned `/etc/gamepanel/ct.env`, so `gp-service stop ssh` is impossible.
- `gp-clamav-ensure` (apt + freshclam, no arguments) keeps the "ClamAV only arrives with the
  first mod" behavior.
- `!use_pty` must be verified on Debian 13: uploads and backups stream binary data on stdin,
  and a pty would mangle it.

**Content operations run as `steam`** (`sudo -n -u steam -- bash -c SCRIPT ...`): files, config
editing, backup creation and listing, mod installers, the antivirus scan, port discovery, and
the console/terminal (`sudo -u steam -i`). Files end up owned by their real owner, every
`chown --reference`/`os.chown` becomes a no-op and the symlink attacks lose their target. This
is better than group write: SteamCMD and the games create files with umask 022, so `g+w` would
need setgid directories plus ACLs and would still leave root-written files around.

**Mod environment without root (phase 6, implemented).** `lib/ct-panel-access.sh install`
adds, once, a drop-in `gamepanel-env.conf` with `EnvironmentFile=-/etc/gamepanel/game-env/service.env`,
and `win-run` sources `/etc/gamepanel/game-env/runtime.env` after `/etc/game-runtime.env`. The
installers, run as steam with `--overlay`, write `LD_PRELOAD`, `DOORSTOP_*`, `UE4SS_TARGET_EXE`
(service.env) and `WINE_DLL_OVERRIDES` (runtime.env) there; removing a line restores the
original. They only affect a process that already runs as `steam` (no escalation), and
`EnvironmentFile` needs no `daemon-reload`: the restart step of the same job applies it. No new
sudo rule, no `gp-modenv`.

Refinements over the first idea, each found while building it:

- **The files are steam's, the folder is root's** (`/etc/gamepanel/game-env`, 0755 root; files
  0644 steam), not `/home/steam/.config/gamepanel/`. systemd reads an `EnvironmentFile` as ROOT;
  in a folder steam controls, steam could replace the file by a symlink to any root-only file
  and read its `KEY=value` lines back from `/proc/self/environ` of the game. In a root folder
  steam edits the content but can neither replace, delete nor create the files.
- **win-run sources runtime.env only when the file belongs to the user running it**, so root
  never sources a steam-writable file (nothing runs win-run as root today; this keeps it true).
- **ARK's `-mods=`** cannot come from an `EnvironmentFile` (ExecStart is not an environment
  variable) and an `ExecStart=` drop-in needs root. ARK starts through win-run (an .exe under
  Proton), so win-run appends `GAMEPANEL_EXTRA_ARGS` from runtime.env to the game's arguments -
  the same place the root drop-in put `-mods=`. An ARK unit that does not go through win-run is
  refused in helper mode (`no_win_run`).
- **Existing win-run files are patched, not rewritten**: the hook is inserted after
  `exe="$1"; shift`; rewriting would also bring every other win-run change (ntsync, xvfb) to a
  live server during a migration. New CTs get the same lines from `lib/ct-phases.sh` (a test
  compares both texts; the sandbox compares a patched win-run with a new one byte by byte).

**Restore.** `sudo gp-service stop`, extract as `steam` with `--no-same-owner
--no-same-permissions` after checking every member (no absolute paths, no `..`, inside the
server's backup paths), then `sudo gp-service start`. `BACKUP_DIR` becomes `steam:steam` 0750.

**What changes for the user:** the console and terminal become a `steam` shell (root
break-glass is `pct enter <CTID>` on the host); backup paths `steam` cannot read (under `/etc`)
fail with a clear error; port discovery shows root-owned sockets without an owner;
`GAMEPANEL_FILE_ROOTS` defaults to `/opt/game:/home/steam` for servers in this mode.

**New cost: helper version drift.** The root helpers live inside each container, so updating the
panel does not update them. Keep them tiny, give them `--version`, make the panel warn when they
are outdated, and update them with a host-side `deploy/game/update-ct-helpers.sh` (`pct exec`
over the pool).

### SSH hardening (every container)

`/etc/ssh/sshd_config.d/10-gamepanel.conf`:

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers gamepanel
```

The panel key gets options: `from="<panel IP>",no-agent-forwarding,no-port-forwarding,no-X11-forwarding`.

### New containers (broker and deploy script)

- Proxmox injects **only the broker key** into root (drop the panel key in `gamebroker/config.py`).
- `setup_panel_access` creates `gamepanel`, installs `sudo` (missing from the Debian 13 template
  and from `debian:13-slim`), the sudoers file and the helpers, and writes the panel key to
  `~gamepanel/.ssh/authorized_keys`.
- `ssh_installer._cleanup` removes the broker key **and** writes the sshd drop-in and reloads ssh
  in the same command.
- Broker-created servers are registered with `ssh_user='gamepanel'`.

### Docker

`docker/gameserver` and `docker/game` add `sudo`, the user, the sudoers file and `gp-service`
(which calls the fake `systemctl` in dev), stop writing `/root/.ssh` and set
`PermitRootLogin no`.

### Panel code

One function, `privileged(server)`: `ssh_user == "root"` is legacy mode, anything else is helper
mode. No schema migration. All wrapping lives in one command-builder module (for example
`runtime/remote_cmd.py`) used by `COMMANDS`, backups, files, mods and the probes; each caller
states its intent (`as_steam(...)`, `as_root("gp-service", "stop")`) instead of a raw prefix.

### Migrating existing servers

Implemented as `deploy/game/migrate-ct.ps1 -Ctid <CT> [-Service x] [-NoLock]`, which runs
`deploy/game/migrate-ct.sh` on the Proxmox host (everything through `pct`) and reuses
`lib/ct-panel-access.sh`. The steps:

1. install `sudo`, create `gamepanel`, write `/etc/gamepanel/ct.env`, install helpers and
   sudoers, copy the panel key;
2. convert the existing mod drop-ins and `WINE_DLL_OVERRIDES` line into the `steam` overlay
   (done by `ct-panel-access.sh install`, so rerunning the migration on an already migrated CT
   converts a CT migrated before phase 6);
3. `chown -R steam:steam` the backup folder;
4. the panel checks `ssh gamepanel@ct sudo -n /usr/local/sbin/gp-service --version` and
   `sudo -n -u steam true`;
5. only if step 4 passes: a second root call removes the panel key from root, writes the sshd
   drop-in and reloads ssh; the panel then switches `servers.ssh_user`.

If step 4 fails nothing has been locked and the server stays in legacy mode.

## Alternatives considered

- **polkit** rule for the game unit: removes sudo for start/stop only; needs `polkitd` in every
  CT, does not exist in Docker, does not cover nft/update/ClamAV.
- **systemd user units**: change cgroup and journal paths and the metrics code. Too invasive.
- **Root forced command** (`command="gp-dispatch",restrict` + `PermitRootLogin
  forced-commands-only`): no sudo package, but root login stays open and a dispatcher bug is
  root. Rejected.

## Other hardening, by priority

1. **High** - restore extracts as root to `/`: add the member check and run it as `steam`, even
   before the rest.
2. **High** - `GAMEPANEL_FILE_ROOTS` defaults to `/`: narrow it.
3. **High** - mod installers download and extract as root: run them as `steam`.
4. **High** - the panel key goes into root of every broker-created container.
5. **Medium** - sandbox the game unit with an opt-in drop-in, tested per game:
   `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectKernelTunables/Modules/
   ControlGroups`, `RestrictSUIDSGID`, `LockPersonality`, `ProtectClock`. **Never
   `MemoryDenyWriteExecute`** (breaks Wine, Proton, Mono, BepInEx, UE4SS). No `ProtectHome`
   (the Wine prefix lives in `/home/steam`). Must be validated on a real unprivileged LXC.
6. **Medium** - `PRE_INSTALL_CMD`/`POST_INSTALL_CMD` run as root: run the ones that do not need
   it as `steam`.
7. **Medium** - panel CT: `ProtectSystem=strict` with `ReadWritePaths=/var/lib/gamepanel`;
   restrict root SSH to the panel CT or move panel deploys to `pct exec`.
8. **Low** - optional egress rule for `steam` (`nft meta skuid`) to log/limit new outbound TCP.
9. **Low** - keep `broker.secrets.env` outside the repository folder.

## Phased plan

| # | Step | Risk | Validated by |
|---|---|---|---|
| | **Done: 1-8** (tests, `docker/ct-sandbox/panel-access.sh`, dev compose; 8 on a real Proxmox; 6 still needs one real CT per loader). **Open: 9, 10.** | | |
| 1 | Safe restore (member check, `--no-same-owner`) and narrower `FILE_ROOTS` default, still in root mode | low | pytest, compose |
| 2 | `remote_cmd` builder + `privileged(server)`; behavior unchanged for `root` | low | full pytest (same strings for root) |
| 3 | `gp-service`, `gp-clamav-ensure`, sudoers and sshd templates in `lib/`, shared by `ct-phases.sh`, Docker and migration | low | `docker/ct-sandbox` (`visudo -cf`) |
| 4 | Docker fakes: one fake game in `gamepanel` mode, one still root | medium | compose + screen walk |
| 5 | Helper mode in the panel (status/logs/metrics unprivileged, actions via sudo, content as `steam`) | medium | compose + unit tests on built commands |
| 6 | Mod `EnvironmentFile` overlay; installers as `steam` | **high** | pytest + **real CT** per loader (BepInEx, UE4SS Linux, Proton overrides) |
| 7 | New containers created with `gamepanel`; broker locks root at cleanup | medium | `compare.sh` (expected diff), `broker.sh`, tests, then **one real broker install** |
| 8 | `ct-migrate-user.sh` + "Migrate access" button + `migrate-ct.sh` | **high** (lockout) | sandbox idempotence; **real throwaway CT** first (`pct enter` is the way back) |
| 9 | Game unit sandboxing drop-in, opt-in per game | medium | **real CT only**, per game |
| 10 | Docker `gameserver` image | low | local build + one real SteamCMD install |

**Done when** every registered server has `ssh_user=gamepanel`, `ssh root@ct` is refused,
`sudo -l -U steam` shows nothing, and every screen of the CLAUDE.md screen walk returns 200.
