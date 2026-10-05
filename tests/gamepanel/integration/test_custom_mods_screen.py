"""The custom mod setup on the Mods screen (Flask client, container swapped for spies)."""
from __future__ import annotations

import io
import json
import shlex

import pytest

from gamepanel import app as panel

AS_STEAM = "cd / && sudo -n -u steam -- "
FORM = {"loader_url": "https://github.com/autor/loader/releases/download/v1/loader.zip",
        "loader_dir": "Binaries/Win64", "mods_dir": "Binaries/Win64/mods", "extensions": ".dll .pak",
        "wine_overrides": "", "ld_preload": ""}


def _insert(database, user: str, service: str = "terraria.service", name: str = "alvo") -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES (?, ?, 22, ?, ?, ?)", (name, f"{name}.invalid", user, service, panel.now_iso()))
    return database.execute("SELECT id FROM servers WHERE name = ?", (name,)).fetchone()["id"]


def _stored(database, sid: int) -> str:
    return database.execute("SELECT mods_custom FROM servers WHERE id = ?", (sid,)).fetchone()["mods_custom"]


@pytest.fixture
def jobs(monkeypatch):
    seen: list[dict] = []

    def fake_start_job(action, target, username, remote_cmd=None, command="", timeout=None, steps=None):
        seen.append({"action": action, "command": command, "steps": steps})
        return 5151

    monkeypatch.setattr(panel, "start_job", fake_start_job)
    return seen


@pytest.fixture
def remote(monkeypatch):
    """What the custom installer's `status` answers (and every command sent to the container)."""
    state: dict = {"loader_installed": False, "mods_dir": "/opt/game/Binaries/Win64/mods", "mods": []}
    sent: list[str] = []

    def ssh_run(server, cmd, timeout=None, **_kw):
        sent.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": json.dumps(state), "stderr": ""})()

    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    return state, sent


def _save(admin, post, sid, **over):
    return post(admin, f"/servers/{sid}/mods/custom", {**FORM, **over})


# ------------------------------------------------------------------ saving the setup

def test_jogo_sem_perfil_oferece_a_configuracao_manual(database, admin, remote):
    sid = _insert(database, "gamepanel")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert f'action="/servers/{sid}/mods/custom"' in html
    assert 'name="loader_url"' in html and 'name="mods_dir"' in html


def test_admin_salva_e_a_tela_vira_o_perfil_manual(database, admin, post, remote, jobs):
    sid = _insert(database, "gamepanel")
    assert _save(admin, post, sid).status_code == 302
    stored = json.loads(_stored(database, sid))
    assert stored["mods_dir"] == "Binaries/Win64/mods" and stored["extensions"] == [".dll", ".pak"]
    assert jobs == [] or all(j["action"] == "mod-setup" for j in jobs)
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'accept=".dll,.pak"' in html, "the upload card comes from the setup"
    assert FORM["loader_url"] in html
    # The status comes from the custom installer, with the setup as JSON and the fixed game folder.
    status = remote[1][-1]
    assert status.startswith(AS_STEAM + "python3 -c ")
    args = shlex.split(status.split(" -- ", 1)[1])
    assert args[args.index("--setup") + 1] == _stored(database, sid)
    assert args[-2:] == ["status", "/opt/game"]
    assert "--overlay" in args


def test_alteracao_fica_no_historico(database, admin, post, remote):
    sid = _insert(database, "gamepanel")
    _save(admin, post, sid)
    row = database.execute("SELECT action, command FROM jobs WHERE server_id = ?", (sid,)).fetchone()
    assert row["action"] == "mod-setup"
    assert FORM["loader_url"] in row["command"]


@pytest.mark.parametrize("over", [{"loader_url": "http://x/y.zip"}, {"mods_dir": "/etc"}, {"mods_dir": "../x"},
                                  {"extensions": ".sh"}, {"wine_overrides": "x=$(id)"}, {"mods_dir": ""}])
def test_configuracao_ruim_nao_e_guardada(database, admin, post, remote, over):
    sid = _insert(database, "gamepanel")
    _save(admin, post, sid, **over)
    assert _stored(database, sid) == ""


def test_jogo_com_perfil_proprio_recusa_a_configuracao_manual(database, admin, post, remote):
    """The built-in profile wins: no form, and a POST made by hand is refused."""
    sid = _insert(database, "gamepanel", "dragonwilds.service")
    _save(admin, post, sid)
    assert _stored(database, sid) == ""
    monkey_html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert f'action="/servers/{sid}/mods/custom"' not in monkey_html


def test_ambiente_no_modo_root_e_recusado(database, admin, post, remote):
    sid = _insert(database, "root")
    _save(admin, post, sid, wine_overrides="winhttp=n,b")
    assert _stored(database, sid) == ""
    _save(admin, post, sid)
    assert _stored(database, sid) != "", "without environment settings the legacy server takes the setup"


def test_ambiente_no_modo_helper_e_aceito(database, admin, post, remote):
    sid = _insert(database, "gamepanel")
    _save(admin, post, sid, wine_overrides="winhttp=n,b", ld_preload="Binaries/Linux/libx.so")
    stored = json.loads(_stored(database, sid))
    assert stored["wine"] == ["winhttp=n,b"] and stored["preload"] == "Binaries/Linux/libx.so"


def test_apagar_a_configuracao(database, admin, post, remote):
    sid = _insert(database, "gamepanel")
    _save(admin, post, sid)
    post(admin, f"/servers/{sid}/mods/custom/clear")
    assert _stored(database, sid) == ""


def test_operador_nao_ve_nem_salva(database, operator, post, remote):
    sid = _insert(database, "gamepanel")
    assert operator.get(f"/servers/{sid}/mods").status_code == 403
    assert post(operator, f"/servers/{sid}/mods/custom", FORM).status_code == 403
    assert post(operator, f"/servers/{sid}/mods/custom/clear").status_code == 403
    assert _stored(database, sid) == ""


def test_sem_csrf_nao_salva(database, admin, remote):
    sid = _insert(database, "gamepanel")
    assert admin.post(f"/servers/{sid}/mods/custom", data=FORM).status_code == 400
    assert _stored(database, sid) == ""


# ------------------------------------------------------------------ the loader, uploads and removal

@pytest.fixture
def configured(database, admin, post, remote):
    def make(user: str, **over) -> int:
        sid = _insert(database, user, name=f"alvo-{user}")
        _save(admin, post, sid, **over)
        assert _stored(database, sid), "the setup must have been stored"
        return sid
    return make


def test_instalar_o_carregador_no_modo_helper(configured, admin, post, jobs):
    sid = configured("gamepanel")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "restart": "1"})
    job = next(j for j in jobs if j["action"] == "mod-loader")
    ensure, installer, restart = job["steps"]
    assert ensure == "sudo -n /usr/local/sbin/gp-clamav-ensure"
    assert installer.startswith(AS_STEAM + "python3 -c ")
    args = shlex.split(installer.split(" -- ", 1)[1])
    assert args[:4] == ["python3", "-c", args[2], "--overlay"]
    assert "--scan" in args and args[-2:] == ["loader-install", "/opt/game"]
    assert "apt-get" not in args[args.index("--scan") + 1]
    assert restart == "sudo -n /usr/local/sbin/gp-service restart"


def test_instalar_o_carregador_no_modo_root(configured, admin, post, jobs):
    sid = configured("root")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    (installer,) = next(j for j in jobs if j["action"] == "mod-loader")["steps"]
    args = shlex.split(installer)
    assert args[0] == "python3" and "--overlay" not in args and "--scan" in args


@pytest.mark.parametrize("action", ["enable", "disable", "bogus"])
def test_carregador_manual_so_instala_e_desinstala(configured, admin, post, jobs, action):
    sid = configured("gamepanel")
    post(admin, f"/servers/{sid}/mods/loader", {"action": action})
    assert [j for j in jobs if j["action"] == "mod-loader"] == []


def test_desinstalar_nao_baixa_nada(configured, admin, post, jobs):
    sid = configured("gamepanel")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "uninstall"})
    (installer,) = next(j for j in jobs if j["action"] == "mod-loader")["steps"]
    assert shlex.split(installer.split(" -- ", 1)[1])[-2:] == ["loader-uninstall", "/opt/game"]


def test_envio_de_mod_vai_pela_espera_e_o_instalador_coloca(configured, admin, jobs, monkeypatch):
    sid = configured("gamepanel")
    sent: list[str] = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "ok")
    with admin.session_transaction() as sess:
        token = sess["csrf"]
    admin.post(f"/servers/{sid}/mods/upload", content_type="multipart/form-data",
               data={"csrf": token, "file": (io.BytesIO(b"x"), "Mod.dll")})
    assert "/var/tmp/gamepanel-incoming-" in sent[0]
    ensure, _scan, place = next(j for j in jobs if j["action"] == "upload-mod")["steps"]
    assert ensure == "sudo -n /usr/local/sbin/gp-clamav-ensure"
    args = shlex.split(place.split(" -- ", 1)[1])
    assert args[-3] == "mod-place" and args[-2] == "/opt/game"
    assert args[-1].startswith("/var/tmp/gamepanel-incoming-")


def test_envio_com_extensao_fora_da_lista_e_recusado(configured, admin, jobs, monkeypatch):
    sid = configured("gamepanel")
    sent: list[str] = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda *a, **k: sent.append(a) or "ok")
    with admin.session_transaction() as sess:
        token = sess["csrf"]
    admin.post(f"/servers/{sid}/mods/upload", content_type="multipart/form-data",
               data={"csrf": token, "file": (io.BytesIO(b"x"), "Mod.jar")})
    assert sent == []


def test_remover_mod_vai_pelo_instalador_manual(configured, admin, jobs):
    sid = configured("gamepanel")
    with admin.session_transaction() as sess:
        token = sess["csrf"]
    admin.post(f"/servers/{sid}/mods/delete",
               data={"csrf": token, "name": ["Mod.dll"], "folder": ["PastaMod"], "restart": "1"})
    remove, restart = next(j for j in jobs if j["action"] == "delete-mod")["steps"]
    args = shlex.split(remove.split(" -- ", 1)[1])
    assert args[-6:] == ["mod-remove", "/opt/game", "f", "Mod.dll", "d", "PastaMod"]
    assert restart == "sudo -n /usr/local/sbin/gp-service restart"


def test_remover_nome_com_caminho_nao_chega(configured, admin, post, jobs):
    sid = configured("gamepanel")
    post(admin, f"/servers/{sid}/mods/delete", {"name": "../../Game.dll"})
    assert [j for j in jobs if j["action"] == "delete-mod"] == []


def test_tela_mostra_carregador_instalado_e_mods(configured, admin, remote):
    state, _ = remote
    sid = configured("gamepanel")
    state.update(loader_installed=True, loader_complete=True, loader_url=FORM["loader_url"], loader_files=3,
                 loader_sha256="ab" * 32, mods=[{"name": "Mod.dll", "dir": False, "size": 10},
                                                {"name": "PastaMod", "dir": True, "size": 0}])
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'name="name" value="Mod.dll"' in html and 'name="folder" value="PastaMod"' in html
    assert "value=uninstall" in html
    with panel.app.test_request_context("/"):
        assert panel.translate("mods.custom_warning")[:30] in html
