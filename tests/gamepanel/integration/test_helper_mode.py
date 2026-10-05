"""A server in helper mode (`ssh_user = 'gamepanel'`), through the HTTP client.

The command builder has its own exact-string tests (`unit/test_remote_cmd.py`); what is checked
here is that the ROUTES reach it - that no screen still builds a command by hand and so sends a
root command to a container where root is locked, or a content command as the login user, who
cannot read the game folders at all. Every test sets the same scene for a root server next to
it, so the legacy path is proven unchanged by the same route.

No SSH anywhere: `ssh_run`, `ssh_stream_in`, `start_job` and `_run_steps` are swapped for spies.
"""
from __future__ import annotations

import io
import json
import threading

import pytest

from gamepanel import app as panel
from gamepanel import i18n
from gamepanel.persistence.repositories import servers as servers_repo
from gamepanel.tasks import broker_jobs

AS_STEAM = "cd / && sudo -n -u steam -- "


def _insert(database, name: str, user: str, service: str = "jogo.service") -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, backup_paths, created_at)"
            " VALUES (?, ?, 22, ?, ?, '/opt/game/save', ?)",
            (name, f"{name}.invalid", user, service, panel.now_iso()))
    return database.execute("SELECT id FROM servers WHERE name = ?", (name,)).fetchone()["id"]


@pytest.fixture
def helper(database) -> int:
    return _insert(database, "novo", "gamepanel")


@pytest.fixture
def legacy(database) -> int:
    return _insert(database, "antigo", "root")


@pytest.fixture
def jobs(monkeypatch):
    seen: list[dict] = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None, steps=None):
        seen.append({"action": action, "remote_cmd": remote_cmd, "steps": steps})
        return 4242

    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return seen


# ------------------------------------------------------------- action buttons

@pytest.fixture
def ran_steps(monkeypatch):
    """The steps the REAL start_job hands to its thread (the thread is what we wait for)."""
    seen: list[list] = []
    done = threading.Event()

    def fake_run_steps(target, steps, timeout):
        seen.append(list(steps))
        done.set()
        return "", "ok", 0

    monkeypatch.setattr(panel, "_run_steps", fake_run_steps)
    return seen, done


@pytest.mark.parametrize(("fixture", "expected"), [
    ("helper", "sudo -n /usr/local/sbin/gp-service stop"),
    ("legacy", "systemctl stop jogo.service"),
])
def test_botao_parar_usa_o_comando_do_modo(request, admin, post, ran_steps, fixture, expected):
    sid = request.getfixturevalue(fixture)
    seen, done = ran_steps
    response = post(admin, f"/servers/{sid}/action/stop")
    assert response.status_code == 302
    assert done.wait(5), "o job nunca chegou a rodar"
    assert seen == [[expected]]


# --------------------------------------------------------------------- console

def test_console_no_modo_helper_roda_como_steam(helper, admin, post, jobs):
    post(admin, f"/servers/{helper}/console", {"command": "id"})
    assert jobs[0]["remote_cmd"] == AS_STEAM + "bash -lc id"


def test_console_no_modo_root_continua_como_antes(legacy, admin, post, jobs):
    post(admin, f"/servers/{legacy}/console", {"command": "id"})
    assert jobs[0]["remote_cmd"] == "bash -lc id"


# ----------------------------------------------------------------------- files

def _upload(cli, url: str, name: str, **fields):
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    return cli.post(url, data={"csrf": token, "file": (io.BytesIO(b"x"), name), **fields},
                    content_type="multipart/form-data")


def test_envio_de_arquivo_no_modo_helper_roda_como_steam(helper, admin, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "ok")
    _upload(admin, f"/servers/{helper}/files/upload", "a.ini", path="/opt/game")
    assert len(sent) == 1
    assert sent[0].startswith(AS_STEAM + "bash -lc ")
    assert sent[0].endswith(" gp /opt/game/a.ini")


def test_leitura_de_pasta_no_modo_helper_roda_como_steam(helper, admin, monkeypatch):
    sent: list[str] = []

    def ssh_run(server, cmd, timeout=None, **_kw):
        sent.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    assert admin.get(f"/servers/{helper}/files?path=/opt/game").status_code == 200
    assert sent and all(cmd.startswith(AS_STEAM) for cmd in sent)


# --------------------------------------------------------------------- backups

def test_restauracao_no_modo_helper(helper, admin, post, jobs):
    post(admin, f"/servers/{helper}/backups/restore", {"name": "jogo-20260101-0000.tar.gz"})
    safety, restore, _pull = jobs[0]["steps"]
    assert safety.startswith(AS_STEAM + "bash -lc ")
    # The restore itself runs as the login user and switches inside (steam for the archive,
    # the fixed helper for the service): the mode and the backup paths are its last arguments.
    assert not restore.startswith("cd / && sudo")
    assert restore.endswith(" gp /var/backups/gamepanel jogo-20260101-0000.tar.gz jogo.service steam /opt/game/save")


def test_restauracao_no_modo_root(legacy, admin, post, jobs):
    post(admin, f"/servers/{legacy}/backups/restore", {"name": "jogo-20260101-0000.tar.gz"})
    safety, restore, _pull = jobs[0]["steps"]
    assert safety.startswith("bash -lc ")
    assert restore.endswith(" gp /var/backups/gamepanel jogo-20260101-0000.tar.gz jogo.service root /opt/game/save")


# ------------------------------------------------------------------------ mods

def _status_reply(state: dict):
    def ssh_run(server, cmd, timeout=None, **_kw):
        ssh_run.sent.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": json.dumps(state), "stderr": ""})()
    ssh_run.sent = []
    return ssh_run


def test_instalador_que_precisa_de_root_e_recusado_no_modo_helper(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "vampiro", "gamepanel", "vrising.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({}))
    response = post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    assert response.status_code == 302
    assert jobs == [], "o instalador nao pode nem virar job: no CT sem root ele quebraria no meio"
    with admin.session_transaction() as sess:
        flashes = [text for _cat, text in sess.get("_flashes", [])]
    with panel.app.test_request_context("/"):
        expected = panel.translate(i18n.Message("mods.needs_root", user="gamepanel"))
    assert flashes == [expected]
    assert "gamepanel" in expected, "a frase tem de estar no catalogo, nao a chave crua"


def test_tela_de_mods_avisa_antes_do_clique_no_modo_helper(database, admin, monkeypatch):
    sid = _insert(database, "vampiro", "gamepanel", "vrising.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({}))
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "docs/security-hardening.md" in html


def test_tela_do_servidor_mostra_o_modo_de_acesso(helper, legacy, admin, monkeypatch):
    monkeypatch.setattr(panel, "in_parallel", lambda tasks, timeout=40.0: dict.fromkeys(tasks, (None, "x")))
    assert "gamepanel" in admin.get(f"/servers/{helper}").get_data(as_text=True)
    legacy_html = admin.get(f"/servers/{legacy}").get_data(as_text=True)
    with panel.app.test_request_context("/"):
        assert panel.translate("server_detail.access_legacy") in legacy_html


def test_instalador_que_precisa_de_root_continua_no_modo_root(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "vampiro", "root", "vrising.service")
    response = post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    assert response.status_code == 302
    assert jobs and jobs[0]["action"] == "mod-loader"
    assert jobs[0]["steps"][0].startswith("python3 -c ")


def test_status_do_instalador_le_como_steam_no_modo_helper(database, admin, monkeypatch):
    """Reading the state is allowed in helper mode: it only lists folders and files."""
    sid = _insert(database, "vampiro", "gamepanel", "vrising.service")
    ssh_run = _status_reply({})
    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    assert admin.get(f"/servers/{sid}/mods").status_code == 200
    assert ssh_run.sent and ssh_run.sent[0].startswith(AS_STEAM + "python3 -c ")


def test_envio_de_mod_no_modo_helper_instala_o_clamav_pelo_helper(database, admin, jobs, monkeypatch):
    sid = _insert(database, "caminhao", "gamepanel", "ets2.service")
    sent: list[str] = []
    monkeypatch.setattr(panel, "ssh_run", _status_reply({}))
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "ok")
    _upload(admin, f"/servers/{sid}/mods/upload", "server_packages.sii")
    assert panel.ssh_run.sent[0].startswith(AS_STEAM + "bash -c ")
    assert sent[0].startswith(AS_STEAM + "bash -lc ")
    ensure, scan, place = jobs[0]["steps"]
    assert ensure == "sudo -n /usr/local/sbin/gp-clamav-ensure"
    assert scan.startswith(AS_STEAM + "bash -c ") and "apt-get" not in scan
    assert place.startswith(AS_STEAM + "bash -c ")


# -------------------------------------------------------- who gets which user

def test_formulario_de_servidor_novo_sugere_o_usuario_sem_root(admin):
    html = admin.get("/servers/new").get_data(as_text=True)
    assert 'value="gamepanel"' in html


def test_deploy_cadastra_servidor_novo_como_gamepanel(database):
    panel.ensure_server(panel.DeployServer(name="novo", host="10.0.0.9", service="x.service"))
    row = servers_repo.by_address(database, "10.0.0.9", 22)
    assert row["ssh_user"] == "gamepanel"


def test_redeploy_sem_usuario_nao_mexe_no_servidor_antigo(database, legacy):
    """No migration: a legacy server stays root until someone migrates it on purpose."""
    panel.ensure_server(panel.DeployServer(name="antigo", host="antigo.invalid", service="jogo.service"))
    assert servers_repo.by_id(database, legacy)["ssh_user"] == "root"


def test_redeploy_que_diz_o_usuario_troca(database, legacy):
    panel.ensure_server(panel.DeployServer(name="antigo", host="antigo.invalid", service="jogo.service",
                                           ssh_user="gamepanel"))
    assert servers_repo.by_id(database, legacy)["ssh_user"] == "gamepanel"


def test_servidor_criado_pelo_broker_nasce_como_gamepanel():
    created: list = []
    deps = broker_jobs.BrokerJobDeps(
        update_job=lambda *a, **k: None, close_job=lambda *a, **k: None,
        ensure_server=created.append, deploy_server=panel.DeployServer,
        connect=panel._connect, forget_host_key=lambda host: None,
        poll=0, max_failures=1, timeout=1,
    )
    with pytest.raises(ValueError):
        # The row is never inserted (ensure_server is a spy), so the id lookup fails; what
        # matters is what was handed to ensure_server.
        broker_jobs.register_server(deps, {"name": "x", "host": "10.0.0.50", "service": "x.service"})
    assert created[0].ssh_user == "gamepanel"


def test_o_modo_de_acesso_chega_aos_templates(helper, legacy, database):
    with panel.app.test_request_context("/"):
        context: dict = {}
        for processor in panel.app.template_context_processors[None]:
            context.update(processor())
        privileged = context["privileged_access"]
        assert privileged(servers_repo.by_id(database, legacy)) is True
        assert privileged(servers_repo.by_id(database, helper)) is False


# ------------------------------------------------------------- Workshop: ARK and Conan

def test_lista_do_ark_e_recusada_no_modo_helper(database, admin, post, jobs, monkeypatch):
    """The ARK list is a systemd drop-in: without root it would fail halfway, so it never becomes a job."""
    sid = _insert(database, "arca", "gamepanel", "ark-ascended.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({"ids": [], "installed": [], "problem": ""}))
    post(admin, f"/servers/{sid}/mods/workshop", {"ids": "928988"})
    assert jobs == []
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'name="ids"' not in html


def test_lista_do_ark_vira_drop_in_no_modo_root(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "arca", "root", "ark-ascended.service")
    post(admin, f"/servers/{sid}/mods/workshop", {"ids": "928988\n929420", "restart": "1"})
    save, restart = jobs[0]["steps"]
    assert save.endswith("--unit ark-ascended.service ark set /opt/game 928988 929420")
    assert restart.endswith("restart ark-ascended.service")


def test_conan_baixa_so_o_que_e_novo_verifica_e_so_depois_poe_no_jogo(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "conan", "gamepanel", "conan-exiles.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({"ids": ["3750659229"], "installed": ["3750659229"]}))
    post(admin, f"/servers/{sid}/mods/workshop", {"ids": "3750659229\n880454836"})
    steps = jobs[0]["steps"]
    incoming, fetch, *scan, place = steps
    staging = incoming.split()[-1]
    assert staging.startswith("/var/tmp/gamepanel-incoming-")
    # Everything as steam: the download, the scan and placing the files are game content.
    assert all(s.startswith(AS_STEAM) for s in (incoming, fetch, place))
    assert fetch.endswith(f"conan fetch /opt/game 880454836 --staging {staging}")
    assert any("clamscan" in s for s in scan)
    assert place.endswith(f"conan set /opt/game 3750659229 880454836 --staging {staging}")


def test_conan_sem_mod_novo_nao_baixa_nem_instala_o_clamav(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "conan", "root", "conan-exiles.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({"ids": ["3750659229", "880454836"],
                                                         "installed": ["3750659229", "880454836"]}))
    post(admin, f"/servers/{sid}/mods/workshop", {"ids": "3750659229"})
    (place,) = jobs[0]["steps"]
    assert place.endswith("conan set /opt/game 3750659229")


def test_conan_atualizar_todos_baixa_a_lista_inteira(database, admin, post, jobs, monkeypatch):
    sid = _insert(database, "conan", "root", "conan-exiles.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({"ids": ["3750659229"], "installed": ["3750659229"]}))
    post(admin, f"/servers/{sid}/mods/workshop", {"ids": "3750659229", "refresh": "1"})
    assert "conan fetch /opt/game 3750659229 --staging" in jobs[0]["steps"][1]


def test_conan_mostra_o_mod_que_o_servidor_recusou(database, admin, monkeypatch):
    sid = _insert(database, "conan", "root", "conan-exiles.service")
    monkeypatch.setattr(panel, "ssh_run", _status_reply({
        "ids": ["3725018456"], "installed": ["3725018456"], "problem": "", "config": "/x",
        "rejected": {"3725018456": "Mod is too old and needs to be updated for this game version"}}))
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "Mod is too old" in html
    with panel.app.test_request_context("/"):
        assert panel.translate("mods.workshop_rejected_badge") in html
        # Conan's download goes through the antivirus, so the screen says that and not the opposite.
        assert panel.translate("mods.workshop_antivirus_note")[:30] not in html
