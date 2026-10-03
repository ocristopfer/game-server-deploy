"""A tela Mods pelo cliente HTTP, com o container trocado por falsos (nada de SSH)."""
from __future__ import annotations

import io
import json

import pytest

from gamepanel import app as panel

PACKAGES = """SiiNunit
{
server_packages_info : _nameless.1 {
 dlc_non_essential_list: 1
 map_name: "/map/brbrasil.mbd"
}
server_mod_detail : _nameless.2 {
 package_name: "Mapa_BR_Brasil_6.1"
 mod_name: "Mapa BR Brasil 6.1"
 workshop_mod: false
}
server_mod_detail : _nameless.3 {
 package_name: "mod_workshop_package.00000000C4089C7D"
 mod_name: "Scania L6 Straight pipe"
 mod_id: 3288898685
 workshop_mod: true
 optional_mod: true
}
}
"""


def _server(database, service: str) -> int:
    with database:
        database.execute(
            "INSERT INTO servers (name, host, ssh_port, ssh_user, service, created_at)"
            " VALUES ('caminhao', 'nao-existe-de-proposito.invalid', 22, 'root', ?, ?)",
            (service, panel.now_iso()))
    return database.execute("SELECT id FROM servers WHERE name = 'caminhao'").fetchone()["id"]


@pytest.fixture
def ets2_server(database) -> int:
    return _server(database, "ets2.service")


@pytest.fixture
def packages_on_server(monkeypatch):
    def read_file(server, path):
        assert path == "/opt/game/server-home/server_packages.sii"
        return {"binary": False, "truncated": False, "text": PACKAGES}
    monkeypatch.setattr(panel, "read_file", read_file)


def test_tela_mostra_o_que_os_pacotes_carregam(admin, ets2_server, packages_on_server):
    html = admin.get(f"/servers/{ets2_server}/mods").get_data(as_text=True)
    assert "Mapa BR Brasil 6.1" in html
    assert "Scania L6 Straight pipe" in html
    assert "/map/brbrasil.mbd" in html
    assert "https://steamcommunity.com/sharedfiles/filedetails/?id=3288898685" in html


def test_sem_pacotes_a_tela_explica_o_que_exportar(admin, ets2_server, monkeypatch):
    def missing(server, path):
        raise panel.RemoteError("nao existe")
    monkeypatch.setattr(panel, "read_file", missing)
    html = admin.get(f"/servers/{ets2_server}/mods").get_data(as_text=True)
    assert "export_server_packages" in html
    assert "server_packages.dat" in html


def test_gabarito_aponta_o_mod_que_falta(admin, post, ets2_server, packages_on_server, database):
    chat = ("[14:48]X : https://steamcommunity.com/sharedfiles/filedetails/?id=3288898685\n"
            "[14:51]X : https://steamcommunity.com/sharedfiles/filedetails/?id=3716293677")
    assert post(admin, f"/servers/{ets2_server}/mods/expected", {"expected": chat}).status_code == 302
    saved = database.execute("SELECT mods_expected FROM servers WHERE id = ?", (ets2_server,)).fetchone()
    assert saved["mods_expected"].split() == ["3288898685", "3716293677"]
    html = admin.get(f"/servers/{ets2_server}/mods").get_data(as_text=True)
    assert "3716293677" in html
    assert "Faltam 1 mods" in html


def test_operador_nao_ve_nem_envia(operator, post, ets2_server):
    assert operator.get(f"/servers/{ets2_server}/mods").status_code == 403
    assert post(operator, f"/servers/{ets2_server}/mods/expected", {"expected": "3288898685"}).status_code == 403


class _Done:
    returncode, stdout, stderr = 0, "", ""


@pytest.fixture
def mkdir_ok(monkeypatch):
    """O `mkdir -p` da pasta de mods, que roda antes do envio, sempre da certo."""
    monkeypatch.setattr(panel, "ssh_run", lambda *a, **k: _Done())


def _upload(cli, sid, name, data=b"conteudo"):
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    return cli.post(f"/servers/{sid}/mods/upload",
                    data={"csrf": token, "file": (io.BytesIO(data), name)},
                    content_type="multipart/form-data")


def test_envio_de_arquivo_que_nao_e_pacote_e_recusado_sem_tocar_no_container(admin, ets2_server, monkeypatch, mkdir_ok):
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda *a, **k: sent.append(a) or "enviado")
    response = _upload(admin, ets2_server, "mapa_br.scs")
    assert response.status_code == 302
    assert sent == []


@pytest.fixture
def upload_jobs(monkeypatch):
    jobs: list[tuple] = []
    monkeypatch.setattr(panel, "start_job", lambda action, server, user, **kw: jobs.append((action, kw)) or 77)
    return jobs


def test_envio_vai_para_a_espera_e_o_job_verifica_antes_de_por_na_pasta(admin, ets2_server, monkeypatch,
                                                                       mkdir_ok, upload_jobs):
    """O arquivo nunca cai direto na pasta do jogo: espera, antivirus, e so entao a pasta."""
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "enviado")
    response = _upload(admin, ets2_server, "server_packages.sii")
    assert "/jobs/77" in response.headers["Location"]
    assert len(sent) == 1
    assert "/var/tmp/gamepanel-incoming-" in sent[0]
    assert "/opt/game/server-home" not in sent[0]
    action, kw = upload_jobs[0]
    assert action == "upload-mod"
    scan, place = kw["steps"]
    incoming = sent[0].split("/var/tmp/", 1)[1].split("/", 1)[0]
    assert "clamscan" in scan and incoming in scan
    assert incoming in place and "/opt/game/server-home" in place


def test_reiniciar_e_o_ultimo_passo_do_envio(admin, ets2_server, monkeypatch, mkdir_ok, upload_jobs):
    """Se o antivirus recusa, o job para antes: o servidor nao reinicia por um mod que nao entrou."""
    monkeypatch.setattr(panel, "ssh_stream_in", lambda *a, **k: "enviado")
    with admin.session_transaction() as sess:
        token = sess.get("csrf", "")
    admin.post(f"/servers/{ets2_server}/mods/upload", content_type="multipart/form-data",
               data={"csrf": token, "restart": "1", "file": (io.BytesIO(b"x"), "server_packages.sii")})
    steps = upload_jobs[0][1]["steps"]
    assert len(steps) == 3
    assert "clamscan" in steps[0]
    assert steps[-1].endswith("restart ets2.service")


def test_nome_com_caminho_vira_so_o_nome(admin, ets2_server, monkeypatch, mkdir_ok, upload_jobs):
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "enviado")
    _upload(admin, ets2_server, "../../etc/server_packages.dat")
    assert "/server_packages.dat" in sent[0]
    assert "/etc/" not in sent[0]


def test_remover_so_vale_para_pasta_de_mods_e_so_pelo_nome(admin, post, database, monkeypatch):
    sid = _server(database, "palworld.service")
    removed: list = []
    monkeypatch.setattr(panel, "delete_file", lambda server, path: removed.append(path) or "apagado")
    post(admin, f"/servers/{sid}/mods/delete", {"name": "../../../etc/passwd"})
    post(admin, f"/servers/{sid}/mods/delete", {"name": "script.sh"})
    post(admin, f"/servers/{sid}/mods/delete", {"name": "MeuMod_P.pak"})
    assert removed == ["/opt/game/Pal/Content/Paks/~mods/MeuMod_P.pak"]


def test_jogo_sem_gestor_manda_para_arquivos(admin, database):
    sid = _server(database, "terraria.service")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert f"/servers/{sid}/files" in html


# ------------------------------------------------------------------ V Rising (Thunderstore)

def _status(**over):
    state = {"loader_installed": True, "loader": "BepInEx-BepInExPack_V_Rising-1.733.2",
             "loader_version": "1.733.2", "enabled": True, "overrides_ok": True, "memory_mb": 12288,
             "plugins": [{"dir": "deca-VampireCommandFramework", "full_name": "deca-VampireCommandFramework-0.11.0",
                          "version": "0.11.0"}]}
    state.update(over)
    return state


# O que o `status` do instalador remoto responde no teste atual (a fixture zera).
REMOTE_STATE: dict = {}


@pytest.fixture
def vrising(database, monkeypatch):
    sid = _server(database, "vrising.service")
    calls: list[str] = []

    def ssh_run(server, cmd, timeout=None, **kw):
        calls.append(cmd)
        out = type("P", (), {})()
        out.returncode, out.stderr = 0, ""
        out.stdout = "progresso\n" + json.dumps(REMOTE_STATE)
        return out
    REMOTE_STATE.clear()
    REMOTE_STATE.update(_status())
    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    jobs: list[tuple] = []
    monkeypatch.setattr(panel, "start_job", lambda action, server, user, **kw: jobs.append((action, kw)) or 99)
    return sid, calls, jobs


def test_tela_do_v_rising_mostra_bepinex_e_plugins(admin, vrising):
    sid, calls, _ = vrising
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "BepInEx-BepInExPack_V_Rising-1.733.2" in html
    assert "deca-VampireCommandFramework" in html
    assert "https://thunderstore.io/c/v-rising/p/deca/VampireCommandFramework/" in html
    # O status e lido rodando o instalador no CT, e nao por um caminho que o painel adivinha.
    assert "python3" in calls[0]
    assert "status" in calls[0]


def test_pouca_memoria_avisa_antes_de_instalar(admin, vrising):
    sid, _, _ = vrising
    REMOTE_STATE.update(memory_mb=8192, loader_installed=False, plugins=[])
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "8192 MB" in html
    assert "10240 MB" in html


def test_ajuste_do_wine_desfeito_aparece(admin, vrising):
    sid, _, _ = vrising
    REMOTE_STATE.update(overrides_ok=False)
    assert "redeploy" in admin.get(f"/servers/{sid}/mods").get_data(as_text=True)


def test_instalar_mod_vira_job_com_reinicio_so_no_fim(admin, post, vrising):
    sid, _, jobs = vrising
    response = post(admin, f"/servers/{sid}/mods/plugin/install",
                    {"package": "https://thunderstore.io/c/v-rising/p/odjit/KindredCommands/", "restart": "1"})
    assert response.status_code == 302
    assert "/jobs/99" in response.headers["Location"]
    action, kw = jobs[0]
    assert action == "mod-install"
    install, restart = kw["steps"]
    assert "plugin-install" in install
    assert "odjit" in install
    assert "KindredCommands" in install
    assert restart.endswith("restart vrising.service")


def test_sem_reiniciar_o_job_tem_um_passo_so(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework"})
    assert len(jobs[0][1]["steps"]) == 1


def test_pacote_irreconhecivel_nao_chega_ao_container(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/x; rm -rf /"})
    assert jobs == []


def test_carregador_so_aceita_as_tres_acoes(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    post(admin, f"/servers/{sid}/mods/loader", {"action": "rm"})
    assert [a for a, _ in jobs] == ["mod-loader"]
    assert "loader-install" in jobs[0][1]["steps"][0]


def test_remover_plugin_so_pela_pasta_do_instalador(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/remove", {"dir": "../../etc"})
    post(admin, f"/servers/{sid}/mods/plugin/remove", {"dir": "deca-VampireCommandFramework"})
    assert len(jobs) == 1
    assert "plugin-remove" in jobs[0][1]["steps"][0]


def test_rotas_do_thunderstore_recusam_outro_jogo(admin, post, ets2_server, monkeypatch):
    jobs: list = []
    monkeypatch.setattr(panel, "start_job", lambda *a, **k: jobs.append(a) or 1)
    post(admin, f"/servers/{ets2_server}/mods/plugin/install", {"package": "deca/VampireCommandFramework"})
    post(admin, f"/servers/{ets2_server}/mods/loader", {"action": "install"})
    assert jobs == []


def test_operador_nao_instala(operator, post, vrising):
    sid, _, jobs = vrising
    response = post(operator, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework"})
    assert response.status_code == 403
    assert jobs == []


# ------------------------------------------------------------------ guia e "onde achar"

def test_toda_tela_de_mods_diz_onde_achar(admin, ets2_server, packages_on_server):
    html = admin.get(f"/servers/{ets2_server}/mods").get_data(as_text=True)
    assert "https://steamcommunity.com/app/227300/workshop/" in html


@pytest.fixture
def enshrouded(database, monkeypatch):
    sid = _server(database, "enshrouded.service")
    calls: list[str] = []
    state = {"loader_installed": False, "loader": "Shroudtopia", "loader_version": "",
             "enabled": False, "mods": [], "log": []}

    def ssh_run(server, cmd, timeout=None, **kw):
        calls.append(cmd)
        out = type("P", (), {})()
        out.returncode, out.stderr, out.stdout = 0, "", json.dumps(state)
        return out
    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    jobs: list[tuple] = []
    monkeypatch.setattr(panel, "start_job", lambda action, server, user, **kw: jobs.append((action, kw)) or 99)
    return sid, calls, jobs, state


def test_enshrouded_oferece_instalar_o_shroudtopia(admin, enshrouded):
    sid, calls, _, _ = enshrouded
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "https://github.com/s0t7x/shroudtopia/releases" in html
    assert "value=install" in html
    # O status sai do instalador do Shroudtopia, rodando na pasta do JOGO (acima de mods/).
    assert "shroudtopia" in calls[0]
    assert "/opt/game" in calls[0]
    assert "/opt/game/mods" not in calls[0]


def test_enshrouded_mostra_mods_e_o_log_do_carregador(admin, enshrouded):
    sid, _, _, state = enshrouded
    state.update(loader_installed=True, enabled=True, loader_version="0.1.1",
                 mods=[{"name": "flight.dll", "dir": False, "size": 2048}],
                 log=["(basics) class NoResourceCostAddress not found"])
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "Shroudtopia 0.1.1" in html
    assert "flight.dll" in html
    assert "NoResourceCostAddress not found" in html
    assert 'accept=".dll"' in html


def test_instalar_o_shroudtopia_vira_job_com_reinicio(admin, post, enshrouded):
    sid, _, jobs, _ = enshrouded
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "restart": "1"})
    action, kw = jobs[0]
    assert action == "mod-loader"
    install, restart = kw["steps"]
    assert "loader-install" in install
    assert "shroudtopia" in install
    assert restart.endswith("restart enshrouded.service")


def test_enshrouded_nao_recebe_plugin_do_thunderstore(admin, post, enshrouded):
    sid, _, jobs, _ = enshrouded
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework"})
    assert jobs == []


def test_lote_com_um_nome_errado_nao_manda_nada(admin, database, monkeypatch):
    """Mod de Unreal 5 vem em tres arquivos: mandar dois e recusar o terceiro deixaria um mod
    pela metade na pasta. Os nomes sao conferidos ANTES de qualquer coisa ir ao container."""
    sid = _server(database, "dragonwilds.service")
    touched: list = []
    monkeypatch.setattr(panel, "ssh_run", lambda *a, **k: touched.append(a) or _Done())
    monkeypatch.setattr(panel, "ssh_stream_in", lambda *a, **k: touched.append(a) or "enviado")
    with admin.session_transaction() as sess:
        token = sess.get("csrf", "")
    admin.post(f"/servers/{sid}/mods/upload", content_type="multipart/form-data", data={
        "csrf": token,
        "file": [(io.BytesIO(b"p"), "Mod_P.pak"), (io.BytesIO(b"u"), "Mod_P.utoc"), (io.BytesIO(b"x"), "dwmapi.dll")],
    })
    assert touched == []


def test_lote_do_dragonwilds_vai_inteiro_para_mods(admin, database, monkeypatch, mkdir_ok, upload_jobs):
    sid = _server(database, "dragonwilds.service")
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "enviado")
    with admin.session_transaction() as sess:
        token = sess.get("csrf", "")
    admin.post(f"/servers/{sid}/mods/upload", content_type="multipart/form-data", data={
        "csrf": token,
        "file": [(io.BytesIO(b"p"), "Mod_P.pak"), (io.BytesIO(b"u"), "Mod_P.utoc"), (io.BytesIO(b"c"), "Mod_P.ucas")],
    })
    assert len(sent) == 3
    # Os tres na MESMA espera: verificados juntos e movidos juntos.
    assert len({c.split("/var/tmp/", 1)[1].split("/", 1)[0] for c in sent}) == 1
    assert "/opt/game/RSDragonwilds/Content/Paks/~mods" in upload_jobs[0][1]["steps"][1]


# ------------------------------------------------------------------ versao escolhida

def test_instalar_mod_em_versao_escolhida(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework", "version": "0.10.4"})
    [step] = jobs[0][1]["steps"]
    assert step.rstrip().endswith("deca VampireCommandFramework 0.10.4")
    assert jobs[0][1]["command"] == "deca/VampireCommandFramework@0.10.4"


def test_versao_colada_no_nome_vale_e_o_campo_vence(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca-VampireCommandFramework-0.10.4"})
    post(admin, f"/servers/{sid}/mods/plugin/install",
         {"package": "deca-VampireCommandFramework-0.10.4", "version": "0.9.0"})
    assert jobs[0][1]["steps"][0].rstrip().endswith("VampireCommandFramework 0.10.4")
    assert jobs[1][1]["steps"][0].rstrip().endswith("VampireCommandFramework 0.9.0")


def test_sem_versao_o_comando_nao_leva_versao(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework", "version": ""})
    assert jobs[0][1]["steps"][0].rstrip().endswith("deca VampireCommandFramework")


@pytest.mark.parametrize("bad", ["latest", "1.2", "1.2.3; rm -rf /", "../1.2.3"])
def test_versao_invalida_nao_chega_ao_container(admin, post, vrising, bad):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/plugin/install", {"package": "deca/VampireCommandFramework", "version": bad})
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "version": bad})
    assert jobs == []


def test_carregador_em_versao_escolhida_e_ligar_ignora_versao(admin, post, vrising):
    sid, _, jobs = vrising
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "version": "1.691.3"})
    post(admin, f"/servers/{sid}/mods/loader", {"action": "enable", "version": "lixo"})
    assert jobs[0][1]["steps"][0].rstrip().endswith("BepInExPack_V_Rising 1.691.3")
    assert "loader-enable" in jobs[1][1]["steps"][0]


def test_servidor_que_ja_roda_pode_trocar_a_versao_de_um_mod(admin, vrising):
    """A tela oferece trocar a versao de cada mod instalado, e mostra qual esta fixada."""
    sid, _, _ = vrising
    REMOTE_STATE["plugins"][0]["pinned"] = True
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert '<option value="deca-VampireCommandFramework">deca-VampireCommandFramework (0.11.0)</option>' in html
    assert html.count('name="version"') == 3, "carregador, instalar e trocar"
    assert "versao fixada" in html


def test_shroudtopia_em_versao_escolhida(admin, post, enshrouded):
    sid, _, jobs, _ = enshrouded
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "version": "0.1.0"})
    step = jobs[0][1]["steps"][0]
    assert "loader-install" in step
    assert step.rstrip().endswith("0.1.0")


def test_tela_avisa_que_todo_mod_passa_pelo_antivirus(admin, vrising):
    assert "ClamAV" in admin.get(f"/servers/{vrising[0]}/mods").get_data(as_text=True)


def test_enshrouded_tambem_avisa_do_antivirus(admin, enshrouded):
    assert "ClamAV" in admin.get(f"/servers/{enshrouded[0]}/mods").get_data(as_text=True)


# ------------------------------------------------------------------ verificar mods instalados

@pytest.mark.parametrize(("service", "expected"), [
    ("vrising.service", ["/opt/game/BepInEx", "/opt/game/winhttp.dll", "/opt/game/dotnet"]),
    ("enshrouded.service", ["/opt/game/mods", "/opt/game/winmm.dll", "/opt/game/shroudtopia.dll"]),
    ("palworld.service", ["/opt/game/Pal/Content/Paks/~mods"]),
])
def test_verificar_instalados_vira_job_so_nas_pastas_de_mod(admin, post, database, upload_jobs, service, expected):
    """Nunca a pasta do jogo inteira: seriam gigas de arquivo do proprio jogo para nada."""
    sid = _server(database, service)
    response = post(admin, f"/servers/{sid}/mods/audit", {})
    assert "/jobs/77" in response.headers["Location"]
    action, kw = upload_jobs[0]
    assert action == "mod-audit"
    [step] = kw["steps"]
    assert "clamscan" in step
    for path in expected:
        assert path in step
    assert not step.rstrip().endswith("/opt/game")


def test_operador_nao_verifica(operator, post, database, upload_jobs):
    sid = _server(database, "palworld.service")
    assert post(operator, f"/servers/{sid}/mods/audit", {}).status_code == 403
    assert upload_jobs == []


def test_jogo_sem_gestor_nao_tem_o_que_verificar(admin, post, database, upload_jobs):
    sid = _server(database, "terraria.service")
    post(admin, f"/servers/{sid}/mods/audit", {})
    assert upload_jobs == []


def test_icarus_instala_o_ue4ss_na_pasta_do_executavel(admin, post, database, monkeypatch):
    sid = _server(database, "icarus.service")
    calls: list[str] = []
    state = {"loader_installed": False, "loader": "UE4SS", "loader_version": "", "loader_pinned": False,
             "enabled": False, "mods": [], "log": []}

    def ssh_run(server, cmd, timeout=None, **kw):
        calls.append(cmd)
        out = type("P", (), {})()
        out.returncode, out.stderr, out.stdout = 0, "", json.dumps(state)
        return out
    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    jobs: list[tuple] = []
    monkeypatch.setattr(panel, "start_job", lambda action, server, user, **kw: jobs.append((action, kw)) or 99)
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "value=install" in html
    # O instalador recebe a pasta do EXECUTAVEL, e nao a de mods (dois niveis abaixo).
    assert calls[0].endswith("status /opt/game/Icarus/Binaries/Win64")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "restart": "1"})
    install, restart = jobs[0][1]["steps"]
    assert "--scan" in install
    assert install.endswith("loader-install /opt/game/Icarus/Binaries/Win64")
    assert restart.endswith("restart icarus.service")


# ------------------------------------------------------------- instaladores ainda sem prova

@pytest.fixture
def remote(database, monkeypatch):
    """Servidor qualquer cujo instalador remoto responde `state`; guarda comandos e jobs."""
    calls: list[str] = []
    jobs: list[tuple] = []
    state: dict = {"loader_installed": False, "loader": "", "loader_version": "", "loader_pinned": False,
                   "enabled": False, "mods": [], "log": [], "plugins": [], "overrides_ok": True,
                   "memory_mb": 16384, "wiped": False}

    def ssh_run(server, cmd, timeout=None, **kw):
        calls.append(cmd)
        out = type("P", (), {})()
        out.returncode, out.stderr, out.stdout = 0, "", json.dumps(state)
        return out
    monkeypatch.setattr(panel, "ssh_run", ssh_run)
    monkeypatch.setattr(panel, "start_job", lambda action, server, user, **kw: jobs.append((action, kw)) or 99)
    return calls, jobs, state


@pytest.mark.parametrize("service", ["satisfactory.service", "valheim.service", "rust.service"])
def test_instalador_sem_prova_avisa_na_tela(admin, database, remote, service):
    sid = _server(database, service)
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "NAO foi testado" in html


def test_satisfactory_instala_mod_do_ficsit_app_com_antivirus(admin, post, database, remote):
    calls, jobs, _ = remote
    sid = _server(database, "satisfactory.service")
    admin.get(f"/servers/{sid}/mods")
    assert calls[0].endswith("status /opt/game")
    post(admin, f"/servers/{sid}/mods/sml/install", {"mod": "https://ficsit.app/mod/RefinedPower", "restart": "1"})
    post(admin, f"/servers/{sid}/mods/sml/install", {"mod": "x; rm -rf /"})
    assert len(jobs) == 1
    install, restart = jobs[0][1]["steps"]
    assert "--scan" in install
    assert install.endswith("mod-install /opt/game RefinedPower")
    assert restart.endswith("restart satisfactory.service")


def test_satisfactory_botao_do_carregador_instala_o_sml(admin, post, database, remote):
    _, jobs, _ = remote
    sid = _server(database, "satisfactory.service")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    post(admin, f"/servers/{sid}/mods/loader", {"action": "disable"})
    assert len(jobs) == 1
    assert jobs[0][1]["steps"][0].endswith("mod-install /opt/game SML")


def test_valheim_instala_o_bepinex_no_modo_linux(admin, post, database, remote):
    _, jobs, _ = remote
    sid = _server(database, "valheim.service")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    step = jobs[0][1]["steps"][0]
    assert "--unit valheim.service loader-install /opt/game denikson BepInExPack_Valheim" in step


def test_rust_recebe_plugin_cs_e_instala_o_oxide(admin, post, database, remote):
    _, jobs, state = remote
    state.update(loader_installed=True, enabled=True, loader_version="2.0.7801",
                 mods=[{"name": "Kits.cs", "size": 900}])
    sid = _server(database, "rust.service")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert 'accept=".cs"' in html
    assert "Kits.cs" in html
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install"})
    assert jobs[0][1]["steps"][0].endswith("loader-install /opt/game")


def test_palworld_instala_o_ue4ss_linux_e_continua_recebendo_pak(admin, post, database, remote, monkeypatch):
    calls, jobs, _ = remote
    monkeypatch.setattr(panel, "list_dir", lambda *a, **k: ([{"name": "MeuMod_P.pak", "dir": False, "size": 10}], None))
    sid = _server(database, "palworld.service")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "NAO foi testado" in html
    assert "MeuMod_P.pak" in html
    assert 'accept=".pak"' in html
    assert calls[0].endswith("--unit palworld.service status /opt/game/Pal/Binaries/Linux")
    post(admin, f"/servers/{sid}/mods/loader", {"action": "install", "restart": "1"})
    install, restart = jobs[0][1]["steps"]
    assert "--scan" in install
    assert install.endswith("--unit palworld.service loader-install /opt/game/Pal/Binaries/Linux")
    assert restart.endswith("restart palworld.service")


def test_dragonwilds_nao_tem_ue4ss(admin, database, monkeypatch):
    """Medido: no Dragonwilds (UE 5.6.1) o port roda Lua puro, mas mod que toca o jogo o derruba."""
    monkeypatch.setattr(panel, "list_dir", lambda *a, **k: ([], None))
    sid = _server(database, "dragonwilds.service")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert "value=install" not in html
    assert 'accept=".pak,.utoc,.ucas"' in html
