"""Which mod manager applies to which server.

The choice is by the SERVICE NAME (`ets2.service`): it is the identity every panel server has,
whether it came from the broker, from deploy-game.ps1 or was registered by hand - the panel
does not keep "which game is this" anywhere else. A server without a profile is not left
stranded: the screen says the game has no manager yet and points to the Files screen.

New profile = one entry in `PROFILES`. A test makes sure two profiles do not claim the same
service (the first would win and the second would silently become dead code).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The server READS the packages exported from the game; no mod is copied to it.
KIND_PACKAGES = "packages"
# The server needs the mod file in one of its folders.
KIND_FOLDER = "folder"
# Thunderstore mods with BepInEx: the CT downloads and installs (games/mods/thunderstore_remote.py).
KIND_THUNDERSTORE = "thunderstore"
# Enshrouded native loader (Shroudtopia): the CT downloads the loader, Wine starts using its
# winmm.dll, and the mods are DLLs that come in through the screen (games/mods/shroudtopia_remote.py).
KIND_SHROUDTOPIA = "shroudtopia"
# UE4SS (Unreal game whose server is the Windows .exe under Proton): the CT downloads the loader,
# Wine starts using its dwmapi.dll, and the mods live in Mods/ next to the executable
# (games/mods/ue4ss_remote.py). The profile folder is Mods/; the loader lives in the one above.
KIND_UE4SS = "ue4ss"
# Satisfactory: SML and the ficsit.app mods, through its API (games/mods/sml_remote.py).
KIND_SML = "sml"
# Rust: Oxide (uMod) overwrites game DLLs and the plugins are .cs (games/mods/oxide_remote.py).
KIND_OXIDE = "oxide"
# Native LINUX Unreal (Palworld, Dragonwilds): the official UE4SS built for Linux, via LD_PRELOAD
# in a systemd drop-in (games/mods/ue4ss_linux_remote.py). The profile folder is still the .pak
# one (upload); UE4SS and the Lua mods live in <loader_dir>/ue4ss.
KIND_UE4SS_LINUX = "ue4ss-linux"
# Workshop through the game CONFIG: the server itself downloads the mods on startup, from the
# list of IDs the panel writes into its file (games/mods/workshop_remote.py). `workshop_format`
# says which file and which format (dst, zomboid, unturned, reforger).
KIND_WORKSHOP = "workshop"
# Guide only (where to find, how to install), no action: the path exists but has not been proven
# on a real server yet, and a button that "installs" without proof is worse than clear instructions.
KIND_GUIDE = "guide"

# Where each game's mods are found. Nexus Mods stays as a LINK, never as an automatic download:
# its API only serves files to Premium accounts, and automating without one violates the terms
# of use. The person downloads from Nexus; the panel receives the file through the screen.
NEXUS = "https://www.nexusmods.com/"


@dataclass(frozen=True)
class ModProfile:
    key: str
    kind: str
    # Service names (without `.service`) that use this profile: the one from the curated catalog
    # and the one the panel search suggests (LinuxGSM/Pterodactyl), which becomes another service name.
    services: tuple[str, ...]
    # Container folder the upload goes to.
    folder: str
    # i18n key of the paragraph that explains how mods work in THIS game.
    help_key: str
    # Accepted upload: exact names (the ETS2 packages) or extensions (.pak). One of the two.
    upload_names: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    # The GAME's Steam App ID, for the Workshop link that goes to the players.
    workshop_appid: int = 0
    # Thunderstore: the community (part of the URL), the loader (namespace, name) and the memory
    # the FIRST startup with it needs - measured, not guessed (see VRISING).
    community: str = ""
    loader: tuple[str, str] = ("", "")
    min_memory_mb: int = 0
    # (i18n key of the label, URL) where this game's mods are found.
    sources: tuple[tuple[str, str], ...] = ()
    # What "Check installed mods" runs through the antivirus, when it is not just `folder`: the
    # loader lives outside the mods folder, and the whole game folder (V Rising) would be gigabytes
    # of the game's own files for nothing.
    audit_paths: tuple[str, ...] = ()
    # Native loader: the folder of the game executable, where the loader goes. Empty = one level
    # above the mods folder (Shroudtopia); experimental UE4SS puts the mods TWO levels below.
    loader_dir: str = ""
    # False = the installer exists but has not run on a real server yet: the screen warns.
    # Whoever proves it on a real CT switches to True, with what was measured written in the profile.
    proven: bool = True
    # Thunderstore on a NATIVE Linux server (Valheim): BepInEx comes in through a systemd drop-in
    # (the doorstop LD_PRELOAD), and not through Wine's winhttp.
    linux_bepinex: bool = False
    # UE4SS Linux: the official one built for Linux (ocristopfer/RE-UE4SS), at this release tag
    # (pinned: changing it is a decision, not "the newest"). `engine_version` picks the template the
    # CT uses to generate VTableLayout.ini from the .sym, when the server ships one.
    ue4ss_release: str = ""
    engine_version: str = ""
    # Workshop through the config: the format workshop_remote knows how to write.
    workshop_format: str = ""

    @property
    def scan_paths(self) -> tuple[str, ...]:
        return self.audit_paths or (self.folder,)

    def accepts(self, name: str) -> bool:
        """The file name that may come in through this game's Mods screen."""
        if self.upload_names:
            return name in self.upload_names
        # With no declared extension (Thunderstore) nothing comes in by upload: `endswith(())` is False.
        return name.lower().endswith(self.extensions)


ETS2 = ModProfile(
    key="ets2",
    kind=KIND_PACKAGES,
    services=("ets2", "euro-truck-simulator-2"),
    # The wrapper in games/ets2.env links the server's default folder to this one (it ignores
    # -homedir): this is where the packages need to be.
    folder="/opt/game/server-home",
    help_key="mods.help_ets2",
    upload_names=("server_packages.sii", "server_packages.dat"),
    audit_paths=("/opt/game/server-home/server_packages.sii", "/opt/game/server-home/server_packages.dat"),
    workshop_appid=227300,
    sources=(("mods.source_workshop", "https://steamcommunity.com/app/227300/workshop/"),),
)

PALWORLD = ModProfile(
    key="palworld",
    # Official UE4SS for Linux (release linux-v1), proven on the real server in Docker
    # (2026-10-04): Lua, FindFirstOf, RegisterHook on Blueprint and native - even on a function
    # that the animation Blueprints call from another thread - and 10 minutes up. No .sym, and it
    # is not needed: the engine is Epic's 5.1.1, and its layout is built into UE4SS. The old ports
    # (XarminaEu and our fork of it) brought this server down. proven=False until the first
    # install through this screen on a real CT.
    kind=KIND_UE4SS_LINUX,
    services=("palworld",),
    # Unreal loads from ~mods the .pak files that did not ship with the game; server and client
    # each have their own copy, and a server mod only counts if it is here.
    folder="/opt/game/Pal/Content/Paks/~mods",
    help_key="mods.help_palworld",
    extensions=(".pak",),
    loader_dir="/opt/game/Pal/Binaries/Linux",
    ue4ss_release="linux-v2",
    engine_version="5.1",
    audit_paths=("/opt/game/Pal/Content/Paks/~mods", "/opt/game/Pal/Binaries/Linux/ue4ss"),
    sources=(("mods.source_nexus", NEXUS + "palworld/mods/"),
             ("mods.source_ue4ss_linux", "https://github.com/ocristopfer/RE-UE4SS/blob/linux/docs/linux.md")),
    proven=False,
)

DRAGONWILDS = ModProfile(
    key="dragonwilds",
    kind=KIND_UE4SS_LINUX,
    services=("dragonwilds",),
    # The server is native Linux Unreal 5: it reads from ~mods whatever did not ship with the
    # game. Checked on the production CT (the game's own files in Paks/ are .pak + .ucas + .utoc).
    folder="/opt/game/RSDragonwilds/Content/Paks/~mods",
    help_key="mods.help_dragonwilds",
    # Unreal 5 (IoStore): a mod usually comes in THREE files with the same name, and the .pak alone
    # does not load. The three go in together.
    extensions=(".pak", ".utoc", ".ucas"),
    # Official UE4SS for Linux (release linux-v1), proven on the real server in Docker:
    # Lua, FindFirstOf, RegisterHook on Blueprint and native, ExecuteInGameThread, and every vtable
    # hook checked by name in the .sym. The engine is a 5.6.1 MODIFIED by Jagex (extra virtuals
    # in AActor): the CT generates VTableLayout.ini and the UE4SS_Signatures of this build from the
    # .sym. A game update requires reinstalling. proven=False until the first install through this screen on a CT.
    loader_dir="/opt/game/RSDragonwilds/Binaries/Linux",
    ue4ss_release="linux-v2",
    engine_version="5.6",
    audit_paths=("/opt/game/RSDragonwilds/Content/Paks/~mods", "/opt/game/RSDragonwilds/Binaries/Linux/ue4ss"),
    sources=(("mods.source_nexus", NEXUS + "runescapedragonwilds/mods/"),
             ("mods.source_ue4ss_linux", "https://github.com/ocristopfer/RE-UE4SS/blob/linux/docs/linux.md")),
    proven=False,
)

ENSHROUDED = ModProfile(
    key="enshrouded",
    kind=KIND_SHROUDTOPIA,
    services=("enshrouded",),
    # The MODS folder; the loader lives in the one above, next to enshrouded_server.exe. Proven
    # on CT 303 (Proton GE 11) on 2026-10-03: with winmm=n,b Shroudtopia starts, loads the DLL
    # from mods/ and the server keeps answering A2S. See shroudtopia_remote.py.
    folder="/opt/game/mods",
    help_key="mods.help_enshrouded",
    extensions=(".dll",),
    audit_paths=("/opt/game/mods", "/opt/game/winmm.dll", "/opt/game/shroudtopia.dll"),
    sources=(("mods.source_shroudtopia", "https://github.com/s0t7x/shroudtopia/releases"),
             ("mods.source_nexus", NEXUS + "enshrouded/mods/")),
)

ICARUS = ModProfile(
    key="icarus",
    kind=KIND_UE4SS,
    services=("icarus",),
    # The server is IcarusServer-Win64-Shipping.exe under Proton (UE 4.27): the UE4SS proxy
    # (dwmapi.dll) goes next to it, and the rest - mods included - in ue4ss/ (the experimental
    # layout, the one that does not break Steam: see ue4ss_remote.py). Proven on a test Icarus.
    folder="/opt/game/Icarus/Binaries/Win64/ue4ss/Mods",
    loader_dir="/opt/game/Icarus/Binaries/Win64",
    help_key="mods.help_icarus",
    audit_paths=("/opt/game/Icarus/Binaries/Win64/ue4ss", "/opt/game/Icarus/Binaries/Win64/dwmapi.dll"),
    sources=(("mods.source_ue4ss", "https://github.com/UE4SS-RE/RE-UE4SS/releases"),
             ("mods.source_nexus", NEXUS + "icarus/mods/")),
)

VRISING = ModProfile(
    key="vrising",
    kind=KIND_THUNDERSTORE,
    services=("vrising", "v-rising"),
    # The GAME folder: BepInExPack goes at its root, and the plugins in BepInEx/plugins.
    folder="/opt/game",
    help_key="mods.help_vrising",
    community="v-rising",
    loader=("BepInEx", "BepInExPack_V_Rising"),
    # All of BepInEx (core, plugins, the .NET folder) and the doorstop winhttp.dll.
    audit_paths=("/opt/game/BepInEx", "/opt/game/winhttp.dll", "/opt/game/dotnet"),
    # Measured on a test CT: the first startup with BepInEx generates the code of the whole game
    # and reached 9.4 GB; with 6 GB the OOM killer brought the server down in a loop. The curated one has 8.
    min_memory_mb=10240,
    sources=(("mods.source_thunderstore", "https://thunderstore.io/c/v-rising/"),),
)

SATISFACTORY = ModProfile(
    key="satisfactory",
    kind=KIND_SML,
    services=("satisfactory",),
    # Native Linux server: each mod in a folder under FactoryGame/Mods, SML included.
    folder="/opt/game/FactoryGame/Mods",
    loader_dir="/opt/game",
    help_key="mods.help_satisfactory",
    audit_paths=("/opt/game/FactoryGame/Mods",),
    sources=(("mods.source_ficsit", "https://ficsit.app/mods"),),
    proven=False,
)

VALHEIM = ModProfile(
    key="valheim",
    kind=KIND_THUNDERSTORE,
    services=("valheim",),
    folder="/opt/game",
    help_key="mods.help_valheim",
    community="valheim",
    loader=("denikson", "BepInExPack_Valheim"),
    # A guess, not measured: Valheim needs much less than V Rising. Measure when proving it.
    min_memory_mb=4096,
    audit_paths=("/opt/game/BepInEx", "/opt/game/doorstop_libs"),
    sources=(("mods.source_thunderstore", "https://thunderstore.io/c/valheim/"),),
    proven=False,
    linux_bepinex=True,
)

RUST = ModProfile(
    key="rust",
    kind=KIND_OXIDE,
    services=("rust",),
    # The PLUGINS folder (.cs); Oxide goes into the game folder (RustDedicated_Data/Managed).
    folder="/opt/game/oxide/plugins",
    loader_dir="/opt/game",
    help_key="mods.help_rust",
    extensions=(".cs",),
    audit_paths=("/opt/game/oxide/plugins", "/opt/game/.gamepanel-oxide/package"),
    sources=(("mods.source_umod", "https://umod.org/plugins?page=1&categories=rust"),),
    proven=False,
)

UE4SS_LINUX_DOCS = "https://github.com/ocristopfer/RE-UE4SS/blob/linux/docs/linux.md"


def _unreal_linux(key: str, services: tuple[str, ...], project: str, engine: str) -> ModProfile:
    """Native Linux Unreal server with UE4SS from release linux-v2, proven on a real server
    in Docker (2026-10-04/05) with the full proof: Lua, FindFirstOf finding the map's GameState,
    native and Blueprint RegisterHook, ExecuteInGameThread. The CT generates this game's files from
    the version's reference pack (ue_linux_layout): every studio tweaks the engine, and the built-in
    layout alone brought down more than half of these servers. proven=False until the first
    install through this screen on a real CT."""
    paks = f"/opt/game/{project}/Content/Paks/~mods"
    loader = f"/opt/game/{project}/Binaries/Linux"
    # Unreal 5 (IoStore): the mod comes in three files with the same name, and the .pak alone does not load.
    extensions = (".pak", ".utoc", ".ucas") if engine.startswith("5.") else (".pak",)
    return ModProfile(
        key=key, kind=KIND_UE4SS_LINUX, services=services, folder=paks, help_key="mods.help_unreal_linux",
        extensions=extensions, loader_dir=loader, ue4ss_release="linux-v2", engine_version=engine,
        audit_paths=(paks, f"{loader}/ue4ss"), sources=(("mods.source_ue4ss_linux", UE4SS_LINUX_DOCS),),
        proven=False)


# The service names are the curated catalog one (when there is one) and the key of the LinuxGSM or
# Pterodactyl suggestion, which becomes the service name of a game created by the panel.
SOULMASK = _unreal_linux("soulmask", ("soulmask",), "WS", "4.27")
# The Front: crashed ONCE in four startups with UE4SS (no trace in the log; in the other three the
# proof passed in full). Known and unexplained: if it happens on a CT, the service comes back on its own.
THE_FRONT = _unreal_linux("the-front", ("the-front", "thefront"), "ProjectWar", "4.27")
SMALLAND = _unreal_linux("smalland", ("smalland", "smalland-survive-the-wil"), "SMALLAND", "4.27")
SANDSTORM = _unreal_linux("insurgency-sandstorm", ("insurgency-sandstorm", "sandstorm"), "Insurgency", "4.27")
ASTRO_COLONY = _unreal_linux("astro-colony", ("astro-colony",), "AstroColony", "4.27")
SQUAD_44 = _unreal_linux("squad-44", ("squad-44", "squad44"), "PostScriptum", "4.27")
MORDHAU = _unreal_linux("mordhau", ("mordhau",), "Mordhau", "4.26")
HYPERCHARGE = _unreal_linux("hypercharge-unboxed", ("hypercharge-unboxed",), "Unboxed", "4.26")
PAVLOV = _unreal_linux("pavlov-vr", ("pavlov-vr", "pavlov"), "Pavlov", "5.1")
THE_BUS = _unreal_linux("the-bus", ("the-bus",), "TheBus", "5.6")
VEIN = _unreal_linux("vein", ("vein",), "Vein", "5.6")
SQUAD = _unreal_linux("squad", ("squad",), "SquadGame", "5.7")
QANGA = _unreal_linux("qanga", ("qanga",), "Qanga", "5.7")
UNREAL_LINUX = (SOULMASK, THE_FRONT, SMALLAND, SANDSTORM, ASTRO_COLONY, SQUAD_44, MORDHAU, HYPERCHARGE, PAVLOV,
                THE_BUS, VEIN, SQUAD, QANGA)

# Workshop through the config. All four proven on a real server (Docker, 2026-10-05) with
# workshop_remote writing the list and the game downloading and loading the mod on the next start:
# DST (Global Positions, Show Me), Zomboid Build 42 (Common Sense), Unturned (Hawaii + the assets,
# a dependency it downloads on its own) and Reforger (Where Am I). proven=False until the first time
# through this screen on a CT. audit_paths is where EACH game keeps what it downloaded: that is
# where the antivirus goes, since the download is done by the game and not by the panel.
DST = ModProfile(
    key="dst", kind=KIND_WORKSHOP, services=("don-t-starve-together", "dst", "dontstarve"),
    folder="/opt/game", help_key="mods.help_workshop_dst", workshop_appid=322330, workshop_format="dst",
    audit_paths=("/opt/game/ugc_mods", "/opt/game/mods"),
    sources=(("mods.source_workshop", "https://steamcommunity.com/app/322330/workshop/"),),
    proven=False,
)
ZOMBOID = ModProfile(
    key="zomboid", kind=KIND_WORKSHOP, services=("project-zomboid", "zomboid", "pz"),
    folder="/opt/game", help_key="mods.help_workshop_zomboid", workshop_appid=108600, workshop_format="zomboid",
    audit_paths=("/opt/game/steamapps/workshop/content/108600",),
    sources=(("mods.source_workshop", "https://steamcommunity.com/app/108600/workshop/"),),
    proven=False,
)
UNTURNED = ModProfile(
    key="unturned", kind=KIND_WORKSHOP, services=("unturned",),
    folder="/opt/game", help_key="mods.help_workshop_unturned", workshop_appid=304930, workshop_format="unturned",
    audit_paths=("/opt/game/Servers",),
    sources=(("mods.source_workshop", "https://steamcommunity.com/app/304930/workshop/"),),
    proven=False,
)
REFORGER = ModProfile(
    key="arma-reforger", kind=KIND_WORKSHOP, services=("arma-reforger", "reforger"),
    folder="/opt/game", help_key="mods.help_workshop_reforger", workshop_format="reforger",
    audit_paths=("/opt/game/profiles",),
    sources=(("mods.source_reforger_workshop", "https://reforger.armaplatform.com/workshop"),),
    proven=False,
)
WORKSHOP_BY_CONFIG = (DST, ZOMBOID, UNTURNED, REFORGER)

PROFILES = (ETS2, PALWORLD, VRISING, DRAGONWILDS, ENSHROUDED, ICARUS, SATISFACTORY, VALHEIM, RUST, *UNREAL_LINUX,
            *WORKSHOP_BY_CONFIG)


def service_stem(service: str) -> str:
    return (service or "").strip().removesuffix(".service")


def profile_for(service: str) -> ModProfile | None:
    stem = service_stem(service)
    return next((p for p in PROFILES if stem in p.services), None)


# A ficsit.app mod reference, bare or inside the page link (ficsit.app/mod/<ref>).
# The same shape sml_remote checks again in the CT: it becomes a folder name.
_FICSIT_REF = re.compile(r"^(?:https?://(?:www\.)?ficsit\.app/mod/)?([A-Za-z0-9_]{1,64})/?(?:[?#].*)?$", re.ASCII)


def ficsit_ref(text: str) -> str:
    found = _FICSIT_REF.match((text or "").strip())
    return found.group(1) if found else ""
