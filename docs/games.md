# Games

Everything about the game catalog: the curated games, how to add a game that is not
listed, Windows-only servers under Proton/Wine, ports and NAT, and per-game notes.
Back to the [README](../README.md).


## Defined games

| Game | Command | Ports |
|------|---------|-------|
| RuneScape: Dragonwilds | `.\deploy\game\deploy-game.ps1 -Game dragonwilds` | 7777/udp |
| Palworld | `.\deploy\game\deploy-game.ps1 -Game palworld` | 8211/udp, 27015/udp |
| Satisfactory | `.\deploy\game\deploy-game.ps1 -Game satisfactory` | 7787/udp, 7787/tcp |
| Enshrouded | `.\deploy\game\deploy-game.ps1 -Game enshrouded` | 15636/udp, 15637/udp |
| DayZ | `.\deploy\game\deploy-game.ps1 -Game dayz` | 2302-2304/udp, 27016/udp |
| Icarus | `.\deploy\game\deploy-game.ps1 -Game icarus` | 17777/udp, 27017/udp |
| Valheim | `.\deploy\game\deploy-game.ps1 -Game valheim` | 2456/udp, 2457/udp |
| V Rising | `.\deploy\game\deploy-game.ps1 -Game vrising` | 9876/udp, 9877/udp |
| Euro Truck Simulator 2 | `.\deploy\game\deploy-game.ps1 -Game ets2` | 27018 and 27019, TCP and UDP |

Replace `deploy-game.ps1` with `deploy-docker.ps1` to run on Docker. Besides the install,
each `games/<game>.env` tells the panel where the config lives (`CONFIG_PATH`/`CONFIG_FILES`),
what to back up (`BACKUP_PATHS`) and how to count players (`QUERY_PORT`/`PLAYER_SOURCE`).
That is what makes the server arrive registered, with the **Config** screen ready and
**Backup** pointing at the right save.

Every `games/*.env` must pass bash `source` (the Proxmox path sources it raw). Log regexes
with parentheses need quotes. To check:

```bash
for f in games/*.env; do bash -c "set -a; source $f"; done
```

## Adding a game that is not defined anywhere

The panel's **Catalog** screen searches by name or App ID in four places: the games already
in the catalog (with a shortcut to **Create instance**), LinuxGSM, the Pterodactyl eggs (~40
games LinuxGSM lacks, half of them Windows-only: Astroneer, Bannerlord, Space Engineers, Myth
of Empires...) and a hand-maintained list in the panel (`manual_suggestions.py`: ARK: Survival
Ascended, Abiotic Factor, Conan Exiles, Sons of the Forest). Each suggestion says which source
it came from; when an egg fills a field LinuxGSM left empty (config files, ports), the notice
says which.

To refresh the two generated lists: `python tools/import-linuxgsm.py` and
`python tools/import-pterodactyl.py` (they need internet; the panel does not). If nothing
matches, the screen offers links to SteamDB (dedicated server App ID) and a web search for the
ports. Your browser opens those links; the panel still never goes to the internet. From there
the path is **Start from a template** by engine: Unreal (Linux, or Windows via Proton), Unity
(Linux, or Windows via Proton) and Source/srcds. A Windows server registered this way runs with
the `.exe` directly in the "Start script": the installer calls it through `win-run`. The
`proton`/`wine` recipes choose the runtime and `xvfb` turns on the virtual X server.

The search is always a **suggestion**: the broker validates on submit.

Notes on the generated sources:

- LinuxGSM (MIT) is converted by `tools/import-linuxgsm.py` and committed in
  `src/gamepanel/games/catalog/suggestions.py`. Only what the broker's validator accepts is
  emitted; RCON/telnet/HTTP ports go only into the argument and **never** into NAT; password,
  name, IP or token variables are never resolved (the argument is dropped with a warning);
  anything after `; | & \` or `$(` is cut.
- Ports for ~30 games that LinuxGSM does not set in `_default.cfg` come from the game's config
  key (LinuxGSM `info_game.sh`) and the default file from `Game-Server-Configs`. Protocol per
  port comes from `info_messages.sh`, except the Steam query, which is always UDP.
- Pterodactyl eggs (`pelican-eggs/games-steamcmd`, MIT) are converted by
  `tools/import-pterodactyl.py` (or `--source` with a local clone). Order of precedence for the
  same App ID: the page catalog, the manual list, LinuxGSM, the egg. An egg only **completes**
  a LinuxGSM suggestion field by field, and the merge is validated at generation time. The egg
  `install` script is shell and is never read. A Windows server from an egg is emitted with
  `proton`, even if the egg uses Wine.
- Enshrouded, Icarus and Dragonwilds are not in LinuxGSM and stay manual.

## Games without a Linux build: Proton or Wine

Enshrouded, Icarus and V Rising only publish Windows servers. The deploy downloads the Windows
build (`STEAM_PLATFORM=windows`) and runs the `.exe` inside the CT with the runtime chosen in
`games/<game>.env`:

| Variable | Purpose |
|----------|---------|
| `WINDOWS_RUNTIME` | `wine` (distro package), `proton` (Proton-GE from GitHub) or empty for a native game |
| `PROTON_VERSION` | pinned Proton-GE tag, e.g. `GE-Proton11-5` |
| `WINE_DLL_OVERRIDES` | goes into `WINEDLLOVERRIDES`; default `mscoree,mshtml=` |
| `WINDOWS_RUNTIME_XVFB` | `1` when the `.exe` creates a window even headless |

`provision-game-lxc.sh` installs the runtime, writes `/etc/game-runtime.env` and creates the
**`win-run`** command inside the CT. The game's start script becomes one line:

```bash
exec win-run /opt/game/servidor.exe "$@"
```

Switching runtime means changing `WINDOWS_RUNTIME` and redeploying; no game script changes.

**Why Proton and not the distro's Wine.** Debian's Wine has no esync or fsync: every Windows
mutex/event/semaphore becomes an expensive syscall, which is a CPU bottleneck on heavily
multi-threaded servers. Proton-GE ships its own Wine with **fsync** (`futex_waitv`, kernel
>= 5.16) on by default.

**Rule for new games without a Linux build: Proton first.** Every `games/*.env`, template and
suggestion for a Windows-only server starts with `proton`; plain `wine` only when Proton was
tried and does not work with that game, with the reason written in the `.env`.

**`UMU_ID` must be the game's REAL appid.** This is the second Proton-outside-Steam trap and
it is silent: with an arbitrary `UMU_ID` (0, for example) Proton propagates `SteamAppId=0` and
**the Steam game server API fails**. The game log shows `[AppId: 0] Game Server API
initialized 0` instead of `[AppId: 1149460] ... 1`, the query port never opens, and the server
stays up, invisible in the server browser and without a player count in the panel.

`win-run` handles it: it reads the `steam_appid.txt` next to the executable and exports
`UMU_ID`/`SteamAppId`/`SteamGameId` with that value. If the game has no such file it falls
back to `0`, which is correct for games that do not use Steam (Enshrouded).

Both Enshrouded and Icarus run on `proton`: Enshrouded because it does not depend on Steam,
Icarus because with the right appid Steam initializes normally **and** it also gets ntsync.

**The detail that makes a dedicated server work under Proton.** By default Proton launches the
game through the `steam.exe` shim, which expects a **live Steam client** to complete a
handshake. A dedicated server has no Steam client, and the result is a silent deadlock: the
process is up, RSS stuck at ~34MB, **zero CPU**, no port open and not even the game's own log
created. `systemd` reports `active` the whole time. The diagnosis: the main thread sits in
`wchan=pipe_read`, with the process holding both ends of the same pipe.

The way out is inside `proton` itself: with **`UMU_ID` set** and the executable passed as a
**Windows path** (`Z:\opt\game\servidor.exe`), it takes the
`"Executable is inside wine prefix, launching normally"` branch and calls Wine directly, with
no shim. `win-run` does both automatically. After that the same server loads in under 20s,
with 35 threads and the main thread in `ntsync_schedule`.

Things that were **not** the problem, already tested and ruled out (so nobody repeats them):
`LimitNOFILE`, working directory, corrupted prefix, systemd vs manual run, and disabling
`lsteamclient` (it already arrives disabled and the hang continues).

**Careful with overrides.** Disabling `explorer.exe`/`services.exe`/`wbemprox.dll` looks like
an obvious saving on a headless server, but it was **measured and rejected**: under Proton each
of the three hangs Enshrouded at startup. On Icarus, without `explorer.exe` the server dies
with `nodrv_CreateWindow`. So the default is conservative. Remember that Proton already injects
its own overrides on top of yours (`steam.exe=b`, `winebth.sys=d`, `d3d11=n`...).

The systemd unit gets `LimitNOFILE=1048576` when there is a Windows runtime: esync/fsync create
one descriptor per synchronization object, and the default limit (1024) kills the server under
load.

**Optional extra: `ntsync`.** The Proxmox 6.14 kernel ships the `ntsync` module
(`/lib/modules/$(uname -r)/kernel/drivers/misc/ntsync.ko`), which implements NT primitives in
the kernel and is faster than fsync. It is **not loaded** by default. To use it, on the host:

```bash
modprobe ntsync && echo ntsync > /etc/modules-load.d/ntsync.conf
ls -l /dev/ntsync
pct set <CTID> -dev0 /dev/ntsync,mode=0666   # exposes the device to the container
pct reboot <CTID>
```

Without `/dev/ntsync` inside the CT, Proton uses fsync normally; nothing breaks, it just does
not take the faster path.

## Port map and NAT

Each game has its own CT and IP, so **there is no conflict on the LAN**: two servers could use
the same port on different IPs. The conflict appears on the **router**, which has a single
public IP where each external port points to a single destination. So the ports below are
unique, not because the games require it, but so that every forward is **1:1** (external port
= internal port).

| Game | Destination | Forward on the router | Never forward |
|------|-------------|------------------------|---------------|
| Dragonwilds | 10.20.1.20 | `7777/udp` (+ `7778`, `7779` for extra worlds) | - |
| Palworld | 10.20.1.21 | `8211/udp`, `27015/udp` | REST `8212/tcp`, RCON `25575/tcp` |
| Satisfactory | 10.20.1.22 | `7787/udp`, `7787/tcp` | - |
| Enshrouded | 10.20.1.23 | `15636/udp`, `15637/udp` | - |
| DayZ | 10.20.1.24 | `2302/udp`, `2303/udp`, `2304/udp`, `27016/udp` | - |
| Icarus | 10.20.1.25 | `17777/udp`, `27017/udp` | - |
| V Rising | (broker CT) | `9876/udp`, `9877/udp` | RCON `25575/tcp` |
| Euro Truck Simulator 2 | (broker CT) | `27018`, `27019` (TCP and UDP) | - |

**1:1 is not an aesthetic preference** for games that publish an A2S query (Palworld, DayZ,
Icarus). These servers announce *their own* port to the Steam master server; if NAT translates
external `27020` to internal `27015`, Steam advertises a port that does not exist outside and
the server is invisible in the browser while still responding. For direct-IP games
(Dragonwilds, Satisfactory, Enshrouded) an asymmetric translation would work, but keeping
everything 1:1 avoids having one port on the LAN and another on the internet.

**Tie-break rule: seniority.** When two games want the same port, the one configured first
keeps it (CTID order tells that story: 210 dragonwilds, 211 palworld, 212 satisfactory, 213
enshrouded, 214 dayz, 215 icarus). The newcomer moves. This avoids touching a server with
people playing and bookmarks already saved in clients; the cost always falls on the newest
game, which has no history yet.

The two collisions resolved by this rule:

- **`7777`**: wanted by Dragonwilds (CT 210) and Satisfactory (CT 212). It stayed with
  **Dragonwilds**, the older one, which also reserves 7778/7779 for extra worlds. Satisfactory
  moved to **7787**, taking the management API's TCP with it.
- **`27015`**: the default Steam query, wanted by Palworld (CT 211) and Icarus (CT 215). It
  stayed with **Palworld**; Icarus moved to **27017** (27016 belongs to DayZ).

No panel, SSH or game API goes to the internet. The panel is reached from the LAN or a VPN;
the containers' SSH only answers the panel.

### How it becomes an OPNsense rule

For games deployed by hand (without the broker), create one port alias per game
(`JOGO_<Name>`) and one port forward rule per game in OPNsense. The rule template is always
the same (the broker does this for you, see the README):

| Field | Value |
|-------|-------|
| Interface | WAN |
| Protocol | UDP (only Satisfactory uses **TCP/UDP**) |
| Destination | WAN address |
| Destination port range | the game's alias |
| Redirect target IP | the game CT's IP |
| Redirect target port | **the same alias** |

Using the same alias in both port fields is what produces the 1:1 mapping; without it, games
with A2S query disappear from the Steam browser. An OPNsense port alias **does not store the
protocol**: it comes from the rule, which is why Satisfactory needs explicit TCP/UDP (UDP is
the game, TCP is the management API, both on the same port).

The exported CSV **does not include the destination or destination port columns**, so it is a
reference and backup, not an import source: reimporting can leave those fields empty, and a
rule without a destination port matches *any* port for that host.

## Per-game notes

### RuneScape: Dragonwilds

- Dedicated server app: `4019830` (native Linux build, `RSDragonwildsServer.sh`).
- Default port **7777/UDP**; each additional world uses the next one (7778, 7779...), so the
  range 7777-7779 is reserved for this game; see [Port map and NAT](#port-map-and-nat).
- Config created on first start (find it with `find /opt/game -name DedicatedServer.ini`):
  server name, world password, admin password, OwnerID. Stop the server before editing.
- Player limit: fixed at 6 (locked by Jagex, not configurable).
- **Publishes nothing queryable**: no Steam A2S query, no RCON, no HTTP API. The server uses
  **EOS** (Epic Online Services), not Steam; the world is found in-game by its exact name
  through Epic sessions. Measured on a real CT: it opens only `7777`, `8888` and a high port,
  and none answers A2S, not even over loopback; Jagex's docs have no query port or argument for
  it. Hosting guides that tell you to open `27015` are copying text from other Unreal games.
  The panel counts **active connections** on the game port (the CT firewall records who talks
  to 7777) and takes the names from the log.
- Saves: `/opt/game/RSDragonwilds/Saved/SaveGames/`.

### Palworld

- Dedicated server app: `2394010` (native Linux build, `PalServer.sh`).
- Ports: **8211/UDP** (game) and **27015/UDP** (Steam query, required to appear in the
  community list). The **REST API (8212/TCP)** and RCON (25575/TCP) only exist if enabled in
  the `.ini`; do not forward either on the router.
- Three ways to count players, best to worst: **REST API** (`8212/tcp`, gives names, level and
  ping), **A2S** (`27015/udp`, count only; Palworld does not answer `A2S_PLAYER`) and the log.
  To enable REST: `RESTAPIEnabled=True`, `RESTAPIPort=8212` and a strong `AdminPassword`; in
  the panel, **Configure counting > HTTP API** with `http://127.0.0.1:8212/v1/api/players` and
  `basic:admin:<the password>`. Pocketpair marked RCON as *deprecated* in favor of REST.
- The deploy creates the symlink `~steam/.steam/sdk64/steamclient.so` (required by
  `PalServer.sh`) and seeds `PalWorldSettings.ini` from `DefaultPalWorldSettings.ini`.
- Config: `/opt/game/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini`. Everything lives in
  `OptionSettings=(...)`, on a single line: `ServerName`, `ServerPassword`, `AdminPassword`,
  `ServerPlayerMaxNum` (max 32), `PublicPort`, XP/capture rates etc. Stop the server before
  editing (`systemctl stop palworld`).
- Memory: the server grows with the world/players; 16GB recommended (8GB is the practical
  minimum).
- Saves: `/opt/game/Pal/Saved/SaveGames/0/`.

### Satisfactory

- Dedicated server app: `1690800` (native Linux build, `FactoryServer.sh`).
- Ports: one port, two protocols: **7787/UDP** (game) and **7787/TCP** (HTTPS management API
  the client uses to claim and configure the server). Open both. The game default is 7777,
  given to Dragonwilds by seniority ([Port map and NAT](#port-map-and-nat)). The old ports
  15000/15777 went away in 1.0.
- The deploy creates the symlink `~steam/.steam/sdk64/steamclient.so` (without it the server
  starts but does not register with Steam).
- Config: there is no `.ini` to fill beforehand. In the client, **Server Manager > Add
  Server** with `IP:7787`, set the admin password and claim the server. Fine-tuning later in
  `/home/steam/.config/Epic/FactoryGame/Saved/Config/LinuxServer/` (`ServerSettings.ini`,
  `GameUserSettings.ini`), with the server stopped.
- Does not publish a Steam A2S query; the panel's player count comes from the log.
- Memory: 12GB is the official recommendation; large factories exceed it, hence 16GB.
- Saves: `/home/steam/.config/Epic/FactoryGame/Saved/SaveGames/server/`.

### Enshrouded

- Dedicated server app: `2278520`, **no Linux build**. The deploy downloads the Windows build
  (`STEAM_PLATFORM=windows`) and runs `enshrouded_server.exe` under Proton (see
  [Games without a Linux build](#games-without-a-linux-build-proton-or-wine)).
- Ports: **15637/UDP** is the main one (`queryPort`), the one players type in the client.
  `15636/UDP` (`gamePort`) went out of use in Content Update #2; opening both does no harm.
  All UDP, no TCP.
- The port is **not** passed on the command line: the server reads everything from
  `enshrouded_server.json`. If you change the port there, also adjust `GAME_PORT`/`GAME_PORTS`
  in `games/enshrouded.env`.
- Config: `/opt/game/enshrouded_server.json`; the deploy creates a template on first run.
  **Change the passwords** in `userGroups` (Admin / Friend / Guest): each player joins with
  their group's password, there is no single server password. `slotCount` goes up to 16. Stop
  the server before editing (`systemctl stop enshrouded`).
- `15637` also answers the Steam **A2S** query: it counts, the log gives the names (and takes
  over the count if the query does not answer).
- Memory: 16GB (official recommendation for 16 slots, plus Wine's overhead). Disk: the Windows
  build exceeds 12GB, hence 40GB.
- The first start takes longer than usual: Wine builds the prefix and the game generates the
  world. Follow it with `game-logs`.
- Saves: `/opt/game/savegame/` (Wine prefix in `/home/steam/.wine-enshrouded`).

### Icarus

- Dedicated server app: `2089300`, **no Linux build**. Like Enshrouded, the deploy downloads
  the Windows build (`STEAM_PLATFORM=windows`) and runs `IcarusServer.exe` under Proton.
- Ports: **17777/UDP** (game) and **27017/UDP** (Steam query, used by Icarus's own server
  browser). Both go on the command line (`-PORT=` / `-QueryPort=`), so changing `GAME_PORT` in
  `.env` is enough. All UDP. The query is not on the default 27015 because Palworld already
  uses it; see [Port map and NAT](#port-map-and-nat).
- Publishes **A2S** on 27017; the panel's player count comes from the query, not the log.
  There is no RCON or HTTP API: administration is done in-game with `AdminPassword`.
- Config: `/opt/game/Icarus/Saved/Config/WindowsServer/ServerSettings.ini`. The game only
  creates it when generating the first prospect, so the deploy seeds a template. **Change
  `AdminPassword`**; adjust `SessionName`, `MaxPlayers` and `JoinPassword` (empty = open).
  Stop the server before editing (`systemctl stop icarus`): the game rewrites this file on
  exit (`LastProspectName` etc.).
- `ShutdownIfEmptyFor` / `ShutdownIfNotJoinedFor` default to 300s (the server shuts itself down
  when nobody joins). systemd restarts it right away; if you prefer the server always up,
  increase both values.
- The world is not born with the server: a connected player creates the **prospect** from the
  game menu (or fill `CreateProspect`/`LoadProspect` in the `.ini`).
- **`vm.max_map_count`**: Unreal under Wine dies with `Freeing X bytes from backup pool` if it
  is at the default. In an unprivileged CT a `sysctl` from inside does not stick; set it on the
  **Proxmox host**: `sysctl -w vm.max_map_count=262144` and
  `echo "vm.max_map_count=262144" > /etc/sysctl.d/99-icarus.conf`.
- **Needs a virtual X server (`xvfb`)**, unlike Enshrouded: the Icarus server build tries to
  create a *window* at startup even though it renders nothing. Without a display Wine dies in
  ~1s with `nodrv_CreateWindow: Application tried to create a window, but no driver could be
  loaded` and **exit 41**, before even creating `Saved/Logs/`. So `PRE_INSTALL_CMD` installs
  `xvfb` and the wrapper runs under `xvfb-run -a`. **`xauth` is explicit** on the same
  `apt-get` line: it is only a *Recommends* of `xvfb`, so with `--no-install-recommends` it
  does not come along and `xvfb-run` dies with `error: xauth command not found` (exit 3) before
  reaching Wine.
- **The wrapper calls the `Shipping` binary directly**, not the root `IcarusServer.exe`. That
  one is only 256KB and is Unreal's *bootstrap*: headless it starts, stays alive using ~1s of
  CPU and **never spawns the server process** (no port, no log, systemd reporting `active` the
  whole time). The real binary is `Icarus/Binaries/Win64/IcarusServer-Win64-Shipping.exe`
  (~108MB). In `ps`, a healthy server shows THAT binary with RSS in the GBs; if you only see
  `IcarusServer.exe` at ~17MB, the bootstrap is stuck.
- The journal shows `XDG_RUNTIME_DIR is invalid or not set`: noise from `libwayland-client` in
  a systemd service ([bug 1093464](https://lists.debian.org/debian-wine/2025/12/msg00004.html)),
  not the cause of any failure. The wrapper sets the variable only to silence it.
- Do not use `WINEDEBUG=-all` in the wrapper: it silences Wine's `err:` lines, which are the
  only clue when the `.exe` dies before creating its own log. The default here is `fixme-all`.
- `START_ARGS` includes `-stdout -FullStdOutLogOutput` so Unreal writes to the process stdout
  and not only to the file. Without it `game-logs` stays **silent with a healthy server** (the
  only stderr would be Wine's), which is confusing when diagnosing. Do not use `-log`: it opens
  a console window that gets stuck inside the virtual X server.
- Memory: 16GB (official recommendation, plus Wine's overhead); the game is heavy on a single
  thread, so a fast core matters more than many cores. Disk: the install takes ~10.5GB (1.1GB
  of it `.pdb`), hence 32GB with headroom.
- The first start takes longer: Wine builds the prefix. Follow it with `game-logs`.
- Saves: `/opt/game/Icarus/Saved/PlayerData/` and `/opt/game/Icarus/Saved/Prospects/` (Wine
  prefix in `/home/steam/.wine-icarus`).

### V Rising

- Dedicated server app: `1829350`, **no Linux build**, and **not in LinuxGSM** (which is why
  the panel's search did not find it). Runs on **Proton** with a virtual X server
  (`WINDOWS_RUNTIME_XVFB=1`): the server is Unity and creates a window at startup.
- Ports: **9876/UDP** (game, the Direct Connect one) and **9877/UDP** (Steam query). Both go on
  the command line (`-gamePort` / `-queryPort`) and override the `.json`.
- **Appid under Proton**: the wrapper sets `SteamAppId=1604030` (the game's) when the depot has
  no `steam_appid.txt`; with 0 the query never opens, as happened with Icarus.
- Config: `/opt/game/save-data/Settings/ServerHostSettings.json` (name, password, public
  listing in `ListOnSteam`/`ListOnEOS`) and `ServerGameSettings.json` (world rules). The deploy
  seeds both from the server's own defaults. Admins: SteamID64 in `adminlist.txt`, in the same
  folder. Stop the server before editing (`systemctl stop vrising`).
- Log: the server only writes to `/opt/game/logs/VRisingServer.log`; the wrapper repeats it in
  the journal with `tail -F`, and that is where the panel's log screen reads it.
- Saves: `/opt/game/save-data/Saves/` (the panel Backup keeps Saves and Settings).
- From the panel: it is curated and creatable, so it can be created directly from
  **Instances**. **Not yet tested against a real CT**; if Proton does not start,
  `WINDOWS_RUNTIME=wine` and redeploy.

### Euro Truck Simulator 2

- Dedicated server app: `1948160`, native Linux build. Official docs:
  modding.scssoft.com/wiki/Documentation/Tools/Dedicated_Server
- **The server does not start without `server_packages.sii` and `server_packages.dat`**, which
  only the GAME generates: with a map loaded, open the console and run
  `export_server_packages`. Upload both files to `/opt/game/server-home` through the **Files**
  screen; the server starts on its own within 30 s. Until then the service stays up, saying in
  the log what it is waiting for (creation through the panel needs the service active, and the
  files can only be uploaded after the CT exists).
- **Mods and DLCs travel inside those packages.** The server downloads no mods (it runs
  without the Steam client and does not see the Workshop): it applies what was active in the
  profile of whoever exported. To play with mods, activate them in the profile BEFORE
  exporting, and every player needs the SAME mods subscribed on the Workshop. Changed the mod
  list? Export and upload the packages again.
- Ports: **27018** (connection) and **27019** (query), TCP and UDP on both, away from the
  default 27015/27016, which on the router already belong to Palworld and DayZ. The start
  script writes them into `server_config.sii` on every start; the virtual ports 100/101 need
  no NAT.
- Config: `/opt/game/server-home/server_config.sii` (created on first start): `lobby_name`,
  `password`, `max_players`. Optional: `server_logon_token`, generated at
  steamcommunity.com/dev/managegameservers with the GAME's App ID (227300), so the server keeps
  the same identity across restarts.

### DayZ

- Dedicated server app: `223350` (**native Linux** build, binary `DayZServer`).
- **The only game here that does not download with anonymous login.** The server depot
  requires a Steam account that **owns DayZ**; see
  [Games that require a Steam account](../README.md#games-that-require-a-steam-account).
- Ports: **2302/UDP** (game), **2303** and **2304/UDP** (engine/Steam) and **27016/UDP**
  (`steamQueryPort`). Without 27016 the server does not show up in the client browser. All
  UDP. In the panel, register **27016** as the query port; DayZ publishes A2S.
- The deploy creates the symlink `~steam/.steam/sdk64/steamclient.so`, the `profiles/` and
  `battleye/` folders, and seeds `serverDZ.cfg` (the sample in the package lacks
  `steamQueryPort`).
- Config: `/opt/game/serverDZ.cfg`: `hostname`, `password` (join), `passwordAdmin`,
  `maxPlayers`, and the mission `template` (`dayzOffline.chernarusplus` or `dayzOffline.enoch`
  for Livonia). Stop the server before editing (`systemctl stop dayz`).
- Persistence: `/opt/game/mpmissions/dayzOffline.chernarusplus/storage_1/`; the number follows
  `instanceId` in `serverDZ.cfg`. Logs and stats in `/opt/game/profiles/`.
- Memory: 8GB (vanilla with ~20 players stays near 4GB; mods go beyond).
