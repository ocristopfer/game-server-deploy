"""A tela Mods: o que o servidor carrega de mod, e como mandar mod para ele.

O que "mod" significa muda por jogo, e quem sabe e o perfil (`games/mods/profiles.py`):
no ETS2 a tela le os `server_packages` e diz o que cada jogador precisa ter; no Palworld
ela lista e recebe os `.pak` da pasta de mods. Tudo e de admin, como a tela Arquivos: o
envio grava dentro do container.
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
    ue_sym_layout,
    workshop,
)
from gamepanel.games.mods import ets2 as ets2_mods
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("mods", __name__)

# O instalador do Thunderstore vai para o CT como TEXTO e roda la com `python3 -c`: o CT nao
# tem o pacote do painel, e e ele (nao o painel) quem pode ir a internet.
REMOTE_SOURCE = Path(thunderstore_remote.__file__).read_text(encoding="utf-8")
SHROUDTOPIA_SOURCE = Path(shroudtopia_remote.__file__).read_text(encoding="utf-8")
UE4SS_SOURCE = Path(ue4ss_remote.__file__).read_text(encoding="utf-8")
OXIDE_SOURCE = Path(oxide_remote.__file__).read_text(encoding="utf-8")
SML_SOURCE = Path(sml_remote.__file__).read_text(encoding="utf-8")
UE4SS_LINUX_SOURCE = Path(ue4ss_linux_remote.__file__).read_text(encoding="utf-8")
# O gerador do VTableLayout.ini e das UE4SS_Signatures: vai como texto para o CT, que o roda
# contra o .sym do jogo (so servidor que traz um; motor modificado, como o Dragonwilds, pede).
UE_SYM_SOURCE = Path(ue_sym_layout.__file__).read_text(encoding="utf-8")
# Baixar o BepInEx (33 MB) e as dependencias leva minutos: vira job, com log e prazo proprio.
INSTALL_TIMEOUT = 1800
LOADER_ACTIONS = ("install", "enable", "disable")
# O endpoint da propria tela, para onde toda acao volta.
INDEX = "mods.index"

# Teto do texto colado como gabarito: a lista e de mods, nao um arquivo.
EXPECTED_MAX_CHARS = 20000


def _profile_or_none(server) -> profiles.ModProfile | None:
    return profiles.profile_for(server["service"])


def _expected_ids(server) -> list[int]:
    return [int(x) for x in (server["mods_expected"] or "").split() if x.isdigit()]


def _packages_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    """O que os server_packages dizem, e o confronto com o gabarito."""
    try:
        opened = panel.read_file(server, f"{profile.folder}/server_packages.sii")
    except panel.RemoteError:
        # Sem pacote ainda e o estado normal de um servidor novo, e nao erro: a tela
        # explica o que exportar.
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
        # So faz sentido falar em "a mais" quando alguem disse o que era para ter.
        "extra": [m for m in packages.mods if m.workshop_id and expected and m.workshop_id not in expected],
    }


def _folder_view(server, profile: profiles.ModProfile) -> dict:
    try:
        entries, _ = panel.list_dir(server, profile.folder)
    except panel.RemoteError:
        # Pasta que ainda nao existe = nenhum mod; ela nasce no primeiro envio.
        return {"files": []}
    return {"files": [e for e in entries if not e["dir"] and profile.accepts(e["name"])]}


# Carregador nativo (DLL ao lado do .exe sob o Proton) -> o instalador que roda no CT.
NATIVE_LOADERS = {profiles.KIND_SHROUDTOPIA: SHROUDTOPIA_SOURCE, profiles.KIND_UE4SS: UE4SS_SOURCE,
                  profiles.KIND_OXIDE: OXIDE_SOURCE}
# Nome do carregador no historico de tarefas.
LOADER_NAMES = {profiles.KIND_SHROUDTOPIA: "Shroudtopia", profiles.KIND_UE4SS: "UE4SS",
                profiles.KIND_OXIDE: "Oxide", profiles.KIND_SML: "SML",
                profiles.KIND_UE4SS_LINUX: "UE4SS Linux"}

# Toda acao que BAIXA algo leva o antivirus junto; o instalador remoto recusa instalar sem ele.
SCANNED_ACTIONS = ("loader-install", "plugin-install", "mod-install")


def _remote_cmd(profile: profiles.ModProfile, action: str, *args: str) -> str:
    scan = ("--scan", antivirus.SCAN_SCRIPT) if action in SCANNED_ACTIONS else ()
    if profile.kind == profiles.KIND_SML:
        return panel.q("python3", "-c", SML_SOURCE, *scan, action, profile.loader_dir, *args)
    if profile.kind == profiles.KIND_UE4SS_LINUX:
        # LD_PRELOAD num drop-in deste servico; o nome sai do perfil (escolhido por ele).
        service = ("--unit", f"{profile.services[0]}.service")
        # O release so importa ao instalar (o gerador sao ~20 KB de texto a toa no status).
        release = ("--release", profile.ue4ss_release, "--engine", profile.engine_version,
                   "--symfiles", UE_SYM_SOURCE) if action == "loader-install" else ()
        return panel.q("python3", "-c", UE4SS_LINUX_SOURCE, *scan, *service, *release, action, profile.loader_dir,
                       *args)
    if profile.kind in NATIVE_LOADERS:
        # O carregador mora um nivel acima da pasta de mods: ao lado do executavel do jogo.
        source = NATIVE_LOADERS[profile.kind]
        game_dir = profile.loader_dir or posixpath.dirname(profile.folder)
        return panel.q("python3", "-c", source, *scan, action, game_dir, *args)
    # Servidor Linux nativo (Valheim): o instalador escreve o drop-in deste servico. O nome sai
    # do perfil, que foi escolhido justamente pelo nome do servico.
    unit = ("--unit", f"{profile.services[0]}.service") if profile.linux_bepinex else ()
    return panel.q("python3", "-c", REMOTE_SOURCE, *scan, *unit, action, profile.folder, *profile.loader, *args)


def _remote_state(server, profile: profiles.ModProfile, errors: list[str]) -> dict | None:
    """A ultima linha JSON do instalador remoto, ou None (com o motivo em `errors`)."""
    try:
        proc = panel.ssh_run(server, _remote_cmd(profile, "status"), timeout=40)
        lines = (proc.stdout or "").strip().splitlines()
        state = json.loads(lines[-1]) if lines else {}
    except (panel.RemoteError, ValueError) as exc:
        errors.append(panel.translate("mods.status_failed", reason=exc))
        return None
    if "error" in state:
        errors.append(panel.translate("mods.status_failed", reason=state["error"]))
        return None
    return state


def _shroudtopia_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    return {"state": _remote_state(server, profile, errors)}


def _thunderstore_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    """O estado do BepInEx e dos plugins, lido na hora (so lista pastas: e rapido)."""
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
    elif profile and profile.kind == profiles.KIND_UE4SS_LINUX:
        # Os dois: o carregador (status no CT) e os .pak da pasta do perfil.
        view = {**_shroudtopia_view(server, profile, errors), **_folder_view(server, profile)}
    return render_template(
        "mods.html", server=server, profile=profile, view=view, errors=errors,
        expected_text="\n".join(str(i) for i in _expected_ids(server)),
        workshop_url=workshop.url, kind_packages=profiles.KIND_PACKAGES,
        kind_thunderstore=profiles.KIND_THUNDERSTORE, kind_folder=profiles.KIND_FOLDER,
        kind_shroudtopia=profiles.KIND_SHROUDTOPIA, kind_ue4ss=profiles.KIND_UE4SS,
        kind_sml=profiles.KIND_SML, kind_oxide=profiles.KIND_OXIDE, kind_ue4ss_linux=profiles.KIND_UE4SS_LINUX,
        loader_url=_loader_url(profile),
    )


def _loader_url(profile: profiles.ModProfile | None) -> str:
    if not profile or not profile.community:
        return ""
    return thunderstore.package_url(profile.community, *profile.loader)


def _thunderstore_job(sid: int, action: str, step: str, label: str):
    """Dispara o job do Thunderstore (e o reinicio, se pedido) e manda para a tela dele."""
    server = panel._server_or_404(sid)
    steps: list[panel.JobStep] = [step]
    # Plugin e BepInEx so entram quando o servidor sobe de novo. O reinicio e um PASSO do mesmo
    # job: se a instalacao falhar, o servidor nao reinicia no meio de uma instalacao quebrada.
    if request.form.get("restart") == "1":
        steps.append(panel.COMMANDS["restart"](server))
    job_id = panel.start_job(action, server, session.get("username", "?"), command=label,
                             timeout=INSTALL_TIMEOUT, steps=steps)
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


# Perfis em que o painel instala o CARREGADOR (o botao "Instalar/Ligar/Desligar").
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
    """A versao do campo do formulario: vazia = a mais nova; None = invalida (e ja avisou)."""
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
    # A versao so vale para instalar: ligar e desligar nao baixam nada.
    version = _form_version() if action == "install" else ""
    if version is None:
        return redirect(url_for(INDEX, sid=sid))
    name = LOADER_NAMES.get(profile.kind) or "-".join(profile.loader)
    args = (version,) if version else ()
    if profile.kind == profiles.KIND_SML:
        # O SML e um mod do ficsit.app como os outros: so se instala ou atualiza, nao se desliga.
        if action != "install":
            return redirect(url_for(INDEX, sid=sid))
        return _thunderstore_job(sid, "mod-loader", _remote_cmd(profile, "mod-install", "SML", *args),
                                 _with_version("SML: install", version))
    return _thunderstore_job(sid, "mod-loader", _remote_cmd(profile, f"loader-{action}", *args),
                             _with_version(f"{name}: {action}", version))


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
    # O campo de versao vence a versao que veio colada no nome: e o que a pessoa escolheu por
    # ultimo. E e por ele que se troca a versao de um mod ja instalado (a linha da tabela).
    version = _form_version()
    if version is None:
        return redirect(url_for(INDEX, sid=sid))
    version = version or pasted_version
    args = (ns, name, version) if version else (ns, name)
    return _thunderstore_job(sid, "mod-install", _remote_cmd(profile, "plugin-install", *args),
                             _with_version(f"{ns}/{name}", version))


@bp.post("/servers/<int:sid>/mods/plugin/remove")
@panel.admin_required
def plugin_remove(sid: int):
    profile = _thunderstore_profile_or_back(sid)
    parsed = thunderstore.split_dir(request.form.get("dir", ""))
    if not profile or not parsed:
        return redirect(url_for(INDEX, sid=sid))
    ns, name = parsed
    return _thunderstore_job(sid, "mod-remove", _remote_cmd(profile, "plugin-remove", ns, name), f"{ns}/{name}")


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
    """Um mod do ficsit.app (e as dependencias dele), pela referencia ou pelo link da pagina."""
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
    return _thunderstore_job(sid, "mod-install", _remote_cmd(profile, "mod-install", *args),
                             _with_version(ref, version))


@bp.post("/servers/<int:sid>/mods/sml/remove")
@panel.admin_required
def sml_remove(sid: int):
    profile = _sml_profile_or_back(sid)
    ref = profiles.ficsit_ref(request.form.get("mod", ""))
    if not profile or not ref:
        return redirect(url_for(INDEX, sid=sid))
    return _thunderstore_job(sid, "mod-remove", _remote_cmd(profile, "mod-remove", ref), ref)


def _checked_name(profile: profiles.ModProfile, sent) -> str:
    """O nome que o arquivo tera no container, ou ValueError se o perfil nao o aceita."""
    # So a ultima parte do nome: "../../etc/passwd" nao vira caminho.
    name = sent.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or not profile.accepts(name):
        allowed = ", ".join(profile.upload_names or profile.extensions)
        raise ValueError(panel.translate("mods.bad_name", name=name or "?", allowed=allowed))
    return name


def _upload_one(server, incoming: str, sent, name: str) -> str:
    """Manda UM arquivo (ja conferido) para a pasta de ESPERA. Devolve a saida do container."""
    return panel.ssh_stream_in(server, panel.q("bash", "-lc", panel.UPLOAD_SCRIPT, "gp", f"{incoming}/{name}"),
                               sent.stream, timeout=panel.JOB_TIMEOUT)


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
    # O arquivo NUNCA vai direto para a pasta de mods: vai para a espera, fora da pasta do
    # jogo, e um job verifica com o antivirus e so entao move. Verificacao que acha algo ou
    # nao roda apaga a espera, e o servidor nao reinicia (o reinicio e o ultimo passo).
    incoming = antivirus.incoming_dir(secrets.token_hex(16))
    try:
        # TODOS os nomes antes de qualquer coisa ir ao container: um mod de Unreal 5 vem em tres
        # arquivos, e mandar dois e recusar o terceiro deixaria um mod pela metade na pasta.
        names = [_checked_name(profile, f) for f in sent]
        proc = panel.ssh_run(server, panel.q("bash", "-c", antivirus.INCOMING_SCRIPT, "gp", incoming), timeout=40)
        if proc.returncode != 0:
            raise panel.RemoteError((proc.stderr or proc.stdout).strip() or incoming)
        for f, n in zip(sent, names, strict=True):
            _upload_one(server, incoming, f, n)
    except (ValueError, panel.RemoteError) as exc:
        panel.log_job("upload-mod", server, user, command=profile.folder, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_upload", reason=exc), "error")
        return redirect(go_back)

    steps: list[panel.JobStep] = [
        panel.q("bash", "-c", antivirus.SCAN_SCRIPT, "gp", incoming),
        panel.q("bash", "-c", antivirus.PLACE_SCRIPT, "gp", incoming, profile.folder),
    ]
    # Mod so entra quando o servidor sobe de novo: o reiniciar mora aqui, como na tela Config.
    if request.form.get("restart") == "1":
        steps.append(panel.COMMANDS["restart"](server))
    job_id = panel.start_job("upload-mod", server, user, command=f"{profile.folder}: {', '.join(names)}",
                             timeout=INSTALL_TIMEOUT, steps=steps)
    panel.invalidate_status(sid)
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/mods/audit")
@panel.admin_required
def audit(sid: int):
    """Passa o antivirus no que JA esta instalado (o que entrou antes dele). So le."""
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    if not profile:
        return redirect(url_for(INDEX, sid=sid))
    paths = profile.scan_paths
    job_id = panel.start_job("mod-audit", server, session.get("username", "?"), command=" ".join(paths),
                             timeout=INSTALL_TIMEOUT,
                             steps=[panel.q("bash", "-c", antivirus.AUDIT_SCRIPT, "gp", *paths)])
    return redirect(url_for("jobs.detail", jid=job_id))


@bp.post("/servers/<int:sid>/mods/delete")
@panel.admin_required
def delete(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for(INDEX, sid=sid)
    name = (request.form.get("name") or "").strip()
    # So o arquivo de mod da pasta do perfil, pelo nome: nada de caminho vindo do formulario.
    # Pasta de mods com arquivo solto: a dos .pak e a das DLLs do Shroudtopia.
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
        flash(panel.translate("flash.could_not_delete", reason=exc), "error")
        return redirect(go_back)
    panel.log_job("delete-mod", server, user, command=path, output=output)
    flash(panel.translate("mods.deleted", name=name), "ok")
    return redirect(go_back)


@bp.post("/servers/<int:sid>/mods/expected")
@panel.admin_required
def expected(sid: int):
    """Guarda o gabarito: os IDs da Workshop que o servidor deveria ter."""
    panel._server_or_404(sid)
    ids = workshop.parse_ids((request.form.get("expected") or "")[:EXPECTED_MAX_CHARS])
    conn = panel.db()
    with conn:
        servers_repo.set_mods_expected(conn, sid, ids)
    flash(panel.translate("mods.expected_saved", n=len(ids)), "ok")
    return redirect(url_for(INDEX, sid=sid))
