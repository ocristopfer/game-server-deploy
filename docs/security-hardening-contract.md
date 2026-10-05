# Unprivileged access: the contract between the panel and the containers

Implementation contract for phases 1-5 and 7 of [security-hardening.md](security-hardening.md).
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
| loader installers that write systemd drop-ins or `/etc/game-runtime.env` (BepInEx, UE4SS, UE4SS Linux, Shroudtopia, Oxide, SML) | unchanged | refused with a clear message: phase 6 of the plan (not implemented yet) |

## Who uses which user

- Broker-created containers and containers deployed by `deploy-game.ps1` /
  `provision-game-lxc.sh` from now on: `gamepanel`, and root login is locked at the end of the
  install.
- Servers registered before this change stay `root` (legacy mode) until migrated (phase 8,
  not implemented yet).
- Docker dev (`docker compose`): `game-palworld` runs in helper mode (`gamepanel`),
  `game-dragonwilds` stays `root`, so both paths are exercised every day.
