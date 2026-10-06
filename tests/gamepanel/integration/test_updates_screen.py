"""The Updates screen (`blueprints/updates.py`): the panel only reads the status and leaves requests."""
from __future__ import annotations

import json

import pytest

from gamepanel import app as panel
from gamepanel import updater


@pytest.fixture
def paths(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    monkeypatch.setattr(panel, "UPDATE_DIR", str(tmp_path / "update"))
    monkeypatch.setattr(panel, "UPDATE_STATUS", str(status))
    return tmp_path, status


def _status(path, **fields):
    path.write_text(json.dumps({"result": "available", "available": True, "latest": "99.0.0",
                                "page": "https://github.com/dono/repo/releases/tag/v99.0.0", **fields}))


def test_so_admin(operator, paths):
    assert operator.get("/updates").status_code == 403


def test_sem_atualizador_instalado_a_tela_explica(admin, paths):
    html = admin.get("/updates").get_data(as_text=True)
    assert "deploy-admin.ps1 -Full" in html


def test_versao_nova_aparece_na_tela_e_no_rodape(admin, paths):
    _, status = paths
    _status(status)
    html = admin.get("/updates").get_data(as_text=True)
    assert "99.0.0" in html
    assert "/updates/install" in html
    footer = admin.get("/").get_data(as_text=True)
    assert "atualização 99.0.0 disponível" in footer


def test_operador_nao_ve_o_aviso_no_rodape(operator, paths):
    _, status = paths
    _status(status)
    assert "99.0.0" not in operator.get("/").get_data(as_text=True)


def test_status_mais_velho_que_o_codigo_nao_anuncia(admin, paths):
    _, status = paths
    _status(status, latest="0.0.1")
    assert panel.update_available() == ""


def test_pedir_instalacao_deixa_o_pedido_para_o_root(admin, paths, post):
    folder, _ = paths
    assert post(admin, "/updates/install").status_code == 302
    assert updater.take_request(str(folder / "update")) == "install"


def test_verificar_agora(admin, paths, post):
    folder, _ = paths
    post(admin, "/updates/check")
    assert updater.take_request(str(folder / "update")) == "check"


def test_modo(admin, paths, post):
    folder, _ = paths
    post(admin, "/updates/mode", {"mode": "notify"})
    assert updater.read_mode(str(folder / "update"), "auto") == "notify"
    post(admin, "/updates/mode", {"mode": "qualquer"})
    assert updater.read_mode(str(folder / "update"), "auto") == "notify"


def test_operador_nao_pede_atualizacao(operator, paths, post):
    folder, _ = paths
    assert post(operator, "/updates/install").status_code == 403
    assert not (folder / "update").exists()


# ------------------------------------------------------------------ the card that refreshes itself

def _post_json(cli, url):
    """What the card's JavaScript sends: the form (with its CSRF), asking for JSON back."""
    with cli.session_transaction() as sess:
        token = sess.get("csrf", "")
    return cli.post(url, data={"csrf": token}, headers={"Accept": "application/json"})


def test_o_cartao_devolve_o_mesmo_miolo_da_tela_e_a_marca_muda_com_o_status(admin, paths):
    _, status = paths
    before = admin.get("/api/v1/updates/panel").get_json()
    assert "deploy-admin.ps1 -Full" in before["html"]
    _status(status, checked_at="2026-10-06T12:00:00Z")
    after = admin.get("/api/v1/updates/panel").get_json()
    assert "99.0.0" in after["html"]
    assert "/updates/install" in after["html"]
    assert after["stamp"] != before["stamp"]
    # The page carries the same stamp, so the card knows what "nothing new yet" looks like.
    assert f'data-update-stamp="{after["stamp"]}"' in admin.get("/updates").get_data(as_text=True)


def test_o_botao_pelo_javascript_recebe_a_frase_em_vez_de_um_redirect(admin, paths):
    folder, _ = paths
    response = _post_json(admin, "/updates/check")
    assert response.status_code == 200
    assert response.get_json() == {"message": "Verificação pedida: aguardando o atualizador."}
    assert updater.take_request(str(folder / "update")) == "check"


def test_falha_ao_gravar_o_pedido_chega_ao_cartao_como_erro(admin, paths, monkeypatch):
    def no_disk(*_args):
        raise OSError("read-only")
    monkeypatch.setattr(updater, "leave_request", no_disk)
    response = _post_json(admin, "/updates/install")
    assert response.status_code == 503
    assert "Não consegui gravar o pedido" in response.get_json()["error"]


def test_operador_nao_le_o_cartao(operator, paths):
    assert operator.get("/api/v1/updates/panel").status_code == 403
