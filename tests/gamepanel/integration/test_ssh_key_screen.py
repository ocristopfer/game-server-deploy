"""The SSH access screen teaches the unprivileged model, in both languages.

It used to hand out an `echo ... >> /root/.ssh/authorized_keys` command: the panel logs in as
`gamepanel` now, and a CT that only has the key on root refuses that user. The screen must point
at migrate-ct.ps1 (or ct-panel-access.sh by hand) and never at root's authorized_keys again.
"""
from __future__ import annotations

import pytest

from gamepanel import app as panel

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITelaDeTeste gamepanel@teste"


@pytest.fixture
def fixed_key(monkeypatch):
    monkeypatch.setattr(panel, "public_key", lambda: KEY)


def _page(cli) -> str:
    resp = cli.get("/ssh-key")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _assert_unprivileged_commands(html: str) -> None:
    assert KEY in html
    assert "migrate-ct.ps1 -Ctid &lt;CTID&gt;" in html
    assert "bash ct-panel-access.sh install" in html
    assert "bash ct-panel-access.sh verify" in html
    assert "bash ct-panel-access.sh lock" in html
    assert "/root/.ssh" not in html
    assert "authorized_keys" not in html
    assert "ssh_key." not in html, "raw key on screen: missing from the catalog"


def test_em_portugues_a_tela_ensina_o_usuario_gamepanel(admin, fixed_key):
    html = _page(admin)
    _assert_unprivileged_commands(html)
    assert "Containers de jogo" in html
    assert "usuário sem privilégios" in html
    assert "jogo.service" in html


def test_em_ingles_a_tela_ensina_o_usuario_gamepanel(admin, fixed_key, post):
    post(admin, "/account/language", {"lang": "en"})
    html = _page(admin)
    _assert_unprivileged_commands(html)
    assert "Game containers" in html
    assert "unprivileged" in html
    assert "game.service" in html


def test_sem_chave_a_tela_avisa_e_nao_quebra(admin, monkeypatch):
    monkeypatch.setattr(panel, "public_key", lambda: "")
    html = _page(admin)
    assert "Chave não encontrada" in html
