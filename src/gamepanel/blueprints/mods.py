"""The Mods screen: what mods the server loads, and how to send mods to it.

What "mod" means changes per game, and the profile is what knows (`games/mods/profiles.py`):
in ETS2 the screen reads the `server_packages` and says what each player needs to have; in Palworld
it lists and receives the `.pak` files of the mods folder. Everything is admin-only, like the Files
screen: the upload writes inside the container.
"""
from __future__ import annotations

import json
import posixpath
import secrets
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.games.mods import (
    antivirus,
    oxide_remote,
    profiles,
    shroudtopia_remote,
    sml_remote,
    thunderstore,
    thunderstore_remote,
    ue4ss_linux_remote,
    ue4ss_remote,
    ue_linux_layout,
    ue_sym_layout,
    workshop,
    workshop_remote,
)
from gamepanel.games.mods import ets2 as ets2_mods
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.runtime import remote_cmd

bp = Blueprint("mods", __name__)

# The Thunderstore installer goes to the CT as TEXT and runs there with `python3 -c`: the CT does not
# have the panel package, and it (not the panel) is the one that can reach the internet.
REMOTE_SOURCE = Path(thunderstore_remote.__file__).read_text(encoding="utf-8")
SHROUDTOPIA_SOURCE = Path(shroudtopia_remote.__file__).read_text(encoding="utf-8")
UE4SS_SOURCE = Path(ue4ss_remote.__file__).read_text(encoding="utf-8")
OXIDE_SOURCE = Path(oxide_remote.__file__).read_text(encoding="utf-8")
SML_SOURCE = Path(sml_remote.__file__).read_text(encoding="utf-8")
UE4SS_LINUX_SOURCE = Path(ue4ss_linux_remote.__file__).read_text(encoding="utf-8")
# The generator of VTableLayout.ini and UE4SS_Signatures: goes as text to the CT, which runs it
# against the game's .sym (only servers that ship one; a modified engine, like Dragonwilds, needs it).
UE_SYM_SOURCE = Path(ue_sym_layout.__file__).read_text(encoding="utf-8")
# The generator that uses the version's reference pack (servers WITHOUT .sym, and the globals of those with one).
UE_LINUX_LAYOUT_SOURCE = Path(ue_linux_layout.__file__).read_text(encoding="utf-8")
# Workshop through the config: the script only reads and writes the mod list in the game config, on the CT.
WORKSHOP_SOURCE = Path(workshop_remote.__file__).read_text(encoding="utf-8")
# Downloading BepInEx (33 MB) and the dependencies takes minutes: it becomes a job, with its own log and deadline.
INSTALL_TIMEOUT = 1800
LOADER_ACTIONS = ("install", "enable", "disable", "uninstall")
# The screen's own endpoint, where every action returns to.
INDEX = "mods.index"

# Cap on the text pasted as the reference list: it is a list of mods, not a file.
EXPECTED_MAX_CHARS = 20000


def _profile_or_none(server) -> profiles.ModProfile | None:
    return profiles.profile_for(server["service"])


def _expected_ids(server) -> list[int]:
    return [int(x) for x in (server["mods_expected"] or "").split() if x.isdigit()]


def _packages_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    """What the server_packages say, and the comparison with the reference list."""
    try:
        opened = panel.read_file(server, f"{profile.folder}/server_packages.sii")
    except panel.RemoteError:
        # No package yet is the normal state of a new server, not an error: the screen
        # explains what to export.
        return {"packages": None, "missing": [], "extra": []}
    if opened["binary"] or opened["truncated"]:
        errors.append(panel.translate("mods.packages_unreadable"))
        return {"packages": None, "missing": [], "extra": []}
    packages = ets2_mods.parse(opened["text"])
    present = set(packages.workshop_ids)
    expected = _expected_ids(server)
    return {
        "packages": packages,
        "missing": [i for i in expected if i not in present],
        # Talking about "extra" only makes sense when someone said what was supposed to be there.
        "extra": [m for m in packages.mods if m.workshop_id and expected and m.workshop_id not in expected],
    }


def _folder_view(server, profile: profiles.ModProfile) -> dict:
    try:
        entries, _ = panel.list_dir(server, profile.folder)
    except panel.RemoteError:
        # A folder that does not exist yet = no mods; it is created on the first upload.
        return {"files": []}
    return {"files": [e for e in entries if not e["dir"] and profile.accepts(e["name"])]}


# Native loader (DLL next to the .exe under Proton) -> the installer that runs on the CT.
NATIVE_LOADERS = {profiles.KIND_SHROUDTOPIA: SHROUDTOPIA_SOURCE, profiles.KIND_UE4SS: UE4SS_SOURCE,
                  profiles.KIND_OXIDE: OXIDE_SOURCE}
# Loader name in the task history.
LOADER_NAMES = {profiles.KIND_SHROUDTOPIA: "Shroudtopia", profiles.KIND_UE4SS: "UE4SS",
                profiles.KIND_OXIDE: "Oxide", profiles.KIND_SML: "SML",
                profiles.KIND_UE4SS_LINUX: "UE4SS Linux"}

# Every action that DOWNLOADS something brings the antivirus along; the remote installer refuses to install without it.
SCANNED_ACTIONS = ("loader-install", "plugin-install", "mod-install")

# The installers that change the game's ENVIRONMENT (a systemd drop-in, /etc/game-runtime.env, ARK's
# ExecStart). In legacy mode they write those as root, exactly as always. In helper mode they run as
# steam with `--overlay` and write steam's overlay instead (/etc/gamepanel/game-env, which
# lib/ct-panel-access.sh prepared once, as root): phase 6 of docs/security-hardening.md.
OVERLAY_KINDS = (profiles.KIND_THUNDERSTORE, profiles.KIND_SHROUDTOPIA, profiles.KIND_UE4SS,
                 profiles.KIND_UE4SS_LINUX)


def uses_overlay(profile: profiles.ModProfile) -> bool:
    return profile.kind in OVERLAY_KINDS or profile.workshop_format in profiles.ENV_WORKSHOP_FORMATS


def _remote_cmd(server, profile: profiles.ModProfile, action: str, *args: str, service: str = "") -> str:
    """The installer command for this server: as root in legacy mode, as steam in helper mode."""
    helper = not remote_cmd.privileged(server)
    return remote_cmd.as_steam(server, *_installer_argv(profile, action, *args, service=service, helper=helper))


def _installer_steps(server, profile: profiles.ModProfile, action: str, *args: str, service: str = "") -> list[str]:
    """The job steps of one installer action.

    Helper mode: an action that downloads gets the ClamAV install through the fixed root helper
    first (steam can neither apt-get nor stop the freshclam daemon), and its scan script only
    CHECKS - the same split the mod upload uses (`antivirus.scan_steps`).
    """
    command = _remote_cmd(server, profile, action, *args, service=service)
    if action in SCANNED_ACTIONS and not remote_cmd.privileged(server):
        return [remote_cmd.clamav_ensure(), command]
    return [command]


def _installer_argv(profile: profiles.ModProfile, action: str, *args: str, service: str = "",
                    helper: bool = False) -> tuple[str, ...]:
    script = antivirus.SCAN_SCRIPT_AS_STEAM if helper else antivirus.SCAN_SCRIPT
    scan = ("--scan", script) if action in SCANNED_ACTIONS else ()
    # First word, so every installer can take it off before its own options.
    overlay = ("--overlay",) if helper and uses_overlay(profile) else ()
    # The drop-in goes on THIS server's service: the profile serves more than one name (the curated
    # catalog's and the LinuxGSM suggestion's), and the first in the list may not even exist on this CT.
    unit_name = profiles.service_stem(service) or profile.services[0]
    if profile.kind == profiles.KIND_WORKSHOP:
        # The config comes from THIS service's ExecStart (-servername, -config, +InternetServer/...).
        return ("python3", "-c", WORKSHOP_SOURCE, *overlay, "--unit", f"{unit_name}.service",
                profile.workshop_format, action, profile.folder, *args)
    if profile.kind == profiles.KIND_SML:
        return ("python3", "-c", SML_SOURCE, *scan, action, profile.loader_dir, *args)
    if profile.kind == profiles.KIND_UE4SS_LINUX:
        # LD_PRELOAD for this service; the name comes from the profile (chosen by it).
        unit = ("--unit", f"{unit_name}.service")
        # The release only matters when installing (the generators are ~40 KB of wasted text in the status).
        release = ("--release", profile.ue4ss_release, "--engine", profile.engine_version,
                   "--symfiles", UE_SYM_SOURCE, "--layout", UE_LINUX_LAYOUT_SOURCE,
                   ) if action == "loader-install" else ()
        return ("python3", "-c", UE4SS_LINUX_SOURCE, *overlay, *scan, *unit, *release, action, profile.loader_dir,
                *args)
    if profile.kind in NATIVE_LOADERS:
        # The loader lives one level above the mods folder: next to the game executable.
        source = NATIVE_LOADERS[profile.kind]
        game_dir = profile.loader_dir or posixpath.dirname(profile.folder)
        return ("python3", "-c", source, *overlay, *scan, action, game_dir, *args)
    # Native Linux server (Valheim): the installer writes this service's drop-in. The name comes
    # from the profile, which was chosen precisely by the service name.
    unit_args: tuple[str, ...] = ("--unit", f"{unit_name}.service") if profile.linux_bepinex else ()
    return ("python3", "-c", REMOTE_SOURCE, *overlay, *scan, *unit_args, action, profile.folder, *profile.loader,
            *args)


def _remote_state(server, profile: profiles.ModProfile, errors: list[str]) -> dict | None:
    """The last JSON line from the remote installer, or None (with the reason in `errors`)."""
    try:
        proc = panel.ssh_run(server, _remote_cmd(server, profile, "status", service=server["service"]), timeout=40)
        lines = (proc.stdout or "").strip().splitlines()
        state = json.loads(lines[-1]) if lines else {}
    except (panel.RemoteError, ValueError) as exc:
        errors.append(panel.translate("mods.status_failed", reason=panel.error_text(exc)))
        return None
    if "error" in state:
        errors.append(panel.translate("mods.status_failed", reason=state["error"]))
        return None
    return state


def _workshop_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    """The list from the game config, each mod with its link and whether the game already downloaded it."""
    state = _remote_state(server, profile, errors)
    if state is None:
        return {"state": None}
    reforger = profile.workshop_format == "reforger"
    installed = set(state.get("installed", []))
    names = state.get("names", {})
    available = state.get("available", {})
    rejected = state.get("rejected", {})
    state["items"] = [{
        "id": i,
        "url": _item_url(profile, i),
        "name": names.get(i, ""),
        "installed": i in installed,
        "mod_ids": available.get(i, []),
        "rejected": rejected.get(i, ""),
    } for i in state.get("ids", [])]
    # What goes in the field: the same list, one per line (with the name, in Reforger).
    state["text"] = "\n".join(f"{i} {names.get(i, '')}".strip() if reforger else i for i in state.get("ids", []))
    return {"state": state}


def _item_url(profile: profiles.ModProfile, item: str) -> str:
    if profile.workshop_format == "reforger":
        return workshop.reforger_url(item)
    if profile.workshop_format == "ark":
        # CurseForge has no page address built from the project ID alone that could be checked
        # (it answers 403 to anything but a browser): the screen shows the number, and the
        # "where to find" button goes to the game's mod listing.
        return ""
    return workshop.url(int(item))


def _shroudtopia_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    return {"state": _remote_state(server, profile, errors)}


def _thunderstore_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    """The state of BepInEx and the plugins, read on the spot (it only lists folders: it is fast)."""
    state = _remote_state(server, profile, errors)
    if state is None:
        return {"state": None}
    for p in state.get("plugins", []):
        parts = thunderstore.split_dir(p.get("dir", ""))
        p["url"] = thunderstore.package_url(profile.community, *parts) if parts else ""
    low_memory = 0 < state.get("memory_mb", 0) < profile.min_memory_mb
    return {"state": state, "low_memory": low_memory}


@bp.get("/servers/<int:sid>/mods")
@panel.admin_required
def index(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    errors: list[str] = []
    view: dict = {}
    if profile and profile.kind == profiles.KIND_PACKAGES:
        view = _packages_view(server, profile, errors)
    elif profile and profile.kind == profiles.KIND_THUNDERSTORE:
        view = _thunderstore_view(server, profile, errors)
    elif profile and (profile.kind in NATIVE_LOADERS or profile.kind == profiles.KIND_SML):
        view = _shroudtopia_view(server, profile, errors)
    elif profile and profile.kind == profiles.KIND_FOLDER:
        view = _folder_view(server, profile)
    elif profile and profile.kind == profiles.KIND_WORKSHOP:
        view = _workshop_view(server, profile, errors)
    elif profile and profile.kind == profiles.KIND_UE4SS_LINUX:
        # Both: the loader (status on the CT) and the .pak files of the profile folder.
        view = {**_shroudtopia_view(server, profile, errors), **_folder_view(server, profile)}
    return render_template(
        "mods.html", server=server, profile=profile, view=view, errors=errors,
        expected_text="\n".join(str(i) for i in _expected_ids(server)),
        workshop_url=workshop.url, kind_packages=profiles.KIND_PACKAGES,
        kind_thunderstore=profiles.KIND_THUNDERSTORE, kind_folder=profiles.KIND_FOLDER,
        kind_shroudtopia=profiles.KIND_SHROUDTOPIA, kind_ue4ss=profiles.KIND_UE4SS,
        kind_sml=profiles.KIND_SML, kind_oxide=profiles.KIND_OXIDE, kind_ue4ss_linux=profiles.KIND_UE4SS_LINUX,
        kind_workshop=profiles.KIND_WORKSHOP, loader_url=_loader_url(profile),
    )


def _loader_url(profile: profiles.ModProfile | None) -> str:
    if not profile or not profile.community:
        return ""
    return thunderstore.package_url(profile.community, *profile.loader)


def _thunderstore_job(sid: int, action: str, step: str | list[str], label: str):
    """Trigger the Thunderstore job (and the restart, if asked) and go to its screen."""
    server = panel._server_or_404(sid)
    steps: list[panel.JobStep] = list(step) if isinstance(step, list) else [step]
    # Plugin and BepInEx only take effect when the server starts again. The restart is a STEP of the same
    # job: if the install fails, the server does not restart in the middle of a broken install.
    if request.form.get("restart") == "1":
        steps.append(panel.COMMANDS["restart"](server))
    job_id = panel.start_job(action, server, session.get("username", "?"), command=label,
                             timeout=INSTALL_TIMEOUT, steps=steps)
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


# Profiles where the panel installs the LOADER (the "Install/Enable/Disable" button).
LOADER_KINDS = (profiles.KIND_THUNDERSTORE, *NATIVE_LOADERS, profiles.KIND_SML, profiles.KIND_UE4SS_LINUX)


def _loader_profile_or_back(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    if not profile or profile.kind not in LOADER_KINDS:
        flash(panel.translate("mods.not_thunderstore"), "error")
        return None
    return profile


def _thunderstore_profile_or_back(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    if not profile or profile.kind != profiles.KIND_THUNDERSTORE:
        flash(panel.translate("mods.not_thunderstore"), "error")
        return None
    return profile


def _form_version() -> str | None:
    """The version from the form field: empty = the newest; None = invalid (and it already warned)."""
    version = thunderstore.parse_version(request.form.get("version", ""))
    if version is None:
        flash(panel.translate("mods.bad_version"), "error")
    return version


def _with_version(label: str, version: str) -> str:
    return f"{label}@{version}" if version else label


@bp.post("/servers/<int:sid>/mods/loader")
@panel.admin_required
def loader(sid: int):
    profile = _loader_profile_or_back(sid)
    action = request.form.get("action", "")
    if not profile or action not in LOADER_ACTIONS:
        return redirect(url_for(INDEX, sid=sid))
    # The version only applies to installing: enabling and disabling download nothing.
    version = _form_version() if action == "install" else ""
    if version is None:
        return redirect(url_for(INDEX, sid=sid))
    server = panel._server_or_404(sid)
    name = LOADER_NAMES.get(profile.kind) or "-".join(profile.loader)
    args = (version,) if version else ()
    if profile.kind == profiles.KIND_SML:
        # SML is a ficsit.app mod like the others: it is only installed or updated, never disabled.
        if action != "install":
            return redirect(url_for(INDEX, sid=sid))
        return _thunderstore_job(sid, "mod-loader", _installer_steps(server, profile, "mod-install", "SML", *args),
                                 _with_version("SML: install", version))
    command = _installer_steps(server, profile, f"loader-{action}", *args, service=server["service"] or "")
    return _thunderstore_job(sid, "mod-loader", command, _with_version(f"{name}: {action}", version))


@bp.post("/servers/<int:sid>/mods/plugin/install")
@panel.admin_required
def plugin_install(sid: int):
    profile = _thunderstore_profile_or_back(sid)
    if not profile:
        return redirect(url_for(INDEX, sid=sid))
    parsed = thunderstore.parse_package(request.form.get("package", ""))
    if not parsed:
        flash(panel.translate("mods.bad_package"), "error")
        return redirect(url_for(INDEX, sid=sid))
    ns, name, pasted_version = parsed
    # The version field wins over the version pasted into the name: it is what the person chose
    # last. And it is how the version of an already installed mod is changed (the table row).
    version = _form_version()
    if version is None:
        return redirect(url_for(INDEX, sid=sid))
    version = version or pasted_version
    args = (ns, name, version) if version else (ns, name)
    command = _installer_steps(panel._server_or_404(sid), profile, "plugin-install", *args)
    return _thunderstore_job(sid, "mod-install", command,
                             _with_version(f"{ns}/{name}", version))


@bp.post("/servers/<int:sid>/mods/plugin/remove")
@panel.admin_required
def plugin_remove(sid: int):
    profile = _thunderstore_profile_or_back(sid)
    parsed = thunderstore.split_dir(request.form.get("dir", ""))
    if not profile or not parsed:
        return redirect(url_for(INDEX, sid=sid))
    ns, name = parsed
    command = _installer_steps(panel._server_or_404(sid), profile, "plugin-remove", ns, name)
    return _thunderstore_job(sid, "mod-remove", command, f"{ns}/{name}")


def _sml_profile_or_back(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    if not profile or profile.kind != profiles.KIND_SML:
        flash(panel.translate("mods.not_thunderstore"), "error")
        return None
    return profile


@bp.post("/servers/<int:sid>/mods/sml/install")
@panel.admin_required
def sml_install(sid: int):
    """A ficsit.app mod (and its dependencies), by reference or by the page link."""
    profile = _sml_profile_or_back(sid)
    if not profile:
        return redirect(url_for(INDEX, sid=sid))
    ref = profiles.ficsit_ref(request.form.get("mod", ""))
    if not ref:
        flash(panel.translate("mods.sml_bad_ref"), "error")
        return redirect(url_for(INDEX, sid=sid))
    version = _form_version()
    if version is None:
        return redirect(url_for(INDEX, sid=sid))
    args = (ref, version) if version else (ref,)
    command = _installer_steps(panel._server_or_404(sid), profile, "mod-install", *args)
    return _thunderstore_job(sid, "mod-install", command,
                             _with_version(ref, version))


@bp.post("/servers/<int:sid>/mods/sml/remove")
@panel.admin_required
def sml_remove(sid: int):
    profile = _sml_profile_or_back(sid)
    ref = profiles.ficsit_ref(request.form.get("mod", ""))
    if not profile or not ref:
        return redirect(url_for(INDEX, sid=sid))
    command = _installer_steps(panel._server_or_404(sid), profile, "mod-remove", ref)
    return _thunderstore_job(sid, "mod-remove", command, ref)


@bp.post("/servers/<int:sid>/mods/workshop")
@panel.admin_required
def workshop_save(sid: int):
    """Replace the Workshop mod list in the game config; the game downloads it on the next start."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for(INDEX, sid=sid)
    if not profile or profile.kind != profiles.KIND_WORKSHOP:
        flash(panel.translate("mods.not_thunderstore"), "error")
        return redirect(go_back)
    text = (request.form.get("ids") or "")[:EXPECTED_MAX_CHARS]
    if profile.workshop_format == "reforger":
        items = [f"{guid}={name}" if name else guid for guid, name in workshop.parse_guids(text)]
    else:
        items = [str(i) for i in workshop.parse_ids(text)]
    # An empty list only counts if the field came empty: text that yielded no ID is a paste error,
    # and saving it would erase every mod on the server.
    if text.strip() and not items:
        flash(panel.translate("mods.workshop_bad_ids"), "error")
        return redirect(go_back)
    extra: tuple[str, ...] = ()
    if profile.workshop_format == "zomboid":
        mods = " ".join((request.form.get("mods") or "").split())
        if not workshop_remote.ZOMBOID_MODS.match(mods):
            flash(panel.translate("mods.zomboid_bad_mods"), "error")
            return redirect(go_back)
        extra = ("--mods", mods)
    label = f"workshop: {len(items)}"
    if profile.workshop_format in profiles.SCANNED_WORKSHOP_FORMATS:
        return _thunderstore_job(sid, "mod-workshop", _download_steps(server, profile, items), label)
    command = _remote_cmd(server, profile, "set", *items, *extra, service=server["service"])
    return _thunderstore_job(sid, "mod-workshop", command, label)


def _download_steps(server, profile: profiles.ModProfile, items: list[str]) -> list[str]:
    """Download what is new, scan it, and only then put it in the game (Conan).

    Only the IDs the server does not have yet are downloaded, unless the person asks to update
    all of them: re-fetching hundreds of MB to remove one mod would be a slow way to say no. With
    nothing to download there is nothing to scan either, and ClamAV is not installed for it.
    """
    service = server["service"]
    state = _remote_state(server, profile, [])
    have = set((state or {}).get("installed", []))
    new = list(items) if request.form.get("refresh") == "1" else [i for i in items if i not in have]
    if not new:
        return [_remote_cmd(server, profile, "set", *items, service=service)]
    staging = antivirus.incoming_dir(secrets.token_hex(16))
    return [
        antivirus.incoming_command(server, staging),
        _remote_cmd(server, profile, "fetch", *new, "--staging", staging, service=service),
        *antivirus.scan_steps(server, staging),
        _remote_cmd(server, profile, "set", *items, "--staging", staging, service=service),
    ]


def _checked_name(profile: profiles.ModProfile, sent) -> str:
    """The name the file will have in the container, or ValueError if the profile does not accept it."""
    # Only the last part of the name: "../../etc/passwd" does not become a path.
    name = sent.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or not profile.accepts(name):
        allowed = ", ".join(profile.upload_names or profile.extensions)
        raise ValueError(panel.translate("mods.bad_name", name=name or "?", allowed=allowed))
    return name


def _upload_one(server, incoming: str, sent, name: str) -> str:
    """Send ONE file (already checked) to the STAGING folder. Return the container's output."""
    command = remote_cmd.as_steam(server, "bash", "-lc", panel.UPLOAD_SCRIPT, "gp", f"{incoming}/{name}")
    return panel.ssh_stream_in(server, command, sent.stream, timeout=panel.JOB_TIMEOUT)


@bp.post("/servers/<int:sid>/mods/upload")
@panel.admin_required
def upload(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for(INDEX, sid=sid)
    sent = [f for f in request.files.getlist("file") if f and f.filename]
    if not profile or not sent:
        flash(panel.translate("flash.pick_a_file"), "error")
        return redirect(go_back)

    user = session.get("username", "?")
    # The file NEVER goes straight to the mods folder: it goes to staging, outside the game
    # folder, and a job scans it with the antivirus and only then moves it. A scan that finds something or
    # does not run deletes the staging, and the server does not restart (the restart is the last step).
    incoming = antivirus.incoming_dir(secrets.token_hex(16))
    try:
        # ALL the names before anything goes to the container: an Unreal 5 mod comes in three
        # files, and sending two and rejecting the third would leave a half mod in the folder.
        names = [_checked_name(profile, f) for f in sent]
        proc = panel.ssh_run(server, antivirus.incoming_command(server, incoming), timeout=40)
        if proc.returncode != 0:
            raise panel.RemoteError((proc.stderr or proc.stdout).strip() or incoming)
        for f, n in zip(sent, names, strict=True):
            _upload_one(server, incoming, f, n)
    except (ValueError, panel.RemoteError) as exc:
        panel.log_job("upload-mod", server, user, command=profile.folder, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_upload", reason=panel.error_text(exc)), "error")
        return redirect(go_back)

    steps: list[panel.JobStep] = [
        *antivirus.scan_steps(server, incoming),
        antivirus.place_command(server, incoming, profile.folder),
    ]
    # A mod only takes effect when the server starts again: restart lives here, as on the Config screen.
    if request.form.get("restart") == "1":
        steps.append(panel.COMMANDS["restart"](server))
    job_id = panel.start_job("upload-mod", server, user, command=f"{profile.folder}: {', '.join(names)}",
                             timeout=INSTALL_TIMEOUT, steps=steps)
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/mods/audit")
@panel.admin_required
def audit(sid: int):
    """Run the antivirus over what is ALREADY installed (what came in before it). Read-only."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    if not profile:
        return redirect(url_for(INDEX, sid=sid))
    paths = profile.scan_paths
    job_id = panel.start_job("mod-audit", server, session.get("username", "?"), command=" ".join(paths),
                             timeout=INSTALL_TIMEOUT,
                             steps=list(antivirus.audit_steps(server, paths)))
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/mods/delete")
@panel.admin_required
def delete(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for(INDEX, sid=sid)
    name = (request.form.get("name") or "").strip()
    # Only the mod file in the profile folder, by name: no path coming from the form.
    # Mods folder with loose files: the one for .pak files and the one for Shroudtopia DLLs.
    deletable = (profiles.KIND_FOLDER, profiles.KIND_SHROUDTOPIA, profiles.KIND_OXIDE, profiles.KIND_UE4SS_LINUX)
    if not profile or profile.kind not in deletable or "/" in name or not profile.accepts(name):
        flash(panel.translate("mods.bad_name", name=name or "?",
                              allowed=", ".join(profile.extensions if profile else ())), "error")
        return redirect(go_back)
    path = f"{profile.folder}/{name}"
    user = session.get("username", "?")
    try:
        output = panel.delete_file(server, panel.clean_path(path))
    except (ValueError, panel.RemoteError) as exc:
        panel.log_job("delete-mod", server, user, command=path, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_delete", reason=panel.error_text(exc)), "error")
        return redirect(go_back)
    panel.log_job("delete-mod", server, user, command=path, output=output)
    flash(panel.translate("mods.deleted", name=name), "ok")
    return redirect(go_back)


@bp.post("/servers/<int:sid>/mods/expected")
@panel.admin_required
def expected(sid: int):
    """Store the reference list: the Workshop IDs the server should have."""
    panel._server_or_404(sid)
    ids = workshop.parse_ids((request.form.get("expected") or "")[:EXPECTED_MAX_CHARS])
    conn = panel.db()
    with conn:
        servers_repo.set_mods_expected(conn, sid, ids)
    flash(panel.translate("mods.expected_saved", n=len(ids)), "ok")
    return redirect(url_for(INDEX, sid=sid))
