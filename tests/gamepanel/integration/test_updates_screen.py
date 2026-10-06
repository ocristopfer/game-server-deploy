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
