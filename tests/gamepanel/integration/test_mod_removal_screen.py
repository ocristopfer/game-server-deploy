"""Removing mods: the routes (Flask client, container swapped for spies) and the REAL removal script.

Before this, a mod could get in and not out: the Lua mods of UE4SS had no button at all, a
Shroudtopia folder mod had none either, and a DLL or a .cs uploaded before its loader was installed
was not even listed. Every route here is a job with the restart as its last step, by NAME only.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gamepanel import app as panel
from gamepanel.games.mods import removal

AS_STEAM = "cd / && sudo -n -u steam -- "


def _insert(database, user: str, service: str) -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('alvo', 'alvo.invalid', 22, ?, ?, ?)", (user, service, panel.now_iso()))
    return database.execute("SELECT id FROM servers WHERE name = 'alvo'").fetchone()["id"]


@pytest.fixture
def jobs(monkeypatch):
    seen: list[dict] = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None, steps=None):
        seen.append({"action": action, "command": command, "steps": steps})
        return 4343

    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return seen


def _state(state: dict):
    def ssh_run(server, cmd, timeout=None, **_kw):
        return type("P", (), {"returncode": 0, "stdout": json.dumps(state), "stderr": ""})()
    return ssh_run


# ------------------------------------------------------------------ files

def test_dragonwilds_remove_o_mod_com_os_tres_arquivos_e_reinicia_no_fim(database, admin, post, jobs):
    sid = _insert(database, "root", "dragonwilds.service")
    response = post(admin, f"/servers/{sid}/mods/delete", {"name": "Mapa_P.pak", "restart": "1"})
    assert "/jobs/4343" in response.headers["Location"]
    job = jobs[0]
    assert job["action"] == "delete-mod"
    remove, restart = job["steps"]
    assert remove.startswith("bash -c ")
    for name in ("Mapa_P.pak", "Mapa_P.utoc", "Mapa_P.ucas"):
        assert f" f {name}" in remove
    assert "'/opt/game/RSDragonwilds/Content/Paks/~mods'" in remove
    assert restart == "systemctl restart dragonwilds.service"


def test_sem_reiniciar_e_um_passo_so(database, admin, post, jobs):
    sid = _insert(database, "root", "dragonwilds.service")
    post(admin, f"/servers/{sid}/mods/delete", {"name": "Mapa_P.pak"})
    assert len(jobs[0]["steps"]) == 1


def test_no_modo_helper_a_remocao_roda_como_steam(database, admin, post, jobs):
    sid = _insert(database, "gamepanel", "palworld.service")
    post(admin, f"/servers/{sid}/mods/delete", {"name": "X.pak", "restart": "1"})
    remove, restart = jobs[0]["steps"]
    assert remove.startswith(AS_STEAM + "bash -c ")
    assert restart == "sudo -n /usr/local/sbin/gp-service restart"


def test_enshrouded_remove_dll_e_pasta_de_mod(database, admin, post, jobs):
    sid = _insert(database, "gamepanel", "enshrouded.service")
    with admin.session_transaction() as sess:
        token = sess["csrf"]
    admin.post(f"/servers/{sid}/mods/delete",
               data={"csrf": token, "name": ["voo.dll"], "folder": ["MeuMod"]})
    (step,) = jobs[0]["steps"]
    assert shlex.split(step)[-5:] == ["/opt/game/mods", "f", "voo.dll", "d", "MeuMod"]


def test_pasta_de_mod_onde_o_perfil_nao_tem_pasta_e_recusada(database, admin, post, jobs):
    sid = _insert(database, "root", "dragonwilds.service")
    post(admin, f"/servers/{sid}/mods/delete", {"folder": "Qualquer"})
    assert jobs == []


def test_jogo_cujos_mods_nao_sao_arquivos_nao_remove_por_aqui(database, admin, post, jobs):
    """V Rising removes through its installer (plugin_remove), ETS2 has packages, not mods."""
    for service in ("vrising.service", "ets2.service"):
        sid = _insert(database, "root", service)
        post(admin, f"/servers/{sid}/mods/delete", {"name": "x.dll"})
        with database:
            database.execute("DELETE FROM servers")
    assert jobs == []


def test_operador_nao_remove(database, operator, post, jobs):
    sid = _insert(database, "root", "dragonwilds.service")
    assert post(operator, f"/servers/{sid}/mods/delete", {"name": "X.pak"}).status_code == 403
    assert post(operator, f"/servers/{sid}/mods/lua/remove", {"lua": "MeuMod"}).status_code == 403
    assert jobs == []


def test_sem_csrf_nao_remove(database, admin, jobs):
    sid = _insert(database, "root", "dragonwilds.service")
    assert admin.post(f"/servers/{sid}/mods/delete", data={"name": "X.pak"}).status_code == 400
    assert jobs == []


# ------------------------------------------------------------------ Lua mods (UE4SS)

@pytest.mark.parametrize(("user", "service", "prefix", "folder"), [
    ("root", "dragonwilds.service", "python3 -c ", "/opt/game/RSDragonwilds/Binaries/Linux"),
    ("gamepanel", "palworld.service", AS_STEAM + "python3 -c ", "/opt/game/Pal/Binaries/Linux"),
    ("root", "icarus.service", "python3 -c ", "/opt/game/Icarus/Binaries/Win64"),
])
def test_mod_lua_sai_pelo_instalador(database, admin, post, jobs, user, service, prefix, folder):
    sid = _insert(database, user, service)
    post(admin, f"/servers/{sid}/mods/lua/remove", {"lua": "MeuMod", "restart": "1"})
    job = jobs[0]
    assert job["action"] == "mod-remove"
    remove, _restart = job["steps"]
    assert remove.startswith(prefix)
    assert remove.endswith(f"mod-remove {folder} MeuMod")
    # Removing downloads nothing: no antivirus, no ClamAV step.
    assert "--scan" not in shlex.split(remove) and "gp-clamav-ensure" not in remove


@pytest.mark.parametrize("name", ["shared", "../x", "a/b", ".oculto", ""])
def test_nome_de_mod_lua_ruim_nao_chega_ao_container(database, admin, post, jobs, name):
    sid = _insert(database, "root", "dragonwilds.service")
    post(admin, f"/servers/{sid}/mods/lua/remove", {"lua": name})
    assert jobs == []


def test_mod_lua_so_para_ue4ss(database, admin, post, jobs):
    sid = _insert(database, "root", "enshrouded.service")
    post(admin, f"/servers/{sid}/mods/lua/remove", {"lua": "MeuMod"})
    assert jobs == []


# ------------------------------------------------------------------ the screen

def test_tela_lista_os_mods_lua_com_caixa_para_marcar(database, admin, monkeypatch):
    sid = _insert(database, "root", "dragonwilds.service")
    monkeypatch.setattr(panel, "ssh_run", _state({"loader_installed": True, "loader": "UE4SS Linux",
                                                  "mods": [{"name": "MeuMod", "enabled": True}]}))
    monkeypatch.setattr(panel, "list_dir", lambda server, path: ([
        {"name": "Mapa_P.pak", "dir": False, "size": 10}], False))
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'name="lua" value="MeuMod"' in html
    assert 'name="name" value="Mapa_P.pak"' in html
    assert f'action="/servers/{sid}/mods/lua/remove"' in html
    assert "data-confirm=" in html


def test_dll_enviada_antes_do_carregador_aparece_e_sai(database, admin, monkeypatch):
    """Shroudtopia not installed yet: the DLL already in mods/ is still listed, and removable."""
    sid = _insert(database, "root", "enshrouded.service")
    monkeypatch.setattr(panel, "ssh_run", _state({
        "loader_installed": False, "mods": [{"name": "voo.dll", "dir": False, "size": 9},
                                            {"name": "MeuMod", "dir": True, "size": 0}]}))
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'name="name" value="voo.dll"' in html
    assert 'name="folder" value="MeuMod"' in html


def test_plugin_cs_antes_do_oxide_aparece_e_sai(database, admin, monkeypatch):
    sid = _insert(database, "root", "rust.service")
    monkeypatch.setattr(panel, "ssh_run", _state({"loader_installed": False,
                                                  "mods": [{"name": "Kits.cs", "size": 9}]}))
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'name="name" value="Kits.cs"' in html


# ------------------------------------------------------------------ the REAL script, in bash

bash_only = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None or shutil.which("realpath") is None,
    reason="script bash; roda no container")


def _run(folder: Path, *pairs: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", removal.REMOVE_SCRIPT, "gp", str(folder), *pairs],
                          capture_output=True, text=True, check=False)


@pytest.fixture
def mods_dir(tmp_path) -> Path:
    folder = Path(os.path.realpath(tmp_path)) / "mods"
    (folder / "PastaMod").mkdir(parents=True)
    (folder / "PastaMod" / "mod.json").write_text("{}", encoding="utf-8")
    for name in ("a.dll", "b.pak", "b.utoc"):
        (folder / name).write_bytes(b"x")
    return folder


@bash_only
def test_script_remove_arquivo_e_pasta_e_pula_o_que_nao_existe(mods_dir):
    proc = _run(mods_dir, "f", "a.dll", "d", "PastaMod", "f", "b.pak", "f", "b.ucas")
    assert proc.returncode == 0, proc.stderr
    assert sorted(os.listdir(mods_dir)) == ["b.utoc"]
    assert "not there (skipped)" in proc.stdout


@bash_only
def test_script_recusa_pasta_de_mods_que_e_link(mods_dir, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(mods_dir, target_is_directory=True)
    proc = _run(link, "f", "a.dll")
    assert proc.returncode == 3
    assert (mods_dir / "a.dll").exists()


@bash_only
def test_script_link_dentro_da_pasta_so_perde_o_link(mods_dir, tmp_path):
    victim = tmp_path / "fora"
    victim.mkdir()
    (victim / "importante").write_text("fica", encoding="utf-8")
    (mods_dir / "Atalho").symlink_to(victim, target_is_directory=True)
    proc = _run(mods_dir, "d", "Atalho")
    assert proc.returncode == 0, proc.stderr
    assert not (mods_dir / "Atalho").exists()
    assert (victim / "importante").exists()


@bash_only
@pytest.mark.parametrize("pairs", [("f", "PastaMod"), ("d", "a.dll"), ("f", "../a.dll"), ("f", "..")])
def test_script_recusa_tipo_trocado_e_nome_com_caminho(mods_dir, pairs):
    proc = _run(mods_dir, *pairs)
    assert proc.returncode != 0
    assert (mods_dir / "PastaMod").is_dir() and (mods_dir / "a.dll").exists()
