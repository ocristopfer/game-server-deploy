"""A tela Mods pelo cliente HTTP, com o container trocado por falsos (nada de SSH)."""
from __future__ import annotations

import io

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


def test_envio_do_pacote_vai_para_a_pasta_do_servidor(admin, ets2_server, monkeypatch, database, mkdir_ok):
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "enviado")
    assert _upload(admin, ets2_server, "server_packages.sii").status_code == 302
    assert len(sent) == 1
    assert "/opt/game/server-home/server_packages.sii" in sent[0]
    job = database.execute("SELECT action, status FROM jobs ORDER BY id DESC LIMIT 1").fetchone()
    assert (job["action"], job["status"]) == ("upload-mod", "ok")


def test_nome_com_caminho_vira_so_o_nome(admin, ets2_server, monkeypatch, mkdir_ok):
    sent: list = []
    monkeypatch.setattr(panel, "ssh_stream_in", lambda server, cmd, source, timeout: sent.append(cmd) or "enviado")
    _upload(admin, ets2_server, "../../etc/server_packages.dat")
    assert "/opt/game/server-home/server_packages.dat" in sent[0]
    assert "/etc/" not in sent[0].replace("/opt/game/server-home/", "")


def test_remover_so_vale_para_pasta_de_mods_e_so_pelo_nome(admin, post, database, monkeypatch):
    sid = _server(database, "palworld.service")
    removed: list = []
    monkeypatch.setattr(panel, "delete_file", lambda server, path: removed.append(path) or "apagado")
    post(admin, f"/servers/{sid}/mods/delete", {"name": "../../../etc/passwd"})
    post(admin, f"/servers/{sid}/mods/delete", {"name": "script.sh"})
    post(admin, f"/servers/{sid}/mods/delete", {"name": "MeuMod_P.pak"})
    assert removed == ["/opt/game/Pal/Content/Paks/~mods/MeuMod_P.pak"]


def test_jogo_sem_gestor_manda_para_arquivos(admin, database):
    sid = _server(database, "valheim.service")
    html = admin.get(f"/servers/{sid}/mods").get_data(as_text=True)
    assert f"/servers/{sid}/files" in html
