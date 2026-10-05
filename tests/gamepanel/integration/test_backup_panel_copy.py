"""The second backup copy, on the panel: the job that stores it, the screen and the restore.

The routes swap `start_job` for a capturer (no thread), and the captured steps run later
through `_run_steps` with fake SSH - that is how the ORDER of the steps is visible, which
is what matters here: the safety copy before extracting, the panel copy before
deactivating the instance.
"""
from __future__ import annotations

import subprocess

import pytest

from gamepanel import app as panel

SAVE = "/opt/game/saves/worlds_local"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "PANEL_BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(panel, "PANEL_BACKUP_KEEP", 10)
    return tmp_path


@pytest.fixture
def server(database):
    panel.ensure_server(panel.DeployServer(
        name="Valheim", host="10.0.0.40", service="valheim.service", backup_paths=SAVE))
    return database.execute("SELECT * FROM servers").fetchone()


@pytest.fixture
def jobs_started(monkeypatch):
    started = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None, steps=None):
        started.append({"action": action, "server": dict(target), "steps": steps, "command": command})
        return 1
    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return started


class FakeContainer:
    """A container that answers commands in order of arrival and keeps what it saw."""

    def __init__(self, backup_name="valheim-20260101-120000.tar.gz", content=b"save-do-mundo"):
        self.backup_name = backup_name
        self.content = content
        self.commands: list[str] = []
        self.received: list[bytes] = []

    def ssh_run(self, server, remote_cmd, timeout=None, stdin_data=None, multiplex=True):
        self.commands.append(remote_cmd)
        if "backup pronto" in remote_cmd:  # it is the BACKUP_SCRIPT
            name = self.backup_name
            if "antes-de-restaurar" in remote_cmd:
                name = name.replace(".tar.gz", "-antes-de-restaurar.tar.gz")
            out = f"backup pronto: {panel.BACKUP_DIR}/{name} ({len(self.content)} bytes)\n"
            return subprocess.CompletedProcess([], 0, out, "")
        return subprocess.CompletedProcess([], 0, "restaurado\n", "")

    def stream(self, server, path):
        self.commands.append(f"cat {path}")
        return iter([self.content])

    def stream_in(self, server, remote_cmd, source, timeout):
        self.commands.append(remote_cmd)
        self.received.append(source.read())
        return "copia do painel enviada ao container"

    def stat(self, server, path):
        return {"size": len(self.content), "name": path.rsplit("/", 1)[-1]}


@pytest.fixture
def container(monkeypatch):
    fake = FakeContainer()
    monkeypatch.setattr(panel, "ssh_run", fake.ssh_run)
    monkeypatch.setattr(panel, "stream_remote_file", fake.stream)
    monkeypatch.setattr(panel, "ssh_stream_in", fake.stream_in)
    monkeypatch.setattr(panel, "stat_file", fake.stat)
    return fake


def _run(job):
    return panel._run_steps(job["server"], job["steps"], 60)


# ------------------------------------------------------------- job steps

def test_passos_param_no_primeiro_que_falha(monkeypatch):
    seen = []
    monkeypatch.setattr(panel, "ssh_run",
                        lambda *a, **k: subprocess.CompletedProcess([], 3, "", "sem espaco\n"))
    output, status, code = panel._run_steps({}, ["cmd", lambda t, o: seen.append(o) or ""], 5)
    assert (status, code, seen) == ("error", 3, [])
    assert "sem espaco" in output


def test_passo_python_que_falha_vira_erro_com_o_motivo():
    def boom(target, output):
        raise panel.RemoteError("disco do painel cheio")
    output, status, code = panel._run_steps({}, [lambda t, o: "antes\n", boom], 5)
    assert (status, code) == ("error", None)
    assert output == "antes\ndisco do painel cheio"


def test_um_passo_so_da_a_mesma_saida_de_antes(monkeypatch):
    monkeypatch.setattr(panel, "ssh_run", lambda *a, **k: subprocess.CompletedProcess([], 0, "ok", "aviso"))
    assert panel._run_steps({}, ["cmd"], 5) == ("okaviso", "ok", 0)


# ------------------------------------------------------------------ backup

def test_backup_guarda_a_segunda_copia_no_painel(admin, post, server, archive, jobs_started, container):
    post(admin, f"/servers/{server['id']}/backups/create")
    (job,) = jobs_started
    output, status, _ = _run(job)
    assert status == "ok", output
    assert (archive / "valheim" / container.backup_name).read_bytes() == b"save-do-mundo"
    assert "copia guardada no painel" in output


def test_backup_agendado_tambem_vai_para_o_painel(server, archive, jobs_started, container, database):
    with database:
        database.execute(
            "INSERT INTO schedules (server_id, action, kind, hour, minute, created_at)"
            " VALUES (?, 'backup', 'diario', 4, 0, ?)", (server["id"], panel.now_iso()))
    sched = database.execute("SELECT * FROM schedules").fetchone()
    panel.fire_schedule(database, sched)
    (job,) = jobs_started
    assert _run(job)[1] == "ok"
    assert (archive / "valheim" / container.backup_name).exists()


def test_copia_que_nao_chega_inteira_faz_o_job_falhar(admin, post, server, archive, jobs_started, container,
                                                       monkeypatch):
    monkeypatch.setattr(panel, "stream_remote_file", lambda s, p: iter([b"meio"]))
    post(admin, f"/servers/{server['id']}/backups/create")
    output, status, _ = _run(jobs_started[0])
    assert status == "error"
    assert "a do painel falhou" in output
    assert not (archive / "valheim" / container.backup_name).exists()


def test_copia_de_seguranca_do_restore_nao_aplica_retencao(server):
    # With the copies at the limit, retention would delete the oldest - precisely the chosen one.
    assert " gp /var/backups/gamepanel valheim 0 -antes-de-restaurar " in panel.backup_command(
        server, [SAVE], "-antes-de-restaurar")
    assert f" valheim {panel.BACKUP_KEEP} '' " in panel.backup_command(server, [SAVE])


def test_restaurar_copia_do_container_le_o_campo_name(admin, post, server, archive, jobs_started, container):
    # The template sent 'nome' and the route reads 'name': restoring always gave 400.
    response = post(admin, f"/servers/{server['id']}/backups/restore", {"name": container.backup_name})
    assert response.status_code == 302
    output, status, _ = _run(jobs_started[0])
    assert status == "ok", output
    safety, restore = container.commands[0], container.commands[1]
    assert "antes-de-restaurar" in safety
    assert container.backup_name in restore
    assert (archive / "valheim" / container.backup_name.replace(".tar.gz", "-antes-de-restaurar.tar.gz")).exists()


def test_formularios_da_tela_mandam_o_campo_que_as_rotas_leem(admin, server, archive, container, monkeypatch):
    monkeypatch.setattr(panel, "list_backups", lambda s: [
        {"name": container.backup_name, "size": 3, "mtime": "2026-01-01 12:00", "seguranca": False}])
    html = admin.get(f"/servers/{server['id']}/backups").get_data(as_text=True)
    assert 'name="nome"' not in html
    assert f'name="name" value="{container.backup_name}"' in html


# ------------------------------------------------------ panel copies

def _keep_in_panel(archive, name="valheim-20250101-000000.tar.gz", data=b"save-antigo"):
    folder = archive / "valheim"
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(data)
    return name


def test_servidor_recriado_enxerga_a_copia_do_anterior(admin, server, archive, monkeypatch):
    # Same service, new id: the prefix is what links the two.
    name = _keep_in_panel(archive)
    monkeypatch.setattr(panel, "list_backups", lambda s: [])
    html = admin.get(f"/servers/{server['id']}/backups").get_data(as_text=True)
    assert name in html
    assert "backups/panel/restore" in html


def test_restaurar_do_painel_manda_a_copia_e_so_entao_extrai(admin, post, server, archive, jobs_started,
                                                             container):
    name = _keep_in_panel(archive)
    post(admin, f"/servers/{server['id']}/backups/panel/restore", {"name": name})
    output, status, _ = _run(jobs_started[0])
    assert status == "ok", output
    assert container.received == [b"save-antigo"]
    kinds = ["seguranca" if "antes-de-restaurar" in c else
             "envio" if "copia do painel enviada" in c else
             "extrai" if "tar -xzf" in c else c.split()[0] for c in container.commands]
    assert kinds[:3] == ["seguranca", "envio", "extrai"]
    assert jobs_started[0]["action"] == "restore-backup"


def test_restaurar_copia_que_nao_esta_no_painel_e_404(admin, post, server, archive, jobs_started):
    response = post(admin, f"/servers/{server['id']}/backups/panel/restore", {"name": "valheim-1.tar.gz"})
    assert response.status_code == 404
    assert jobs_started == []


def test_apagar_do_painel(admin, post, server, archive, database):
    name = _keep_in_panel(archive)
    post(admin, f"/servers/{server['id']}/backups/panel/delete", {"name": name})
    assert not (archive / "valheim" / name).exists()
    assert database.execute("SELECT action FROM jobs").fetchone()["action"] == "delete-backup"


def test_baixar_do_painel(admin, server, archive):
    name = _keep_in_panel(archive)
    response = admin.get(f"/servers/{server['id']}/backups/panel/download?name={name}")
    assert response.status_code == 200
    assert response.data == b"save-antigo"
    response.close()


def test_enviar_ao_painel_copia_que_so_estava_no_container(admin, post, server, archive, jobs_started,
                                                           container):
    post(admin, f"/servers/{server['id']}/backups/send-to-panel", {"name": container.backup_name})
    output, status, _ = _run(jobs_started[0])
    assert status == "ok", output
    assert (archive / "valheim" / container.backup_name).read_bytes() == b"save-do-mundo"


@pytest.mark.parametrize("url", ["panel/restore", "panel/delete", "send-to-panel"])
def test_operador_nao_mexe_nas_copias_do_painel(operator, post, server, archive, url):
    assert post(operator, f"/servers/{server['id']}/backups/{url}", {"name": "valheim-1.tar.gz"}).status_code == 403


# ----------------------------------------------- overall screen: /backups

def test_copia_de_jogo_sem_servidor_aparece_na_tela_geral(admin, archive, database):
    # The missing case: the server was removed and the copy was left with no screen at all.
    name = _keep_in_panel(archive)
    html = admin.get("/backups").get_data(as_text=True)
    assert name in html
    assert "Nenhum servidor deste jogo no painel" in html


def test_tela_geral_aponta_o_servidor_do_mesmo_jogo(admin, server, archive):
    _keep_in_panel(archive)
    html = admin.get("/backups").get_data(as_text=True)
    assert f"/servers/{server['id']}/backups" in html


def test_tela_geral_baixa_e_apaga_sem_servidor(admin, post, archive, database):
    name = _keep_in_panel(archive)
    response = admin.get(f"/backups/valheim/download?name={name}")
    assert (response.status_code, response.data) == (200, b"save-antigo")
    # send_file holds the file open until the response closes (and Windows does not delete
    # an open file).
    response.close()
    post(admin, "/backups/valheim/delete", {"name": name})
    assert not (archive / "valheim" / name).exists()
    targets = [r["target"] for r in database.execute("SELECT target FROM jobs")]
    assert targets == ["painel@valheim", "painel@valheim"]


@pytest.mark.parametrize("url", ["/backups/..%2Fetc/download?name=x-1.tar.gz",
                                 "/backups/valheim/download?name=nada-1.tar.gz"])
def test_tela_geral_recusa_o_que_nao_e_copia_guardada(admin, archive, url):
    assert admin.get(url).status_code in (400, 404)


def test_tela_geral_e_so_de_admin(operator, archive):
    assert operator.get("/backups").status_code == 403
