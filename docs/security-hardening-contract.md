# Unprivileged access: the contract between the panel and the containers

Implementation contract for phases 1-8 of [security-hardening.md](security-hardening.md).
Both sides (panel code and the container provisioning) build against exactly this.

## Users

- `gamepanel` - the SSH login user of the panel. System user, shell `/bin/bash`, home
  `/var/lib/gamepanel-agent` (0700), member of `systemd-journal`, NOT in group `steam`.
  The panel public key goes to `/var/lib/gamepanel-agent/.ssh/authorized_keys`.
- `steam` - runs SteamCMD and the game. No sudo rights at all.

## Root helpers (root-owned, 0755, in the container)

| Path | Arguments | Does |
|---|---|---|
| `/usr/local/sbin/gp-service` | `start` \| `stop` \| `restart` \| `--version` | `systemctl <verb> "$GAME_UNIT"`; `GAME_UNIT` comes from `/etc/gamepanel/ct.env` (root-owned 0644), never from an argument. `--version` prints `gp-helpers 1`. Any other argument: exit 2. |
| `/usr/local/sbin/gp-clamav-ensure` | none | installs ClamAV if missing (apt) and refreshes signatures (same steps `games/mods/antivirus.py` runs today as root). |
| `/usr/local/bin/update-game`, `/usr/local/bin/check-game-update` | none | unchanged (already written by `lib/ct-phases.sh`). |
| `/usr/sbin/nft` | exactly `-j list set inet ct_firewall players` | player presence. |

`/etc/gamepanel/ct.env`:

```
GAME_UNIT=<service name, e.g. palworld.service>
GP_HELPERS_VERSION=1
```

## `/etc/sudoers.d/gamepanel` (0440, must pass `visudo -cf`)

```
Defaults:gamepanel !requiretty, !use_pty, env_reset, !log_output
Cmnd_Alias GP_ROOT = /usr/local/sbin/gp-service start, /usr/local/sbin/gp-service stop, \
  /usr/local/sbin/gp-service restart, /usr/local/sbin/gp-service --version, \
  /usr/local/bin/update-game "", /usr/local/bin/check-game-update "", \
  /usr/sbin/nft -j list set inet ct_firewall players, /usr/local/sbin/gp-clamav-ensure ""
gamepanel ALL=(root)  NOPASSWD: GP_ROOT
gamepanel ALL=(steam) NOPASSWD: ALL
```

A trailing `""` means "no arguments": in sudoers a command written without arguments
accepts ANY arguments, so the helpers that take none say so explicitly.

## Mod environment overlay (phase 6), written by `ct-panel-access.sh install`

| Path | Owner, mode | Read by |
|---|---|---|
| `/etc/gamepanel/game-env/` | root:root 0755 | - (steam can neither create, delete nor replace files in it) |
| `/etc/gamepanel/game-env/service.env` | steam:steam 0644 | systemd, through the drop-in below (`KEY='value'` lines) |
| `/etc/gamepanel/game-env/runtime.env` | steam:steam 0644 | `win-run`, sourced after `/etc/game-runtime.env`, only when owned by the running user; `GAMEPANEL_EXTRA_ARGS` is appended to the game's arguments |
| `/etc/systemd/system/<GAME_UNIT>.d/gamepanel-env.conf` | root:root 0644 | systemd: `[Service]` + `EnvironmentFile=-/etc/gamepanel/game-env/service.env` |

Values are limited to `[A-Za-z0-9_./:,;=@+ -]` on both sides (they go between single quotes in a
file bash sources). No sudoers line changes: the panel writes these files as `steam`.

`install` also converts, idempotently, what a root installer left before a CT was migrated:
`gamepanel-*.conf` loader drop-ins of the game unit (only `[Service]`/`Environment=` lines) move
to service.env; ARK's `gamepanel-mods.conf` becomes `GAMEPANEL_EXTRA_ARGS` (only when its recorded
base is the unit's current ExecStart and runs through win-run); a loader `WINE_DLL_OVERRIDES` in
`/etc/game-runtime.env` moves to runtime.env and the base gets the original back (BepInEx's
`overrides_before`, or without `winmm=n,b`/`dwmapi=n,b`); a win-run without the hook gets it
inserted after `exe="$1"; shift` (FIRST: the runtime.env conversions only run once win-run reads
it, otherwise the loader would vanish at the next restart); root-owned files under the unit's `WorkingDirectory` (under
`/opt`) go back to steam (`chown -R -P`). `daemon-reload` runs only when a drop-in changed.

## sshd (`/etc/ssh/sshd_config.d/10-gamepanel.conf`), written only when root is locked

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AllowUsers gamepanel
```

## How the panel calls things (helper mode = `servers.ssh_user != 'root'`)

| Need | Legacy mode (`root`) | Helper mode |
|---|---|---|
| start/stop/restart | `systemctl start <unit>` (unchanged) | `sudo -n /usr/local/sbin/gp-service start` |
| update / check | `/usr/local/bin/update-game` | `sudo -n /usr/local/bin/update-game` |
| status, logs, metrics | unchanged | unchanged (no sudo) |
| presence | `nft -j list set inet ct_firewall players` | `sudo -n /usr/sbin/nft -j list set inet ct_firewall players` |
| files, backups, port probe, console, terminal, workshop/folder mods, antivirus scan | as root (unchanged) | `sudo -n -u steam -- <same command>`; terminal: `sudo -n -u steam -i` |
| ClamAV install | inline apt (unchanged) | `sudo -n /usr/local/sbin/gp-clamav-ensure` |
| loader installers (BepInEx, UE4SS, UE4SS Linux, Shroudtopia) and the ARK mod list | unchanged (systemd drop-ins, `/etc/game-runtime.env`, as root) | as `steam` with `--overlay`: they write the mod environment overlay below, never root's files |
| Oxide, SML | unchanged | as `steam` (they only write inside the game folder) |
| antivirus for an installer that downloads | inline in the scan script | `sudo -n /usr/local/sbin/gp-clamav-ensure` as the step before, then the check-only scan as `steam` |

## Who uses which user

- Broker-created containers and containers deployed by `deploy-game.ps1` /
  `provision-game-lxc.sh` from now on: `gamepanel`, and root login is locked at the end of the
  install.
- Servers registered before this change stay `root` (legacy mode) until migrated (phase 8,
  not implemented yet).
- Docker dev (`docker compose`): `game-palworld` runs in helper mode (`gamepanel`),
  `game-dragonwilds` stays `root`, so both paths are exercised every day.
