"""A tela Mods: o que o servidor carrega de mod, e como mandar mod para ele.

O que "mod" significa muda por jogo, e quem sabe e o perfil (`games/mods/profiles.py`):
no ETS2 a tela le os `server_packages` e diz o que cada jogador precisa ter; no Palworld
ela lista e recebe os `.pak` da pasta de mods. Tudo e de admin, como a tela Arquivos: o
envio grava dentro do container.
"""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from gamepanel import app as panel
from gamepanel.games.mods import ets2 as ets2_mods
from gamepanel.games.mods import profiles, workshop
from gamepanel.persistence.repositories import servers as servers_repo

bp = Blueprint("mods", __name__)

# Cria a pasta de mods se ela ainda nao existe (o ~mods do Palworld so nasce quando alguem
# poe o primeiro mod), com o dono da pasta de cima: o jogo roda como 'steam' e precisa ler.
MKDIR_SCRIPT = r"""
set -e
d=$1
[ -d "$d" ] && exit 0
mkdir -p -- "$d"
chown --reference="$(dirname -- "$d")" -- "$d" 2>/dev/null || true
"""
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


def _folder_view(server, profile: profiles.ModProfile, errors: list[str]) -> dict:
    try:
        entries, _ = panel.list_dir(server, profile.folder)
    except panel.RemoteError:
        # Pasta que ainda nao existe = nenhum mod; ela nasce no primeiro envio.
        return {"files": []}
    return {"files": [e for e in entries if not e["dir"] and profile.accepts(e["name"])]}


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
    elif profile:
        view = _folder_view(server, profile, errors)
    return render_template(
        "mods.html", server=server, profile=profile, view=view, errors=errors,
        expected_text="\n".join(str(i) for i in _expected_ids(server)),
        workshop_url=workshop.url, kind_packages=profiles.KIND_PACKAGES,
    )


def _upload_one(server, profile: profiles.ModProfile, sent) -> str:
    """Manda UM arquivo para a pasta do perfil. Devolve a saida do container."""
    # So a ultima parte do nome: "../../etc/passwd" nao vira caminho.
    name = sent.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or not profile.accepts(name):
        allowed = ", ".join(profile.upload_names or profile.extensions)
        raise ValueError(panel.translate("mods.bad_name", name=name or "?", allowed=allowed))
    target = panel.clean_path(f"{profile.folder}/{name}")
    return panel.ssh_stream_in(server, panel.q("bash", "-lc", panel.UPLOAD_SCRIPT, "gp", target),
                               sent.stream, timeout=panel.JOB_TIMEOUT)


@bp.post("/servers/<int:sid>/mods/upload")
@panel.admin_required
def upload(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for("mods.index", sid=sid)
    sent = [f for f in request.files.getlist("file") if f and f.filename]
    if not profile or not sent:
        flash(panel.translate("flash.pick_a_file"), "error")
        return redirect(go_back)

    user = session.get("username", "?")
    try:
        proc = panel.ssh_run(server, panel.q("bash", "-lc", MKDIR_SCRIPT, "gp", profile.folder), timeout=40)
        if proc.returncode != 0:
            raise panel.RemoteError((proc.stderr or proc.stdout).strip() or profile.folder)
        outputs = [_upload_one(server, profile, f) for f in sent]
    except (ValueError, panel.RemoteError) as exc:
        panel.log_job("upload-mod", server, user, command=profile.folder, output=str(exc), status="error")
        flash(panel.translate("flash.could_not_upload", reason=exc), "error")
        return redirect(go_back)

    panel.log_job("upload-mod", server, user, command=profile.folder, output="\n".join(outputs))
    flash(panel.translate("mods.uploaded", n=len(outputs)), "ok")
    # Mod so entra quando o servidor sobe de novo: o reiniciar mora aqui, como na tela Config.
    if request.form.get("restart") == "1":
        job_id = panel.start_job("restart", server, user)
        panel.invalidate_status(sid)
        return redirect(url_for("jobs.detail", jid=job_id))
    return redirect(go_back)


@bp.post("/servers/<int:sid>/mods/delete")
@panel.admin_required
def delete(sid: int):
    panel._files_guard()
    server = panel._server_or_404(sid)
    profile = _profile_or_none(server)
    go_back = url_for("mods.index", sid=sid)
    name = (request.form.get("name") or "").strip()
    # So o arquivo de mod da pasta do perfil, pelo nome: nada de caminho vindo do formulario.
    if not profile or profile.kind != profiles.KIND_FOLDER or "/" in name or not profile.accepts(name):
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
    return redirect(url_for("mods.index", sid=sid))
